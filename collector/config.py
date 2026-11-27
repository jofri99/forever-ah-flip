"""Konfiguration aus Umgebungsvariablen, optional aus einer .env-Datei."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT / ".env"

# Die API nennt sich bei automatisierten Zugriffen beim Projektnamen, nicht beim Nutzer.
USER_AGENT = "forever-ah-flip/0.1"

# Regeln des Spiels, mit denen mehrere Module rechnen.
AH_CUT = 0.05                    # was das Auktionshaus vom Verkaufspreis behaelt
AH_KEEP = 1 - AH_CUT             # was dem Verkaeufer bleibt
# Gesammelt wird das Auktionshaus der Horde. Haendler dieser Fraktion sind von dort
# aus nicht erreichbar.
UNREACHABLE_SIDE = "Alliance"

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
    locale: str = "en_US"
    rulesets: tuple[int, ...] = (1, 2, 3, 15)
    ruleset: int = 2            # Normal; die ID im Pfad filtert ohnehin nichts
    house: int = 114            # Auktionshaus der Horde, Normal-Ruleset (gemessen)
    foreverdb_key: str = ""     # optional, fuer Daten von foreverdb.net
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
            locale=env.get("BLIZZARD_LOCALE", "en_US").strip(),
            rulesets=rulesets,
            ruleset=int(env.get("FOREVER_RULESET", "2")),
            house=int(env.get("FOREVER_HOUSE", "114")),
            foreverdb_key=env.get("FOREVERDB_API_KEY", "").strip(),
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

    @property
    def local_dir(self) -> Path:
        """Daten, die diesen Rechner nicht verlassen sollen - etwa Abzuege von ForeverDB,
        deren Bedingungen eine Weiterveroeffentlichung ausschliessen. Liegt ausserhalb
        des Warehouse und damit ausserhalb des oeffentlichen Branches `data`."""
        return self.data_dir / "local"

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
