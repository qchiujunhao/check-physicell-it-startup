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
