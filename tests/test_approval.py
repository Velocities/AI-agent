from ai_agent.approval.session import ApprovalSession, risk_requires_confirmation
from ai_agent.config import ConfirmationMode
from ai_agent.policy.risk import RiskLevel


def test_balanced_mode_auto_allows_read_only() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.READ_ONLY,
            ConfirmationMode.BALANCED,
            session,
        )
        is False
    )


def test_paranoid_mode_requires_read_only_confirmation() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.READ_ONLY,
            ConfirmationMode.PARANOID,
            session,
        )
        is True
    )


def test_session_read_only_grant_disables_paranoid_confirmation() -> None:
    session = ApprovalSession()
    session.enable_read_only_auto()
    assert (
        risk_requires_confirmation(
            RiskLevel.READ_ONLY,
            ConfirmationMode.PARANOID,
            session,
        )
        is False
    )


def test_reversible_requires_confirmation_in_balanced_mode() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.REVERSIBLE,
            ConfirmationMode.BALANCED,
            session,
        )
        is True
    )


def test_permissive_mode_auto_allows_read_only() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.READ_ONLY,
            ConfirmationMode.PERMISSIVE,
            session,
        )
        is False
    )


def test_permissive_mode_auto_allows_reversible() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.REVERSIBLE,
            ConfirmationMode.PERMISSIVE,
            session,
        )
        is False
    )


def test_permissive_mode_requires_destructive_confirmation() -> None:
    session = ApprovalSession()
    assert (
        risk_requires_confirmation(
            RiskLevel.DESTRUCTIVE,
            ConfirmationMode.PERMISSIVE,
            session,
        )
        is True
    )
