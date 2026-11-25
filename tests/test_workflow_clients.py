"""Clients start a workflow through the same conversation API."""

from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.config import Settings
from ai_agent.conversations.db import open_store_at
from ai_agent.workflows.lifecycle import ManualWorkflowLifecycle
from ai_agent.workflows.runtime import attachment_for
from ai_agent.workflows.status import WorkflowStatus
from tests.test_conversations import ALICE, _FakeAgent, _Tokens


def _client(tmp_path):
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    app = create_app(
        Settings(supabase_url="", supabase_anon_key="", supabase_jwt_secret=""),
        _Tokens(),
        store=store,
    )
    seen = []

    def factory(**kwargs):
        seen.append(kwargs.get("workflow_attachment"))
        return _FakeAgent()

    lifecycle = ManualWorkflowLifecycle()

    app.state.agent_factory = factory
    app.state.workflow_lifecycle = lifecycle
    return TestClient(app), store, seen, lifecycle


def test_clients_can_list_and_start_text_lab(tmp_path) -> None:
    client, store, seen, lifecycle = _client(tmp_path)
    headers = {"Authorization": "Bearer alice"}

    listed = client.get("/api/workflows", headers=headers)
    assert listed.status_code == 200
    text_lab = next(item for item in listed.json()["workflows"] if item["name"] == "text-lab")
    assert text_lab["parameters"][0]["name"] == "label"
    assert text_lab["parameters"][0]["required"] is False

    created = client.post(
        "/api/conversations",
        headers=headers,
        json={"workflow": {"name": "text-lab", "parameters": {"label": "north-office"}}},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["title"] == "text-lab"
    assert body["workflow"]["name"] == "text-lab"
    assert body["workflow"]["parameters"] == {"label": "north-office"}
    assert body["workflow"]["status"] == WorkflowStatus.IS_BUILDING
    assert lifecycle.begun[0][0].name == "text-lab"
    assert lifecycle.begun[0][0].container_name.startswith("wf")
    lifecycle.set_status(body["id"], WorkflowStatus.IS_READY)

    saved = store.get_conversation(ALICE, body["id"])
    assert saved is not None
    assert saved.workflow_name == "text-lab"
    assert attachment_for(
        user_id=ALICE,
        conversation_id=saved.id,
        workflow_name=saved.workflow_name,
        parameters=saved.workflow_parameters,
    ).parameters == {"label": "north-office"}

    turned = client.post(
        f"/api/conversations/{body['id']}/turns",
        headers=headers,
        json={"content": "count the lines"},
    )
    assert turned.status_code == 200
    assert seen[0] is not None
    assert seen[0].name == "text-lab"
    assert seen[0].parameters == {"label": "north-office"}


def test_unknown_workflow_is_rejected_before_a_container_starts(tmp_path) -> None:
    client, _store, seen, lifecycle = _client(tmp_path)
    response = client.post(
        "/api/conversations",
        headers={"Authorization": "Bearer alice"},
        json={"workflow": {"name": "missing", "parameters": {}}},
    )
    assert response.status_code == 400
    assert seen == []
    assert lifecycle.begun == []
