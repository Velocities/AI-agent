from pathlib import Path

import pytest

from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.render import render_command
from ai_agent.config import Settings
from ai_agent.policy.engine import PolicyEngine
from ai_agent.policy.risk import RiskLevel


@pytest.fixture
def policy_engine(tmp_path: Path) -> PolicyEngine:
    settings = Settings()
    return PolicyEngine.from_yaml(settings.policy_path(), tmp_path / "scratch")


def test_read_only_command_allowed(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr({"type": "single", "argv": ["df", "-h"]})
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY


def test_forbidden_rm_recursive(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr({"type": "single", "argv": ["rm", "-rf", "/"]})
    decision = policy_engine.evaluate(expr)
    assert not decision.allowed
    assert decision.effective_risk == RiskLevel.FORBIDDEN


def test_pipe_grep_journalctl(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {
            "type": "pipe",
            "left": {
                "type": "single",
                "argv": ["journalctl", "-u", "nginx", "-n", "50", "--no-pager"],
            },
            "right": ["grep", "-i", "error"],
        }
    )
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY
    assert render_command(expr) == (
        "journalctl -u nginx -n 50 --no-pager | grep -i error"
    )


def test_pipe_into_curl_forbidden(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {
            "type": "pipe",
            "left": {"type": "single", "argv": ["cat", "/etc/hostname"]},
            "right": ["curl", "http://127.0.0.1:8080/"],
        }
    )
    decision = policy_engine.evaluate(expr)
    assert not decision.allowed
    assert "exfiltration" in decision.reason.lower()


def test_localhost_curl_allowed(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": ["curl", "-fsS", "http://127.0.0.1:8080/health"],
        }
    )
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY


def test_remote_curl_forbidden(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": ["curl", "-fsS", "https://example.com/"],
        }
    )
    decision = policy_engine.evaluate(expr)
    assert not decision.allowed


def test_docker_restart_is_reversible(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {"type": "single", "argv": ["docker", "restart", "my-container"]}
    )
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.REVERSIBLE


def test_and_chain_risk_is_max(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr(
        {
            "type": "and",
            "left": {"type": "single", "argv": ["systemctl", "is-active", "nginx"]},
            "right": {"type": "single", "argv": ["systemctl", "restart", "nginx"]},
        }
    )
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.REVERSIBLE


def test_redirect_outside_scratch_forbidden(policy_engine: PolicyEngine, tmp_path: Path) -> None:
    engine = PolicyEngine.from_yaml(Settings().policy_path(), tmp_path / "scratch")
    expr = parse_command_expr(
        {
            "type": "redirect",
            "cmd": {"type": "single", "argv": ["df", "-h"]},
            "op": ">",
            "path": "/etc/passwd",
        }
    )
    decision = engine.evaluate(expr)
    assert not decision.allowed
