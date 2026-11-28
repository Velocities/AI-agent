"""Image identity for a workflow.

The tag changes when the tool closure changes. Session parameters and the
initial prompt are not hashed, so personalizing a session does not rebuild
the image. Docker is asked to build only when that tag is absent.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from ai_agent.workflows.manifests import (
    WorkflowManifest,
    default_workflow_image_root,
    workflow_engine_root,
)

_IMAGE_PREFIX = "ai-agent-workflow"


def closure_fingerprint(
    manifest: WorkflowManifest,
    workflow_image_root: Path | None = None,
    engine_root: Path | None = None,
) -> str:
    """Hash the Nix inputs for this workflow. Ignores parameters and prompts.

    Only this workflow's pinned tool and library versions are hashed, plus
    the engine Dockerfile and flake. Another workflow's files do not change
    this tag.
    """
    del workflow_image_root  # pins are already resolved onto the manifest
    engine = (engine_root or workflow_engine_root()).resolve()
    digest = hashlib.sha256()
    digest.update(b"workflow-closure-v3\0")
    digest.update(manifest.name.encode())
    digest.update(b"\0")
    digest.update(manifest.version.encode())
    seen_libraries: set[tuple[str, str]] = set()
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
        for lib in tool.libraries:
            key = (lib.name, lib.version)
            if key in seen_libraries:
                continue
            seen_libraries.add(key)
            digest.update(b"\0library\0")
            digest.update(lib.name.encode())
            digest.update(b"\0")
            digest.update(lib.version.encode())
            _hash_tree(digest, lib.directory)
    for name in ("flake.nix", "Dockerfile"):
        _hash_file(digest, engine / name, name)
    return digest.hexdigest()[:16]


def image_tag(
    manifest: WorkflowManifest,
    workflow_image_root: Path | None = None,
    engine_root: Path | None = None,
) -> str:
    fingerprint = closure_fingerprint(manifest, workflow_image_root, engine_root)
    return f"{_IMAGE_PREFIX}:{manifest.name}-{fingerprint}"


def docker_image_inspect_argv(tag: str) -> list[str]:
    """Exit 0 when this exact closure image is already present."""
    return ["docker", "image", "inspect", "--format", "{{.Id}}", tag]


def stage_workflow_context(manifest: WorkflowManifest, engine: Path, dest: Path) -> None:
    """Write one workflow's build context. Other workflows are not copied."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in ("Dockerfile", "flake.nix"):
        shutil.copy2(engine / name, dest / name)
    shutil.copy2(manifest.directory / "workflow.lock.json", dest / "workflow.lock.json")
    for tool in manifest.tools:
        target = dest / "tools" / tool.name / tool.version
        shutil.copytree(tool.directory, target)
        # Nix reads this file. It is written from tool.yaml, not from the workflow.
        library_list = [
            {"name": lib.name, "version": lib.version}
            for lib in tool.libraries
        ]
        (target / "libraries.json").write_text(
            json.dumps(library_list, indent=2) + "\n",
            encoding="utf-8",
        )
    copied: set[tuple[str, str]] = set()
    for tool in manifest.tools:
        for lib in tool.libraries:
            key = (lib.name, lib.version)
            if key in copied:
                continue
            copied.add(key)
            shutil.copytree(lib.directory, dest / "libraries" / lib.name / lib.version)
    libraries = dest / "libraries"
    libraries.mkdir(parents=True, exist_ok=True)
    if not any(libraries.iterdir()):
        (libraries / ".keep").write_text("")


def docker_build_argv(
    manifest: WorkflowManifest,
    *,
    workflow_image_root: Path | None = None,
    engine_root: Path | None = None,
    nix_system: str = "x86_64-linux",
) -> list[str]:
    """Stage this workflow and build that directory with BuildKit.

    ``--load`` puts the finished image in the local engine, which is where
    the later inspect and ``docker run`` look for it. The context is
    ``<catalog>/.build/<name>-<fingerprint>``, not the whole catalog.
    """
    catalog = (workflow_image_root or default_workflow_image_root()).resolve()
    engine = (engine_root or workflow_engine_root()).resolve()
    tag = image_tag(manifest, catalog, engine)
    fingerprint = tag.rsplit("-", 1)[-1]
    dest = catalog / ".build" / f"{manifest.name}-{fingerprint}"
    stage_workflow_context(manifest, engine, dest)
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
        str(dest),
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
