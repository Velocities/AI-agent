from __future__ import annotations

from dataclasses import dataclass

from ai_agent.approval.selection import (
    MIXED,
    ORDERED,
    describe_ordering,
    normalize_groups,
    resolve_selection,
)
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
    target_display: str | None = None
    target_name: str | None = None
    target_kind: str | None = None


@dataclass
class ApprovalResult:
    approved: bool
    grant_scope: str | None = None
    # Final per-command accepts after an ordered cascade. None means the
    # boolean above applies to every command (approve all / reject all).
    accepted: tuple[bool, ...] | None = None
    # True where the user accepted a command and ordering rejected it.
    cascade_rejected: tuple[bool, ...] | None = None


class ApprovalPrompter:
    def __init__(self, mode: ConfirmationMode, session: ApprovalSession, console):
        self.mode = mode
        self.session = session
        self.console = console

    def should_auto_run(self, decision: PolicyDecision) -> bool:
        return auto_approves(self.session, self.mode, decision)

    def prompt_single(
        self,
        decision: PolicyDecision,
        *,
        reason: str | None = None,
        target_display: str | None = None,
        target_name: str | None = None,
        target_kind: str | None = None,
    ) -> ApprovalResult:
        if not decision.allowed:
            self._print_header(
                decision, reason=reason, target_display=target_display
            )
            self.console.print("[red]This command is forbidden by policy.[/red]")
            return ApprovalResult(approved=False)

        if self.should_auto_run(decision):
            return ApprovalResult(approved=True)

        self._print_header(decision, reason=reason, target_display=target_display)
        return self._prompt_yes_no(decision)

    def prompt_batch(
        self,
        pending: list[PendingCommand],
        *,
        order_groups: list[int | None] | None = None,
    ) -> ApprovalResult:
        if not pending:
            return ApprovalResult(approved=True)
        groups = normalize_groups(order_groups, len(pending))

        forbidden = [item for item in pending if not item.decision.allowed]
        if forbidden:
            self.console.print("[red]Batch contains forbidden commands; rejected.[/red]")
            for item in forbidden:
                self.console.print(
                    f"  - {render_command(item.expr)}{_target_suffix(item)}"
                )
                self.console.print(f"    Reason: {item.decision.reason}")
            return ApprovalResult(approved=False)

        if batch_runs_unattended(self, pending):
            return ApprovalResult(approved=True)
        return self._prompt_batch_interactive(pending, groups)

    def _prompt_batch_interactive(
        self,
        pending: list[PendingCommand],
        groups: list[int | None],
    ) -> ApprovalResult:
        risks = {item.decision.effective_risk for item in pending}
        read_only_batch = risks <= {RiskLevel.READ_ONLY}
        grant = (
            self.mode == ConfirmationMode.BALANCED
            and read_only_batch
            and not self.session.has_read_only_auto()
        )
        heading = (
            "AI wants to run these READ_ONLY checks:"
            if read_only_batch
            else "AI wants to run these commands:"
        )
        self.console.print(f"\n[bold]{heading}[/bold]")
        self._print_batch_commands(pending)
        self._print_ordering_hint(groups)
        selectable = len(pending) > 1
        if selectable:
            self.console.print("[dim]s = choose which commands to run[/dim]")
        if grant:
            prompt = "\nProceed with batch? (y/n/a/s) " if selectable else "\nProceed with batch? (y/n/a) "
        else:
            prompt = "\nProceed with batch? (y/n/s) " if selectable else "\nProceed with batch? (y/n) "
        response = input(prompt).strip().lower()
        if response in {"s", "select"} and selectable:
            return self._prompt_batch_selection(pending, groups)
        if grant and response in {"a", "allow"}:
            self.session.enable_read_only_auto()
            return ApprovalResult(approved=True, grant_scope="read_only_session")
        if response in {"", "y", "yes"} and grant:
            return ApprovalResult(approved=True)
        return ApprovalResult(approved=response in {"y", "yes"})

    def _print_batch_commands(self, pending: list[PendingCommand]) -> None:
        for index, item in enumerate(pending, start=1):
            self.console.print(
                f"  {index}. {render_command(item.expr)}  "
                f"[dim][{item.decision.effective_risk.label()}]"
                f"{_target_suffix(item)}[/dim]"
            )

    def _print_ordering_hint(self, groups: list[int | None]) -> None:
        kind = describe_ordering(groups)
        if kind == ORDERED:
            self.console.print(
                "[dim]Ordered batch: rejecting a command also rejects every command below it.[/dim]"
            )
        elif kind == MIXED:
            self.console.print(
                "[dim]Some commands are a sequence. Rejecting one also rejects "
                "later commands in that sequence.[/dim]"
            )

    def _prompt_batch_selection(
        self,
        pending: list[PendingCommand],
        groups: list[int | None],
    ) -> ApprovalResult:
        chosen: list[bool] = []
        blocked: set[int] = set()
        self.console.print("[dim]y runs that command. n rejects it.[/dim]")
        for index, item in enumerate(pending):
            group = groups[index]
            rendered = render_command(item.expr)
            if group is not None and group in blocked:
                self.console.print(
                    f"  {index + 1}. {rendered}  "
                    "[dim]rejected — an earlier command in this sequence was rejected[/dim]"
                )
                # The user was not asked. Record an accept so the ordered rule,
                # not an explicit rejection, explains the skip to the model.
                chosen.append(True)
                continue
            answer = input(f"  Run {index + 1}. {rendered}? (y/n) ").strip().lower()
            accept = answer in {"y", "yes"}
            chosen.append(accept)
            if not accept and group is not None:
                blocked.add(group)
        approved, accepted, cascade = resolve_selection(chosen, groups)
        return ApprovalResult(
            approved=approved,
            accepted=accepted,
            cascade_rejected=cascade,
        )

    def _print_header(
        self,
        decision: PolicyDecision,
        *,
        reason: str | None,
        target_display: str | None = None,
    ) -> None:
        self.console.print("\n[bold]AI wants to execute:[/bold]")
        self.console.print(f"  {render_command(decision.expr)}")
        if target_display:
            self.console.print(f"  Target: {target_display}")
        self.console.print(f"  Risk: [bold]{decision.effective_risk.label()}[/bold]")
        if reason:
            self.console.print(f"  Reason: {reason}")
        if decision.segments:
            self.console.print("  Segments:")
            self.console.print(summarize_segments(decision))

    def _prompt_yes_no(self, decision: PolicyDecision) -> ApprovalResult:
        if decision.effective_risk in {RiskLevel.REVERSIBLE, RiskLevel.READ_ONLY}:
            self.console.print("[dim]a = allow this risk for the rest of the session[/dim]")
            prompt = "\nApprove? (y/n/a) "
        else:
            prompt = "\nApprove? (y/n) "

        response = input(prompt).strip().lower()
        if response in {"a", "allow"}:
            if decision.effective_risk == RiskLevel.REVERSIBLE:
                self.session.add_grant(RiskLevel.REVERSIBLE, "global")
                return ApprovalResult(approved=True, grant_scope="reversible_session")
            if decision.effective_risk == RiskLevel.READ_ONLY:
                self.session.enable_read_only_auto()
                return ApprovalResult(approved=True, grant_scope="read_only_session")
        return ApprovalResult(approved=response in {"y", "yes"})


def batch_runs_unattended(prompter, pending: list[PendingCommand]) -> bool:
    """True when this batch can run without showing the user a prompt.

    A pure read-only batch in balanced mode still asks once, until the user
    grants read-only for the session. A batch that contains any command the
    user must approve is not unattended, even if some of its commands are.
    """
    if any(item.decision.effective_risk != RiskLevel.READ_ONLY for item in pending):
        return all(prompter.should_auto_run(item.decision) for item in pending)
    if prompter.mode == ConfirmationMode.PERMISSIVE:
        return True
    if prompter.mode == ConfirmationMode.BALANCED and prompter.session.has_read_only_auto():
        return True
    return False


def auto_approves(session: ApprovalSession, mode: ConfirmationMode, decision: PolicyDecision) -> bool:
    """True when policy allows the command and this session does not need a person."""
    if not decision.allowed:
        return False
    if session.has_grant(decision.effective_risk, "global"):
        return True
    return not risk_requires_confirmation(decision.effective_risk, mode, session)


def _target_suffix(item: PendingCommand) -> str:
    if not item.target_display:
        return ""
    return f"  [{item.target_display}]"
