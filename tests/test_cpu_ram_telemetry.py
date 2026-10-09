from ai_agent.monitoring.cpu_telemetry import collect_cpu_data
from ai_agent.monitoring.custom_exceptions import GPUTelemetryNotSupportedError
from ai_agent.monitoring.host_telemetry import collect_host_telemetry
from ai_agent.monitoring.interval import COLLECTION_INTERVAL_SECONDS
from ai_agent.monitoring.ram_telemetry import collect_ram_data


class _Freq:
    current = 3600.0
    min = 800.0
    max = 4700.0


class _Temp:
    def __init__(self, label: str, current: float) -> None:
        self.label = label
        self.current = current


class _Memory:
    total = 32 * 1024**3
    used = 8 * 1024**3
    available = 24 * 1024**3
    percent = 25.0


class _Swap:
    total = 4 * 1024**3
    used = 1024**3
    percent = 25.0


class _Psutil:
    def __init__(self) -> None:
        self.cpu_calls: list[dict] = []

    def cpu_percent(self, interval=None, percpu=False):
        self.cpu_calls.append({"interval": interval, "percpu": percpu})
        if percpu:
            return [10.0, 20.0]
        return 15.0

    def cpu_count(self, logical=True):
        return 2 if logical else 1

    def cpu_freq(self):
        return _Freq()

    def getloadavg(self):
        return (0.5, 0.4, 0.3)

    def sensors_temperatures(self):
        return {
            "nvme": [_Temp("Composite", 40.0)],
            "coretemp": [_Temp("Package id 0", 61.0), _Temp("Core 0", 58.0)],
        }

    def virtual_memory(self):
        return _Memory()

    def swap_memory(self):
        return _Swap()


def test_collection_interval_is_four_seconds() -> None:
    assert COLLECTION_INTERVAL_SECONDS == 4


def test_collect_cpu_data_reads_a_nonblocking_sample() -> None:
    psutil = _Psutil()
    sample = collect_cpu_data(psutil)
    assert sample.usage_percent == 15.0
    assert sample.per_core_usage_percent == [10.0, 20.0]
    assert sample.logical_core_count == 2
    assert sample.physical_core_count == 1
    assert sample.frequency_mhz == 3600.0
    assert sample.min_frequency_mhz == 800.0
    assert sample.max_frequency_mhz == 4700.0
    assert sample.temperature_celsius == 61.0
    assert sample.load_average_1m == 0.5
    assert sample.load_average_5m == 0.4
    assert sample.load_average_15m == 0.3
    assert all(call["interval"] is None for call in psutil.cpu_calls)


def test_collect_cpu_data_leaves_optional_readings_empty() -> None:
    class _Bare:
        def cpu_percent(self, interval=None, percpu=False):
            return [1.0] if percpu else 1.0

        def cpu_count(self, logical=True):
            return None

        def cpu_freq(self):
            raise NotImplementedError

        def getloadavg(self):
            raise OSError("not supported")

        def sensors_temperatures(self):
            raise OSError("not supported")

    sample = collect_cpu_data(_Bare())
    assert sample.logical_core_count is None
    assert sample.physical_core_count is None
    assert sample.frequency_mhz is None
    assert sample.temperature_celsius is None
    assert sample.load_average_1m is None


def test_collect_ram_data_reads_memory_and_swap() -> None:
    sample = collect_ram_data(_Psutil())
    assert sample.total_bytes == 32 * 1024**3
    assert sample.used_bytes == 8 * 1024**3
    assert sample.available_bytes == 24 * 1024**3
    assert sample.percent_used == 25.0
    assert sample.swap_total_bytes == 4 * 1024**3
    assert sample.swap_used_bytes == 1024**3
    assert sample.swap_percent_used == 25.0


def test_collect_ram_data_zeros_swap_when_it_is_unavailable() -> None:
    class _MemoryOnly(_Psutil):
        def swap_memory(self):
            raise NotImplementedError

    sample = collect_ram_data(_MemoryOnly())
    assert sample.total_bytes == 32 * 1024**3
    assert sample.swap_total_bytes == 0
    assert sample.swap_used_bytes == 0
    assert sample.swap_percent_used == 0.0


def test_collect_host_telemetry_keeps_cpu_and_ram_when_gpu_is_unsupported(monkeypatch) -> None:
    cpu = collect_cpu_data(_Psutil())
    ram = collect_ram_data(_Psutil())

    def unsupported():
        raise GPUTelemetryNotSupportedError(RuntimeError("no sensor"))

    monkeypatch.setattr("ai_agent.monitoring.host_telemetry.collect_cpu_data", lambda: cpu)
    monkeypatch.setattr("ai_agent.monitoring.host_telemetry.collect_ram_data", lambda: ram)
    monkeypatch.setattr("ai_agent.monitoring.host_telemetry.collect_gpu_data", unsupported)

    sample = collect_host_telemetry()
    assert sample.cpu is cpu
    assert sample.ram is ram
    assert sample.gpus == []
