from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "deploy" / "systemd" / "ai-agent.service.in"
INSTALL = ROOT / "deploy" / "systemd" / "install.sh"


def test_unit_keeps_service_account_and_drops_filesystem_sandbox() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "User=@SERVICE_USER@" in text
    assert "AmbientCapabilities=CAP_SETUID CAP_SETGID" in text
    assert "CapabilityBoundingSet=CAP_SETUID CAP_SETGID" in text
    assert "ProtectSystem=" not in text
    assert "ProtectHome=" not in text
    assert "ReadWritePaths=" not in text
    assert "PrivateTmp=false" in text


def test_installer_does_not_select_protect_home() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert "protect_home" not in text
    assert "@PROTECT_HOME@" not in text
