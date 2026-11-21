import subprocess

from ai_agent.workflows.image_supply import BrokerBackedImageSupply


def test_broker_backed_supply_treats_inspect_success_as_cached() -> None:
    calls: list[list[str]] = []

    def runner(argv, *, timeout):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    supply = BrokerBackedImageSupply(runner)
    presence = supply.inspect("ai-agent-workflow:text-lab-0123456789abcdef")
    assert presence.present
    assert not presence.unavailable
    assert calls[0][:3] == ["docker", "image", "inspect"]