"""Turns wait until a workflow image is built and its container is up."""

import logging
import subprocess

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.config import Settings
from ai_agent.conversations.db import open_store_at
from ai_agent.workflows.lifecycle import DockerWorkflowLifecycle, ManualWorkflowLifecycle
from ai_agent.workflows.runtime import attachment_for
from ai_agent.workflows.status import (
    WORKFLOW_NOT_READY_CODE,
    WORKFLOW_NOT_READY_STATUS,
    WORKFLOW_STATUSES,
    WorkflowStatus,
)
from tests.test_conversations import _FakeAgent, _Tokens


def _client(tmp_path, lifecycle):
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    app = create_app(
        Settings(supabase_url="", supabase_anon_key="", supabase_jwt_secret=""),
        _Tokens(),
        store=store,
    )
    app.state.agent_factory = lambda **_kwargs: _FakeAgent()
    app.state.workflow_lifecycle = lifecycle
    return TestClient(app), lifecycle


def _start(client: TestClient) -> str:
    created = client.post(
        "/api/conversations",
        headers={"Authorization": "Bearer alice"},
        json={"workflow": {"name": "text-lab", "parameters": {}}},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_workflow_statuses_are_a_fixed_set() -> None:
    assert [status.value for status in WORKFLOW_STATUSES] == [
        "is_building",
        "is_starting_up",
        "is_ready",
        "is_failed",
    ]


def test_turn_is_refused_while_the_workflow_is_starting(tmp_path) -> None:
    lifecycle = ManualWorkflowLifecycle()
    client, lifecycle = _client(tmp_path, lifecycle)
    headers = {"Authorization": "Bearer alice"}
    conversation_id = _start(client)
    lifecycle.set_status(conversation_id, WorkflowStatus.IS_STARTING_UP)

    refused = client.post(
        f"/api/conversations/{conversation_id}/turns",
        headers=headers,
        json={"content": "count the lines"},
    )
    assert refused.status_code == WORKFLOW_NOT_READY_STATUS
    detail = refused.json()["detail"]
    assert detail["code"] == WORKFLOW_NOT_READY_CODE
    assert detail["status"] == WorkflowStatus.IS_STARTING_UP
    assert "not ready yet" in detail["message"]

    listed = client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert listed.json()["workflow"]["status"] == WorkflowStatus.IS_STARTING_UP

    lifecycle.set_status(conversation_id, WorkflowStatus.IS_READY)
    accepted = client.post(
        f"/api/conversations/{conversation_id}/turns",
        headers=headers,
        json={"content": "count the lines"},
    )
    assert accepted.status_code == 200


def test_failed_workflow_reports_the_docker_error(tmp_path) -> None:
    lifecycle = ManualWorkflowLifecycle()
    client, lifecycle = _client(tmp_path, lifecycle)
    conversation_id = _start(client)
    lifecycle.set_failure(
        conversation_id,
        "permission denied while trying to connect to the Docker daemon socket",
    )

    listed = client.get(
        f"/api/conversations/{conversation_id}",
        headers={"Authorization": "Bearer alice"},
    )
    body = listed.json()["workflow"]
    assert body["status"] == WorkflowStatus.IS_FAILED
    assert "permission denied" in body["error"]


def test_turn_is_refused_while_the_image_is_building(tmp_path) -> None:
    lifecycle = ManualWorkflowLifecycle()
    client, lifecycle = _client(tmp_path, lifecycle)
    conversation_id = _start(client)
    lifecycle.set_status(conversation_id, WorkflowStatus.IS_BUILDING)

    refused = client.post(
        f"/api/conversations/{conversation_id}/turns",
        headers={"Authorization": "Bearer alice"},
        json={"content": "count the lines"},
    )
    assert refused.status_code == WORKFLOW_NOT_READY_STATUS
    assert refused.json()["detail"]["status"] == WorkflowStatus.IS_BUILDING


def test_cached_image_is_not_rebuilt_before_startup() -> None:
    calls: list[list[str]] = []
    started: list[str] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        cached = "inspect" in argv
        return subprocess.CompletedProcess(argv, 0 if cached else 1, "", "")

    lifecycle = DockerWorkflowLifecycle(
        runner=runner,
        start_container=lambda session: started.append(session.container_name),
        spawn=lambda target, args: target(*args),
    )
    attachment = attachment_for(
        user_id="alice",
        conversation_id="11111111-1111-1111-1111-111111111111",
        workflow_name="text-lab",
        parameters={},
    )
    lifecycle.begin(attachment, "alice")

    assert lifecycle.status(attachment.conversation_id) is WorkflowStatus.IS_READY
    assert started == [attachment.container_name]
    assert not any(argv[1:3] == ["buildx", "build"] for argv in calls)


def test_missing_image_is_built_and_then_started() -> None:
    calls: list[list[str]] = []
    started: list[str] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        code = 1 if "inspect" in argv else 0
        return subprocess.CompletedProcess(argv, code, "", "")

    lifecycle = DockerWorkflowLifecycle(
        runner=runner,
        start_container=lambda session: started.append(session.image),
        spawn=lambda target, args: target(*args),
    )
    attachment = attachment_for(
        user_id="alice",
        conversation_id="22222222-2222-2222-2222-222222222222",
        workflow_name="text-lab",
        parameters={},
    )
    lifecycle.begin(attachment, "alice")

    assert [argv[1:3] for argv in calls] == [["image", "inspect"], ["buildx", "build"]]
    assert started
    assert lifecycle.status(attachment.conversation_id) is WorkflowStatus.IS_READY


def test_docker_permission_failure_is_logged_and_not_treated_as_a_build(caplog) -> None:
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        return subprocess.CompletedProcess(
            argv,
            1,
            "",
            "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock",
        )

    lifecycle = DockerWorkflowLifecycle(
        runner=runner,
        start_container=lambda session: None,
        spawn=lambda target, args: target(*args),
    )
    attachment = attachment_for(
        user_id="alice",
        conversation_id="33333333-3333-3333-3333-333333333333",
        workflow_name="text-lab",
        parameters={},
    )
    with caplog.at_level(logging.ERROR):
        status = lifecycle.begin(attachment, "alice")

    assert status is WorkflowStatus.IS_FAILED
    assert lifecycle.status(attachment.conversation_id) is WorkflowStatus.IS_FAILED
    assert "permission denied" in lifecycle.failure(attachment.conversation_id)
    assert "permission denied" in caplog.text
    assert not any(argv[1:3] == ["buildx", "build"] for argv in calls)
