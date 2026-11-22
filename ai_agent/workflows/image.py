"""Image identity for a workflow.

The tag changes when the tool closure changes. Session parameters and the
initial prompt are not hashed, so personalizing a session does not rebuild
the image. Docker is asked to build only when that tag is absent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ai_agent.workflows.manifests import WorkflowManifest, default_workflow_image_root

_IMAGE_PREFIX = "ai-agent-workflow"


def closure_fingerprint(manifest: WorkflowManifest, workflow_image_root: Path | None = None) -> str:
    """Hash the Nix inputs for this workflow. Ignores parameters and prompts."""
    root = (workflow_image_root or default_workflow_image_root()).resolve()
    digest = hashlib.sha256()
    digest.update(b"workflow-closure-v2\0")
    digest.update(manifest.name.encode())
    digest.update(b"\0")
    digest.update(manifest.version.encode())
    for tool in manifest.tools:
        digest.update(b"\0tool\0")
        digest.update(tool.name.encode())
        digest.update(b"\0")
        digest.update(tool.version.encode())
        digest.update(b"\0")
        digest.update(tool.nix_attr.encode())
        digest.update(b"\0")
        digest.update(tool.entrypoint.encode())
        _hash_tree(digest, tool.directory, skip_names={"tool.yaml"})
    _hash_tree(digest, root / "nix")
    for name in ("flake.nix", "Dockerfile"):
        _hash_file(digest, root / name, name)
    return digest.hexdigest()[:16]


def image_tag(manifest: WorkflowManifest, workflow_image_root: Path | None = None) -> str:
    fingerprint = closure_fingerprint(manifest, workflow_image_root)
    return f"{_IMAGE_PREFIX}:{manifest.name}-{fingerprint}"


def docker_image_inspect_argv(tag: str) -> list[str]:
    """Exit 0 when this exact closure image is already present."""
    return ["docker", "image", "inspect", "--format", "{{.Id}}", tag]


def docker_build_argv(
    manifest: WorkflowManifest,
    *,
    workflow_image_root: Path | None = None,
    nix_system: str = "x86_64-linux",
) -> list[str]:
    """Build the generic Dockerfile with BuildKit.

    ``--load`` puts the finished image in the local engine, which is where
    the later inspect and ``docker run`` look for it.
    """
    root = workflow_image_root or default_workflow_image_root()
    tag = image_tag(manifest, root)
    return [
        "docker",
        "buildx",
        "build",
        "--load",
        "--build-arg",
        f"WORKFLOW={manifest.name}",
        "--build-arg",
        f"NIX_SYSTEM={nix_system}",
        "-t",
        tag,
        str(root),
    ]


def _hash_tree(digest: hashlib._Hash, directory: Path, *, skip_names: set[str] | None = None) -> None:
    if not directory.is_dir():
        return
    skipped = skip_names or set()
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name not in skipped and "__pycache__" not in path.parts
    ]
    for path in sorted(files, key=lambda item: item.as_posix()):
        relative = path.relative_to(directory).as_posix()
        _hash_file(digest, path, f"{directory.name}/{relative}")


def _hash_file(digest: hashlib._Hash, path: Path, label: str) -> None:
    digest.update(b"\0file\0")
    digest.update(label.encode())
    digest.update(b"\0")
    digest.update(path.read_bytes())
