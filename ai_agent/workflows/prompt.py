"""Extra system-prompt text for a workflow session.

The base administration prompt stays as it is. This block tells the model
that the only place commands run is the workflow container.
"""

from __future__ import annotations

from ai_agent.workflows.session import WorkflowSession


def append_workflow_prompt(system_prompt: str, session: WorkflowSession | None) -> str:
    if session is None:
        return system_prompt
    head = system_prompt.rstrip("\n")
    return f"{head}\n\n{workflow_prompt_suffix(session)}\n"


def workflow_prompt_suffix(session: WorkflowSession) -> str:
    manifest = session.manifest
    tool_lines = "\n".join(
        f"- {tool.name} ({tool.version}): {tool.description}" for tool in manifest.tools
    )
    if session.parameters:
        parameter_lines = "\n".join(
            f"- {name}: {value}" for name, value in sorted(session.parameters.items())
        )
    else:
        parameter_lines = "- (none)"
    return f"""## Workflow session
You are in workflow {manifest.name} {manifest.version}. Your only execution target is sandbox ({session.container_name}).
Commands run inside that container. You can do what the work needs there, including as root inside the container. Nothing you run is executed on the host, and you cannot choose another target.
Use run_tool with a tool name and a JSON input object for the workflow tools. Use run_command or run_commands for anything else inside the container.
Copying files out of the container onto the user's machine is a separate confirmation. Do not claim host files were written unless a promotion result says so.

Initial task:
{manifest.initial_prompt}

Session parameters:
{parameter_lines}

Workflow tools:
{tool_lines}"""
