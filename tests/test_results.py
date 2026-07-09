from helpers.results import build_result


def test_build_result_includes_timings_and_tool_metadata() -> None:
    result = build_result(
        True,
        0.123,
        timings={"job_running": 1.234},
        preflight={"status": "ok"},
        configured_tool_id="tool/0.7",
        tool_id="tool/0.11",
        tool_version_policy="latest",
    )

    assert result["status"] == "ok"
    assert result["startup_seconds"] == 0.12
    assert result["timings"] == {"job_running": 1.23}
    assert result["preflight"] == {"status": "ok"}
    assert result["configured_tool_id"] == "tool/0.7"
    assert result["tool_id"] == "tool/0.11"
    assert result["tool_version_policy"] == "latest"
