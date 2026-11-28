"""Fetch catalog definitions without rebuilding images or restarting containers."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class CatalogPullError(RuntimeError):
    """The catalog was not updated."""


@dataclass(frozen=True)
class CatalogPullResult:
    action: str
    detail: str
    dirty: tuple[str, ...] = ()


def pull_catalog(catalog: Path, *, url: str = "", force: bool = False) -> CatalogPullResult:
    """Fast-forward a catalog checkout. ``--force`` resets tracked files.

    Untracked files are kept in both modes. This does not build images.
    """
    catalog = catalog.resolve()
    _assert_not_agent_checkout(catalog)
    if not (catalog / ".git").is_dir():
        if not url:
            raise CatalogPullError(
                "This catalog is not a git checkout. "
                "Set WORKFLOW_CATALOG_URL to the catalog repository."
            )
        if _has_definitions(catalog):
            raise CatalogPullError(
                "The catalog already has tools or workflows and is not a git checkout. "
                "Refusing to replace it."
            )
        _clone(url, catalog)
        return CatalogPullResult("cloned", f"Cloned {url} into {catalog}.")
    if url:
        _ensure_origin(catalog, url)
    fetch = _git(catalog, "fetch", "origin")
    if fetch.returncode != 0:
        raise CatalogPullError(_git_text(fetch) or "git fetch failed")
    upstream = _upstream(catalog)
    dirty = _tracked_edits(catalog)
    if dirty and not force:
        listed = "\n".join(f"  {path}" for path in dirty)
        return CatalogPullResult(
            "skipped",
            "Catalog left unchanged. Local edits:\n"
            f"{listed}\n"
            "Re-run with --force to replace tracked files with the upstream catalog.",
            dirty=tuple(dirty),
        )
    if force:
        reset = _git(catalog, "reset", "--hard", upstream)
        if reset.returncode != 0:
            raise CatalogPullError(_git_text(reset) or "git reset failed")
        return CatalogPullResult(
            "reset",
            f"Reset {catalog} to {upstream}. Untracked files were kept.",
        )
    merge = _git(catalog, "merge", "--ff-only", upstream)
    if merge.returncode != 0:
        raise CatalogPullError(
            _git_text(merge)
            or "Could not fast-forward. Re-run with --force to replace tracked files."
        )
    return CatalogPullResult("updated", f"Updated {catalog} from {upstream}.")


def _assert_not_agent_checkout(catalog: Path) -> None:
    if (catalog / "pyproject.toml").is_file() or (catalog / "ai_agent").is_dir():
        raise CatalogPullError(
            "Refusing to pull a catalog that looks like the agent repository."
        )


def _has_definitions(catalog: Path) -> bool:
    for name in ("tools", "libraries", "workflows"):
        directory = catalog / name
        if directory.is_dir() and any(directory.iterdir()):
            return True
    return False


def _clone(url: str, catalog: Path) -> None:
    catalog.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "repo"
        cloned = _git(None, "clone", url, str(destination))
        if cloned.returncode != 0:
            raise CatalogPullError(_git_text(cloned) or "git clone failed")
        for name in ("tools", "libraries", "workflows", ".git"):
            source = destination / name
            if not source.exists():
                continue
            target = catalog / name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(source), str(target))


def _ensure_origin(catalog: Path, url: str) -> None:
    current = _git(catalog, "remote", "get-url", "origin")
    if current.returncode != 0:
        added = _git(catalog, "remote", "add", "origin", url)
        if added.returncode != 0:
            raise CatalogPullError(_git_text(added) or "Could not add origin.")
        return
    if current.stdout.strip() == url:
        return
    updated = _git(catalog, "remote", "set-url", "origin", url)
    if updated.returncode != 0:
        raise CatalogPullError(_git_text(updated) or "Could not set origin.")


def _upstream(catalog: Path) -> str:
    tracking = _git(catalog, "rev-parse", "--abbrev-ref", "@{upstream}")
    if tracking.returncode == 0 and tracking.stdout.strip():
        return tracking.stdout.strip()
    origin_head = _git(catalog, "rev-parse", "--abbrev-ref", "origin/HEAD")
    if origin_head.returncode == 0 and origin_head.stdout.strip():
        return origin_head.stdout.strip()
    raise CatalogPullError("The catalog has no upstream branch to update from.")


def _tracked_edits(catalog: Path) -> list[str]:
    status = _git(catalog, "status", "--porcelain")
    if status.returncode != 0:
        raise CatalogPullError(_git_text(status) or "git status failed")
    edits: list[str] = []
    for line in status.stdout.splitlines():
        if line.startswith("??"):
            continue
        path = line[3:].strip()
        if path:
            edits.append(path)
    return edits


def _git(
    catalog: Path | None,
    *args: str,
) -> subprocess.CompletedProcess[str]:
    command = ["git", *args]
    if catalog is not None:
        # The installer owns this directory as the service user. Pull runs as
        # the admin, and Git refuses that mismatch unless this invocation
        # names the directory.
        command = ["git", "-c", f"safe.directory={catalog.resolve()}", *args]
    return subprocess.run(
        command,
        cwd=catalog,
        check=False,
        capture_output=True,
        text=True,
    )


def _git_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()
