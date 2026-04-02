from helpers import galaxy_client
from helpers.results import determine_failure_stage


class FakeResponse:
    def __init__(self, payload) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class FakeGalaxyInstance:
    def __init__(self, responses) -> None:
        self.base_url = "https://usegalaxy.org"
        self._responses = list(responses)
        self._index = 0

    def make_get_request(self, url: str) -> FakeResponse:
        index = min(self._index, len(self._responses) - 1)
        self._index += 1
        return FakeResponse(self._responses[index])


class FakeClock:
    def __init__(self) -> None:
        self.now = 0

    def time(self) -> int:
        return self.now

    def sleep(self, seconds: int) -> None:
        self.now += seconds


def test_get_interactive_tool_url_waits_for_target(monkeypatch) -> None:
    gi = FakeGalaxyInstance(
        [
            [{"id": "entry-1"}],
            [{"id": "entry-1", "target": "/interactivetool/ep/ready"}],
        ]
    )
    clock = FakeClock()
    monkeypatch.setattr(galaxy_client.time, "time", clock.time)
    monkeypatch.setattr(galaxy_client.time, "sleep", clock.sleep)

    target = galaxy_client.get_interactive_tool_url(
        gi, "job-123", timeout=10, poll_interval=2
    )

    assert target == "https://usegalaxy.org/interactivetool/ep/ready"


def test_get_interactive_tool_url_times_out_when_target_never_appears(
    monkeypatch,
) -> None:
    gi = FakeGalaxyInstance([[{"id": "entry-1"}]])
    clock = FakeClock()
    monkeypatch.setattr(galaxy_client.time, "time", clock.time)
    monkeypatch.setattr(galaxy_client.time, "sleep", clock.sleep)

    try:
        galaxy_client.get_interactive_tool_url(
            gi, "job-123", timeout=6, poll_interval=2
        )
    except galaxy_client.EntryPointTimeout as exc:
        assert "Entry point for job job-123 has no target URL yet" in str(exc)
    else:
        raise AssertionError("Expected EntryPointTimeout")


def test_determine_failure_stage_recognizes_entry_point_message() -> None:
    exc = RuntimeError("Entry point for job abc has no target URL")
    assert determine_failure_stage(exc) == "entry_point"
