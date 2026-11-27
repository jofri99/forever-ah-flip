"""Was mehrere Testdateien brauchen."""

from __future__ import annotations

from pathlib import Path

import pytest

from collector.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Einstellungen mit einem leeren Datenordner, der nur diesem Test gehoert."""
    return Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "id", "BLIZZARD_CLIENT_SECRET": "secret", "AH_DATA_DIR": str(tmp_path / "data")}
    )
