import subprocess

from ai_agent.cli.app import main as app_main
from ai_agent.cli.service_cmd import main


def test_serve_dispatches_to_the_supervisor(monkeypatch) -> None:
    monkeypatch.setattr("ai_agent.service.supervisor.main", lambda: 0)
    assert app_main(["serve"]) == 0


def test_serve_rejects_extra_arguments() -> None:
    assert app_main(["serve", "--foreground"]) == 2


def test_start_reports_a_missing_unit(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ai_agent.cli.service_cmd.unit_load_state", lambda: "not-found")
    assert main(["start"]) == 1
    assert "ai-agent serve" in capsys.readouterr().err


def test_start_delegates_to_systemctl(monkeypatch) -> None:
    monkeypatch.setattr("ai_agent.cli.service_cmd.unit_load_state", lambda: "loaded")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stderr="")

    monkeypatch.setattr("ai_agent.cli.service_cmd.subprocess.run", fake_run)
    assert app_main(["start"]) == 0
    assert seen == [["systemctl", "start", "ai-agent.service"]]


def test_status_command_includes_no_pager(monkeypatch) -> None:
    monkeypatch.setattr("ai_agent.cli.service_cmd.unit_load_state", lambda: "loaded")
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 3, stderr="")

    monkeypatch.setattr("ai_agent.cli.service_cmd.subprocess.run", fake_run)
    assert main(["status"]) == 3
    assert seen == [
        ["systemctl", "status", "ai-agent.service", "--no-pager", "--full"]
    ]


def test_start_prints_sudo_hint_on_access_denied(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ai_agent.cli.service_cmd.unit_load_state", lambda: "loaded")

    def fake_run(cmd, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr="Access denied\n")

    monkeypatch.setattr("ai_agent.cli.service_cmd.subprocess.run", fake_run)
    assert main(["start"]) == 1
    assert "sudo systemctl start ai-agent" in capsys.readouterr().err


def test_start_without_systemctl_points_at_serve(monkeypatch, capsys) -> None:
    def missing():
        raise FileNotFoundError

    monkeypatch.setattr("ai_agent.cli.service_cmd.unit_load_state", missing)
    assert main(["restart"]) == 1
    assert "ai-agent serve" in capsys.readouterr().err
