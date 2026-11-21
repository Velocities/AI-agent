"""Unix-socket service. This process is the one that may open the Docker socket.

systemd starts it with ``SupplementaryGroups=docker``. The API connects as
the service user. Peer credentials are checked before a request is read.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import struct
import subprocess
import threading
from pathlib import Path

from ai_agent.docker_broker.authorize import BrokerRejected
from ai_agent.docker_broker.broker import DockerBroker
from ai_agent.docker_broker.host_runtime import (
    UsernsRemapGuard,
    broker_subprocess_env,
    prepare_broker_host_runtime,
)
from ai_agent.workflows.container import SLEEP_ROOT

logger = logging.getLogger(__name__)

_MAX_REQUEST = 1_500_000


class BrokerServer:
    def __init__(
        self,
        path: Path,
        *,
        runner,
        sandbox_root: Path,
        api_uid: int | None,
        sleep_root: Path = SLEEP_ROOT,
        run_guard=None,
    ) -> None:
        self.path = Path(path)
        self.broker = DockerBroker(
            runner,
            sandbox_root=sandbox_root,
            sleep_root=sleep_root,
            run_guard=run_guard,
        )
        self.api_uid = api_uid
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None

    def serve_forever(self) -> None:
        if self._sock is None:
            self._sock = self._listen()
        while not self._stop.is_set():
            try:
                conn, _addr = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                raise
            threading.Thread(
                target=self._serve_connection,
                args=(conn,),
                name="docker-broker",
                daemon=True,
            ).start()

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="docker-broker-accept", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            sock.close()
        if self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass

    def _listen(self) -> socket.socket:
        if self.path.exists():
            self.path.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        os.chmod(self.path, 0o660)
        sock.listen(16)
        sock.settimeout(0.5)
        return sock

    def _serve_connection(self, conn: socket.socket) -> None:
        with conn:
            if not self._peer_allowed(conn):
                _write(conn, {"ok": False, "error": "Docker broker connection refused.", "code": 126})
                return
            try:
                raw = _read_request(conn)
                message = json.loads(raw.decode())
                result = self.broker.handle(message)
            except BrokerRejected as exc:
                logger.warning("Docker broker rejected socket request: %s", exc)
                _write(conn, {"ok": False, "error": str(exc), "code": 126})
                return
            except (json.JSONDecodeError, UnicodeError, OSError) as exc:
                logger.warning("Docker broker request failed: %s", exc)
                _write(conn, {"ok": False, "error": "Docker broker could not read the request.", "code": 126})
                return
            _write(
                conn,
                {
                    "ok": True,
                    "code": result.returncode,
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                },
            )

    def _peer_allowed(self, conn: socket.socket) -> bool:
        if self.api_uid is None:
            return True
        try:
            return _peer_uid(conn) == self.api_uid
        except OSError:
            return False


def subprocess_runner(
    argv: list[str],
    *,
    timeout: float,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an authorized argv. ``shell`` is never set."""
    logger.info("Docker broker exec: %s", " ".join(argv[:6]))
    try:
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=broker_subprocess_env(),
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"timed out after {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the AI Agent Docker broker.")
    parser.add_argument("--socket", default="/run/ai-agent/docker.sock")
    parser.add_argument("--api-user", required=True)
    parser.add_argument("--sandbox-root", required=True)
    parser.add_argument("--sleep-root", default=str(SLEEP_ROOT))
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    prepare_broker_host_runtime()
    import pwd

    api_uid = pwd.getpwnam(args.api_user).pw_uid
    api_gid = pwd.getpwnam(args.api_user).pw_gid
    path = Path(args.socket)
    server = BrokerServer(
        path,
        runner=subprocess_runner,
        sandbox_root=Path(args.sandbox_root),
        api_uid=api_uid,
        sleep_root=Path(args.sleep_root),
        run_guard=UsernsRemapGuard(),
    )
    server._sock = server._listen()
    os.chown(path, os.getuid(), api_gid)
    os.chmod(path, 0o660)
    logger.info("Docker broker listening on %s for uid %s", path, api_uid)
    server.serve_forever()


def _peer_uid(conn: socket.socket) -> int:
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def _read_request(conn: socket.socket) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        block = conn.recv(65536)
        if not block:
            break
        size += len(block)
        if size > _MAX_REQUEST:
            raise OSError("Docker broker request is too large.")
        chunks.append(block)
        if b"\n" in block:
            break
    return b"".join(chunks).split(b"\n", 1)[0]


def _write(conn: socket.socket, payload: dict) -> None:
    try:
        conn.sendall(json.dumps(payload).encode() + b"\n")
    except OSError:
        logger.warning("Docker broker could not write the response.")


if __name__ == "__main__":
    raise SystemExit(main())
