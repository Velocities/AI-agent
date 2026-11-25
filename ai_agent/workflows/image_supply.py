"""Workflow image cache: inspect by closure tag, build only when missing.

Like a Makefile rule for object files: the tag is the artifact name. If
``docker image inspect`` succeeds, preparation skips the build. Otherwise the
supply backend materializes that tag once; later conversations reuse it.

Callers talk to :class:`WorkflowImageCache` and a :class:`WorkflowImageSupply`
implementation. They do not reference the broker OS user or host paths.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ai_agent.workflows.image import docker_build_argv, docker_image_inspect_argv
from ai_agent.workflows.session import WorkflowSession

logger = logging.getLogger(__name__)

BUILD_TIMEOUT_SECONDS = 30 * 60
INSPECT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class ImagePresence:
    present: bool
    unavailable: str = ""


class WorkflowImageSupply(Protocol):
    """Materialize workflow closure images without naming broker host details."""

    def inspect(self, tag: str, *, docker_bin: str = "docker") -> ImagePresence:
        """Return whether this exact tag is already in the local engine."""

    def build(
        self,
        session: WorkflowSession,
        *,
        workflow_image_root: Path,
        nix_system: str,
    ) -> None:
        """Create the session image when :meth:`inspect` reported absent."""


class WorkflowImageCache:
    """Make-style ensure: cached tag wins; otherwise build through the supply."""

    def __init__(
        self,
        supply: WorkflowImageSupply,
        *,
        workflow_image_root: Path,
        nix_system: str,
    ) -> None:
        self._supply = supply
        self._workflow_image_root = workflow_image_root
        self._nix_system = nix_system

    def inspect_session(self, session: WorkflowSession) -> ImagePresence:
        logger.info("Checking workflow image %s", session.image)
        presence = self._supply.inspect(session.image, docker_bin=session.spec.docker_bin)
        if presence.present:
            logger.info("Workflow image %s is already present", session.image)
        elif presence.unavailable:
            logger.error(
                "Docker cannot be used for workflow image %s: %s",
                session.image,
                presence.unavailable,
            )
        else:
            logger.info("Workflow image %s is not cached", session.image)
        return presence

    def build_session(self, session: WorkflowSession) -> None:
        logger.info("Building workflow image %s", session.image)
        self._supply.build(
            session,
            workflow_image_root=self._workflow_image_root,
            nix_system=self._nix_system,
        )
        logger.info("Built workflow image %s", session.image)


class BrokerBackedImageSupply:
    """Local engine via the Docker broker socket. Default for on-host builds."""

    def __init__(self, runner) -> None:
        self._runner = runner

    def inspect(self, tag: str, *, docker_bin: str = "docker") -> ImagePresence:
        argv = [docker_bin, *docker_image_inspect_argv(tag)[1:]]
        result = self._runner(argv, timeout=INSPECT_TIMEOUT_SECONDS)
        if result.returncode == 0:
            return ImagePresence(present=True)
        detail = _command_detail(result)
        if _docker_unavailable(result):
            return ImagePresence(
                present=False,
                unavailable=detail or "Docker is not usable.",
            )
        return ImagePresence(present=False)

    def build(
        self,
        session: WorkflowSession,
        *,
        workflow_image_root: Path,
        nix_system: str,
    ) -> None:
        from ai_agent.workflows.runtime import WorkflowRuntimeError

        argv = docker_build_argv(
            session.manifest,
            workflow_image_root=workflow_image_root,
            nix_system=nix_system,
        )
        argv = [session.spec.docker_bin, *argv[1:]]
        result = self._runner(argv, timeout=BUILD_TIMEOUT_SECONDS)
        if result.returncode != 0:
            detail = _command_detail(result) or f"Could not build {session.image}."
            logger.error(
                "Workflow image build failed for %s (exit %s): %s",
                session.image,
                result.returncode,
                detail,
            )
            raise WorkflowRuntimeError(detail)


class RemoteRegistryImageSupply:
    """TODO (solution E): images built on a farm or in CI, pulled on demand.

    Future: verify signature, pull ``ai-agent-workflow:<name>-<fingerprint>``
    from a registry (or object store), then load into the local engine. The
  API lifecycle would select this supply instead of :class:`BrokerBackedImageSupply`
    when ``WORKFLOW_IMAGE_SUPPLY=remote`` (or similar) is configured.
    """

    def __init__(self, registry_url: str = "") -> None:
        self.registry_url = registry_url

    def inspect(self, tag: str, *, docker_bin: str = "docker") -> ImagePresence:
        # TODO: resolve tag in registry or a local promotion manifest; fall back
        # to engine inspect when the image was already pulled.
        pass

    def build(
        self,
        session: WorkflowSession,
        *,
        workflow_image_root: Path,
        nix_system: str,
    ) -> None:
        # TODO: pull (and verify) the closure image instead of buildx on host.
        pass


def broker_workflow_image_supply(runner) -> WorkflowImageSupply:
    """Default on-server supply: authorized broker ``invoke`` only."""
    return BrokerBackedImageSupply(runner)


def remote_workflow_image_supply(registry_url: str = "") -> WorkflowImageSupply:
    """TODO (solution E): factory for off-host image materialization."""
    return RemoteRegistryImageSupply(registry_url)


def _command_detail(result: subprocess.CompletedProcess[str]) -> str:
    text = (result.stderr or result.stdout or "").strip()
    if len(text) <= 2000:
        return text
    return text[-2000:]


def _docker_unavailable(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 127:
        return True
    text = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return any(
        phrase in text
        for phrase in (
            "permission denied",
            "cannot connect to the docker daemon",
            "is the docker daemon running",
            "dial unix",
        )
    )