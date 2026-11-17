"""Konfiguration aus Umgebungsvariablen, optional aus einer .env-Datei."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT / ".env"

# Die API nennt sich bei automatisierten Zugriffen beim Projektnamen, nicht beim Nutzer.
USER_AGENT = "forever-ah-flip/0.1"

REGIONS = ("eu", "us", "kr", "tw")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Liest KEY=VALUE-Zeilen. Kommentare und Leerzeilen werden uebersprungen.

    Bereits gesetzte Umgebungsvariablen gewinnen - in GitHub Actions kommen die
    Werte aus den Secrets und es gibt gar keine .env.
    """
    found: dict[str, str] = {}
    if not path.is_file():
        return found
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found[key] = value
        os.environ.setdefault(key, value)
    return found


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    region: str = "eu"
    locale: str = "de_DE"
    rulesets: tuple[int, ...] = (1, 2, 3, 15)
    ruleset: int = 2            # Normal; die ID im Pfad filtert ohnehin nichts
    house: int = 114            # Auktionshaus der Horde, Normal-Ruleset (gemessen)
    data_dir: Path = field(default=ROOT / "data")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        region = env.get("BLIZZARD_REGION", "eu").strip().lower()
        if region not in REGIONS:
            raise ValueError(f"BLIZZARD_REGION={region!r} - erlaubt sind {', '.join(REGIONS)}")

        raw_rulesets = env.get("FOREVER_RULESETS", "1,2,3,15")
        rulesets = tuple(int(part) for part in raw_rulesets.replace(" ", "").split(",") if part)

        data_dir = Path(env.get("AH_DATA_DIR") or "data")
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir

        return cls(
            client_id=env.get("BLIZZARD_CLIENT_ID", "").strip(),
            client_secret=env.get("BLIZZARD_CLIENT_SECRET", "").strip(),
            region=region,
            locale=env.get("BLIZZARD_LOCALE", "de_DE").strip(),
            rulesets=rulesets,
            ruleset=int(env.get("FOREVER_RULESET", "2")),
            house=int(env.get("FOREVER_HOUSE", "114")),
            data_dir=data_dir,
        )

    @property
    def api_host(self) -> str:
        return f"https://{self.region}.api.blizzard.com"

    def namespace(self, kind: str = "dynamic") -> str:
        """kind ist dynamic, static oder profile."""
        return f"{kind}-forever-{self.region}"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def warehouse_dir(self) -> Path:
        """Was dauerhaft bleibt. In Actions ist das der ausgecheckte Branch `data`."""
        return self.data_dir / "warehouse"

    @property
    def state_dir(self) -> Path:
        """Die letzte rohe Momentaufnahme. Liegt absichtlich ausserhalb des Warehouse:
        sie aendert sich bei jedem Stand komplett und hat in Git nichts verloren."""
        return self.data_dir / "state"

    def require_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("BLIZZARD_CLIENT_ID", self.client_id),
                ("BLIZZARD_CLIENT_SECRET", self.client_secret),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "Fehlende Zugangsdaten: "
                + ", ".join(missing)
                + ". Client anlegen auf https://develop.battle.net/access/clients, "
                + "dann .env.example nach .env kopieren und eintragen."
            )


def settings() -> Settings:
    """Bequemer Einstieg: .env lesen, dann Settings bauen."""
    load_env_file()
    return Settings.from_env()
