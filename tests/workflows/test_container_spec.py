"""Container launch contract. Bodies are still TODOs."""

import pytest


def test_run_argv_requires_a_user_namespace():
    """Container root must not be host root.

    TODO: SandboxContainerSpec(user_namespace="host") raises SandboxSpecError.
    TODO: an empty user namespace raises SandboxSpecError.
    TODO: user_namespace="default" is accepted and the argv contains --userns default.
    TODO: the argv does not contain --privileged or --userns host.
    """
    pytest.skip("TODO")


def test_run_argv_rejects_docker_socket_mount():
    """The container must not be able to drive the host Docker daemon.

    TODO: a mount of /var/run/docker.sock raises SandboxSpecError.
    TODO: a mount whose source name is docker.sock, whatever the target, raises.
    TODO: the accepted argv never contains docker.sock.
    """
    pytest.skip("TODO")


def test_run_argv_rejects_host_network_pid_and_privileged():
    """Host namespaces are an escape.

    TODO: network="host" raises SandboxSpecError.
    TODO: a mount whose target is /, /home, or /etc raises SandboxSpecError.
    TODO: a mount other than /work or /nix/store raises SandboxSpecError.
    """
    pytest.skip("TODO")


def test_sleep_volume_must_stay_under_the_sleep_root():
    """The writable mount is the sleep area, not the user's home.

    TODO: /work sourced from a directory under sleep_root is accepted.
    TODO: /work sourced from a home directory raises SandboxSpecError.
    TODO: a read-only /work raises SandboxSpecError.
    TODO: two /work mounts raise SandboxSpecError.
    """
    pytest.skip("TODO")


def test_nix_store_mount_is_optional_and_read_only():
    """The baked image needs no store mount. A shared store must be read-only.

    TODO: a spec with only /work is accepted.
    TODO: an extra read-only /nix/store mount is accepted.
    TODO: a writable /nix/store mount raises SandboxSpecError.
    """
    pytest.skip("TODO")
