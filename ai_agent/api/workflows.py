"""List the workflows a client can start."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.workflows.manifests import WorkflowError, default_workflow_image_root, load_workflow

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowParameterResponse(BaseModel):
    name: str
    required: bool
    description: str = ""


class WorkflowSummaryResponse(BaseModel):
    name: str
    version: str
    description: str = ""
    parameters: list[WorkflowParameterResponse] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummaryResponse]


@router.get("", response_model=WorkflowListResponse)
def list_workflows(
    _user: AuthenticatedUser = Depends(require_deployment_access),
) -> WorkflowListResponse:
    root = default_workflow_image_root()
    directory = root / "workflows"
    items: list[WorkflowSummaryResponse] = []
    if directory.is_dir():
        for child in sorted(directory.iterdir(), key=lambda path: path.name):
            if not (child / "workflow.yaml").is_file():
                continue
            try:
                manifest = load_workflow(root, child.name)
            except WorkflowError:
                continue
            items.append(
                WorkflowSummaryResponse(
                    name=manifest.name,
                    version=manifest.version,
                    description=manifest.description,
                    parameters=[
                        WorkflowParameterResponse(
                            name=item.name,
                            required=item.required,
                            description=item.description,
                        )
                        for item in manifest.parameters
                    ],
                )
            )
    return WorkflowListResponse(workflows=items)
