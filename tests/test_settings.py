from config import settings


def test_blank_galaxy_base_url_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("GALAXY_BASE_URL", "")
    assert (
        settings.env_or_default("GALAXY_BASE_URL", "https://usegalaxy.org")
        == "https://usegalaxy.org"
    )


def test_blank_credentials_are_normalized_to_empty_strings(monkeypatch) -> None:
    monkeypatch.setenv("GALAXY_API_KEY", "  ")
    monkeypatch.setenv("GALAXY_USERNAME", "  ")
    monkeypatch.setenv("GALAXY_PASSWORD", "  ")
    assert settings.env_or_empty("GALAXY_API_KEY") == ""
    assert settings.env_or_empty("GALAXY_USERNAME") == ""
    assert settings.env_or_empty("GALAXY_PASSWORD") == ""


def test_blank_integer_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("STARTUP_TIMEOUT_SECONDS", "  ")
    assert settings.env_int("STARTUP_TIMEOUT_SECONDS", 600, minimum=1) == 600


def test_boolean_setting_parses_common_values(monkeypatch) -> None:
    monkeypatch.setenv("REQUIRE_UI_VERIFICATION", "yes")
    assert settings.env_bool("REQUIRE_UI_VERIFICATION", False) is True

    monkeypatch.setenv("REQUIRE_UI_VERIFICATION", "off")
    assert settings.env_bool("REQUIRE_UI_VERIFICATION", True) is False


def test_choice_setting_parses_known_values(monkeypatch) -> None:
    monkeypatch.setenv("PHYSICELL_TOOL_VERSION_POLICY", "PINNED")

    assert (
        settings.env_choice(
            "PHYSICELL_TOOL_VERSION_POLICY",
            "latest",
            {"latest", "pinned"},
        )
        == "pinned"
    )
