import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_agent.agent.loop import AgentLoop
from ai_agent.agent.tools import build_tool_definitions
from ai_agent.api.approvals import ApprovalBroker, RemoteApprovalPrompter
from ai_agent.approval.prompt import ApprovalPrompter, ApprovalResult, PendingCommand
from ai_agent.approval.selection import (
    apply_cascade,
    partial_batch_note,
    resolve_choices,
    resolve_selection,
)
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.ast import SingleCommand
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import ConfirmationMode, Settings
from ai_agent.llm.base import LLMMessage, LLMResponse, ToolCall
from ai_agent.policy.engine import PolicyDecision, PolicyEngine
from ai_agent.policy.risk import RiskLevel

ALICE = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def agent_parts(tmp_path: Path):
    settings = Settings()
    settings.agent_max_iterations = 3
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    executor = CommandExecutor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path / "scratch",
    )
    audit = AuditLogger(log_path=tmp_path / "audit.jsonl", user="test")
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, MagicMock())
    llm = MagicMock()
    agent = AgentLoop(
        settings=settings,
        llm=llm,
        policy=policy,
        executor=executor,
        audit=audit,
        prompter=prompter,
        session=session,
    )
    return agent, llm, audit


def _decision(argv: list[str]) -> PolicyDecision:
    return PolicyDecision(
        expr=SingleCommand(argv=argv),
        effective_risk=RiskLevel.READ_ONLY,
        segments=[],
        allowed=True,
        reason="inspect",
    )


def test_ordered_cascade_rejects_everything_after_the_first_gap() -> None:
    groups = [0, 0, 0, 0]
    assert apply_cascade([True, False, True, True], groups) == [True, False, False, False]
    assert apply_cascade([False, True, True], groups[:3]) == [False, False, False]


def test_unordered_choices_stay_independent() -> None:
    groups = [None, None, None]
    assert apply_cascade([True, False, True], groups) == [True, False, True]


def test_cascade_stays_inside_one_sequence() -> None:
    groups = [0, 0, None, 1, 1]
    assert apply_cascade([True, False, True, False, True], groups) == [
        True,
        False,
        True,
        False,
        False,
    ]


def test_resolve_choices_requires_every_id_once() -> None:
    groups = [0, 0, 0, 0]
    try:
        resolve_choices([(1, "accept"), (2, "reject")], 4, groups)
    except ValueError as exc:
        assert "Missing: 3, 4" in str(exc)
    else:
        raise AssertionError("missing ids should be rejected")

    try:
        resolve_choices(
            [(1, "accept"), (1, "reject"), (2, "accept"), (3, "accept"), (4, "accept")],
            4,
            groups,
        )
    except ValueError as exc:
        assert "more than once" in str(exc)
    else:
        raise AssertionError("duplicate ids should be rejected")

    approved, accepted, cascade = resolve_choices(
        [(1, "accept"), (2, "reject"), (3, "accept"), (4, "accept")],
        4,
        groups,
    )
    assert approved is False
    assert accepted == (True, False, False, False)
    assert cascade == (False, False, True, True)

    approved, accepted, _cascade = resolve_choices(
        [(1, "accept"), (2, "accept"), (3, "accept"), (4, "accept")],
        4,
        groups,
    )
    assert approved is True
    assert accepted is None

    approved, accepted, _cascade = resolve_choices(
        [(1, "reject"), (2, "reject"), (3, "reject"), (4, "reject")],
        4,
        [None, None, None, None],
    )
    assert approved is False
    assert accepted is None


def test_partial_note_names_approved_commands_and_ordered_skips() -> None:
    note = partial_batch_note(
        [
            ("pwd", True, False),
            ("whoami", False, False),
            ("echo hi", False, True),
        ]
    )
    assert note is not None
    assert note.startswith("The user only approved these commands you requested in the batch: 1. pwd.")
    assert "The user rejected: 2. whoami." in note
    assert "earlier command in this ordered batch was rejected: 3. echo hi." in note
    assert partial_batch_note([("pwd", True, False), ("whoami", True, False)]) is None
    assert partial_batch_note([("pwd", False, False)]) is None


def test_batch_tool_requires_an_ordering() -> None:
    tools = build_tool_definitions(["local"])
    run_commands = next(item for item in tools if item["function"]["name"] == "run_commands")
    parameters = run_commands["function"]["parameters"]
    assert parameters["properties"]["ordering"]["enum"] == ["ordered", "unordered"]
    assert "ordering" in parameters["required"]
    assert "ordered" in run_commands["function"]["description"]


def _pending(*commands: list[str]) -> list[PendingCommand]:
    return [
        PendingCommand(expr=SingleCommand(argv=argv), decision=_decision(argv), reason="inspect")
        for argv in commands
    ]


def test_local_prompter_can_approve_all_or_select_an_ordered_prefix(monkeypatch) -> None:
    prompter = ApprovalPrompter(ConfirmationMode.PARANOID, ApprovalSession(), MagicMock())
    pending = _pending(["pwd"], ["whoami"], ["echo", "hi"])

    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    approved = prompter.prompt_batch(pending, order_groups=[0, 0, 0])
    assert approved == ApprovalResult(approved=True)

    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    denied = prompter.prompt_batch(pending, order_groups=[0, 0, 0])
    assert denied == ApprovalResult(approved=False)

    answers = iter(["s", "y", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    selected = prompter.prompt_batch(pending, order_groups=[0, 0, 0])
    assert selected.accepted == (True, False, False)
    assert selected.cascade_rejected == (False, False, True)
    assert next(answers, None) is None


def test_approval_event_carries_ids_and_ordered_cascade() -> None:
    broker = ApprovalBroker()
    seen: list[dict] = []
    prompter = RemoteApprovalPrompter(
        ConfirmationMode.PARANOID,
        ApprovalSession(),
        broker,
        user_id=ALICE,
        conversation_id="chat",
        emit=seen.append,
        cancel=threading.Event(),
        timeout=5,
    )

    def respond() -> None:
        while not seen:
            threading.Event().wait(0.01)
        event = seen[0]
        assert event["ordering"] == "ordered"
        assert [item["id"] for item in event["commands"]] == [1, 2, 3]
        assert event["commands"][2]["order_group"] == 0
        assert broker.resolve(
            user_id=ALICE,
            conversation_id="chat",
            approval_id=event["approval_id"],
            approved=False,
            grant_scope=None,
            decisions=[(1, "accept"), (2, "reject"), (3, "accept")],
        )

    threading.Thread(target=respond, daemon=True).start()
    result = prompter.prompt_batch(
        _pending(["pwd"], ["whoami"], ["echo", "hi"]),
        order_groups=[0, 0, 0],
    )
    assert result.approved is False
    assert result.accepted == (True, False, False)
    assert result.cascade_rejected == (False, False, True)


def _batch_turn(
    agent,
    llm,
    *,
    ordering: str | None,
    approval: ApprovalResult,
) -> tuple[list[dict], list]:
    seen: dict = {}

    def prompt_batch(pending, order_groups=None):
        seen["groups"] = order_groups
        seen["count"] = len(pending)
        return approval

    agent.prompter.prompt_batch = prompt_batch
    arguments = {
        "reason": "inspect",
        "commands": [
            {"type": "single", "argv": ["pwd"]},
            {"type": "single", "argv": ["whoami"]},
            {"type": "single", "argv": ["echo", "hi"]},
        ],
    }
    if ordering is not None:
        arguments["ordering"] = ordering
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(id="1", name="run_commands", arguments=arguments),
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"finished": True, "message": "Done."},
                    )
                ],
            )
        ),
    ]
    result = agent.run("inspect")
    assert result.final_message == "Done."
    assert seen["count"] == 3
    tool_messages = [message for message in agent.messages if message.role == "tool"]
    return json.loads(tool_messages[0].content), seen["groups"]


def test_ordered_partial_approval_runs_the_prefix_and_tells_the_model(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    approved, _accepted, cascade = resolve_selection([True, False, True], [0, 0, 0])
    payloads, groups = _batch_turn(
        agent,
        llm,
        ordering="ordered",
        approval=ApprovalResult(
            approved=approved,
            accepted=_accepted,
            cascade_rejected=cascade,
        ),
    )
    assert groups == [0, 0, 0]
    assert payloads[0]["success"] is True
    assert payloads[0]["user_decision"] == "accept"
    assert "pwd" in payloads[0]["stdout"] or payloads[0]["rendered_command"] == "pwd"
    assert payloads[1]["user_denied"] is True
    assert payloads[1]["user_decision"] == "reject"
    assert payloads[2]["rejected_by_order"] is True
    assert payloads[2]["success"] is False
    assert "echo" not in payloads[2].get("stdout", "")
    note = payloads[0]["batch_approval"]
    assert note.startswith("The user only approved these commands you requested in the batch:")
    assert "1. pwd" in note
    assert "whoami" in note
    assert "echo hi" in note
    assert payloads[1]["batch_approval"] == note
    assert payloads[2]["batch_approval"] == note


def test_unordered_partial_approval_runs_the_selected_commands(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    approved, accepted, cascade = resolve_selection([True, False, True], [None, None, None])
    payloads, groups = _batch_turn(
        agent,
        llm,
        ordering="unordered",
        approval=ApprovalResult(
            approved=approved,
            accepted=accepted,
            cascade_rejected=cascade,
        ),
    )
    assert groups == [None, None, None]
    assert [item["success"] for item in payloads] == [True, False, True]
    assert payloads[1]["user_denied"] is True
    assert "rejected_by_order" not in payloads[2]
    assert "hi" in payloads[2]["stdout"]
    assert "1. pwd" in payloads[0]["batch_approval"]
    assert "3. echo hi" in payloads[0]["batch_approval"]


@pytest.mark.parametrize(
    ("approved", "expect_success"),
    [(True, True), (False, False)],
)
def test_whole_batch_approval_is_unchanged(agent_parts, approved: bool, expect_success: bool) -> None:
    agent, llm, _audit = agent_parts
    payloads, groups = _batch_turn(
        agent,
        llm,
        ordering="ordered",
        approval=ApprovalResult(approved=approved),
    )
    assert groups == [0, 0, 0]
    assert [item["success"] for item in payloads] == [expect_success] * 3
    assert all("batch_approval" not in item for item in payloads)
    if not expect_success:
        assert all(item["user_denied"] is True for item in payloads)


def test_omitted_ordering_stays_unordered(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    _payloads, groups = _batch_turn(
        agent,
        llm,
        ordering=None,
        approval=ApprovalResult(approved=True),
    )
    assert groups == [None, None, None]


def test_invalid_ordering_is_a_tool_error(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_commands",
                        arguments={
                            "reason": "inspect",
                            "ordering": "series",
                            "commands": [{"type": "single", "argv": ["pwd"]}],
                        },
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"finished": True, "message": "Done."},
                    )
                ],
            )
        ),
    ]
    result = agent.run("inspect")
    assert result.final_message == "Done."
    payload = json.loads(next(message.content for message in agent.messages if message.role == "tool"))
    assert payload["success"] is False
    assert "ordering" in payload["error"]


def _risk_pending(argv: list[str], risk: RiskLevel) -> PendingCommand:
    expr = SingleCommand(argv=argv)
    return PendingCommand(
        expr=expr,
        decision=PolicyDecision(
            expr=expr,
            effective_risk=risk,
            segments=[],
            allowed=True,
            reason="inspect",
        ),
        reason="inspect",
    )


def test_mixed_risk_batch_asks_once_and_does_not_offer_a_session_grant(monkeypatch) -> None:
    prompter = ApprovalPrompter(ConfirmationMode.BALANCED, ApprovalSession(), MagicMock())
    pending = [
        _risk_pending(["uptime"], RiskLevel.READ_ONLY),
        _risk_pending(["dmesg"], RiskLevel.DESTRUCTIVE),
        _risk_pending(["last"], RiskLevel.DESTRUCTIVE),
    ]
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "y")
    result = prompter.prompt_batch(pending, order_groups=[None, None, None])
    assert result == ApprovalResult(approved=True)
    assert prompts == ["\nProceed with batch? (y/n/s) "]


def test_permissive_destructive_batch_still_asks_once(monkeypatch) -> None:
    prompter = ApprovalPrompter(ConfirmationMode.PERMISSIVE, ApprovalSession(), MagicMock())
    pending = [
        _risk_pending(["dmesg"], RiskLevel.DESTRUCTIVE),
        _risk_pending(["last"], RiskLevel.DESTRUCTIVE),
    ]
    prompts: list[str] = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "n")
    result = prompter.prompt_batch(pending, order_groups=[None, None, None])
    assert result == ApprovalResult(approved=False)
    assert len(prompts) == 1


def test_permissive_read_only_batch_runs_without_a_prompt(monkeypatch) -> None:
    prompter = ApprovalPrompter(ConfirmationMode.PERMISSIVE, ApprovalSession(), MagicMock())

    def refuse_prompt(_prompt: str = "") -> str:
        raise AssertionError("a read-only batch should not prompt in permissive mode")

    monkeypatch.setattr("builtins.input", refuse_prompt)
    assert prompter.prompt_batch(_pending(["pwd"], ["whoami"])) == ApprovalResult(approved=True)


def test_remote_mixed_batch_is_one_approval() -> None:
    broker = ApprovalBroker()
    seen: list[dict] = []
    prompter = RemoteApprovalPrompter(
        ConfirmationMode.BALANCED,
        ApprovalSession(),
        broker,
        user_id=ALICE,
        conversation_id="chat",
        emit=seen.append,
        cancel=threading.Event(),
        timeout=5,
    )
    pending = [
        _risk_pending(["uptime"], RiskLevel.READ_ONLY),
        _risk_pending(["dmesg"], RiskLevel.DESTRUCTIVE),
    ]

    def respond() -> None:
        while not seen:
            threading.Event().wait(0.01)
        event = seen[0]
        assert [item["command"] for item in event["commands"]] == ["uptime", "dmesg"]
        assert {item["risk"] for item in event["commands"]} == {"READ_ONLY", "DESTRUCTIVE"}
        assert broker.resolve(
            user_id=ALICE,
            conversation_id="chat",
            approval_id=event["approval_id"],
            approved=True,
            grant_scope=None,
            decisions=None,
        )

    threading.Thread(target=respond, daemon=True).start()
    result = prompter.prompt_batch(pending, order_groups=[None, None])
    assert result == ApprovalResult(approved=True)
    assert len(seen) == 1


def test_stringified_commands_array_runs_as_one_batch(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    commands = [
        {"type": "single", "argv": ["pwd"]},
        {"type": "single", "argv": ["whoami"]},
    ]
    seen: dict = {}

    def prompt_batch(pending, order_groups=None):
        seen["count"] = len(pending)
        return ApprovalResult(approved=True)

    agent.prompter.prompt_batch = prompt_batch
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_commands",
                        arguments={
                            "reason": "inspect",
                            "ordering": "unordered",
                            "commands": json.dumps(commands),
                        },
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"finished": True, "message": "Done."},
                    )
                ],
            )
        ),
    ]
    result = agent.run("inspect")
    assert result.final_message == "Done."
    assert seen["count"] == 2
    payloads = json.loads(next(message.content for message in agent.messages if message.role == "tool"))
    assert [item["success"] for item in payloads] == [True, True]


def test_string_that_is_not_an_array_tells_the_model_not_to_split(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_commands",
                        arguments={
                            "reason": "inspect",
                            "ordering": "unordered",
                            "commands": "uptime && df",
                        },
                    )
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="2",
                        name="respond",
                        arguments={"finished": True, "message": "Done."},
                    )
                ],
            )
        ),
    ]
    result = agent.run("inspect")
    assert result.final_message == "Done."
    payload = json.loads(next(message.content for message in agent.messages if message.role == "tool"))
    assert payload["success"] is False
    assert "not a string" in payload["error"]
    assert "Do not split" in payload["error"]


def test_separate_calls_with_mixed_risk_stay_one_batch(agent_parts) -> None:
    agent, llm, _audit = agent_parts
    seen: dict = {}

    def prompt_batch(pending, order_groups=None):
        seen["commands"] = [item.decision.expr.argv for item in pending]
        return ApprovalResult(approved=False)

    agent.prompter.prompt_batch = prompt_batch
    llm.chat.side_effect = [
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="run_command",
                        arguments={
                            "reason": "uptime",
                            "command": {"type": "single", "argv": ["uptime"]},
                        },
                    ),
                    ToolCall(
                        id="2",
                        name="run_command",
                        arguments={
                            "reason": "kernel log",
                            "command": {"type": "single", "argv": ["dmesg"]},
                        },
                    ),
                ],
            )
        ),
        LLMResponse(
            message=LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="3",
                        name="respond",
                        arguments={"finished": True, "message": "Done."},
                    )
                ],
            )
        ),
    ]
    result = agent.run("inspect")
    assert result.final_message == "Done."
    assert seen["commands"] == [["uptime"], ["dmesg"]]
    payloads = [
        json.loads(message.content)
        for message in agent.messages
        if message.role == "tool" and message.name == "run_command"
    ]
    assert len(payloads) == 2
    assert all(item["user_denied"] is True for item in payloads)
