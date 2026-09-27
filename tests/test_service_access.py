from ai_agent.cli.service_access_cmd import main


def test_service_access_show(capsys) -> None:
    assert main(["show"]) == 0
    out = capsys.readouterr().out
    assert "Local execution target" in out


def test_service_access_plan(capsys) -> None:
    assert main(["plan", "velocities", "--list-home"]) == 0
    out = capsys.readouterr().out
    assert "grant-access.sh" in out
    assert "--list-home" in out
