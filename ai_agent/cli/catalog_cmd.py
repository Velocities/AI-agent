"""Pull workflow, tool, and library definitions."""

from __future__ import annotations

import sys

from ai_agent.config import Settings
from ai_agent.workflows.catalog_pull import CatalogPullError, pull_catalog
from ai_agent.workflows.manifests import default_catalog_root


def main(argv: list[str]) -> int:
    if argv != ["pull"] and argv != ["pull", "--force"]:
        print("usage: ai-agent catalog pull [--force]", file=sys.stderr)
        return 2
    settings = Settings()
    try:
        result = pull_catalog(
            default_catalog_root(),
            url=settings.workflow_catalog_url.strip(),
            force=argv == ["pull", "--force"],
        )
    except CatalogPullError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(result.detail)
    if result.action == "skipped":
        return 1
    return 0
