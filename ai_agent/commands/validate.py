from __future__ import annotations

from ai_agent.commands.ast import CommandExpr, iter_leaves
from ai_agent.policy.engine import PolicyEngine

SEMICOLON_CHAIN_NUDGE = (
    "Semicolons are forbidden in all argv (no shell chaining). Use run_commands "
    "with multiple separate single commands, or and/or CommandExpr. For find -exec "
    "use only '+' after '{}' (never ';'). Prefer grep -R or run_commands instead."
)


def command_expression_issue(expr: CommandExpr) -> str | None:
    """Return a tool-facing error when argv shape violates batch/chain rules."""
    for leaf in iter_leaves(expr):
        if PolicyEngine.forbidden_semicolon_usage(leaf.argv):
            return SEMICOLON_CHAIN_NUDGE
    return None
