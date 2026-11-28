"""create-tool writes a loadable 1.0.0 tool and refuses collisions."""

from pathlib import Path

import pytest

from ai_agent.cli.app import main as app_main
from ai_agent.workflows.create_tool import CreateToolError, create_tool
from ai_agent.workflows.manifests import _load_tool


def test_create_tool_writes_a_loadable_starter(tmp_path: Path) -> None:
    version_dir = create_tool(tmp_path, "demo-tool")
    assert version_dir == tmp_path / "tools" / "demo-tool" / "1.0.0"
    tool = _load_tool(tmp_path, "demo-tool", "1.0.0")
    assert tool.version == "1.0.0"
    assert tool.libraries == ()
    assert tool.entrypoint == "demo-tool"
    text = (version_dir / "tool.yaml").read_text(encoding="utf-8")
    assert "Latest line of this tool" in text
    nix = (version_dir / "default.nix").read_text(encoding="utf-8")
    assert "where you add Nix package requirements" in nix
    assert (version_dir / "demo_tool.py").is_file()


def test_create_tool_refuses_an_existing_name(tmp_path: Path) -> None:
    create_tool(tmp_path, "demo-tool")
    with pytest.raises(CreateToolError, match="already exists"):
        create_tool(tmp_path, "demo-tool")


def test_create_tool_refuses_a_bad_name(tmp_path: Path) -> None:
    with pytest.raises(CreateToolError, match="not valid"):
        create_tool(tmp_path, "1demo")
    assert not (tmp_path / "tools").exists()


def test_create_tool_command_prints_the_directory(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "ai_agent.cli.catalog_cmd.default_catalog_root",
        lambda: tmp_path,
    )
    assert app_main(["catalog", "create-tool", "demo-tool"]) == 0
    assert "tools/demo-tool/1.0.0" in capsys.readouterr().out
    assert app_main(["catalog", "create-tool", "demo-tool"]) == 1
