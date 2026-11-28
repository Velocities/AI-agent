"""Per-Discord-user deployments and sign-in. The terminal client's files stay separate."""

from __future__ import annotations

import json
import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

from ai_agent_cli.client_state import StoredSession


class StoreError(Exception):
    """The state file is missing fields or is not valid JSON."""


@dataclass(frozen=True)
class Deployment:
    server_url: str
    supabase_url: str
    supabase_publishable_key: str
    conversation_id: str | None = None


class UserStore:
    """Deployments, the active one, and Supabase sessions, keyed by Discord user id."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def list_deployments(self, user_id: int) -> list[Deployment]:
        with self._lock:
            record = self._users().get(str(user_id))
            if record is None:
                return []
            return [_deployment(item) for item in record.get("servers", [])]

    def active_deployment(self, user_id: int) -> Deployment | None:
        with self._lock:
            record = self._users().get(str(user_id))
            if record is None:
                return None
            servers = [_deployment(item) for item in record.get("servers", [])]
            if not servers:
                return None
            active = record.get("active")
            for server in servers:
                if server.server_url == active:
                    return server
            return servers[0]

    def find(self, user_id: int, server_url: str) -> Deployment | None:
        for server in self.list_deployments(user_id):
            if server.server_url == server_url:
                return server
        return None

    def save_deployment(self, user_id: int, deployment: Deployment) -> None:
        """Insert or replace [deployment] and make it the active one."""
        with self._lock:
            document = self._read()
            record = _record(document, user_id)
            servers = [_deployment(item) for item in record.get("servers", [])]
            replaced = False
            updated: list[Deployment] = []
            for server in servers:
                if server.server_url == deployment.server_url:
                    updated.append(deployment)
                    replaced = True
                else:
                    updated.append(server)
            if not replaced:
                updated.append(deployment)
            record["servers"] = [_dump_deployment(server) for server in updated]
            record["active"] = deployment.server_url
            self._write(document)

    def set_conversation(
        self,
        user_id: int,
        server_url: str,
        conversation_id: str | None,
    ) -> None:
        with self._lock:
            document = self._read()
            record = _record(document, user_id)
            servers = []
            found = False
            for item in record.get("servers", []):
                server = _deployment(item)
                if server.server_url == server_url:
                    found = True
                    server = Deployment(
                        server_url=server.server_url,
                        supabase_url=server.supabase_url,
                        supabase_publishable_key=server.supabase_publishable_key,
                        conversation_id=conversation_id or None,
                    )
                servers.append(_dump_deployment(server))
            if not found:
                raise StoreError("That deployment is not saved.")
            record["servers"] = servers
            self._write(document)

    def remove_deployment(self, user_id: int, server_url: str) -> Deployment | None:
        """Forget [server_url] and its sign-in. Returns the deployment that is active now."""
        with self._lock:
            document = self._read()
            record = _record(document, user_id)
            servers = [_deployment(item) for item in record.get("servers", [])]
            if not any(server.server_url == server_url for server in servers):
                raise StoreError("That server is not saved.")
            remaining = [server for server in servers if server.server_url != server_url]
            sessions = record.get("sessions")
            if isinstance(sessions, dict):
                sessions.pop(server_url, None)
            active = record.get("active")
            next_url = None
            if remaining:
                next_url = remaining[0].server_url
                if isinstance(active, str) and active != server_url:
                    next_url = active
            record["servers"] = [_dump_deployment(server) for server in remaining]
            record["active"] = next_url
            self._write(document)
            if next_url is None:
                return None
            for server in remaining:
                if server.server_url == next_url:
                    return server
            return None

    def session_for(self, user_id: int, server_url: str) -> StoredSession | None:
        with self._lock:
            record = self._users().get(str(user_id))
            if record is None:
                return None
            sessions = record.get("sessions")
            if not isinstance(sessions, dict):
                return None
            return _session(sessions.get(server_url))

    def save_session(self, user_id: int, server_url: str, session: StoredSession) -> None:
        with self._lock:
            document = self._read()
            record = _record(document, user_id)
            sessions = record.get("sessions")
            if not isinstance(sessions, dict):
                sessions = {}
                record["sessions"] = sessions
            sessions[server_url] = {
                "access_token": session.access_token,
                "refresh_token": session.refresh_token,
                "expires_at": session.expires_at,
            }
            self._write(document)

    def clear_session(self, user_id: int, server_url: str) -> None:
        with self._lock:
            document = self._read()
            record = _record(document, user_id)
            sessions = record.get("sessions")
            if isinstance(sessions, dict):
                sessions.pop(server_url, None)
            self._write(document)

    def _users(self) -> dict:
        users = self._read().get("users")
        return users if isinstance(users, dict) else {}

    def _read(self) -> dict:
        if not self.path.exists():
            return {"users": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StoreError(f"Saved Discord state could not be read: {self.path}") from exc
        if not isinstance(payload, dict):
            raise StoreError(f"Saved Discord state could not be read: {self.path}")
        users = payload.get("users")
        if users is None:
            payload["users"] = {}
        elif not isinstance(users, dict):
            raise StoreError(f"Saved Discord state could not be read: {self.path}")
        return payload

    def _write(self, document: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.parent.chmod(stat.S_IRWXU)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(document), encoding="utf-8")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, self.path)
        self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _record(document: dict, user_id: int) -> dict:
    users = document.setdefault("users", {})
    key = str(user_id)
    record = users.get(key)
    if not isinstance(record, dict):
        record = {"active": None, "servers": [], "sessions": {}}
        users[key] = record
    if not isinstance(record.get("servers"), list):
        record["servers"] = []
    if not isinstance(record.get("sessions"), dict):
        record["sessions"] = {}
    return record


def _deployment(item: object) -> Deployment:
    if not isinstance(item, dict):
        raise StoreError("Saved Discord state has a deployment that is not an object.")
    conversation = item.get("conversation_id")
    if not isinstance(conversation, str) or not conversation:
        conversation = None
    return Deployment(
        server_url=_text(item, "server_url"),
        supabase_url=_text(item, "supabase_url").rstrip("/"),
        supabase_publishable_key=_text(item, "supabase_publishable_key"),
        conversation_id=conversation,
    )


def _dump_deployment(server: Deployment) -> dict:
    return {
        "server_url": server.server_url,
        "supabase_url": server.supabase_url,
        "supabase_publishable_key": server.supabase_publishable_key,
        "conversation_id": server.conversation_id,
    }


def _session(item: object) -> StoredSession | None:
    if not isinstance(item, dict):
        return None
    access = item.get("access_token")
    refresh = item.get("refresh_token")
    expires = item.get("expires_at")
    if not isinstance(access, str) or not isinstance(refresh, str):
        return None
    if not isinstance(expires, (int, float)):
        expires = 0
    return StoredSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=float(expires),
    )


def _text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise StoreError(f"Saved Discord state is missing {key}.")
    return value.strip()
