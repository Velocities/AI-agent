from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

TARGET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
RESERVED_LOCAL_NAME = "local"


class TargetConfigError(ValueError):
    """Invalid execution-target configuration."""


class LocalTargetRecord(BaseModel):
    type: Literal["local"]
    description: str = "This machine (where the agent CLI runs)"


class SshTargetRecord(BaseModel):
    type: Literal["ssh"]
    description: str = ""
    host: str
    user: str
    port: int = 22
    identity_file: Path
    known_hosts: Path | None = None

    @field_validator("host", "user")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()


class DockerTargetRecord(BaseModel):
    type: Literal["docker"]
    description: str = ""
    container: str
    docker_bin: str = "docker"
    user: str = ""

    @field_validator("container")
    @classmethod
    def container_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("container must not be empty")
        return value.strip()


TargetRecord = LocalTargetRecord | SshTargetRecord | DockerTargetRecord


class ExecutionTargetsFile(BaseModel):
    default_target: str = RESERVED_LOCAL_NAME
    execution_targets: dict[str, TargetRecord] = Field(default_factory=dict)


def validate_target_name(name: str) -> str:
    if not TARGET_NAME_RE.match(name):
        raise TargetConfigError(
            f"Invalid target name {name!r}. Use a letter, then letters, "
            "digits, hyphens, or underscores."
        )
    return name


def default_targets_path() -> Path:
    return Path("execution_targets.yaml")


def execution_target_dir(name: str, *, root: Path | None = None) -> Path:
    base = root or Path.cwd()
    return base / ".ai-agent" / "execution-targets" / name


def load_targets_file(path: Path) -> ExecutionTargetsFile:
    if not path.is_file():
        return ExecutionTargetsFile(
            default_target=RESERVED_LOCAL_NAME,
            execution_targets={
                RESERVED_LOCAL_NAME: LocalTargetRecord(type="local"),
            },
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TargetConfigError(f"{path} must contain a YAML mapping")
    parsed = _parse_file(raw, base=path.parent)
    if RESERVED_LOCAL_NAME not in parsed.execution_targets:
        parsed.execution_targets[RESERVED_LOCAL_NAME] = LocalTargetRecord(type="local")
    return parsed


def _parse_file(raw: dict[str, Any], *, base: Path) -> ExecutionTargetsFile:
    default_target = str(raw.get("default_target") or RESERVED_LOCAL_NAME)
    items = raw.get("execution_targets") or {}
    if not isinstance(items, dict):
        raise TargetConfigError("execution_targets must be a mapping of name → target")
    targets: dict[str, TargetRecord] = {}
    for name, spec in items.items():
        validate_target_name(str(name))
        if not isinstance(spec, dict):
            raise TargetConfigError(f"Target {name!r} must be a mapping")
        targets[str(name)] = _parse_record(str(name), spec, base=base)
    return ExecutionTargetsFile(default_target=default_target, execution_targets=targets)


def _parse_record(name: str, spec: dict[str, Any], *, base: Path) -> TargetRecord:
    kind = spec.get("type") or spec.get("backend")
    if kind == "local":
        if name != RESERVED_LOCAL_NAME:
            raise TargetConfigError(
                f"Local targets must be named {RESERVED_LOCAL_NAME!r}, not {name!r}"
            )
        return LocalTargetRecord.model_validate({**spec, "type": "local"})
    if kind == "ssh":
        if name == RESERVED_LOCAL_NAME:
            raise TargetConfigError(f"{RESERVED_LOCAL_NAME!r} is reserved for the local target")
        data = {**spec, "type": "ssh"}
        record = SshTargetRecord.model_validate(data)
        return record.model_copy(
            update={
                "identity_file": _resolve_path(record.identity_file, base),
                "known_hosts": _resolve_path(
                    record.known_hosts
                    or execution_target_dir(name, root=base) / "known_hosts",
                    base,
                ),
            }
        )
    if kind == "docker":
        if name == RESERVED_LOCAL_NAME:
            raise TargetConfigError(f"{RESERVED_LOCAL_NAME!r} is reserved for the local target")
        return DockerTargetRecord.model_validate({**spec, "type": "docker"})
    raise TargetConfigError(
        f"Target {name!r} has unknown type {kind!r}. Use local, ssh, or docker."
    )


def _resolve_path(path: Path, base: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_absolute():
        return expanded
    return (base / expanded).resolve()


def dump_targets_file(document: ExecutionTargetsFile, path: Path, *, base: Path | None = None) -> None:
    root = base or path.parent
    payload: dict[str, Any] = {
        "default_target": document.default_target,
        "execution_targets": {},
    }
    for name, record in document.execution_targets.items():
        payload["execution_targets"][name] = _record_to_yaml(name, record, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _record_to_yaml(name: str, record: TargetRecord, base: Path) -> dict[str, Any]:
    if isinstance(record, LocalTargetRecord):
        return {"type": "local", "description": record.description}
    if isinstance(record, SshTargetRecord):
        known = record.known_hosts or execution_target_dir(name, root=base) / "known_hosts"
        return {
            "type": "ssh",
            "description": record.description,
            "host": record.host,
            "user": record.user,
            "port": record.port,
            "identity_file": _rel_or_posix(record.identity_file, base),
            "known_hosts": _rel_or_posix(known, base),
        }
    payload = {
        "type": "docker",
        "description": record.description,
        "container": record.container,
        "docker_bin": record.docker_bin,
    }
    if record.user:
        payload["user"] = record.user
    return payload


def _rel_or_posix(path: Path, base: Path) -> str:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        return resolved.as_posix()
    try:
        return resolved.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return resolved.resolve().as_posix()


def upsert_target(path: Path, name: str, record: TargetRecord) -> ExecutionTargetsFile:
    document = load_targets_file(path)
    document.execution_targets[name] = record
    dump_targets_file(document, path)
    return document
