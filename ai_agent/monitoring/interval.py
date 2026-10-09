"""Cadence for one full host sample.

CPU, RAM, and GPU are gathered together, then the caller waits this long
before the next sample. CPU usage is the change since the previous reading,
so one sampler owns the cadence. The Android monitoring screen polls
``/api/monitoring/telemetry`` on this same cadence
(``HostTelemetryFetcher.POLL_INTERVAL_MILLIS``). The MQTT publish loop is
the sampler when metrics are published to the broker.
"""

# Seconds between CPU, RAM, and GPU samples.
COLLECTION_INTERVAL_SECONDS = 4
