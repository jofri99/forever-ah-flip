"""Stammdaten zu den Items: alles, was Blizzards statische API hergibt.

Die Auktionsdaten kennen nur Item-IDs. Die statische API liefert dazu deutsche
Namen, Qualitaet, Haendlerpreise, Ausruestungsplatz und die Werte eines
Gegenstands - aber laengst nicht fuer jedes Item: bei einer Stichprobe aus dem
Markt antwortete sie fuer gut die Haelfte, der Rest ergab 404.

Abgelegt wird je Tag eine Datei mit den an diesem Tag geprueften IDs:

    ref/items/dt=2026-11-17.parquet

Die wichtigsten Felder stehen als eigene Spalten da. Die vollstaendige Antwort
liegt zusaetzlich unveraendert in `raw`, damit sich spaeter jedes weitere Feld
herausziehen laesst, ohne erneut abzurufen.

Auch Fehlanzeigen stehen in der Datei. Sonst wuerde jeder Lauf dieselben
tausend unbekannten IDs wieder abfragen. Nach einer Woche wird eine Fehlanzeige
erneut versucht, falls Blizzard das Item inzwischen nachgetragen hat.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

import duckdb

from . import store
from .blizzard import BlizzardClient
from .config import Settings

log = logging.getLogger(__name__)

RETRY_MISSING_AFTER = dt.timedelta(days=7)

# Reihenfolge und Typen der Ablage. Neue Spalten kommen ans Ende; aeltere Dateien
# ohne sie werden beim Lesen mit NULL aufgefuellt.
FIELDS: dict[str, str] = {
    "item_id": "INTEGER",
    "status": "SMALLINT",            # 200 gefunden, 404 kennt die API nicht
    "name": "VARCHAR",
    "quality": "VARCHAR",            # POOR, COMMON, UNCOMMON, RARE, EPIC, ...
    "sell_price": "BIGINT",          # was ein Haendler zahlt, in Kupfer
    "purchase_price": "BIGINT",      # Listenpreis beim Haendler fuer purchase_quantity Stueck
    "purchase_quantity": "INTEGER",
    "item_class": "VARCHAR",
    "item_subclass": "VARCHAR",
    "inventory_type": "VARCHAR",     # Ausruestungsplatz, z. B. WRIST
    "level": "INTEGER",
    "required_level": "INTEGER",
    "is_stackable": "BOOLEAN",
    "is_equippable": "BOOLEAN",
    "max_count": "INTEGER",
    "icon": "VARCHAR",               # Adresse des Icons
    "raw": "VARCHAR",                # die ganze Antwort als JSON
    "checked_at": "TIMESTAMP",
}
SCHEMA = ", ".join(f"{name} {kind}" for name, kind in FIELDS.items())
PLACEHOLDERS = ", ".join("?" for _ in FIELDS)


def ref_dir(warehouse: Path) -> Path:
    return warehouse / "ref" / "items"


def day_path(warehouse: Path, day: dt.date) -> Path:
    return ref_dir(warehouse) / f"dt={day:%Y-%m-%d}.parquet"


def load_known(con: duckdb.DuckDBPyConnection, warehouse: Path) -> int:
    """Baut `known`: je Item die juengste Pruefung."""
    con.execute(f"CREATE OR REPLACE TEMP TABLE known ({SCHEMA})")
    base = ref_dir(warehouse)
    if not base.is_dir() or next(base.glob("dt=*.parquet"), None) is None:
        return 0
    con.execute(
        f"""
        INSERT INTO known BY NAME
        SELECT * FROM read_parquet('{store.sql_path(base / "dt=*.parquet")}',
                                   union_by_name = true, hive_partitioning = false)
        QUALIFY row_number() OVER (PARTITION BY item_id ORDER BY checked_at DESC) = 1
        """
    )
    return con.execute("SELECT count(*) FROM known").fetchone()[0]


def market_item_ids(con: duckdb.DuckDBPyConnection, settings: Settings, house: int) -> list[int]:
    """Alle Item-IDs, die lokal bekannt sind: aus den Staenden und der Momentaufnahme.

    In Actions liegt vom Warehouse nur ein Ausschnitt auf der Platte. Die
    Momentaufnahme des juengsten Standes ist aber immer da und enthaelt jedes
    Item, das gerade im Auktionshaus steht.
    """
    sources = []
    items = store.dataset_glob(settings.warehouse_dir, store.ITEMS, house)
    if items:
        sources.append(f"SELECT item_id FROM read_parquet('{items}', hive_partitioning = false)")
    state = settings.state_dir / f"house{house}.parquet"
    if state.is_file():
        sources.append(f"SELECT item_id FROM read_parquet('{store.sql_path(state)}')")
    if not sources:
        return []
    rows = con.execute(
        "SELECT DISTINCT item_id FROM (" + " UNION ALL ".join(sources) + ") ORDER BY item_id"
    ).fetchall()
    return [row[0] for row in rows]


def pending_ids(con: duckdb.DuckDBPyConnection, ids: list[int], now: dt.datetime) -> list[int]:
    """Was noch nie geprueft wurde, und Fehlanzeigen, die alt genug fuer einen neuen Versuch sind."""
    if not ids:
        return []
    con.execute("CREATE OR REPLACE TEMP TABLE wanted (item_id INTEGER)")
    con.executemany("INSERT INTO wanted VALUES (?)", [(item_id,) for item_id in ids])
    rows = con.execute(
        """
        SELECT w.item_id FROM wanted w LEFT JOIN known k USING (item_id)
        WHERE k.item_id IS NULL OR (k.status <> 200 AND k.checked_at < ?)
        ORDER BY w.item_id
        """,
        [now - RETRY_MISSING_AFTER],
    ).fetchall()
    return [row[0] for row in rows]


def _label(value: Any, key: str = "name") -> Any:
    """Die API liefert Klassen, Qualitaet und Platz als {"type": ..., "name": ...}."""
    if isinstance(value, dict):
        return value.get(key) or value.get("name") or value.get("type")
    return value


def fetch_icon(client: BlizzardClient, item_id: int) -> str | None:
    response = client.get(f"/data/wow/media/item/{item_id}", namespace="static")
    if not response.ok or not isinstance(response.data, dict):
        return None
    for asset in response.data.get("assets") or []:
        if asset.get("key") == "icon":
            return asset.get("value")
    return None


def fetch_item(client: BlizzardClient, item_id: int, now: dt.datetime) -> dict[str, Any] | None:
    """Eine Zeile fuer die Ablage, oder None, wenn die Antwort nichts aussagt (5xx, 429)."""
    row: dict[str, Any] = dict.fromkeys(FIELDS)
    row.update(item_id=item_id, checked_at=now)

    response = client.get(f"/data/wow/item/{item_id}", namespace="static")
    if response.status == 404:
        row["status"] = 404
        return row
    if not response.ok or not isinstance(response.data, dict):
        log.warning("Item %s: HTTP %s", item_id, response.status)
        return None

    data = {key: value for key, value in response.data.items() if key != "_links"}
    row.update(
        status=200,
        name=data.get("name"),
        quality=_label(data.get("quality"), "type"),
        sell_price=data.get("sell_price"),
        purchase_price=data.get("purchase_price"),
        purchase_quantity=data.get("purchase_quantity"),
        item_class=_label(data.get("item_class")),
        item_subclass=_label(data.get("item_subclass")),
        inventory_type=_label(data.get("inventory_type"), "type"),
        level=data.get("level"),
        required_level=data.get("required_level"),
        is_stackable=data.get("is_stackable"),
        is_equippable=data.get("is_equippable"),
        max_count=data.get("max_count"),
        icon=fetch_icon(client, item_id),
        raw=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
    )
    return row


def run(
    settings: Settings,
    house: int | None = None,
    limit: int | None = None,
    client: BlizzardClient | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    house = house or settings.house
    warehouse = settings.warehouse_dir
    now = now or dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)

    con = store.connect()
    try:
        known = load_known(con, warehouse)
        ids = market_item_ids(con, settings, house)
        todo = pending_ids(con, ids, now)
        result: dict[str, Any] = {
            "market_items": len(ids),
            "known": known,
            "pending": len(todo),
            "found": 0,
            "missing": 0,
            "failed": 0,
        }
        if limit is not None:
            todo = todo[:limit]
        if not todo:
            return result

        owns_client = client is None
        client = client or BlizzardClient(settings)
        rows: list[dict[str, Any]] = []
        try:
            for item_id in todo:
                row = fetch_item(client, item_id, now)
                if row is None:
                    result["failed"] += 1
                    continue
                rows.append(row)
                result["found" if row["status"] == 200 else "missing"] += 1
        finally:
            if owns_client:
                client.close()

        if rows:
            path = day_path(warehouse, now.date())
            con.execute(f"CREATE OR REPLACE TEMP TABLE merged ({SCHEMA})")
            # Die Tagesdatei waechst nur um die heute geprueften IDs - nach dem
            # ersten Durchlauf sind das je Stunde eine Handvoll.
            if path.exists():
                con.execute(
                    f"INSERT INTO merged BY NAME SELECT * FROM read_parquet('{store.sql_path(path)}')"
                )
            con.executemany(
                f"INSERT INTO merged ({', '.join(FIELDS)}) VALUES ({PLACEHOLDERS})",
                [tuple(row[field] for field in FIELDS) for row in rows],
            )
            store.write_parquet(con, "merged", path, order_by="item_id, checked_at")
            result["file"] = path
        return result
    finally:
        con.close()


def names_from_known(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """ID als Text -> Name, fuer die Oberflaeche. Setzt ein geladenes `known` voraus."""
    rows = con.execute(
        "SELECT item_id, name FROM known WHERE status = 200 AND name IS NOT NULL ORDER BY item_id"
    ).fetchall()
    return {str(item_id): name for item_id, name in rows}


def main(settings: Settings, house: int | None = None, limit: int | None = None) -> int:
    result = run(settings, house=house, limit=limit)
    print(
        f"{result['market_items']} Items im Markt, {result['known']} schon geprueft, "
        f"{result['pending']} offen"
    )
    checked = result["found"] + result["missing"] + result["failed"]
    if checked:
        print(
            f"  jetzt geprueft: {checked} - {result['found']} gefunden, "
            f"{result['missing']} kennt Blizzard nicht, {result['failed']} ohne Antwort"
        )
    if result.get("file"):
        print(f"  nach {result['file']}")
    return 0
