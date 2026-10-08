from fastapi.testclient import TestClient

from ai_agent.api.app import create_app
from ai_agent.api.auth import AuthenticatedUser
from ai_agent.config import Settings
from ai_agent.monitoring.gpu_telemetry import GPUTelemetry

USER = "11111111-1111-4111-8111-111111111111"


class _Verifier:
    def verify(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id=token)


def _app(admin_ids: str) -> TestClient:
    settings = Settings(
        supabase_url="https://proj.supabase.co",
        supabase_anon_key="publishable",
        monitoring_admin_user_ids=admin_ids,
    )
    return TestClient(create_app(settings, _Verifier()))


def test_monitoring_access_reports_admin_membership() -> None:
    with _app(USER) as client:
        admin = client.get("/api/monitoring/access", headers={"Authorization": f"Bearer {USER}"})
        other = client.get(
            "/api/monitoring/access",
            headers={"Authorization": "Bearer 22222222-2222-4222-8222-222222222222"},
        )
    assert admin.status_code == 200
    assert admin.json() == {"is_admin": True}
    assert other.json() == {"is_admin": False}


def test_monitoring_gpus_rejects_non_admins_without_collecting(monkeypatch) -> None:
    def fail_collect() -> list[GPUTelemetry]:
        raise AssertionError("collect_gpu_data should not run")

    monkeypatch.setattr("ai_agent.api.monitoring.collect_gpu_data", fail_collect)
    with _app("") as client:
        response = client.get("/api/monitoring/gpus", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 403
    assert response.json()["detail"] == "Monitoring is limited to admin users."


def test_monitoring_gpus_returns_readings_for_an_admin(monkeypatch) -> None:
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
    with _app(f" someone-else , {USER} ") as client:
        response = client.get("/api/monitoring/gpus", headers={"Authorization": f"Bearer {USER}"})
    assert response.status_code == 200
    assert response.json() == {
        "gpus": [
            {
                "name": "Test GPU",
                "index": 1,
                "temperature_celsius": 41.5,
                "memory_used_bytes": 1024,
                "memory_total_bytes": 2048,
                "power_usage_watts": None,
                "fan_speed_percent": 12.0,
            }
        ]
    }
