from pathlib import Path

import pytest

from ai_agent.approval.session import ApprovalSession, risk_requires_confirmation
from ai_agent.commands.ast import parse_command_expr
from ai_agent.commands.render import render_command
from ai_agent.config import ConfirmationMode, Settings
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


@pytest.mark.parametrize(
    "argv",
    [["date"], ["date", "-u"], ["date", "+%Z %z"], ["timedatectl", "status"], ["timedatectl", "show"]],
)
def test_clock_reads_are_read_only(policy_engine: PolicyEngine, argv: list[str]) -> None:
    decision = policy_engine.evaluate(parse_command_expr({"type": "single", "argv": argv}))
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY


@pytest.mark.parametrize(
    "argv",
    [
        ["date", "-s", "2020-01-01"],
        ["date", "-us", "2020-01-01"],
        ["date", "--set=2020-01-01"],
        ["/usr/bin/date", "-u", "-s", "2020-01-01"],
    ],
)
def test_clock_changes_are_forbidden(policy_engine: PolicyEngine, argv: list[str]) -> None:
    decision = policy_engine.evaluate(parse_command_expr({"type": "single", "argv": argv}))
    assert not decision.allowed


@pytest.mark.parametrize(
    "argv",
    [["lsblk"], ["timedatectl", "set-time", "2020-01-01"], ["dir", "/B", "."]],
)
def test_unlisted_command_needs_approval_every_time(policy_engine: PolicyEngine, argv: list[str]) -> None:
    decision = policy_engine.evaluate(parse_command_expr({"type": "single", "argv": argv}))
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.DESTRUCTIVE
    session = ApprovalSession()
    session.add_grant(RiskLevel.REVERSIBLE, "global")
    assert risk_requires_confirmation(decision.effective_risk, ConfirmationMode.PERMISSIVE, session)
    assert policy_engine.unlisted_need_approval()


def test_forbidden_patterns_stay_blocked_despite_approval_fallback(policy_engine: PolicyEngine) -> None:
    for argv in (["bash", "-c", "id"], ["mkfs", "/dev/sda1"], ["rm", "-rf", "/tmp/x"]):
        decision = policy_engine.evaluate(parse_command_expr({"type": "single", "argv": argv}))
        assert not decision.allowed, argv


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


def test_echo_redirect_into_scratch_is_reversible(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    engine = PolicyEngine.from_yaml(Settings().policy_path(), scratch)
    expr = parse_command_expr(
        {
            "type": "redirect",
            "cmd": {"type": "single", "argv": ["echo", "hello from agent"]},
            "op": ">",
            "path": str(scratch / "testfile.txt"),
        }
    )
    decision = engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.REVERSIBLE


def test_echo_alone_is_read_only(policy_engine: PolicyEngine) -> None:
    expr = parse_command_expr({"type": "single", "argv": ["echo", "hello"]})
    decision = policy_engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY


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


def test_powershell_get_childitem_allowed_on_windows(tmp_path: Path) -> None:
    import platform

    if platform.system() != "Windows":
        pytest.skip("Windows-only policy overlay")

    engine = PolicyEngine.from_yaml(Settings().policy_path(), tmp_path / "scratch")
    project = Path.cwd()
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-ChildItem",
                "-LiteralPath",
                str(project),
                "-Name",
            ],
        }
    )
    decision = engine.evaluate(expr)
    assert decision.allowed
    assert decision.effective_risk == RiskLevel.READ_ONLY


def test_powershell_invoke_expression_forbidden(tmp_path: Path) -> None:
    import platform

    if platform.system() != "Windows":
        pytest.skip("Windows-only policy overlay")

    engine = PolicyEngine.from_yaml(Settings().policy_path(), tmp_path / "scratch")
    expr = parse_command_expr(
        {
            "type": "single",
            "argv": [
                "powershell",
                "-NoProfile",
                "-Command",
                "Invoke-Expression",
                "Get-ChildItem",
            ],
        }
    )
    decision = engine.evaluate(expr)
    assert not decision.allowed

