"""Installer helpers that used to be inline Python in install.sh."""

import json
from pathlib import Path

import pytest

from deploy.systemd.docker_daemon_userns import enable, revert
from deploy.systemd.ensure_env import ensure
from deploy.systemd.read_env import read_value
from deploy.systemd.render_unit import render


def test_ensure_env_fills_missing_lines_and_keeps_existing_ones(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("LLM_MODEL=qwen\n", encoding="utf-8")
    ensure(env, "sqlite:////var/lib/ai-agent/conversations.db", "/var/lib/ai-agent/catalog")
    text = env.read_text(encoding="utf-8")
    assert "CONVERSATION_DATABASE=sqlite:////var/lib/ai-agent/conversations.db" in text
    assert "WORKFLOW_CATALOG_ROOT=/var/lib/ai-agent/catalog" in text
    ensure(env, "sqlite:////elsewhere.db", "/tmp/other")
    again = env.read_text(encoding="utf-8")
    assert "elsewhere" not in again
    assert "/tmp/other" not in again


def test_read_env_skips_comments_and_quotes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# WORKFLOW_CATALOG_URL=ignored\nWORKFLOW_CATALOG_URL='https://example.test/catalog.git'\n",
        encoding="utf-8",
    )
    assert read_value(env, "WORKFLOW_CATALOG_URL") == "https://example.test/catalog.git"
    assert read_value(env, "MISSING") == ""


def test_render_unit_replaces_placeholders_and_escapes_percent(tmp_path: Path) -> None:
    template = tmp_path / "unit.in"
    template.write_text("User=@SERVICE_USER@\nExec=@EXEC@\n", encoding="utf-8")
    dest = tmp_path / "unit"
    render(template, dest, {"@SERVICE_USER@": "ai", "@EXEC@": "run %h"})
    assert dest.read_text(encoding="utf-8") == "User=ai\nExec=run %%h\n"


def test_render_unit_refuses_a_missing_placeholder(tmp_path: Path) -> None:
    template = tmp_path / "unit.in"
    template.write_text("User=@SERVICE_USER@\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing @MISSING@"):
        render(template, tmp_path / "unit", {"@MISSING@": "x"})


def test_userns_enable_and_revert(tmp_path: Path) -> None:
    daemon = tmp_path / "daemon.json"
    daemon.write_text("{}\n", encoding="utf-8")
    enable(daemon)
    assert json.loads(daemon.read_text(encoding="utf-8"))["userns-remap"] == "default"
    revert(daemon)
    assert "userns-remap" not in json.loads(daemon.read_text(encoding="utf-8"))


def test_userns_enable_leaves_a_custom_value(tmp_path: Path) -> None:
    daemon = tmp_path / "daemon.json"
    daemon.write_text('{"userns-remap": "custom"}\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="leave-userns:custom"):
        enable(daemon)
    assert json.loads(daemon.read_text(encoding="utf-8"))["userns-remap"] == "custom"
