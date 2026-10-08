"""Admin-only read of the latest GPU telemetry.

Collection stays in ai_agent.monitoring.gpu_telemetry. This module only
calls collect_gpu_data() for an allowlisted user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import get_current_user
from ai_agent.config import Settings
from ai_agent.monitoring.gpu_telemetry import GPUTelemetry, collect_gpu_data

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


class MonitoringAccessBody(BaseModel):
    is_admin: bool


class GpuReadingBody(BaseModel):
    name: str
    index: int
    temperature_celsius: float
    memory_used_bytes: int
    memory_total_bytes: int
    power_usage_watts: float | None = None
    fan_speed_percent: float | None = None


class GpuReadingsBody(BaseModel):
    gpus: list[GpuReadingBody]


def monitoring_admin_ids(settings: Settings) -> frozenset[str]:
    return frozenset(
        part.strip()
        for part in settings.monitoring_admin_user_ids.split(",")
        if part.strip()
    )


def is_monitoring_admin(settings: Settings, user_id: str) -> bool:
    return user_id in monitoring_admin_ids(settings)


def require_monitoring_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    settings: Settings = request.app.state.settings
    if not is_monitoring_admin(settings, user.user_id):
        raise HTTPException(status_code=403, detail="Monitoring is limited to admin users.")
    return user


def _reading(sample: GPUTelemetry) -> GpuReadingBody:
    fan = sample.fan_speed_percent
    return GpuReadingBody(
        name=sample.name,
        index=sample.index,
        temperature_celsius=float(sample.temperature_celsius),
        memory_used_bytes=int(sample.memory_used_bytes),
        memory_total_bytes=int(sample.memory_total_bytes),
        power_usage_watts=None if sample.power_usage_watts is None else float(sample.power_usage_watts),
        fan_speed_percent=None if fan is None else float(fan),
    )


@router.get("/access", response_model=MonitoringAccessBody)
def monitoring_access(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> MonitoringAccessBody:
    settings: Settings = request.app.state.settings
    return MonitoringAccessBody(is_admin=is_monitoring_admin(settings, user.user_id))


@router.get("/gpus", response_model=GpuReadingsBody)
def monitoring_gpus(
    _user: AuthenticatedUser = Depends(require_monitoring_admin),
) -> GpuReadingsBody:
    return GpuReadingsBody(gpus=[_reading(sample) for sample in collect_gpu_data()])
