from __future__ import annotations

from dataclasses import dataclass

from ai_agent.approval.session import ApprovalSession, risk_requires_confirmation
from ai_agent.commands.render import render_command
from ai_agent.config import ConfirmationMode
from ai_agent.policy.engine import PolicyDecision, summarize_segments
from ai_agent.policy.risk import RiskLevel


@dataclass
class PendingCommand:
    expr: object
    decision: PolicyDecision
    reason: str | None = None


@dataclass
class ApprovalResult:
    approved: bool
    grant_scope: str | None = None


class ApprovalPrompter:
    def __init__(self, mode: ConfirmationMode, session: ApprovalSession, console):
        self.mode = mode
        self.session = session
        self.console = console

    def should_auto_run(self, decision: PolicyDecision) -> bool:
        if not decision.allowed:
            return False
        if self.session.has_grant(decision.effective_risk, "global"):
            return True
        return not risk_requires_confirmation(
            decision.effective_risk,
            self.mode,
            self.session,
        )

    def prompt_single(
        self,
        decision: PolicyDecision,
        *,
        reason: str | None = None,
    ) -> ApprovalResult:
        if not decision.allowed:
            self._print_header(decision, reason=reason)
            self.console.print("[red]This command is forbidden by policy.[/red]")
            return ApprovalResult(approved=False)

        if self.should_auto_run(decision):
            return ApprovalResult(approved=True)

        self._print_header(decision, reason=reason)
        return self._prompt_yes_no(decision)

    def prompt_batch(self, pending: list[PendingCommand]) -> ApprovalResult:
        if not pending:
            return ApprovalResult(approved=True)

        forbidden = [item for item in pending if not item.decision.allowed]
        if forbidden:
            self.console.print("[red]Batch contains forbidden commands; rejected.[/red]")
            for item in forbidden:
                self.console.print(f"  - {render_command(item.expr)}")
                self.console.print(f"    Reason: {item.decision.reason}")
            return ApprovalResult(approved=False)

        non_read_only = [
            item
            for item in pending
            if item.decision.effective_risk != RiskLevel.READ_ONLY
        ]
        if non_read_only:
            self.console.print(
                "[yellow]Batch contains non-READ_ONLY commands; "
                "falling back to individual approval.[/yellow]"
            )
            for item in non_read_only:
                result = self.prompt_single(item.decision, reason=item.reason)
                if not result.approved:
                    return ApprovalResult(approved=False)
            return ApprovalResult(approved=True)

        if self.mode == ConfirmationMode.BALANCED and not self.session.has_read_only_auto():
            self.console.print("\n[bold]AI wants to run these READ_ONLY checks:[/bold]")
            for index, item in enumerate(pending, start=1):
                self.console.print(
                    f"  {index}. {render_command(item.expr)}  "
                    f"[dim][{item.decision.effective_risk.label()}][/dim]"
                )
            response = input("\nProceed with batch? [Y/n/a=allow READ_ONLY this session]: ").strip().lower()
            if response in {"a", "allow"}:
                self.session.enable_read_only_auto()
                return ApprovalResult(approved=True, grant_scope="read_only_session")
            if response in {"", "y", "yes"}:
                return ApprovalResult(approved=True)
            return ApprovalResult(approved=False)

        if self.mode == ConfirmationMode.PARANOID:
            return self._prompt_batch_paranoid(pending)

        return ApprovalResult(approved=True)

    def _prompt_batch_paranoid(self, pending: list[PendingCommand]) -> ApprovalResult:
        self.console.print("\n[bold]AI wants to run these commands:[/bold]")
        for index, item in enumerate(pending, start=1):
            self.console.print(
                f"  {index}. {render_command(item.expr)}  "
                f"[{item.decision.effective_risk.label()}]"
            )
        response = input("\nProceed with batch? [y/N]: ").strip().lower()
        return ApprovalResult(approved=response in {"y", "yes"})

    def _print_header(self, decision: PolicyDecision, *, reason: str | None) -> None:
        self.console.print("\n[bold]AI wants to execute:[/bold]")
        self.console.print(f"  {render_command(decision.expr)}")
        self.console.print(f"  Risk: [bold]{decision.effective_risk.label()}[/bold]")
        if reason:
            self.console.print(f"  Reason: {reason}")
        if decision.segments:
            self.console.print("  Segments:")
            self.console.print(summarize_segments(decision))

    def _prompt_yes_no(self, decision: PolicyDecision) -> ApprovalResult:
        if decision.effective_risk == RiskLevel.REVERSIBLE:
            prompt = "\nApprove? [y/N/a=allow REVERSIBLE this session]: "
        elif decision.effective_risk == RiskLevel.READ_ONLY:
            prompt = "\nApprove? [y/N/a=allow READ_ONLY this session]: "
        else:
            prompt = "\nApprove? [y/N]: "

        response = input(prompt).strip().lower()
        if response in {"a", "allow"}:
            if decision.effective_risk == RiskLevel.REVERSIBLE:
                self.session.add_grant(RiskLevel.REVERSIBLE, "global")
                return ApprovalResult(approved=True, grant_scope="reversible_session")
            if decision.effective_risk == RiskLevel.READ_ONLY:
                self.session.enable_read_only_auto()
                return ApprovalResult(approved=True, grant_scope="read_only_session")
        return ApprovalResult(approved=response in {"y", "yes"})
