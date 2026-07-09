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


class FakeHistories:
    def __init__(self) -> None:
        self.deleted = []

    def get_histories(self, name: str):
        return [{"id": "history-1", "name": name}]

    def show_matching_datasets(self, history_id: str):
        return [{"id": "dataset-1"}, {"id": "dataset-2"}]

    def delete_dataset(self, history_id: str, dataset_id: str, purge: bool) -> None:
        self.deleted.append((history_id, dataset_id, purge))

    def create_history(self, name: str):
        return {"id": "created-history", "name": name}


class FakeHistoryGalaxyInstance:
    def __init__(self) -> None:
        self.histories = FakeHistories()


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


def test_get_or_create_history_does_not_purge_by_default() -> None:
    gi = FakeHistoryGalaxyInstance()

    history_id = galaxy_client.get_or_create_history(gi, "PhysiCell Monitor")

    assert history_id == "history-1"
    assert gi.histories.deleted == []


def test_get_or_create_history_can_purge_when_requested() -> None:
    gi = FakeHistoryGalaxyInstance()

    history_id = galaxy_client.get_or_create_history(
        gi,
        "PhysiCell Monitor",
        purge_existing=True,
    )

    assert history_id == "history-1"
    assert gi.histories.deleted == [
        ("history-1", "dataset-1", True),
        ("history-1", "dataset-2", True),
    ]


def test_determine_failure_stage_recognizes_proxy_target_error() -> None:
    exc = RuntimeError("Interactive tool proxy failed: Proxy target missing")
    assert determine_failure_stage(exc) == "entry_point"


def test_resolve_tool_id_latest_uses_natural_version_order() -> None:
    tool_id = (
        "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/"
        "interactive_tool_pcstudio/0.7"
    )
    metadata = {
        "version": "0.7",
        "versions": ["0.3", "0.7", "0.8", "0.10", "0.11"],
    }

    selected = galaxy_client.resolve_tool_id(tool_id, "latest", metadata)

    assert selected.endswith("/0.11")


def test_resolve_tool_id_pinned_keeps_configured_tool() -> None:
    tool_id = (
        "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/"
        "interactive_tool_pcstudio/0.7"
    )
    metadata = {"version": "0.7", "versions": ["0.7", "0.11"]}

    selected = galaxy_client.resolve_tool_id(tool_id, "pinned", metadata)

    assert selected == tool_id


def test_run_preflight_checks_records_status_and_selected_tool(monkeypatch) -> None:
    configured_tool_id = (
        "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/"
        "interactive_tool_pcstudio/0.7"
    )
    selected_tool_id = configured_tool_id.removesuffix("/0.7") + "/0.11"
    base_url = "https://usegalaxy.org"
    statuspage_url = "https://status.example/api/v2/summary.json"

    payloads = {
        statuspage_url: {
            "status": {"indicator": "none", "description": "All Systems Operational"},
            "components": [
                {"name": "Galaxy Main", "status": "operational"},
                {"name": "Main Tool Shed", "status": "operational"},
            ],
            "incidents": [],
            "scheduled_maintenances": [],
        },
        f"{base_url}/api/version": {
            "version_major": "26.0",
            "version_minor": "1.dev1",
        },
        f"{base_url}/api/tools/{configured_tool_id}": {
            "id": configured_tool_id,
            "name": "PhysiCell Studio",
            "version": "0.7",
            "versions": ["0.7", "0.11"],
            "model_class": "InteractiveTool",
        },
        f"{base_url}/api/tools/{selected_tool_id}": {
            "id": selected_tool_id,
            "name": "PhysiCell Studio",
            "version": "0.11",
            "versions": ["0.7", "0.11"],
            "model_class": "InteractiveTool",
        },
    }

    def fake_fetch(url: str, timeout: int):
        assert timeout == 1
        return payloads[url], None

    monkeypatch.setattr(galaxy_client, "_fetch_json_result", fake_fetch)

    preflight = galaxy_client.run_preflight_checks(
        base_url,
        configured_tool_id,
        "latest",
        statuspage_url,
        timeout=1,
    )

    assert preflight["status"] == "ok"
    assert preflight["galaxy_version"]["version_major"] == "26.0"
    assert preflight["selected_tool_id"] == selected_tool_id
    assert preflight["tool"]["configured_available"] is True
    assert preflight["tool"]["selected_available"] is True
    assert preflight["tool"]["selected"]["version"] == "0.11"
