from pathlib import Path

import pytest

from collector.config import Settings, load_env_file


def test_load_env_file_parses_and_skips_noise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# Kommentar",
                "",
                "BLIZZARD_CLIENT_ID=abc123",
                'BLIZZARD_CLIENT_SECRET="mit anfuehrungszeichen"',
                "FOREVER_RULESETS = 2, 15 ",
                "kaputte zeile ohne gleichheitszeichen",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("BLIZZARD_CLIENT_ID", raising=False)
    monkeypatch.delenv("BLIZZARD_CLIENT_SECRET", raising=False)

    values = load_env_file(env_file)

    assert values["BLIZZARD_CLIENT_ID"] == "abc123"
    assert values["BLIZZARD_CLIENT_SECRET"] == "mit anfuehrungszeichen"
    assert "kaputte zeile ohne gleichheitszeichen" not in values


def test_load_env_file_does_not_override_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("BLIZZARD_CLIENT_ID=aus-datei", encoding="utf-8")
    monkeypatch.setenv("BLIZZARD_CLIENT_ID", "aus-umgebung")

    load_env_file(env_file)

    import os

    assert os.environ["BLIZZARD_CLIENT_ID"] == "aus-umgebung"


def test_missing_env_file_is_fine(tmp_path: Path) -> None:
    assert load_env_file(tmp_path / "gibtsnicht") == {}


def test_settings_from_env_defaults() -> None:
    config = Settings.from_env({"BLIZZARD_CLIENT_ID": "id", "BLIZZARD_CLIENT_SECRET": "secret"})

    assert config.region == "eu"
    assert config.api_host == "https://eu.api.blizzard.com"
    assert config.namespace() == "dynamic-forever-eu"
    assert config.namespace("static") == "static-forever-eu"
    assert config.rulesets == (1, 2, 3, 15)


def test_settings_parses_rulesets_and_region() -> None:
    config = Settings.from_env(
        {
            "BLIZZARD_CLIENT_ID": "id",
            "BLIZZARD_CLIENT_SECRET": "secret",
            "BLIZZARD_REGION": "US",
            "FOREVER_RULESETS": "2, 15,",
        }
    )

    assert config.region == "us"
    assert config.namespace() == "dynamic-forever-us"
    assert config.rulesets == (2, 15)


def test_settings_rejects_unknown_region() -> None:
    with pytest.raises(ValueError, match="BLIZZARD_REGION"):
        Settings.from_env({"BLIZZARD_REGION": "mars"})


def test_require_credentials_names_what_is_missing() -> None:
    config = Settings.from_env({"BLIZZARD_CLIENT_ID": "nur-die-id"})

    with pytest.raises(RuntimeError) as excinfo:
        config.require_credentials()

    assert "BLIZZARD_CLIENT_SECRET" in str(excinfo.value)
    assert "BLIZZARD_CLIENT_ID" not in str(excinfo.value)


def test_relative_data_dir_is_anchored_at_repo_root() -> None:
    config = Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "id", "BLIZZARD_CLIENT_SECRET": "s", "AH_DATA_DIR": "data"}
    )

    assert config.data_dir.is_absolute()
    assert config.warehouse_dir == config.data_dir / "warehouse"
    assert config.raw_dir == config.data_dir / "raw"
