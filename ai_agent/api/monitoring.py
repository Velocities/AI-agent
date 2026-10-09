"""Admin-only read of host telemetry.

Collection stays in ai_agent.monitoring. This module only calls
collect_gpu_data() and collect_host_telemetry() for a user id present in
the monitoring_admin SQLite table. Who is an admin is changed with
``ai-agent config monitoring grant|revoke``, not with an environment variable.
See ai_agent/deployment/monitoring_admin_store.py and the README section
"Monitoring admins".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ai_agent.api.auth import AuthenticatedUser
from ai_agent.api.deps import get_current_user
from ai_agent.deployment.monitoring_admin_store import MonitoringAdminStore
from ai_agent.monitoring.cpu_telemetry import CPUTelemetry, collect_cpu_data
from ai_agent.monitoring.gpu_telemetry import GPUTelemetry, collect_gpu_data
from ai_agent.monitoring.host_telemetry import collect_host_telemetry
from ai_agent.monitoring.ram_telemetry import RAMTelemetry, collect_ram_data

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


class CpuReadingBody(BaseModel):
    usage_percent: float
    per_core_usage_percent: list[float]
    logical_core_count: int | None = None
    physical_core_count: int | None = None
    frequency_mhz: float | None = None
    min_frequency_mhz: float | None = None
    max_frequency_mhz: float | None = None
    temperature_celsius: float | None = None
    load_average_1m: float | None = None
    load_average_5m: float | None = None
    load_average_15m: float | None = None


class RamReadingBody(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent_used: float
    swap_total_bytes: int
    swap_used_bytes: int
    swap_percent_used: float


class HostTelemetryBody(BaseModel):
    cpu: CpuReadingBody
    ram: RamReadingBody
    gpus: list[GpuReadingBody]


def monitoring_admin_store(request: Request) -> MonitoringAdminStore | None:
    store = getattr(request.app.state, "monitoring_admin_store", None)
    if isinstance(store, MonitoringAdminStore):
        return store
    return None


def is_monitoring_admin(request: Request, user_id: str) -> bool:
    store = monitoring_admin_store(request)
    if store is None:
        return False
    return store.contains(user_id)


def require_monitoring_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    if not is_monitoring_admin(request, user.user_id):
        raise HTTPException(status_code=403, detail="Monitoring is limited to admin users.")
    return user


def _cpu_reading(sample: CPUTelemetry) -> CpuReadingBody:
    return CpuReadingBody(
        usage_percent=float(sample.usage_percent),
        per_core_usage_percent=[float(value) for value in sample.per_core_usage_percent],
        logical_core_count=sample.logical_core_count,
        physical_core_count=sample.physical_core_count,
        frequency_mhz=sample.frequency_mhz,
        min_frequency_mhz=sample.min_frequency_mhz,
        max_frequency_mhz=sample.max_frequency_mhz,
        temperature_celsius=sample.temperature_celsius,
        load_average_1m=sample.load_average_1m,
        load_average_5m=sample.load_average_5m,
        load_average_15m=sample.load_average_15m,
    )


def _ram_reading(sample: RAMTelemetry) -> RamReadingBody:
    return RamReadingBody(
        total_bytes=int(sample.total_bytes),
        used_bytes=int(sample.used_bytes),
        available_bytes=int(sample.available_bytes),
        percent_used=float(sample.percent_used),
        swap_total_bytes=int(sample.swap_total_bytes),
        swap_used_bytes=int(sample.swap_used_bytes),
        swap_percent_used=float(sample.swap_percent_used),
    )


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
    return MonitoringAccessBody(is_admin=is_monitoring_admin(request, user.user_id))


@router.get("/gpus", response_model=GpuReadingsBody)
def monitoring_gpus(
    _user: AuthenticatedUser = Depends(require_monitoring_admin),
) -> GpuReadingsBody:
    return GpuReadingsBody(gpus=[_reading(sample) for sample in collect_gpu_data()])


@router.get("/cpu", response_model=CpuReadingBody)
def monitoring_cpu(
    _user: AuthenticatedUser = Depends(require_monitoring_admin),
) -> CpuReadingBody:
    return _cpu_reading(collect_cpu_data())


@router.get("/ram", response_model=RamReadingBody)
def monitoring_ram(
    _user: AuthenticatedUser = Depends(require_monitoring_admin),
) -> RamReadingBody:
    return _ram_reading(collect_ram_data())


@router.get("/telemetry", response_model=HostTelemetryBody)
def monitoring_telemetry(
    _user: AuthenticatedUser = Depends(require_monitoring_admin),
) -> HostTelemetryBody:
    """CPU, RAM, and GPU from one sample. Clients poll this on the collection interval."""
    sample = collect_host_telemetry()
    return HostTelemetryBody(
        cpu=_cpu_reading(sample.cpu),
        ram=_ram_reading(sample.ram),
        gpus=[_reading(gpu) for gpu in sample.gpus],
    )
