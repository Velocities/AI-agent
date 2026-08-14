from __future__ import annotations

import platform
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ai_agent.commands.ast import (
    AndCommand,
    CommandExpr,
    OrCommand,
    PipeCommand,
    RedirectCommand,
    SingleCommand,
    iter_leaves,
)
from ai_agent.policy.risk import RiskLevel


@dataclass
class SegmentDecision:
    argv: list[str]
    binary: str
    risk: RiskLevel
    reason: str
    cwd: str | None = None


@dataclass
class PolicyDecision:
    expr: CommandExpr
    effective_risk: RiskLevel
    segments: list[SegmentDecision]
    allowed: bool
    reason: str
    redirect_path: str | None = None


@dataclass
class PolicyRule:
    binary: str
    risk: RiskLevel
    subcommand: str | None = None
    arg_prefix: str | None = None
    path_args: str | None = None
    network: bool = False
    powershell: bool = False


@dataclass
class NetworkPolicy:
    allowed_hosts: set[str] = field(default_factory=set)
    allowed_methods: set[str] = field(default_factory=lambda: {"GET", "HEAD"})
    forbid_upload_flags: set[str] = field(default_factory=set)
    forbid_stdin: bool = True


@dataclass
class FilesystemPolicy:
    readable_paths: list[Path] = field(default_factory=list)
    writable_redirect_paths: list[Path] = field(default_factory=list)


@dataclass
class PolicyConfig:
    rules: list[PolicyRule]
    forbidden_patterns: list[dict]
    filesystem: FilesystemPolicy
    network: NetworkPolicy
    fallback_risk: RiskLevel = RiskLevel.FORBIDDEN
    fallback_reason: str = "No matching policy rule"


class PolicyEngine:
    POWERSHELL_ALLOWED_CMDLETS = frozenset({"Get-ChildItem", "Get-Content", "Test-Path"})
    POWERSHELL_FORBIDDEN_TOKENS = frozenset(
        {
            ";",
            "|",
            "&",
            "`",
            "Invoke-Expression",
            "iex",
            "Start-Process",
            "Remove-Item",
            "Set-Content",
            "Add-Content",
            "New-Item",
            "DownloadString",
            "WebClient",
        }
    )

    def __init__(self, config: PolicyConfig, scratch_dir: Path):
        self.config = config
        self.scratch_dir = scratch_dir.resolve()

    @classmethod
    def from_yaml(cls, path: Path, scratch_dir: Path) -> "PolicyEngine":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if platform.system() == "Windows":
            overlay_path = path.parent / "windows_policy.yaml"
            if overlay_path.exists():
                overlay = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
                raw["rules"] = raw.get("rules", []) + overlay.get("rules", [])
                raw["forbidden_patterns"] = raw.get("forbidden_patterns", []) + overlay.get(
                    "forbidden_patterns", []
                )
        rules = [
            PolicyRule(
                binary=item["binary"],
                risk=RiskLevel[item["risk"]],
                subcommand=item.get("subcommand"),
                arg_prefix=item.get("arg_prefix"),
                path_args=item.get("path_args"),
                network=item.get("network", False),
                powershell=item.get("powershell", False),
            )
            for item in raw.get("rules", [])
        ]
        fs = raw.get("filesystem", {})
        net = raw.get("network", {})
        fallback = raw.get("fallback", {})
        readable_paths = [Path(p) for p in fs.get("readable_paths", [])]
        readable_paths.extend(cls._extra_readable_paths_for_platform())
        config = PolicyConfig(
            rules=rules,
            forbidden_patterns=raw.get("forbidden_patterns", []),
            filesystem=FilesystemPolicy(
                readable_paths=readable_paths,
                writable_redirect_paths=[
                    Path(p) for p in fs.get("writable_redirect_paths", [])
                ],
            ),
            network=NetworkPolicy(
                allowed_hosts=set(net.get("allowed_hosts", [])),
                allowed_methods=set(net.get("allowed_methods", ["GET", "HEAD"])),
                forbid_upload_flags=set(net.get("forbid_upload_flags", [])),
                forbid_stdin=net.get("forbid_stdin", True),
            ),
            fallback_risk=RiskLevel[fallback.get("risk", "FORBIDDEN")],
            fallback_reason=fallback.get("reason", "No matching policy rule"),
        )
        return cls(config, scratch_dir)

    @staticmethod
    def _extra_readable_paths_for_platform() -> list[Path]:
        extras = [Path.home(), Path.cwd()]
        if platform.system() == "Windows":
            extras.append(Path("C:/Users"))
        return extras

    def allowed_binaries(self) -> list[str]:
        return sorted({rule.binary for rule in self.config.rules})

    def evaluate(self, expr: CommandExpr, *, piped_to: str | None = None) -> PolicyDecision:
        segments: list[SegmentDecision] = []
        redirect_path: str | None = None

        if isinstance(expr, RedirectCommand):
            redirect_path = expr.path
            redirect_decision = self._validate_redirect(expr)
            if not redirect_decision.allowed:
                return redirect_decision
            inner = self.evaluate(expr.cmd)
            segments.extend(inner.segments)
            effective = RiskLevel.max(inner.effective_risk, RiskLevel.REVERSIBLE)
            return PolicyDecision(
                expr=expr,
                effective_risk=effective,
                segments=segments,
                allowed=inner.allowed,
                reason=inner.reason,
                redirect_path=redirect_path,
            )

        if isinstance(expr, PipeCommand):
            left = self.evaluate(expr.left)
            segments.extend(left.segments)
            if not left.allowed:
                return PolicyDecision(
                    expr=expr,
                    effective_risk=RiskLevel.FORBIDDEN,
                    segments=segments,
                    allowed=False,
                    reason=left.reason,
                )
            right = self._evaluate_argv(expr.right_argv, piped_to=expr.right_argv[0])
            segments.append(right)
            if right.risk == RiskLevel.FORBIDDEN:
                return PolicyDecision(
                    expr=expr,
                    effective_risk=RiskLevel.FORBIDDEN,
                    segments=segments,
                    allowed=False,
                    reason=right.reason,
                )
            if self.config.network.forbid_stdin and right.binary in {"curl", "wget"}:
                return PolicyDecision(
                    expr=expr,
                    effective_risk=RiskLevel.FORBIDDEN,
                    segments=segments,
                    allowed=False,
                    reason="Piping into curl/wget is forbidden (data exfiltration risk)",
                )
            effective = RiskLevel.max(left.effective_risk, right.risk)
            return PolicyDecision(
                expr=expr,
                effective_risk=effective,
                segments=segments,
                allowed=True,
                reason="Allowed",
            )

        if isinstance(expr, (AndCommand, OrCommand)):
            left = self.evaluate(expr.left)
            right = self.evaluate(expr.right)
            segments.extend(left.segments)
            segments.extend(right.segments)
            if not left.allowed:
                return PolicyDecision(
                    expr=expr,
                    effective_risk=RiskLevel.FORBIDDEN,
                    segments=segments,
                    allowed=False,
                    reason=left.reason,
                )
            if not right.allowed:
                return PolicyDecision(
                    expr=expr,
                    effective_risk=RiskLevel.FORBIDDEN,
                    segments=segments,
                    allowed=False,
                    reason=right.reason,
                )
            effective = RiskLevel.max(left.effective_risk, right.effective_risk)
            return PolicyDecision(
                expr=expr,
                effective_risk=effective,
                segments=segments,
                allowed=True,
                reason="Allowed",
            )

        if isinstance(expr, SingleCommand):
            segment = self._evaluate_argv(expr.argv, cwd=expr.cwd)
            segments.append(segment)
            allowed = segment.risk != RiskLevel.FORBIDDEN
            return PolicyDecision(
                expr=expr,
                effective_risk=segment.risk,
                segments=segments,
                allowed=allowed,
                reason=segment.reason if allowed else segment.reason,
            )

        return PolicyDecision(
            expr=expr,
            effective_risk=RiskLevel.FORBIDDEN,
            segments=segments,
            allowed=False,
            reason=f"Unsupported expression type: {type(expr)!r}",
        )

    def _validate_redirect(self, expr: RedirectCommand) -> PolicyDecision:
        target = Path(expr.path).resolve()
        allowed_roots = [
            path.resolve() for path in self.config.filesystem.writable_redirect_paths
        ]
        allowed_roots.append(self.scratch_dir)
        if not any(self._is_under(target, root) for root in allowed_roots):
            return PolicyDecision(
                expr=expr,
                effective_risk=RiskLevel.FORBIDDEN,
                segments=[],
                allowed=False,
                reason=f"Redirect target not allowed: {expr.path}",
                redirect_path=expr.path,
            )
        return PolicyDecision(
            expr=expr,
            effective_risk=RiskLevel.REVERSIBLE,
            segments=[],
            allowed=True,
            reason="Redirect target allowed",
            redirect_path=expr.path,
        )

    def _evaluate_argv(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        piped_to: str | None = None,
    ) -> SegmentDecision:
        if self._matches_forbidden_pattern(argv):
            return SegmentDecision(
                argv=argv,
                binary=argv[0],
                risk=RiskLevel.FORBIDDEN,
                reason="Matched forbidden pattern",
                cwd=cwd,
            )

        binary = Path(argv[0]).name
        rule = self._match_rule(argv, binary)
        if rule is None:
            return SegmentDecision(
                argv=argv,
                binary=binary,
                risk=self.config.fallback_risk,
                reason=self.config.fallback_reason,
                cwd=cwd,
            )

        if rule.path_args:
            path_error = self._validate_path_args(argv, rule.path_args)
            if path_error:
                return SegmentDecision(
                    argv=argv,
                    binary=binary,
                    risk=RiskLevel.FORBIDDEN,
                    reason=path_error,
                    cwd=cwd,
                )

        if rule.network:
            network_error = self._validate_network(argv, binary)
            if network_error:
                return SegmentDecision(
                    argv=argv,
                    binary=binary,
                    risk=RiskLevel.FORBIDDEN,
                    reason=network_error,
                    cwd=cwd,
                )

        if rule.powershell:
            powershell_error = self._validate_powershell(argv)
            if powershell_error:
                return SegmentDecision(
                    argv=argv,
                    binary=binary,
                    risk=RiskLevel.FORBIDDEN,
                    reason=powershell_error,
                    cwd=cwd,
                )

        return SegmentDecision(
            argv=argv,
            binary=binary,
            risk=rule.risk,
            reason=f"Matched rule for {binary}",
            cwd=cwd,
        )

    def _match_rule(self, argv: list[str], binary: str) -> PolicyRule | None:
        subcommand = argv[1] if len(argv) > 1 else None
        normalized = self._normalize_binary(binary)
        for rule in self.config.rules:
            if self._normalize_binary(rule.binary) != normalized:
                continue
            if rule.subcommand is not None and rule.subcommand != subcommand:
                continue
            if rule.arg_prefix is not None:
                if len(argv) < 3 or argv[2] != rule.arg_prefix:
                    continue
            return rule
        return None

    def _validate_powershell(self, argv: list[str]) -> str | None:
        if "-Command" not in argv:
            return (
                "PowerShell must use argv form: powershell -NoProfile -Command "
                "<Cmdlet> -LiteralPath <path> [extra args]"
            )

        command_index = argv.index("-Command")
        script_parts = argv[command_index + 1 :]
        if not script_parts:
            return "PowerShell -Command requires a cmdlet"

        cmdlet = script_parts[0]
        if cmdlet not in self.POWERSHELL_ALLOWED_CMDLETS:
            return f"PowerShell cmdlet not allowed: {cmdlet}"

        joined = " ".join(script_parts)
        for token in self.POWERSHELL_FORBIDDEN_TOKENS:
            if token in joined:
                return f"PowerShell script contains forbidden token: {token}"

        for index, arg in enumerate(script_parts):
            if arg in {"-Path", "-LiteralPath"} and index + 1 < len(script_parts):
                path_error = self._validate_readable_path(script_parts[index + 1])
                if path_error:
                    return path_error
        return None

    def _validate_readable_path(self, raw_path: str) -> str | None:
        resolved = Path(raw_path).expanduser().resolve()
        if not any(
            self._is_under(resolved, root.resolve())
            for root in self.config.filesystem.readable_paths
        ):
            return f"Path not allowed by filesystem policy: {raw_path}"
        return None

    @staticmethod
    def _normalize_binary(name: str) -> str:
        lower = name.lower()
        if lower.endswith(".exe"):
            return lower[:-4]
        return lower

    def _matches_forbidden_pattern(self, argv: list[str]) -> bool:
        joined = " ".join(argv)
        for pattern in self.config.forbidden_patterns:
            if "argv_contains" in pattern:
                parts = pattern["argv_contains"]
                if all(part in argv for part in parts):
                    return True
            if "argv_regex" in pattern:
                regex = re.compile(pattern["argv_regex"])
                if not regex.match(argv[0]):
                    continue
                sub_regex = pattern.get("subcommand_regex")
                if sub_regex and (len(argv) < 2 or not re.match(sub_regex, argv[1])):
                    continue
                return True
            if "pattern" in pattern and re.search(pattern["pattern"], joined):
                return True
        return False

    def _validate_path_args(self, argv: list[str], mode: str) -> str | None:
        path_candidates = [
            arg
            for arg in argv[1:]
            if not arg.startswith("-") and self._looks_like_path(arg)
        ]
        if not path_candidates:
            if mode == "true":
                return "Path argument required but missing"
            return None
        for raw_path in path_candidates:
            path_error = self._validate_readable_path(raw_path)
            if path_error:
                return path_error
        return None

    @staticmethod
    def _looks_like_path(arg: str) -> bool:
        if re.match(r"^[A-Za-z]:[\\/]", arg):
            return True
        return arg.startswith(("/", "./", "../", "~"))

    def _validate_network(self, argv: list[str], binary: str) -> str | None:
        for flag in self.config.network.forbid_upload_flags:
            if flag in argv:
                return f"Network upload flag forbidden: {flag}"

        url = self._extract_url(argv, binary)
        if url is None:
            return "Network command requires an explicit localhost URL"

        host = self._extract_host(url)
        if host not in self.config.network.allowed_hosts:
            return f"Network host not allowed: {host}"

        method = self._extract_method(argv, binary)
        if method not in self.config.network.allowed_methods:
            return f"Network method not allowed: {method}"
        return None

    def _extract_url(self, argv: list[str], binary: str) -> str | None:
        for arg in reversed(argv[1:]):
            if arg.startswith("http://") or arg.startswith("https://"):
                return arg
        if binary == "curl" and len(argv) >= 2 and not argv[1].startswith("-"):
            return argv[1]
        return None

    def _extract_host(self, url: str) -> str:
        without_scheme = url.split("://", 1)[-1]
        host_part = without_scheme.split("/", 1)[0]
        if host_part.startswith("[") and "]" in host_part:
            return host_part[1 : host_part.index("]")]
        return host_part.split(":", 1)[0]

    def _extract_method(self, argv: list[str], binary: str) -> str:
        if binary == "curl":
            for index, arg in enumerate(argv):
                if arg in {"-X", "--request"} and index + 1 < len(argv):
                    return argv[index + 1].upper()
            return "GET"
        if binary == "wget":
            return "GET"
        return "GET"

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def summarize_segments(decision: PolicyDecision) -> str:
    lines = []
    for index, segment in enumerate(decision.segments, start=1):
        lines.append(
            f"  {index}. {' '.join(segment.argv)}  [{segment.risk.label()}]"
        )
    return "\n".join(lines)
