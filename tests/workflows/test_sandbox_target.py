"""Sandbox execution target. No model. Bodies are still TODOs.

Live cases need a Docker daemon and are marked docker. They stay skipped
until the container fixture exists.
"""

import pytest


def test_exec_prefix_uses_the_bound_container_only():
    """The model cannot choose which container docker exec enters.

    TODO: build a SandboxExecutionTarget with container name text-lab-demo.
    TODO: docker_argv for ["whoami"] starts with docker exec -i -w /work text-lab-demo.
    TODO: the argv does not contain -u. Root inside the container is the image default.
    TODO: a container name that starts with "-" is rejected at construction.
    """
    pytest.skip("TODO")


def test_write_file_is_applied_inside_the_container():
    """write_file must not call the host executor's host write.

    TODO: run a write_file for /work/note.txt against a fake executor.
    TODO: assert the executor saw docker exec argv, not a host WriteFileCommand.
    TODO: the file body is the process stdin, and the path is a separate argv element.
    """
    pytest.skip("TODO")


def test_write_file_rejects_paths_that_leave_work():
    """Lexical escapes never become a host path.

    TODO: confine_work_path("../etc/passwd") raises SandboxEscape.
    TODO: confine_work_path("/etc/passwd") raises SandboxEscape.
    TODO: confine_work_path("/work/nested/note.txt") returns that path.
    TODO: SandboxExecutionTarget.run returns success False and does not call the executor.
    """
    pytest.skip("TODO")


def test_run_tool_entrypoint_comes_from_the_manifest():
    """A tool call cannot substitute its own binary path.

    TODO: run_tool("count-lines", stdin) execs count-lines under /work.
    TODO: run_tool("../bin/sh") returns sandbox_rejected and does not exec.
    TODO: an unknown tool name fails in the tool handler before any docker argv is built.
    """
    pytest.skip("TODO")


@pytest.mark.docker
def test_live_container_has_no_docker_socket_or_host_mounts():
    """Start text-lab with the spec argv and try the obvious escapes.

    TODO: build the generic Dockerfile for WORKFLOW=text-lab.
    TODO: run it with --userns=default, no docker.sock, /work under the sleep root.
    TODO: inside the container, test -S /var/run/docker.sock is false.
    TODO: `docker ps` fails because the docker client is not installed.
    TODO: a write to /work/escape via a symlink to / does not create a file on the host
          outside the sleep volume.
    TODO: whoami inside the container is root, and the host uid of a file created in
          /work is not 0.
    """
    pytest.skip("TODO")


@pytest.mark.docker
def test_live_commands_cannot_reach_the_host_filesystem():
    """Pen-test commands, no model.

    TODO: send argv ["cat", "/etc/passwd"] and assert the contents are the image's
          passwd, not the host's.
    TODO: send a command that reads the agent source tree and assert it is not visible.
    TODO: send mount, nsenter, and a write to /nix/store and assert each one fails.
    """
    pytest.skip("TODO")
