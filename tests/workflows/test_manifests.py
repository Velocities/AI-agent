"""Manifest and tool-interface checks. Bodies are still TODOs."""

import pytest


def test_load_text_lab_manifest():
    """text-lab loads both tools from tool.yaml.

    TODO: load_workflow(default_sandbox_root(), "text-lab").
    TODO: assert the tool names are count-lines and count-words, in that order.
    TODO: assert each tool's entrypoint equals its nix attr and its directory name.
    """
    pytest.skip("TODO")


def test_tool_interface_is_json_object_in_and_out():
    """The Dockerfile and the agent share one tool contract.

    TODO: reject a tool.yaml whose interface.stdin is not json.
    TODO: reject an input schema that is not type object.
    TODO: validate_tool_input accepts {"text": "a"} for count-lines.
    TODO: validate_tool_input rejects a missing text field and a non-string text.
    TODO: parse_tool_output accepts {"lines": 2} and rejects {"lines": "2"}.
    """
    pytest.skip("TODO")


def test_workflow_lock_matches_tool_yaml_and_omits_personalization():
    """Nix reads the lock, not the prompt or the session parameters.

    TODO: lock_document(manifest) equals the committed workflow.lock.json.
    TODO: assert "parameters" and "initial_prompt" are absent from the lock.
    TODO: a lock whose tool version differs from tool.yaml raises WorkflowError.
    """
    pytest.skip("TODO")


def test_session_parameters_do_not_change_the_manifest_tools():
    """A label is session data. It does not add or remove tools.

    TODO: validate_parameters accepts {"label": "north-office"}.
    TODO: a required parameter that is missing raises WorkflowError.
    TODO: a parameter value with a newline is rejected.
    TODO: session_document stores the label and the workflow name only.
    """
    pytest.skip("TODO")
