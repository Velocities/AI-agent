import json

import pytest

from ai_agent.workflows.admin_containers import (
    WORKFLOW_CONTAINER_NAME,
    _container_name,
    _state_matches,
    list_workflow_containers,
    remove_workflow_containers,
)
from ai_agent.workflows.admin_containers import WorkflowContainer


def test_workflow_name_pattern() -> None:
    assert WORKFLOW_CONTAINER_NAME.fullmatch("wf40f11de7c8a9b0012345678abcdef01")
    assert not WORKFLOW_CONTAINER_NAME.fullmatch("text-lab-demo")


def test_container_name_from_docker_field() -> None:
    assert _container_name("/wf40f11de7c8a9b0012345678abcdef01") == (
        "wf40f11de7c8a9b0012345678abcdef01"
    )
    assert _container_name("postgres-wf40f11de7") is None


def test_state_filter_running() -> None:
    running = WorkflowContainer(
        name="wfab" * 8,
        container_id="1",
        image="img",
        state="running",
        status="Up",
        created="",
    )
    assert _state_matches(running, "running")
    assert not _state_matches(running, "stopped")


def test_list_filters_non_workflow_rows() -> None:
    payload = json.dumps(
        {
            "ID": "aaa",
            "Names": "wf40f11de7c8a9b0012345678abcdef01",
            "Image": "ai-agent-workflow:text-lab-deadbeefcafebabe",
            "State": "running",
            "Status": "Up 2 hours",
            "CreatedAt": "2026-03-21 10:00:00 -0400 EDT",
        }
    )
    other = json.dumps(
        {
            "ID": "bbb",
            "Names": "nginx",
            "Image": "nginx",
            "State": "running",
            "Status": "Up",
            "CreatedAt": "",
        }
    )

    def fake(argv: list[str]):
        import subprocess

        return subprocess.CompletedProcess(argv, 0, f"{payload}\n{other}\n", "")

    rows = list_workflow_containers(runner=fake)
    assert len(rows) == 1
    assert rows[0].name == "wf40f11de7c8a9b0012345678abcdef01"


def test_remove_validates_names() -> None:
    with pytest.raises(ValueError, match="not a workflow container"):
        remove_workflow_containers(["nginx"], runner=lambda argv: None)  # type: ignore[arg-type]


def test_remove_invokes_docker_rm() -> None:
    captured: list[list[str]] = []

    def fake(argv: list[str]):
        import subprocess

        captured.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    removed = remove_workflow_containers(["wf40f11de7c8a9b0012345678abcdef01"], runner=fake)
    assert removed == ["wf40f11de7c8a9b0012345678abcdef01"]
    assert captured[0][:3] == ["docker", "rm", "-f"]