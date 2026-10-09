from ai_agent.monitoring.interval import COLLECTION_INTERVAL_SECONDS
from ai_agent.monitoring.publish_loop import publish_all_telemetry, run_publish_loop


class _Publisher:
    pass


def test_publish_all_telemetry_continues_after_one_resource_fails(monkeypatch) -> None:
    published: list[str] = []

    def fail_cpu(_publisher) -> None:
        raise RuntimeError("cpu unavailable")

    def publish_ram(_publisher) -> None:
        published.append("ram")

    def publish_gpu(_publisher) -> None:
        published.append("gpu")

    monkeypatch.setattr("ai_agent.monitoring.publish_loop.publish_cpu_data", fail_cpu)
    monkeypatch.setattr("ai_agent.monitoring.publish_loop.publish_ram_data", publish_ram)
    monkeypatch.setattr("ai_agent.monitoring.publish_loop.publish_gpu_data", publish_gpu)

    publish_all_telemetry(_Publisher())
    assert published == ["ram", "gpu"]


def test_publish_loop_waits_out_the_collection_interval(monkeypatch) -> None:
    passes = {"count": 0}
    slept: list[float] = []

    def publish(_publisher) -> None:
        passes["count"] += 1

    monkeypatch.setattr("ai_agent.monitoring.publish_loop.publish_all_telemetry", publish)
    monkeypatch.setattr("ai_agent.monitoring.publish_loop.time.monotonic", lambda: 0.0)

    run_publish_loop(
        _Publisher(),
        interval_seconds=COLLECTION_INTERVAL_SECONDS,
        sleep=slept.append,
        iterations=2,
    )
    assert passes["count"] == 2
    assert slept == [COLLECTION_INTERVAL_SECONDS]
