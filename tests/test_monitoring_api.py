from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser
from ai_agent.config import Settings
from ai_agent.conversations.db import open_stores_at
from ai_agent.monitoring.cpu_telemetry import CPUTelemetry
from ai_agent.monitoring.gpu_telemetry import GPUTelemetry
from ai_agent.monitoring.host_telemetry import HostTelemetry
from ai_agent.monitoring.ram_telemetry import RAMTelemetry

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class _Verifier:
    def verify(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=token)


def _client(tmp_path, *, grant: str | None = None) -> TestClient:
    _store, _access, _repo, admins = open_stores_at(f"sqlite:///{tmp_path / 'db.sqlite3'}")
    if grant:
        admins.grant(grant)
    settings = Settings(
        supabase_url="https://proj.supabase.co",
        supabase_anon_key="publishable",
    )
    return TestClient(
        create_app(settings, _Verifier(), monitoring_admin_store=admins)
    )


def test_monitoring_access_follows_the_sqlite_allowlist(tmp_path) -> None:
    with _client(tmp_path, grant=USER) as client:
        admin = client.get("/api/monitoring/access", headers={"Authorization": f"Bearer {USER}"})
        other = client.get("/api/monitoring/access", headers={"Authorization": f"Bearer {OTHER}"})
    assert admin.status_code == 200
    assert admin.json() == {"is_admin": True}
    assert other.json() == {"is_admin": False}


def test_monitoring_gpus_rejects_non_admins_without_collecting(tmp_path, monkeypatch) -> None:
    def fail_collect() -> list[GPUTelemetry]:
        raise AssertionError("collect_gpu_data should not run")

    monkeypatch.setattr("ai_agent.api.monitoring.collect_gpu_data", fail_collect)
    with _client(tmp_path) as client:
        response = client.get("/api/monitoring/gpus", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Monitoring is limited to admin users."


def test_monitoring_gpus_returns_readings_for_a_granted_admin(tmp_path, monkeypatch) -> None:
    sample = GPUTelemetry(
        name="Test GPU",
        index=1,
        temperature_celsius=41.5,
        memory_used_bytes=1024,
        memory_total_bytes=2048,
        power_usage_watts=None,
        fan_speed_percent=12,
    )
    monkeypatch.setattr("ai_agent.api.monitoring.collect_gpu_data", lambda: [sample])
    with _client(tmp_path, grant=USER) as client:
        response = client.get("/api/monitoring/gpus", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 200
    assert response.json()["gpus"][0]["name"] == "Test GPU"
    assert response.json()["gpus"][0]["fan_speed_percent"] == 12.0


def test_monitoring_telemetry_rejects_non_admins_without_collecting(tmp_path, monkeypatch) -> None:
    def fail_collect():
        raise AssertionError("collect_host_telemetry should not run")

    monkeypatch.setattr("ai_agent.api.monitoring.collect_host_telemetry", fail_collect)
    with _client(tmp_path) as client:
        response = client.get(
            "/api/monitoring/telemetry",
            headers={"Authorization": f"Bearer {USER}"},
        )
    assert response.status_code == 403


def test_monitoring_telemetry_returns_cpu_ram_and_gpu(tmp_path, monkeypatch) -> None:
    sample = HostTelemetry(
        cpu=CPUTelemetry(
            usage_percent=12.5,
            per_core_usage_percent=[10.0, 15.0],
            logical_core_count=8,
            physical_core_count=4,
            frequency_mhz=3600.0,
            temperature_celsius=None,
            load_average_1m=0.4,
            load_average_5m=0.5,
            load_average_15m=0.25,
        ),
        ram=RAMTelemetry(
            total_bytes=8192,
            used_bytes=2048,
            available_bytes=6144,
            percent_used=25.0,
            swap_total_bytes=1024,
            swap_used_bytes=0,
            swap_percent_used=0.0,
        ),
        gpus=[
            GPUTelemetry(
                name="Test GPU",
                index=0,
                temperature_celsius=41.0,
                memory_used_bytes=1024,
                memory_total_bytes=2048,
            )
        ],
    )
    monkeypatch.setattr("ai_agent.api.monitoring.collect_host_telemetry", lambda: sample)
    with _client(tmp_path, grant=USER) as client:
        response = client.get(
            "/api/monitoring/telemetry",
            headers={"Authorization": f"Bearer {USER}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["cpu"]["usage_percent"] == 12.5
    assert body["cpu"]["temperature_celsius"] is None
    assert body["ram"]["used_bytes"] == 2048
    assert body["gpus"][0]["name"] == "Test GPU"
