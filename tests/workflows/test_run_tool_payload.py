"""run_tool returns structured output only."""

import json

from ai_agent.agent.tool_handler import ToolHandler
from ai_agent.workflows.manifests import WorkflowTool


def _fetch_pages_tool() -> WorkflowTool:
    return WorkflowTool(
        name="fetch-pages",
        version="0.1.0",
        description="",
        nix_attr="fetch-pages",
        entrypoint="fetch-pages",
        input_schema={"type": "object", "required": ["urls"], "properties": {}},
        output_schema={
            "type": "object",
            "required": ["pages", "fetched", "failed"],
            "properties": {
                "pages": {"type": "array"},
                "fetched": {"type": "integer"},
                "failed": {"type": "integer"},
            },
        },
    )


def test_run_tool_payload_drops_stdout() -> None:
    tool = _fetch_pages_tool()
    stdout = json.dumps({"pages": [], "fetched": 0, "failed": 0})
    payload = {
        "success": True,
        "exit_status": 0,
        "stdout": stdout,
        "stderr": "",
        "execution_target": {"name": "sandbox", "kind": "sandbox"},
    }
    slim = ToolHandler._run_tool_payload(payload, tool)
    assert "stdout" not in slim
    assert slim["output"] == {"pages": [], "fetched": 0, "failed": 0}