"""Workflow package.

Session objects are imported from ``ai_agent.workflows.session``. Keeping them
out of this module avoids a cycle through the execution targets, which call
the Docker broker, which validates container specs defined here.
"""

from ai_agent.workflows.manifests import WorkflowError, load_workflow

__all__ = [
    "WorkflowError",
    "load_workflow",
]
