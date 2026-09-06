from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from ai_agent.commands.executor import CommandExecutor
from ai_agent.execution_targets.docker import DockerExecutionTarget

IMAGE = "ai-agent-test-exec-target:local"
DOCKERFILE_DIR = Path(__file__).resolve().parent


def _docker_bin() -> str | None:
    return shutil.which("docker")


def docker_ready() -> bool:
    binary = _docker_bin()
    if not binary:
        return False
    result = subprocess.run(
        [binary, "info"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def docker(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    binary = _docker_bin()
    if not binary:
        raise RuntimeError("docker is not on PATH")
    return subprocess.run(
        [binary, *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def executor(tmp_path: Path) -> CommandExecutor:
    return CommandExecutor(
        timeout=30,
        output_limit=32768,
        scratch_dir=tmp_path / "scratch",
    )


@pytest.fixture(scope="module")
def docker_container():
    """Build the test image and run one disposable Linux container."""
    if not docker_ready():
        pytest.skip("Docker daemon is not available")

    build = docker("build", "-t", IMAGE, str(DOCKERFILE_DIR), timeout=300)
    if build.returncode != 0:
        pytest.fail(
            "Failed to build the live Docker test image:\n"
            f"{build.stderr or build.stdout}"
        )

    name = f"ai-agent-test-{uuid.uuid4().hex[:8]}"
    run = docker(
        "run",
        "-d",
        "--name",
        name,
        IMAGE,
        "sleep",
        "infinity",
    )
    if run.returncode != 0:
        pytest.fail(f"Failed to start test container:\n{run.stderr or run.stdout}")
    container_id = run.stdout.strip()
    try:
        yield {"id": container_id, "name": name}
    finally:
        docker("rm", "-f", name, timeout=30)


@pytest.fixture
def docker_target(docker_container, executor) -> DockerExecutionTarget:
    return DockerExecutionTarget(
        name="lab",
        container=docker_container["name"],
        executor=executor,
        description="Live Linux test container",
    )


@pytest.fixture
def docker_root_target(docker_container, executor) -> DockerExecutionTarget:
    """Same existing container, but docker exec -u root (no sudo in the image)."""
    return DockerExecutionTarget(
        name="lab-root",
        container=docker_container["name"],
        executor=executor,
        description="Existing container, exec as root",
        user="root",
    )
