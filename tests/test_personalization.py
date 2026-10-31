"""Personalization settings, the system-prompt suffix, and speech respelling."""

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ai_agent.agent.context import append_personalization, build_system_prompt, gather_runtime_context
from ai_agent.agent.loop import AgentLoop
from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser, InvalidTokenError
from ai_agent.api.settings import UserSettingsBody
from ai_agent.approval.prompt import ApprovalPrompter
from ai_agent.approval.session import ApprovalSession
from ai_agent.audit.logger import AuditLogger
from ai_agent.commands.executor import CommandExecutor
from ai_agent.config import Settings
from ai_agent.conversations.db import open_store_at
from zoneinfo import ZoneInfo

from ai_agent.conversations.personalization import (
    UserPreferences,
    normalize_spoken,
    selectable_timezones,
)
from ai_agent.policy.engine import PolicyEngine
from ai_agent.speech.text import SpokenSentenceBuffer, apply_pronunciations

ALICE = "11111111-1111-4111-8111-111111111111"


class _Tokens:
    def verify(self, token: str) -> AuthenticatedUser:
        if token != "alice":
            raise InvalidTokenError("no")
        return AuthenticatedUser(user_id=ALICE)


def _client(tmp_path: Path) -> TestClient:
    store = open_store_at(f"sqlite:///{tmp_path / 'conversations.db'}")
    return TestClient(create_app(Settings(), _Tokens(), store=store))


def test_name_requires_a_respelling_and_partial_patch_keeps_it(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer alice"}
    with _client(tmp_path) as client:
        missing = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"agent_name": "CLU"},
        )
        saved = client.patch(
            "/api/me/settings",
            headers=headers,
            json={
                "agent_name": "CLU",
                "agent_name_pronunciation": "clue",
                "user_name": "Sam",
                "user_name_pronunciation": "sam",
                "reply_length": "brief",
                "timezone": "America/New_York",
                "coding_preferences": "Prefer `#` headings.",
            },
        )
        kept = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"strip_image_metadata": False},
        )
        cleared = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"agent_name": ""},
        )
        empty_zone = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"timezone": "Not/AZone"},
        )
    assert missing.status_code == 422
    assert "sounds-like" in missing.json()["detail"]
    assert saved.status_code == 200
    assert saved.json()["agent_name"] == "CLU"
    assert saved.json()["agent_name_pronunciation"] == "clue"
    assert saved.json()["reply_length"] == "brief"
    assert saved.json()["timezone"] == "America/New_York"
    assert kept.status_code == 200
    assert kept.json()["strip_image_metadata"] is False
    assert kept.json()["agent_name"] == "CLU"
    assert kept.json()["coding_preferences"] == "Prefer `#` headings."
    assert cleared.status_code == 200
    assert cleared.json()["agent_name"] == ""
    assert cleared.json()["agent_name_pronunciation"] == ""
    assert cleared.json()["user_name"] == "Sam"
    assert empty_zone.status_code == 422
    assert UserSettingsBody().reply_length == "normal"


def test_timezone_catalog_lists_only_zones_the_server_accepts(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer alice"}
    with _client(tmp_path) as client:
        missing = client.get("/api/timezones")
        listed = client.get("/api/timezones", headers=headers)
    assert missing.status_code == 401
    assert listed.status_code == 200
    zones = listed.json()["timezones"]
    assert zones == list(selectable_timezones())
    assert zones == sorted(zones)
    assert "America/New_York" in zones
    assert "UTC" in zones
    assert "Etc/GMT+5" not in zones
    assert "Factory" not in zones
    assert all(ZoneInfo(zone) for zone in zones)


def test_defaults_do_not_change_the_system_prompt(tmp_path: Path) -> None:
    settings = Settings()
    context = gather_runtime_context(settings)
    base = build_system_prompt(context, ["echo"])
    assert append_personalization(base, None) is base
    assert append_personalization(base, UserPreferences()) is base

    policy = PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")
    executor = CommandExecutor(timeout=5, output_limit=1024, scratch_dir=tmp_path / "scratch")
    session = ApprovalSession()
    prompter = ApprovalPrompter(settings.agent_confirmation_mode, session, MagicMock())

    def make(personalization: UserPreferences | None) -> str:
        agent = AgentLoop(
            settings=settings,
            llm=MagicMock(),
            policy=policy,
            executor=executor,
            audit=AuditLogger(log_path=tmp_path / "audit.jsonl", user="test"),
            prompter=prompter,
            session=session,
            personalization=personalization,
        )
        return agent.messages[0].content

    plain = make(None)
    named = make(
        UserPreferences(
            agent_name="CLU",
            agent_name_pronunciation="clue",
            user_name="Sam",
            user_name_pronunciation="samm",
            reply_length="thorough",
            timezone="UTC",
            coding_preferences="Use `pathlib`.",
        )
    )
    assert "User preferences" not in plain
    assert named.startswith(plain.rstrip("\n"))
    tail = named[len(plain.rstrip("\n")) :]
    assert "Your name is CLU." in tail
    assert "The user's name is Sam." in tail
    assert "Prefer thorough replies." in tail
    assert "timezone is UTC" in tail
    assert "Use `pathlib`." in tail
    assert "clue" not in tail
    assert "samm" not in tail
    assert "never override tool policy" in tail
    # Speech settings stay out of the prompt. The model must not learn the wake phrase
    # or treat a spoken "yes" as something it can interpret.
    spoken = make(
        UserPreferences(
            agent_name="CLU",
            agent_name_pronunciation="clue",
            stt_provider="vosk",
            wake_phrase="Hey CLU",
            close_phrase="Bye CLU",
            voice_command_approval=True,
        )
    )
    spoken_tail = spoken[len(plain.rstrip("\n")) :]
    assert "Hey CLU" not in spoken_tail
    assert "Bye CLU" not in spoken_tail
    assert "vosk" not in spoken_tail
    assert "voice" not in spoken_tail.lower()


def test_speech_settings_round_trip_and_reject_a_bad_gate(tmp_path: Path) -> None:
    headers = {"Authorization": "Bearer alice"}
    with _client(tmp_path) as client:
        saved = client.patch(
            "/api/me/settings",
            headers=headers,
            json={
                "agent_name": "CLU",
                "agent_name_pronunciation": "clue",
                "stt_provider": "vosk",
                "wake_phrase": "Hey, CLU",
                "close_phrase": "Bye CLU",
                "voice_command_approval": True,
            },
        )
        kept = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"strip_image_metadata": False},
        )
        unknown = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"stt_provider": "whisper"},
        )
        same = client.patch(
            "/api/me/settings",
            headers=headers,
            json={"wake_phrase": "Bye CLU"},
        )
        defaults = client.get("/api/me/settings", headers=headers)
    assert saved.status_code == 200
    assert saved.json()["stt_provider"] == "vosk"
    assert saved.json()["wake_phrase"] == "Hey, CLU"
    assert saved.json()["voice_command_approval"] is True
    assert kept.status_code == 200
    assert kept.json()["stt_provider"] == "vosk"
    assert kept.json()["wake_phrase"] == "Hey, CLU"
    assert kept.json()["voice_command_approval"] is True
    assert kept.json()["strip_image_metadata"] is False
    assert unknown.status_code == 422
    assert same.status_code == 422
    assert "different" in same.json()["detail"]
    assert defaults.json()["stt_provider"] == "vosk"
    assert normalize_spoken("Hey, CLU!") == "hey clu"


def test_speech_respells_whole_names_longest_first() -> None:
    assert apply_pronunciations("CLUE then CLU.", [("CLU", "clue")]) == "CLUE then clue."
    assert apply_pronunciations("ALICE met AL.", [("AL", "al"), ("ALICE", "a-lease")]) == (
        "a-lease met al."
    )
    assert apply_pronunciations("clu", [("CLU", "clue")]) == "clu"
    spoken = SpokenSentenceBuffer(pronunciations=(("CLU", "clue"), ("Sam", "sam")))
    assert spoken.push("Ask CLU about Sam today. ") == ["Ask clue about sam today."]
    untouched = SpokenSentenceBuffer()
    assert untouched.push("Please ask CLU now. ") == ["Please ask CLU now."]
