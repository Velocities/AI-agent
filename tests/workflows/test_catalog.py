"""Catalog pins, staged builds, and catalog pull."""

import shutil
import subprocess
from pathlib import Path

from ai_agent.cli.app import main as app_main
from ai_agent.workflows.catalog_pull import pull_catalog
from ai_agent.workflows.image import closure_fingerprint, stage_workflow_context
from ai_agent.workflows.manifests import (
    default_catalog_root,
    load_workflow,
    workflow_engine_root,
)


def test_workflow_lock_names_tools_only() -> None:
    root = default_catalog_root()
    for name in ("text-lab", "product-ideas"):
        text = (root / "workflows" / name / "workflow.lock.json").read_text(encoding="utf-8")
        assert "libraries" not in text
        assert "textkit" not in text
        assert "wordnotes" not in text


def test_text_lab_tools_share_one_textkit_directory() -> None:
    manifest = load_workflow(default_catalog_root(), "text-lab")
    by_name = {tool.name: tool for tool in manifest.tools}
    assert [tool.version for tool in manifest.tools] == ["1.0.0", "1.0.0"]
    assert [lib.name for lib in by_name["count-lines"].libraries] == ["textkit"]
    assert [lib.name for lib in by_name["count-words"].libraries] == ["textkit", "wordnotes"]
    assert (
        by_name["count-lines"].libraries[0].directory
        == by_name["count-words"].libraries[0].directory
    )
    ideas = load_workflow(default_catalog_root(), "product-ideas")
    assert ideas.tools[0].libraries == ()
    assert ideas.tools[0].version == "1.0.0"


def test_stage_copies_only_the_pinned_closure(tmp_path: Path) -> None:
    engine = workflow_engine_root()
    manifest = load_workflow(default_catalog_root(), "product-ideas")
    dest = tmp_path / "stage"
    stage_workflow_context(manifest, engine, dest)
    assert (dest / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py").is_file()
    assert (dest / "tools" / "fetch-pages" / "1.0.0" / "libraries.json").read_text(
        encoding="utf-8"
    ) == "[]\n"
    assert (dest / "Dockerfile").is_file()
    assert (dest / "workflow.lock.json").is_file()
    assert not (dest / "tools" / "count-lines").exists()
    assert not (dest / "workflows").exists()
    assert (dest / "libraries" / ".keep").is_file()


def test_fingerprint_ignores_tools_this_workflow_does_not_pin(tmp_path: Path) -> None:
    catalog = default_catalog_root()
    engine = workflow_engine_root()
    copy = tmp_path / "catalog"
    shutil.copytree(catalog, copy, ignore=shutil.ignore_patterns(".build", ".git"))
    original = closure_fingerprint(load_workflow(catalog, "text-lab"), engine_root=engine)
    page = copy / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py"
    page.write_text(page.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert (
        closure_fingerprint(load_workflow(copy, "text-lab"), engine_root=engine)
        == original
    )
    notes = copy / "libraries" / "wordnotes" / "1.0.0" / "wordnotes.py"
    notes.write_text(notes.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert (
        closure_fingerprint(load_workflow(copy, "text-lab"), engine_root=engine)
        != original
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin"
    tool = origin / "tools" / "fetch-pages" / "1.0.0"
    tool.mkdir(parents=True)
    (origin / "workflows").mkdir()
    (origin / "libraries").mkdir()
    (tool / "fetch_pages.py").write_text("print('one')\n", encoding="utf-8")
    _git(origin, "init", "-b", "main")
    _git(origin, "config", "user.email", "catalog@example.com")
    _git(origin, "config", "user.name", "Catalog Test")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "one")
    return origin


def test_pull_keeps_local_edits_until_force(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    catalog = tmp_path / "catalog"
    subprocess.run(
        ["git", "clone", str(origin), str(catalog)],
        check=True,
        capture_output=True,
        text=True,
    )
    page = catalog / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py"
    page.write_text("print('local')\n", encoding="utf-8")
    (origin / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py").write_text(
        "print('two')\n",
        encoding="utf-8",
    )
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "two")
    skipped = pull_catalog(catalog)
    assert skipped.action == "skipped"
    assert "fetch_pages.py" in skipped.dirty[0]
    assert page.read_text(encoding="utf-8") == "print('local')\n"
    local_workflow = catalog / "workflows" / "mine"
    local_workflow.mkdir(parents=True)
    (local_workflow / "workflow.yaml").write_text("name: mine\n", encoding="utf-8")
    forced = pull_catalog(catalog, force=True)
    assert forced.action == "reset"
    assert page.read_text(encoding="utf-8") == "print('two')\n"
    assert (local_workflow / "workflow.yaml").is_file()


def test_clean_pull_fast_forwards(tmp_path: Path) -> None:
    origin = _origin(tmp_path)
    catalog = tmp_path / "catalog"
    subprocess.run(
        ["git", "clone", str(origin), str(catalog)],
        check=True,
        capture_output=True,
        text=True,
    )
    (origin / "tools" / "count-lines" / "1.0.0").mkdir(parents=True)
    (origin / "tools" / "count-lines" / "1.0.0" / "tool.yaml").write_text(
        "name: count-lines\n",
        encoding="utf-8",
    )
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "add count-lines")
    updated = pull_catalog(catalog)
    assert updated.action == "updated"
    assert (catalog / "tools" / "count-lines" / "1.0.0" / "tool.yaml").is_file()


def test_catalog_pull_command_accepts_force(tmp_path: Path, monkeypatch, capsys) -> None:
    origin = _origin(tmp_path)
    catalog = tmp_path / "catalog"
    subprocess.run(
        ["git", "clone", str(origin), str(catalog)],
        check=True,
        capture_output=True,
        text=True,
    )
    page = catalog / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py"
    page.write_text("print('local')\n", encoding="utf-8")
    (origin / "tools" / "fetch-pages" / "1.0.0" / "fetch_pages.py").write_text(
        "print('remote')\n",
        encoding="utf-8",
    )
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "remote")
    monkeypatch.setenv("WORKFLOW_CATALOG_ROOT", str(catalog))
    monkeypatch.setenv("WORKFLOW_CATALOG_URL", "")
    assert app_main(["catalog", "pull"]) == 1
    assert page.read_text(encoding="utf-8") == "print('local')\n"
    assert app_main(["catalog", "pull", "--force"]) == 0
    assert page.read_text(encoding="utf-8") == "print('remote')\n"
    assert "Reset" in capsys.readouterr().out
