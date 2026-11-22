"""Image cache identity. Bodies are still TODOs."""

import pytest


def test_fingerprint_ignores_session_parameters_and_initial_prompt():
    """Personalizing a session must not produce a new image tag.

    TODO: closure_fingerprint(text-lab) is stable across two calls.
    TODO: rewriting initial_prompt in memory does not change the fingerprint.
    TODO: image_tag is ai-agent-workflow:text-lab-<fingerprint>.
    """
    pytest.skip("TODO")


def test_fingerprint_changes_when_a_tool_source_changes():
    """A different tool package is a different closure.

    TODO: hash the text-lab tree, then hash it again with count_lines.py bytes changed.
    TODO: assert the fingerprints differ.
    TODO: changing wordnotes.py changes the fingerprint because count-words imports it.
    """
    pytest.skip("TODO")


def test_docker_build_uses_the_generic_dockerfile_and_workflow_name():
    """One Dockerfile, selected by the WORKFLOW build arg.

    TODO: docker_build_argv for text-lab includes --build-arg WORKFLOW=text-lab.
    TODO: the context directory is the workflow_image root, not the repo root.
    TODO: docker_image_inspect_argv uses the same tag the build would create.
    TODO: the tag does not contain the session label.
    """
    pytest.skip("TODO")
