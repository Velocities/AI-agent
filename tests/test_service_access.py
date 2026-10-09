from ai_agent.cli.service_access_cmd import main


def test_service_access_show(capsys) -> None:
    assert main(["show"]) == 0
    out = capsys.readouterr().out
    assert "Local execution target" in out
    assert "UID/GID" in out


def test_service_access_plan(capsys) -> None:
    assert main(["plan", "velocities"]) == 0
    out = capsys.readouterr().out
    assert "--run-as velocities" in out
    assert "Unix permissions" in out
