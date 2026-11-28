"""Catalog commands: pull definitions, or scaffold a tool."""

from __future__ import annotations

import sys

from ai_agent.config import Settings
from ai_agent.workflows.catalog_pull import CatalogPullError, pull_catalog
from ai_agent.workflows.create_tool import CreateToolError, create_tool
from ai_agent.workflows.manifests import default_catalog_root

_USAGE = "usage: ai-agent catalog pull [--force]\n   or: ai-agent catalog create-tool <name>"


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"pull", "create-tool"}:
        print(_USAGE, file=sys.stderr)
        return 2
    if argv[0] == "pull":
        return _pull(argv[1:])
    return _create_tool(argv[1:])


def _pull(argv: list[str]) -> int:
    if argv not in ([], ["--force"]):
        print(_USAGE, file=sys.stderr)
        return 2
    settings = Settings()
    try:
        result = pull_catalog(
            default_catalog_root(),
            url=settings.workflow_catalog_url.strip(),
            force=argv == ["--force"],
        )
    except CatalogPullError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.detail)
    if result.action == "skipped":
        return 1
    return 0


def _create_tool(argv: list[str]) -> int:
    if len(argv) != 1:
        print(_USAGE, file=sys.stderr)
        return 2
    name = argv[0]
    try:
        version_dir = create_tool(default_catalog_root(), name)
    except CreateToolError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Created {version_dir}")
    print("tool.yaml sets the version and the JSON interface.")
    print("default.nix is where Nix package requirements are added.")
    print("Pin it from a workflow with:")
    print(f"  - name: {name.strip()}")
    print("    version: 1.0.0")
    return 0
