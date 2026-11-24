import bioblend
import pytest
import requests

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


# --- Galaxy API requests that are never answered, or answered with an error ---

GATEWAY_PAGE = "<html>\n<title>Galaxy</title>\nPlease login again later\n</html>"


def _read_timeout() -> requests.exceptions.ReadTimeout:
    return requests.exceptions.ReadTimeout("Read timed out. (read timeout=60)")


def _bad_gateway() -> bioblend.ConnectionError:
    return bioblend.ConnectionError(
        "GET: error 502: b'<html>', 0 attempts left",
        body=GATEWAY_PAGE,
        status_code=502,
    )


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(f"{status} Error", response=response)


def _play(steps: list, index: int):
    step = steps[min(index, len(steps) - 1)]
    if isinstance(step, Exception):
        raise step
    return step


class ScriptedEntryPoints:
    """A Galaxy whose entry point polls follow a script; exceptions are raised."""

    def __init__(self, steps: list) -> None:
        self.base_url = "https://usegalaxy.org"
        self._steps = steps
        self.requests = 0

    def make_get_request(self, url: str) -> FakeResponse:
        self.requests += 1
        return FakeResponse(_play(self._steps, self.requests - 1))


class ScriptedJobs:
    def __init__(self, steps: list) -> None:
        self._steps = steps
        self.requests = 0

    def show_job(self, job_id: str, full_details: bool = False) -> dict:
        self.requests += 1
        return _play(self._steps, self.requests - 1)


class ScriptedJobGalaxy:
    def __init__(self, steps: list) -> None:
        self.jobs = ScriptedJobs(steps)


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(galaxy_client.time, "time", fake.time)
    monkeypatch.setattr(galaxy_client.time, "sleep", fake.sleep)
    return fake


def test_get_galaxy_instance_bounds_every_request(monkeypatch) -> None:
    monkeypatch.setattr(galaxy_client, "GALAXY_API_KEY", "not-a-real-key")
    monkeypatch.setattr(galaxy_client, "GALAXY_API_TIMEOUT_SECONDS", 7)

    gi = galaxy_client.get_galaxy_instance()

    assert gi.timeout == 7
    assert gi.max_get_attempts == 3


def test_entry_point_poll_survives_an_unanswered_request(clock) -> None:
    gi = ScriptedEntryPoints(
        [
            _read_timeout(),
            _http_error(502),
            [{"id": "entry-1", "target": "/interactivetool/ep/ready"}],
        ]
    )

    target = galaxy_client.get_interactive_tool_url(
        gi, "job-123", timeout=20, poll_interval=2
    )

    assert target == "https://usegalaxy.org/interactivetool/ep/ready"
    assert gi.requests == 3


def test_entry_point_poll_reports_an_api_outage_as_galaxy_unreachable(clock) -> None:
    gi = ScriptedEntryPoints([[{"id": "entry-1"}], _read_timeout()])

    with pytest.raises(galaxy_client.GalaxyAPIUnavailable) as raised:
        galaxy_client.get_interactive_tool_url(
            gi, "job-123", timeout=20, poll_interval=2
        )

    assert "ReadTimeout" in str(raised.value)
    assert determine_failure_stage(raised.value) == "galaxy_unreachable"


def test_entry_point_poll_with_one_late_unanswered_request_is_a_timeout(
    clock,
) -> None:
    # Polls happen at t=0, 2 and 4. Galaxy answered until the last one, so the
    # tool being slow is still the honest verdict.
    gi = ScriptedEntryPoints(
        [[{"id": "entry-1"}], [{"id": "entry-1"}], _read_timeout()]
    )

    with pytest.raises(galaxy_client.EntryPointTimeout) as raised:
        galaxy_client.get_interactive_tool_url(
            gi, "job-123", timeout=6, poll_interval=2
        )

    assert "has no target URL yet" in str(raised.value)


def test_entry_point_poll_does_not_wait_out_a_client_error(clock) -> None:
    gi = ScriptedEntryPoints([_http_error(403)])

    with pytest.raises(requests.exceptions.HTTPError):
        galaxy_client.get_interactive_tool_url(
            gi, "job-123", timeout=20, poll_interval=2
        )

    assert gi.requests == 1


def test_job_poll_survives_a_bad_gateway(clock) -> None:
    gi = ScriptedJobGalaxy(
        [{"state": "queued"}, _bad_gateway(), _read_timeout(), {"state": "running"}]
    )

    galaxy_client.wait_for_tool_ready(gi, "job-123", timeout=30, poll_interval=3)

    assert gi.jobs.requests == 4


def test_job_poll_reports_an_api_outage_as_galaxy_unreachable(clock) -> None:
    gi = ScriptedJobGalaxy([{"state": "queued"}, _bad_gateway()])

    with pytest.raises(galaxy_client.GalaxyAPIUnavailable) as raised:
        galaxy_client.wait_for_tool_ready(gi, "job-123", timeout=30, poll_interval=3)

    message = str(raised.value)
    assert "502" in message
    assert "login" not in message  # the gateway page itself is left out
    assert determine_failure_stage(raised.value) == "galaxy_unreachable"


def test_job_poll_that_stays_queued_is_a_startup_timeout(clock) -> None:
    gi = ScriptedJobGalaxy([{"state": "queued"}])

    with pytest.raises(galaxy_client.ToolStartupTimeout):
        galaxy_client.wait_for_tool_ready(gi, "job-123", timeout=9, poll_interval=3)


def test_job_poll_does_not_wait_out_a_client_error(clock) -> None:
    gi = ScriptedJobGalaxy(
        [bioblend.ConnectionError("GET: error 404", body="{}", status_code=404)]
    )

    with pytest.raises(bioblend.ConnectionError):
        galaxy_client.wait_for_tool_ready(gi, "job-123", timeout=30, poll_interval=3)

    assert gi.jobs.requests == 1


class ScriptedTools:
    def __init__(self, outcome) -> None:
        self._outcome = outcome

    def show_tool(self, tool_id: str) -> dict:
        return _play([self._outcome], 0)


class ScriptedToolGalaxy:
    base_url = "https://usegalaxy.org"

    def __init__(self, outcome) -> None:
        self.tools = ScriptedTools(outcome)


def test_unanswered_tool_lookup_is_not_reported_as_a_missing_tool() -> None:
    gi = ScriptedToolGalaxy(_read_timeout())

    with pytest.raises(requests.exceptions.ReadTimeout) as raised:
        galaxy_client.check_tool_exists(gi, "tool-1")

    assert determine_failure_stage(raised.value) == "galaxy_unreachable"


def test_tool_lookup_rejected_by_galaxy_is_a_missing_tool() -> None:
    gi = ScriptedToolGalaxy(
        bioblend.ConnectionError("GET: error 404", body="{}", status_code=404)
    )

    with pytest.raises(galaxy_client.ToolNotAvailable):
        galaxy_client.check_tool_exists(gi, "tool-1")


class StopResponse:
    def __init__(self, payload=None, status: int = 200) -> None:
        self._payload = payload
        self._status = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise _http_error(self._status)

    def json(self):
        return self._payload


class StoppableJobs:
    def __init__(self, outcomes: list) -> None:
        self._outcomes = outcomes
        self.cancel_calls = 0

    def cancel_job(self, job_id: str) -> bool:
        self.cancel_calls += 1
        return _play(self._outcomes, self.cancel_calls - 1)


class StoppableGalaxy:
    base_url = "https://usegalaxy.org"

    def __init__(self, cancel_outcomes: list, entry_points=None) -> None:
        self.jobs = StoppableJobs(cancel_outcomes)
        self._entry_points = entry_points
        self.deleted: list[str] = []

    def make_get_request(self, url: str) -> StopResponse:
        if isinstance(self._entry_points, Exception):
            raise self._entry_points
        return StopResponse(self._entry_points)

    def make_delete_request(self, url: str) -> StopResponse:
        self.deleted.append(url)
        return StopResponse()


def test_stop_reports_success_when_galaxy_cancels_the_job() -> None:
    gi = StoppableGalaxy([True])

    assert galaxy_client.stop_interactive_tool(gi, "job-123") is True
    assert gi.jobs.cancel_calls == 1


def test_stop_sends_the_cancel_again_when_galaxy_does_not_answer() -> None:
    gi = StoppableGalaxy([_read_timeout(), True])

    assert galaxy_client.stop_interactive_tool(gi, "job-123") is True
    assert gi.jobs.cancel_calls == 2


def test_stop_reports_failure_when_galaxy_never_answers() -> None:
    gi = StoppableGalaxy([_read_timeout()], entry_points=_read_timeout())

    assert galaxy_client.stop_interactive_tool(gi, "job-123") is False
    assert gi.jobs.cancel_calls == 2  # bounded, not retried forever


def test_stop_falls_back_to_removing_the_entry_point() -> None:
    rejected = bioblend.ConnectionError("Unexpected HTTP status code: 403")
    rejected.status_code = 403
    gi = StoppableGalaxy([rejected], entry_points=[{"id": "ep-1"}])

    assert galaxy_client.stop_interactive_tool(gi, "job-123") is True
    assert gi.jobs.cancel_calls == 1  # Galaxy said no; asking again is pointless
    assert gi.deleted == ["https://usegalaxy.org/api/entry_points/ep-1"]


def test_gateway_error_page_is_not_classified_by_its_wording() -> None:
    # The page says "login", which used to make this an authentication failure.
    assert "login" in str(_bad_gateway())
    assert determine_failure_stage(_bad_gateway()) == "galaxy_unreachable"


def test_api_error_that_galaxy_answered_keeps_its_classification() -> None:
    forbidden = bioblend.ConnectionError(
        "GET: error 403: b'{}'", body="{}", status_code=403
    )
    assert determine_failure_stage(forbidden) == "authentication"


def test_unanswered_api_request_is_galaxy_unreachable() -> None:
    assert determine_failure_stage(_read_timeout()) == "galaxy_unreachable"
