"""Per-user execution targets in SQLite (docs/execution-targets.md)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.commands.executor import CommandExecutor, CommandResult
from ai_agent.conversations.db import open_stores_at
from ai_agent.execution_targets.build_router import build_router_for_user
from ai_agent.execution_targets.repository import UserExecutionTargetRepository
from ai_agent.execution_targets.secure_key_store import OSSecureKeyStore
from ai_agent.execution_targets.store import TargetConfigError

ALICE = "11111111-1111-4111-8111-111111111111"
BOB = "22222222-2222-4222-8222-222222222222"


def _executor(tmp_path: Path) -> CommandExecutor:
    ex = MagicMock(spec=CommandExecutor)

    def run(_expr):
        return CommandResult(
            success=True,
            exit_status=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
            rendered="",
        )

    ex.run.side_effect = run
    return ex


def _repo(tmp_path: Path) -> UserExecutionTargetRepository:
    _store, _access, repo = open_stores_at(f"sqlite:///{tmp_path / 'targets.sqlite3'}")
    return repo


def test_users_do_not_see_each_others_target_names(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.add_docker(ALICE, name="web", container="alice-nginx")
    repo.add_docker(BOB, name="web", container="bob-nginx")

    alice_names = {r.name for r in repo.list_for_user(ALICE)}
    bob_names = {r.name for r in repo.list_for_user(BOB)}
    assert alice_names == {"web"}
    assert bob_names == {"web"}
    assert repo.get_by_name(ALICE, "web").spec["container"] == "alice-nginx"
    assert repo.get_by_name(BOB, "web").spec["container"] == "bob-nginx"


def test_router_for_user_only_includes_own_targets(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    repo.add_docker(ALICE, name="lab", container="c1")
    repo.add_docker(BOB, name="lab", container="c2")

    monkeypatch.setattr(
        "ai_agent.execution_targets.secure_key_store.lookup_posix_account",
        lambda _name: (tmp_path, 1000, 1000),
    )
    key_store = OSSecureKeyStore()
    executor = _executor(tmp_path)

    alice_router = build_router_for_user(
        user_id=ALICE,
        linux_username="alice_unix",
        executor=executor,
        target_repo=repo,
        key_store=key_store,
    )
    bob_router = build_router_for_user(
        user_id=BOB,
        linux_username="bob_unix",
        executor=executor,
        target_repo=repo,
        key_store=key_store,
    )

    assert set(alice_router.names()) == {"local", "lab"}
    assert set(bob_router.names()) == {"local", "lab"}
    alice_docker = alice_router.resolve("lab")
    bob_docker = bob_router.resolve("lab")
    assert alice_docker.container == "c1"
    assert bob_docker.container == "c2"


def test_cannot_store_local_as_user_target(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(TargetConfigError, match="reserved"):
        repo.add_docker(ALICE, name="local", container="x")
