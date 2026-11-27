from ai_agent.api.auth import InvalidTokenError
from ai_agent.api.local_auth import LocalStandaloneVerifier, bootstrap_local_standalone_access
from ai_agent.conversations.db import open_stores_at
from ai_agent.config import Settings


def test_local_standalone_verifier_accepts_shared_token() -> None:
    verifier = LocalStandaloneVerifier(
        user_id="00000000-0000-4000-8000-000000000001",
        token="test-secret",
    )
    user = verifier.verify("test-secret")
    assert user.user_id == "00000000-0000-4000-8000-000000000001"
    try:
        verifier.verify("wrong")
    except InvalidTokenError:
        pass
    else:
        raise AssertionError("expected InvalidTokenError")


def test_bootstrap_local_standalone_access(tmp_path) -> None:
    _store, access, _repo, _admins = open_stores_at(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    settings = Settings(
        LOCAL_STANDALONE_MODE=True,
        LOCAL_STANDALONE_USER_ID="00000000-0000-4000-8000-000000000002",
        LOCAL_STANDALONE_LINUX_USER="dev",
    )
    bootstrap_local_standalone_access(access, settings)
    record = access.get("00000000-0000-4000-8000-000000000002")
    assert record is not None
    assert record.linux_username == "dev"