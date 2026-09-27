from ai_agent.deployment.identity import (
    normalize_linux_username,
    profile_from_jwt_payload,
    suggest_linux_username,
)


def test_profile_from_jwt_payload_uses_email_and_metadata() -> None:
    email, name = profile_from_jwt_payload(
        {
            "email": "Ada@Example.com",
            "user_metadata": {"full_name": "Ada Lovelace"},
        }
    )
    assert email == "Ada@Example.com"
    assert name == "Ada Lovelace"


def test_suggest_linux_username_from_email() -> None:
    assert suggest_linux_username("velocities@example.com") == "velocities"
    assert suggest_linux_username("bad") is None


def test_normalize_linux_username() -> None:
    assert normalize_linux_username("Velocities") == "velocities"
    try:
        normalize_linux_username("9bad")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
