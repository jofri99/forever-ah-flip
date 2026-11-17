"""Zieht Listen von ForeverDB lokal ab - fortsetzbar und innerhalb des Kontingents.

Abgelegt wird unter data/local/foreverdb/, eine Zeile JSON je Eintrag:

    items.jsonl      alle Items mit Name, Qualitaet, Klasse, Icon
    vendors.jsonl    alle Haendler
    ...
    state.json       wie weit jede Liste ist

Das liegt bewusst ausserhalb des Warehouse und damit ausserhalb des
oeffentlichen Branches `data`: der Schluessel ist persoenlich, und die
Bedingungen von ForeverDB schliessen eine Weiterveroeffentlichung aus.

Bricht ein Lauf ab - Kontingent, Netz, Strg+C -, macht der naechste an der
Stelle weiter. Jede Seite wird sofort geschrieben, nichts haengt nur im Speicher.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import duckdb

from . import store
from .config import Settings
from .foreverdb import ForeverDBClient, ForeverDBQuotaError

log = logging.getLogger(__name__)

PAGE_SIZE = 100          # das Maximum der API

# Listen, die sich seitenweise abziehen lassen: Name der Datei -> Pfad der API.
LISTS: dict[str, str] = {
    "items": "/items",
    "vendors": "/vendors",
    "quests": "/quests",
    "spells": "/spells",
    "itemsets": "/itemsets",
}


def dump_dir(settings: Settings) -> Path:
    return settings.local_dir / "foreverdb"


def _load_state(directory: Path) -> dict[str, Any]:
    path = directory / "state.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _save_state(directory: Path, state: dict[str, Any]) -> None:
    path = directory / "state.json"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def dump_list(
    client: ForeverDBClient,
    name: str,
    directory: Path,
    max_requests: int | None = None,
    restart: bool = False,
) -> dict[str, Any]:
    """Zieht eine Liste ab oder setzt sie fort. Gibt den Stand zurueck."""
    path = LISTS[name]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{name}.jsonl"

    state = _load_state(directory)
    progress = state.get(name) or {}
    if restart or not target.is_file():
        progress = {}
    offset = int(progress.get("offset", 0))
    total = progress.get("total")
    if offset == 0:
        target.write_text("", encoding="utf-8")      # sauber von vorn

    requests_made = 0
    stopped: str | None = None

    while total is None or offset < total:
        if max_requests is not None and requests_made >= max_requests:
            stopped = "Grenze fuer diesen Lauf erreicht"
            break
        try:
            response = client.get(path, {"limit": PAGE_SIZE, "offset": offset})
        except ForeverDBQuotaError as exc:
            stopped = str(exc)
            break
        requests_made += 1
        if not response.ok:
            stopped = f"HTTP {response.status}"
            break

        payload = response.data or {}
        rows = payload.get("data") or []
        total = (payload.get("meta") or {}).get("total", total)
        if not rows:
            total = offset                              # nichts mehr da
            break

        with open(target, "a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        offset += len(rows)

        # Nach jeder Seite festhalten: ein Abbruch kostet hoechstens diese eine.
        state[name] = {"offset": offset, "total": total, "done": False}
        _save_state(directory, state)

    done = stopped is None
    state[name] = {"offset": offset, "total": total, "done": done}
    _save_state(directory, state)
    return {
        "name": name,
        "rows": offset,
        "total": total,
        "done": done,
        "requests": requests_made,
        "stopped": stopped,
        "file": target,
    }


def english_names(con: duckdb.DuckDBPyConnection, settings: Settings) -> dict[str, str]:
    """ID als Text -> englischer Name aus dem lokalen Abzug. Leer, wenn es keinen gibt."""
    target = dump_dir(settings) / "items.jsonl"
    if not target.is_file() or target.stat().st_size == 0:
        return {}
    rows = con.execute(
        f"SELECT id, name FROM read_json('{store.sql_path(target)}', format = 'newline_delimited', "
        "columns = {'id': 'INTEGER', 'name': 'VARCHAR'}) WHERE name IS NOT NULL AND name <> ''"
    ).fetchall()
    return {str(item_id): name for item_id, name in rows}


def main(settings: Settings, lists: list[str], max_requests: int | None = None, restart: bool = False) -> int:
    directory = dump_dir(settings)
    with ForeverDBClient(settings.foreverdb_key) as client:
        budget = max_requests
        for name in lists:
            result = dump_list(client, name, directory, max_requests=budget, restart=restart)
            total = result["total"] if result["total"] is not None else "?"
            status = "fertig" if result["done"] else f"unterbrochen: {result['stopped']}"
            print(f"{name:<9} {result['rows']:>6} von {total} Zeilen, {result['requests']} Anfragen - {status}")
            if budget is not None:
                budget -= result["requests"]
            if not result["done"]:
                break
        print(f"nach {directory}")
    return 0
