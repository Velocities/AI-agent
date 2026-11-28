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


def test_installer_seeds_catalog_outside_the_checkout() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert "catalog_root=/var/lib/ai-agent/catalog" in text
    assert "install_workflow_catalog" in text
    broker = (ROOT / "deploy" / "systemd" / "ai-agent-docker.service.in").read_text(encoding="utf-8")
    assert "--workflow-image-root @CATALOG_ROOT@" in broker
    assert "workflow_image" not in broker


def test_installer_calls_helper_scripts_instead_of_inline_python() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert "<<'PY'" not in text
    for name in ("ensure_env.py", "render_unit.py", "read_env.py", "docker_daemon_userns.py"):
        assert name in text
        assert (INSTALL.parent / name).is_file()


def test_installer_does_not_select_protect_home() -> None:
    text = INSTALL.read_text(encoding="utf-8")
    assert "protect_home" not in text
    assert "@PROTECT_HOME@" not in text
