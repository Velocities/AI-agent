"""What this process's model can do. Authenticated, like speech status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import require_deployment_access
from ai_agent.llm.capabilities import ModelInfo

router = APIRouter(tags=["model"])


class ModelInfoResponse(BaseModel):
    engine: str
    model: str
    vision: bool
    tools: bool
    vision_source: str
    tools_source: str
    vision_verified: bool
    tools_verified: bool
    capabilities: list[str]
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    context_length: int | None = None

    @classmethod
    def from_info(cls, info: ModelInfo) -> ModelInfoResponse:
        return cls(
            engine=info.engine,
            model=info.model,
            vision=info.vision,
            tools=info.tools,
            vision_source=info.vision_source,
            tools_source=info.tools_source,
            vision_verified=info.vision_verified,
            tools_verified=info.tools_verified,
            capabilities=sorted(info.capabilities),
            family=info.family,
            parameter_size=info.parameter_size,
            quantization=info.quantization,
            context_length=info.context_length,
        )


@router.get("/api/model", response_model=ModelInfoResponse)
def read_model_info(
    request: Request,
    _user: AuthenticatedUser = Depends(require_deployment_access),
) -> ModelInfoResponse:
    info = getattr(request.app.state, "model_info", None)
    if info is None:
        raise HTTPException(status_code=503, detail="Model information is not available.")
    return ModelInfoResponse.from_info(info)
