import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from ai_agent.agent.loop import AgentLoop
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.llm.client.provider import FacadeLlmClient
from ai_agent.llm.client.streaming import (
    RespondMessageStreamer,
    ResumeOverlapTrimmer,
    sanitize_terminal_text,
    trim_resume_overlap,
)
from ai_agent.llm.client.types import LLMMessage, LLMResponse, StreamChunk, ToolCall
from ai_agent.llm.http.errors import LLMErrorKind
from ai_agent.llm.http.session import LlmHttpSession
from ai_agent.policy.engine import PolicyEngine


def test_respond_streamer_streams_message_incrementally() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "Hello') == "Hello"
    assert streamer.feed(' world"') == " world"


def test_respond_streamer_streams_before_finished_field() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "Hel') == "Hel"
    assert streamer.feed('lo"') == "lo"


def test_respond_streamer_ignores_finished_false_messages() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": false, "message": "Working') == ""
    assert streamer.feed(' still"}') == ""


def test_respond_streamer_decodes_json_escapes() -> None:
    streamer = RespondMessageStreamer()
    text = streamer.feed(r'{"finished": true, "message": "line1\nline2"}')
    assert text == "line1\nline2"


def test_respond_streamer_holds_incomplete_unicode_escape() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed(r'{"finished": true, "message": "test \uD83D') == "test "
    assert streamer.feed(r'\uDE00"}') == "\U0001f600"


def test_respond_streamer_holds_incomplete_escape_sequence() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "line1\\') == "line1"
    assert streamer.feed(r'nline2"}') == "\nline2"


def test_respond_streamer_flush_message_emits_remainder() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "Hello') == "Hello"
    assert streamer.flush_message("Hello world") == " world"


def test_respond_streamer_flush_message_uses_partial_json() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "Hello wo') == "Hello wo"
    assert streamer.flush_message("") == ""


def test_respond_streamer_flush_message_prefers_longest_source() -> None:
    streamer = RespondMessageStreamer()
    assert streamer.feed('{"finished": true, "message": "Hello wo') == "Hello wo"
    assert streamer.flush_message("Hello world") == "rld"


def test_sanitize_terminal_text_replaces_lone_surrogates() -> None:
    assert sanitize_terminal_text("hello\ud83eworld") == "hello\ufffdworld"


def test_trim_resume_overlap_removes_restated_tail() -> None:
    tail = "Common mistakes include catching overly broad"
    text = "Common mistakes include catching overly broad exceptions."
    assert trim_resume_overlap(tail, text) == " exceptions."


def test_trim_resume_overlap_skips_repeat_after_new_heading() -> None:
    tail = "Common mistakes include catching overly broad"
    text = "# Continuing\n\nCommon mistakes include catching overly broad exceptions."
    assert trim_resume_overlap(tail, text) == " exceptions."


def test_trim_resume_overlap_ignores_short_repeats() -> None:
    # Short matches are left alone: a visible seam beats deleting real content.
    tail = "try:\n    result = 10 / denominator\nexcept"
    text = " except ZeroDivisionError:"
    assert trim_resume_overlap(tail, text) == text


def test_trim_resume_overlap_keeps_clean_continuation() -> None:
    tail = "Common mistakes include catching overly broad"
    text = " exceptions that hide real bugs."
    assert trim_resume_overlap(tail, text) == text


def test_trim_resume_overlap_ignores_tiny_tails() -> None:
    assert trim_resume_overlap("ab", "abcdef") == "abcdef"


def test_resume_overlap_trimmer_streams_after_scan_window() -> None:
    tail = "Common mistakes include catching overly broad"
    trimmer = ResumeOverlapTrimmer(tail)

    assert trimmer.feed("Common mistakes include catching overly broad") == ""
    assert trimmer.feed(" exceptions.") == ""
    assert trimmer.flush() == " exceptions."
    assert trimmer.feed(" More text.") == " More text."


def test_resume_overlap_trimmer_passes_through_without_tail() -> None:
    trimmer = ResumeOverlapTrimmer("")
    assert trimmer.feed("hello") == "hello"
    assert trimmer.flush() == ""


class _MockStream:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://localhost:11434/api/chat")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def iter_lines(self):
        yield from self._lines


class _MockClient:
    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self._status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def stream(self, method: str, url: str, json: dict):
        assert method == "POST"
        assert url.endswith("/api/chat")
        assert json["stream"] is True
        return _MockStream(self._lines, self._status_code)


def test_ollama_chat_stream_yields_tool_argument_deltas(monkeypatch) -> None:
    lines = [
        json.dumps(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "respond",
                                "arguments": '{"finished": true, "message": "Hel',
                            }
                        }
                    ],
                },
                "done": False,
            }
        ),
        json.dumps(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "respond",
                                "arguments": 'lo"}',
                            }
                        }
                    ],
                },
                "done": True,
            }
        ),
    ]
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda timeout: _MockClient(lines),
    )

    provider = FacadeLlmClient(LlmHttpSession("http://localhost:11434"), "test-model")
    chunks = list(
        provider.chat_stream(
            [LLMMessage(role="user", content="hello")],
            tools=[{"type": "function", "function": {"name": "respond"}}],
        )
    )

    tool_deltas = [
        chunk.tool_arguments_delta
        for chunk in chunks
        if chunk.tool_arguments_delta
    ]
    assert "".join(tool_deltas) == '{"finished": true, "message": "Hello"}'
    final = chunks[-1]
    assert final.done is True
    assert final.response is not None
    assert final.response.message.tool_calls[0].arguments == {
        "finished": True,
        "message": "Hello",
    }


def test_ollama_chat_stream_sends_context_options(monkeypatch) -> None:
    captured: dict = {}

    class _CapturingClient(_MockClient):
        def stream(self, method: str, url: str, json: dict):
            captured.update(json)
            return _MockStream(self._lines, self._status_code)

    lines = [
        json.dumps(
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": "hi"},
                "done": True,
                "done_reason": "stop",
            }
        )
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: _CapturingClient(lines))

    provider = FacadeLlmClient(
        LlmHttpSession("http://localhost:11434"),
        "test-model",
        num_ctx=16384,
        num_predict=4096,
    )
    chunks = list(provider.chat_stream([LLMMessage(role="user", content="hello")]))

    assert captured["options"] == {"num_ctx": 16384, "num_predict": 4096}
    assert chunks[-1].response is not None
    assert chunks[-1].response.stop_reason == "stop"


def test_ollama_chat_stream_reports_length_stop_reason(monkeypatch) -> None:
    lines = [
        json.dumps(
            {
                "model": "test-model",
                "message": {"role": "assistant", "content": "partial"},
                "done": True,
                "done_reason": "length",
            }
        )
    ]
    monkeypatch.setattr(httpx, "Client", lambda timeout: _MockClient(lines))

    provider = FacadeLlmClient(LlmHttpSession("http://localhost:11434"), "test-model")
    chunks = list(provider.chat_stream([LLMMessage(role="user", content="hello")]))

    assert chunks[-1].response is not None
    assert chunks[-1].response.stop_reason == "length"
    assert chunks[-1].response.error is None


def test_ollama_chat_stream_handles_interrupted_stream(monkeypatch) -> None:
    class _BrokenStream(_MockStream):
        def iter_lines(self):
            yield self._lines[0]
            raise httpx.ReadError("connection reset")

    class _BrokenClient(_MockClient):
        def stream(self, method: str, url: str, json: dict):
            return _BrokenStream(self._lines, self._status_code)

    lines = [
        json.dumps(
            {
                "model": "test-model",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "respond",
                                "arguments": '{"finished": true, "message": "Partial',
                            }
                        }
                    ],
                },
                "done": False,
            }
        ),
    ]
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda timeout: _BrokenClient(lines),
    )

    provider = FacadeLlmClient(LlmHttpSession("http://localhost:11434"), "test-model")
    chunks = list(provider.chat_stream([LLMMessage(role="user", content="hello")]))

    assert chunks[-1].done is True
    assert chunks[-1].error_kind == LLMErrorKind.STREAM_INTERRUPTED
    assert chunks[-1].error == "LLM stream was interrupted."
    assert chunks[-1].response is not None
    malformed = chunks[-1].response.message.tool_calls[0].arguments.get("_malformed", "")
    assert "Partial" in malformed


@pytest.fixture
def agent_parts(tmp_path: Path):
    settings = Settings()
    settings.agent_max_iterations = 3
    settings.agent_stream_responses = True
    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    executor = CommandExecutor(
        timeout=5,
        output_limit=1024,
        scratch_dir=tmp_path / "scratch",
    )
    audit_log = tmp_path / "audit.jsonl"
    audit = AuditLogger(log_path=audit_log, user="test")
    session = ApprovalSession()
    console = MagicMock()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, console)
    prompter.should_auto_run = MagicMock(return_value=True)
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
    return agent, llm, audit_log


def test_agent_streams_plain_text_answer_token_by_token(agent_parts) -> None:
    agent, llm, _ = agent_parts
    tokens = ["Add", " a", " Django", " model", " first."]

    def fake_chat_stream(messages, tools=None):
        for token in tokens:
            yield StreamChunk(content_delta=token)
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content="".join(tokens))
            ),
        )

    llm.chat_stream = MagicMock(side_effect=fake_chat_stream)
    streamed: list[str] = []
    result = agent.run("how do I add a table?", stream_callback=streamed.append)

    assert streamed == tokens
    assert result.final_message == "Add a Django model first."
    assert result.error is None
    assert llm.chat_stream.call_count == 1


def test_agent_streams_answer_after_tool_call(agent_parts) -> None:
    agent, llm, _ = agent_parts

    def first_stream(messages, tools=None):
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="run_command",
                            arguments={
                                "reason": "inspect",
                                "command": {"type": "single", "argv": ["docker", "ps"]},
                            },
                        )
                    ],
                )
            ),
        )

    def second_stream(messages, tools=None):
        yield StreamChunk(content_delta="Docker ")
        yield StreamChunk(content_delta="is running.")
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content="Docker is running.")
            ),
        )

    stream_calls = iter([first_stream, second_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )

    streamed: list[str] = []
    result = agent.run("is docker up?", stream_callback=streamed.append)

    assert streamed == ["Docker ", "is running."]
    assert result.final_message == "Docker is running."


def test_agent_streams_resumed_answer_as_one_flow(agent_parts) -> None:
    agent, llm, _ = agent_parts
    tail = "Common mistakes include catching overly broad"

    def cut_off_stream(messages, tools=None):
        yield StreamChunk(content_delta=tail)
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content=tail),
                stop_reason="length",
            ),
        )

    def resumed_stream(messages, tools=None):
        text = f"# Continuing\n\n{tail} exceptions."
        yield StreamChunk(content_delta=text)
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content=text)
            ),
        )

    stream_calls = iter([cut_off_stream, resumed_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )

    streamed: list[str] = []
    result = agent.run("explain error handling", stream_callback=streamed.append)

    assert "".join(streamed) == f"{tail} exceptions."
    assert result.final_message == f"{tail} exceptions."
    assert result.error is None


def test_agent_flushes_plain_content_not_seen_in_deltas(agent_parts) -> None:
    agent, llm, _ = agent_parts

    def fake_chat_stream(messages, tools=None):
        yield StreamChunk(content_delta="Hello")
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content="Hello world")
            ),
        )

    llm.chat_stream = MagicMock(side_effect=fake_chat_stream)
    streamed: list[str] = []
    result = agent.run("hello", stream_callback=streamed.append)

    assert "".join(streamed) == "Hello world"
    assert result.final_message == "Hello world"


def test_agent_flushes_respond_tail_after_interrupted_json(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_iterations = 5

    def interrupted_stream(messages, tools=None):
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='{"finished": true, "message": "Hello wo',
        )
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="respond",
                            arguments={
                                "_malformed": '{"finished": true, "message": "Hello wo',
                            },
                        )
                    ],
                ),
                error="LLM stream was interrupted.",
                error_kind=LLMErrorKind.STREAM_INTERRUPTED,
            ),
            error="LLM stream was interrupted.",
            error_kind=LLMErrorKind.STREAM_INTERRUPTED,
        )

    def completed_stream(messages, tools=None):
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='{"finished": true, "message": "rld."}',
        )
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="2",
                            name="respond",
                            arguments={"finished": True, "message": "rld."},
                        )
                    ],
                )
            ),
        )

    stream_calls = iter([interrupted_stream, completed_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )
    streamed: list[str] = []
    result = agent.run("hello", stream_callback=streamed.append)

    assert streamed == ["Hello wo", "rld."]
    assert result.final_message == "rld."
    assert llm.chat_stream.call_count == 2


def test_agent_stream_callback_receives_final_respond_message(agent_parts) -> None:
    agent, llm, _ = agent_parts

    def fake_chat_stream(messages, tools=None):
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='{"finished": true, "message": "Hello ',
        )
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='world"}',
        )
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="respond",
                            arguments={
                                "finished": True,
                                "message": "Hello world",
                            },
                        )
                    ],
                )
            ),
        )

    llm.chat_stream = MagicMock(side_effect=fake_chat_stream)
    streamed: list[str] = []
    result = agent.run("hello", stream_callback=streamed.append)

    assert "".join(streamed) == "Hello world"
    assert result.final_message == "Hello world"
    assert llm.chat_stream.call_count == 1
    assert llm.chat.call_count == 0


def test_agent_routes_progress_notes_away_from_answer_text(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_max_iterations = 5

    def first_stream(messages, tools=None):
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='{"finished": false, "message": "Working"}',
        )
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="respond",
                            arguments={
                                "finished": False,
                                "message": "Working",
                            },
                        )
                    ],
                )
            ),
        )

    def second_stream(messages, tools=None):
        yield StreamChunk(
            tool_name="respond",
            tool_arguments_delta='{"finished": true, "message": "Done."}',
        )
        yield StreamChunk(
            done=True,
            response=LLMResponse(
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
        )

    stream_calls = iter([first_stream, second_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )

    streamed: list[str] = []
    notices: list[str] = []
    result = agent.run(
        "hello",
        stream_callback=streamed.append,
        notice_callback=notices.append,
    )

    assert streamed == ["Done."]
    assert notices == ["Working"]
    assert result.final_message == "Done."
    assert llm.chat_stream.call_count == 2
    llm.chat.assert_not_called()


def test_string_command_argument_returns_tool_error(agent_parts) -> None:
    agent, llm, _ = agent_parts

    def first_stream(messages, tools=None):
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="run_command",
                            arguments={"reason": "inspect", "command": "docker ps"},
                        )
                    ],
                )
            ),
        )

    def second_stream(messages, tools=None):
        yield StreamChunk(content_delta="Recovered.")
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content="Recovered.")
            ),
        )

    stream_calls = iter([first_stream, second_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )

    result = agent.run("show docker", stream_callback=lambda _text: None)

    assert result.final_message == "Recovered."
    tool_messages = [message for message in agent.messages if message.role == "tool"]
    assert tool_messages
    payload = json.loads(tool_messages[-1].content)
    assert payload["success"] is False
    assert "Invalid command expression" in payload["error"]


def test_string_command_in_batch_returns_tool_error(agent_parts) -> None:
    agent, llm, _ = agent_parts

    def first_stream(messages, tools=None):
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(
                    role="assistant",
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="1",
                            name="run_commands",
                            arguments={
                                "reason": "inspect",
                                "commands": ["docker ps", "df -h"],
                            },
                        )
                    ],
                )
            ),
        )

    def second_stream(messages, tools=None):
        yield StreamChunk(content_delta="Done.")
        yield StreamChunk(
            done=True,
            response=LLMResponse(
                message=LLMMessage(role="assistant", content="Done.")
            ),
        )

    stream_calls = iter([first_stream, second_stream])
    llm.chat_stream = MagicMock(
        side_effect=lambda messages, tools=None: next(stream_calls)(messages, tools)
    )

    result = agent.run("inspect host", stream_callback=lambda _text: None)

    assert result.final_message == "Done."
    tool_messages = [message for message in agent.messages if message.role == "tool"]
    payloads = json.loads(tool_messages[-1].content)
    assert all(item["success"] is False for item in payloads)


def test_agent_non_streaming_mode_uses_batch_chat(agent_parts) -> None:
    agent, llm, _ = agent_parts
    agent.settings.agent_stream_responses = False
    llm.chat.return_value = LLMResponse(
        message=LLMMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="1",
                    name="respond",
                    arguments={"finished": True, "message": "Batch reply."},
                )
            ],
        )
    )

    streamed: list[str] = []
    result = agent.run("hello", stream_callback=streamed.append)

    assert streamed == []
    assert result.final_message == "Batch reply."
    llm.chat.assert_called_once()
    llm.chat_stream.assert_not_called()
