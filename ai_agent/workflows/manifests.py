"""Load workflow and tool manifests.

The YAML files are the authoring format. workflow.lock.json is the file Nix
and the Dockerfile read. Personalization parameters are not part of the lock.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

TOOL_API = "ai-agent.tool/v1"
WORKFLOW_API = "ai-agent.workflow/v1"
_SEGMENT = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_LIBRARY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SCHEMA_TYPES = {"string", "integer", "number", "boolean", "object", "array"}


class WorkflowError(ValueError):
    """A workflow or tool manifest cannot be loaded or called."""


class _NixRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attr: str


class _Interface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stdin: str
    stdout: str
    input: dict
    output: dict


class _LibraryFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str


class _ToolFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apiVersion: str
    name: str
    version: str
    description: str = ""
    libraries: list[_LibraryFile] = Field(default_factory=list)
    nix: _NixRef
    entrypoint: str
    interface: _Interface


class _ParameterFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    required: bool = False
    description: str = ""


class _ToolRefFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    version: str


class _WorkflowFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    apiVersion: str
    name: str
    version: str
    description: str = ""
    initial_prompt: str = ""
    parameters: list[_ParameterFile] = Field(default_factory=list)
    tools: list[_ToolRefFile]


@dataclass(frozen=True)
class WorkflowParameter:
    name: str
    required: bool
    description: str


@dataclass(frozen=True)
class WorkflowLibrary:
    name: str
    version: str
    directory: Path


@dataclass(frozen=True)
class WorkflowTool:
    name: str
    version: str
    description: str
    nix_attr: str
    entrypoint: str
    input_schema: dict
    output_schema: dict
    directory: Path
    libraries: tuple[WorkflowLibrary, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class WorkflowManifest:
    name: str
    version: str
    description: str
    initial_prompt: str
    parameters: tuple[WorkflowParameter, ...]
    tools: tuple[WorkflowTool, ...]
    directory: Path

    def tool(self, name: str) -> WorkflowTool:
        for item in self.tools:
            if item.name == name:
                return item
        known = ", ".join(item.name for item in self.tools) or "(none)"
        raise WorkflowError(f"Unknown workflow tool {name!r}. Tools: {known}")


def workflow_engine_root() -> Path:
    """Dockerfile and flake.nix. These stay with the engine install."""
    return Path(__file__).resolve().parents[2] / "workflow_image"


def default_catalog_root() -> Path:
    """Definitions tree: tools/, libraries/, and workflows/.

    ``WORKFLOW_CATALOG_ROOT`` is that directory. The engine Dockerfile and
    flake stay in this checkout and are not part of the catalog.
    """
    from ai_agent.config import Settings

    configured = Settings().workflow_catalog_root.strip()
    if not configured:
        raise WorkflowError(
            "WORKFLOW_CATALOG_ROOT is not set. "
            "Point it at a checkout of the workflow catalog."
        )
    return Path(configured)


def default_workflow_image_root() -> Path:
    """Catalog root. The name remains for callers that stage image builds."""
    return default_catalog_root()


def load_workflow(workflow_image_root: Path, name: str) -> WorkflowManifest:
    """Load one workflow directory and require its lock to match the YAML."""
    workflow_name = _segment(name, "workflow name")
    directory = workflow_image_root / "workflows" / workflow_name
    workflow_path = directory / "workflow.yaml"
    if not workflow_path.is_file():
        raise WorkflowError(f"No workflow.yaml in {directory}")
    document = _parse_yaml(workflow_path, _WorkflowFile)
    if document.apiVersion != WORKFLOW_API:
        raise WorkflowError(
            f"{workflow_path} has apiVersion {document.apiVersion!r}, expected {WORKFLOW_API}"
        )
    if document.name != workflow_name:
        raise WorkflowError(
            f"{workflow_path} name is {document.name!r}, directory is {workflow_name!r}"
        )
    _version(document.version, "workflow version")
    parameters = _parameters(document.parameters)
    tools = tuple(
        _load_tool(workflow_image_root, ref.name, ref.version) for ref in document.tools
    )
    if not tools:
        raise WorkflowError(f"Workflow {workflow_name!r} requires at least one tool")
    _require_one_library_version(tools)
    manifest = WorkflowManifest(
        name=document.name,
        version=document.version,
        description=document.description.strip(),
        initial_prompt=document.initial_prompt.strip(),
        parameters=parameters,
        tools=tools,
        directory=directory,
    )
    _require_matching_lock(directory / "workflow.lock.json", manifest)
    return manifest


def lock_document(manifest: WorkflowManifest) -> dict:
    """The Nix/Docker contract. Parameters and the initial prompt are omitted."""
    return {
        "name": manifest.name,
        "version": manifest.version,
        "tools": [
            {
                "attr": tool.nix_attr,
                "entrypoint": tool.entrypoint,
                "name": tool.name,
                "version": tool.version,
            }
            for tool in manifest.tools
        ],
    }


def validate_parameters(
    manifest: WorkflowManifest,
    parameters: dict[str, str] | None,
) -> dict[str, str]:
    """Return session parameters. These never change the image."""
    supplied = dict(parameters or {})
    known = {item.name: item for item in manifest.parameters}
    unknown = sorted(set(supplied) - set(known))
    if unknown:
        raise WorkflowError(
            "Unknown workflow parameters: " + ", ".join(unknown)
        )
    stored: dict[str, str] = {}
    for name, spec in known.items():
        if name not in supplied:
            if spec.required:
                raise WorkflowError(f"Workflow parameter {name!r} is required")
            continue
        value = supplied[name]
        if not isinstance(value, str):
            raise WorkflowError(f"Workflow parameter {name!r} must be a string")
        if len(value) > 200 or any(ord(char) < 32 for char in value):
            raise WorkflowError(
                f"Workflow parameter {name!r} must be a single line of at most 200 characters"
            )
        stored[name] = value
    return stored


def session_document(manifest: WorkflowManifest, parameters: dict[str, str]) -> dict:
    """JSON the host writes to /work/session.json after the container starts."""
    return {
        "workflow": manifest.name,
        "version": manifest.version,
        "parameters": validate_parameters(manifest, parameters),
    }


def validate_tool_input(tool: WorkflowTool, value: object) -> dict:
    if not isinstance(value, dict):
        raise WorkflowError("tool input must be a JSON object")
    _check_object(tool.input_schema, value, label="input")
    return value


def parse_tool_output(tool: WorkflowTool, stdout: str) -> dict:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Tool {tool.name} did not return JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"Tool {tool.name} output must be a JSON object")
    _check_object(tool.output_schema, value, label="output")
    return value


def _require_one_library_version(tools: tuple[WorkflowTool, ...]) -> None:
    seen: dict[str, str] = {}
    for tool in tools:
        for lib in tool.libraries:
            previous = seen.get(lib.name)
            if previous is not None and previous != lib.version:
                raise WorkflowError(
                    f"Tools in this image request {lib.name} {previous} and {lib.name} {lib.version}. "
                    "A library name is installed once per image."
                )
            seen[lib.name] = lib.version


def _load_tool(catalog: Path, name: str, version: str) -> WorkflowTool:
    tool_name = _segment(name, "tool name")
    tool_version = _version(version, "tool version")
    directory = catalog / "tools" / tool_name / tool_version
    path = directory / "tool.yaml"
    if not path.is_file():
        raise WorkflowError(f"Workflow requires {tool_name!r} but {path} is missing")
    if not (directory / "default.nix").is_file():
        raise WorkflowError(f"Tool {tool_name!r} is missing default.nix")
    document = _parse_yaml(path, _ToolFile)
    if document.apiVersion != TOOL_API:
        raise WorkflowError(
            f"{path} has apiVersion {document.apiVersion!r}, expected {TOOL_API}"
        )
    if document.name != tool_name:
        raise WorkflowError(f"{path} name is {document.name!r}, directory is {tool_name!r}")
    if document.version != version:
        raise WorkflowError(
            f"Workflow asks for {tool_name} {version}, tool.yaml says {document.version}"
        )
    _version(document.version, "tool version")
    attr = _segment(document.nix.attr, "nix attr")
    entrypoint = _segment(document.entrypoint, "entrypoint")
    if document.interface.stdin != "json" or document.interface.stdout != "json":
        raise WorkflowError(f"Tool {tool_name!r} must use JSON on stdin and stdout")
    _require_object_schema(document.interface.input, f"{tool_name} input")
    _require_object_schema(document.interface.output, f"{tool_name} output")
    return WorkflowTool(
        name=tool_name,
        version=document.version,
        description=document.description.strip(),
        nix_attr=attr,
        entrypoint=entrypoint,
        input_schema=document.interface.input,
        output_schema=document.interface.output,
        directory=directory,
        libraries=tuple(
            _load_library(catalog, item.name, item.version) for item in document.libraries
        ),
    )


def _load_library(catalog: Path, name: str, version: str) -> WorkflowLibrary:
    lib_name = _token(name, "library name", _LIBRARY)
    lib_version = _version(version, "library version")
    directory = catalog / "libraries" / lib_name / lib_version
    source = directory / f"{lib_name}.py"
    if not source.is_file():
        raise WorkflowError(f"Library {lib_name} {lib_version} is missing {source.name}")
    return WorkflowLibrary(name=lib_name, version=lib_version, directory=directory)


def _parameters(items: list[_ParameterFile]) -> tuple[WorkflowParameter, ...]:
    seen: set[str] = set()
    parameters: list[WorkflowParameter] = []
    for item in items:
        name = _segment(item.name, "parameter name")
        if name in seen:
            raise WorkflowError(f"Duplicate workflow parameter {name!r}")
        seen.add(name)
        parameters.append(
            WorkflowParameter(
                name=name,
                required=item.required,
                description=item.description.strip(),
            )
        )
    return tuple(parameters)


def _require_matching_lock(path: Path, manifest: WorkflowManifest) -> None:
    if not path.is_file():
        raise WorkflowError(
            f"{path} is missing. Nix reads this file; write it from lock_document()."
        )
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"{path} is not JSON: {exc}") from exc
    expected = lock_document(manifest)
    if loaded != expected:
        raise WorkflowError(
            f"{path} does not match workflow.yaml. Rebuild the lock from the "
            "tool names, versions, nix attrs, and entrypoints. "
            "Leave parameters out."
        )


def _require_object_schema(schema: dict, label: str) -> None:
    if schema.get("type") != "object":
        raise WorkflowError(f"{label} schema must be a JSON object")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise WorkflowError(f"{label} properties must be a mapping")
    for name, spec in properties.items():
        _segment(str(name), f"{label} property")
        if not isinstance(spec, dict) or spec.get("type") not in _SCHEMA_TYPES:
            raise WorkflowError(f"{label} property {name!r} needs a supported type")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise WorkflowError(f"{label} required must be a list of names")
    missing = [item for item in required if item not in properties]
    if missing:
        raise WorkflowError(f"{label} requires unknown properties: {', '.join(missing)}")


def _check_object(schema: dict, value: dict, *, label: str) -> None:
    properties = schema.get("properties") or {}
    required = schema.get("required") or []
    for name in required:
        if name not in value:
            raise WorkflowError(f"{label} missing {name}")
    for name, item in value.items():
        spec = properties.get(name)
        if spec is None:
            raise WorkflowError(f"{label} has unexpected field {name}")
        if not _matches_type(item, spec["type"]):
            raise WorkflowError(f"{label} field {name} must be {spec['type']}")


def _matches_type(value: object, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _parse_yaml(path: Path, model: type[BaseModel]) -> BaseModel:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowError(f"Could not read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkflowError(f"{path} must be a mapping")
    try:
        return model.model_validate(raw)
    except Exception as exc:
        raise WorkflowError(f"Invalid manifest {path}: {exc}") from exc


def _segment(value: str, label: str) -> str:
    return _token(value, label, _SEGMENT)


def _version(value: str, label: str) -> str:
    return _token(value, label, _VERSION)


def _token(value: str, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise WorkflowError(
            f"Invalid {label} {value!r}. Use letters, digits, dots, hyphens, or underscores."
        )
    return value
