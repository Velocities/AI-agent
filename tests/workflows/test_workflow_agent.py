"""Agent wiring for a workflow session. Bodies are still TODOs."""

import pytest


def test_workflow_session_hides_local_and_other_targets():
    """The model only receives the sandbox target.

    TODO: bind_workflow for text-lab with a sleep directory under a temp sleep root.
    TODO: build_agent(..., workflow_session=session) with a fake LLM.
    TODO: router.names() is ["sandbox"] and default_name is "sandbox".
    TODO: the tool list includes run_tool with enum count-lines and count-words.
    TODO: run_command's target enum is only sandbox.
    """
    pytest.skip("TODO")


def test_workflow_prompt_keeps_the_base_prompt():
    """The sandbox note is appended. The existing rules stay in front of it.

    TODO: the system prompt still contains the run_command rules and the base behavior rules.
    TODO: it also contains "Workflow session", the initial prompt, and the session label.
    TODO: an agent built without a workflow session does not contain "Workflow session".
    """
    pytest.skip("TODO")


def test_run_tool_unknown_name_never_executes():
    """A made-up tool is an error before docker exec.

    TODO: call the tool handler with run_tool tool="rm" on a text-lab session.
    TODO: assert the payload error names the known tools.
    TODO: assert the fake executor was not called.
    """
    pytest.skip("TODO")


def test_run_tool_approved_call_uses_manifest_entrypoint_and_stdin():
    """Approval still goes through the existing prompter.

    TODO: a fake prompter records one prompt whose rendered command is count-lines.
    TODO: on approval, the sandbox target is invoked with stdin {"text": "a\\nb"}.
    TODO: a denied approval does not exec and returns user_denied.
    TODO: the prompt is not skipped when confirmation mode is permissive.
    """
    pytest.skip("TODO")
