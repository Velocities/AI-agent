from pathlib import Path
from unittest.mock import MagicMock

from ai_agent.cli.confirm import confirm
from ai_agent.cli.host_setup import _read_public_key
from ai_agent.llm.host_setup import (
    linux_authorized_keys_path,
    merge_authorized_key,
    normalize_public_key,
    windows_authorized_keys_path,
)


def test_confirm_uses_yn_prompt() -> None:
    console = MagicMock()
    console.input.return_value = "y"
    assert confirm(console, "Continue") is True
    console.input.assert_called_with("Continue (y/n) ")
    console.input.return_value = "n"
    assert confirm(console, "Continue") is False


def test_normalize_and_merge_authorized_key(tmp_path: Path) -> None:
    key = normalize_public_key("  ssh-ed25519  AAAA  comment  ")
    assert key == "ssh-ed25519 AAAA comment"
    path = tmp_path / "authorized_keys"
    assert merge_authorized_key(path, key) is True
    assert merge_authorized_key(path, key) is False
    assert path.read_text(encoding="utf-8").count("AAAA") == 1


def test_windows_admin_uses_programdata() -> None:
    path = windows_authorized_keys_path(home=Path("C:/Users/x"), admin_account=True)
    assert path.name == "administrators_authorized_keys"
    user = windows_authorized_keys_path(home=Path("C:/Users/x"), admin_account=False)
    assert user.name == "authorized_keys"


def test_linux_authorized_keys_under_home() -> None:
    assert linux_authorized_keys_path(Path("/home/ai")) == Path("/home/ai/.ssh/authorized_keys")


def test_public_key_file_rejects_a_folder(tmp_path: Path) -> None:
    from argparse import Namespace

    try:
        _read_public_key(Namespace(public_key_file=str(tmp_path), public_key=None))
    except ValueError as exc:
        assert "folder" in str(exc)
    else:
        raise AssertionError("expected ValueError")
