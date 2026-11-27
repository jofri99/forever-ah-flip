"""Zieht Listen von ForeverDB lokal ab - fortsetzbar und innerhalb des Kontingents.

Abgelegt wird unter data/local/foreverdb/, eine Zeile JSON je Eintrag:

    items.jsonl      alle Items mit Name, Qualitaet, Klasse, Icon
    vendors.jsonl    alle Haendler
    recipes.jsonl    alle Rezepte der Berufe mit Zutaten und Lernquelle
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
from .config import UNREACHABLE_SIDE, Settings
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


DETAILS_FILE = "item_details.jsonl"
DETAILS_MISSING = "item_details_missing"      # Schluessel in state.json
VENDOR_DETAILS_FILE = "vendor_details.jsonl"

# Was sich einzeln abziehen laesst: Pfad der API, Zieldatei, Schluessel der Fehlanzeigen.
DETAIL_KINDS: dict[str, tuple[str, str, str]] = {
    "items": ("/items/{id}", DETAILS_FILE, DETAILS_MISSING),
    "vendors": ("/vendors/{id}", VENDOR_DETAILS_FILE, "vendor_details_missing"),
}


def details_done(directory: Path, kind: str = "items") -> set[int]:
    """Was schon abgezogen ist oder was es bei ForeverDB nicht gibt."""
    _, file_name, missing_key = DETAIL_KINDS[kind]
    done: set[int] = set(_load_state(directory).get(missing_key) or [])
    target = directory / file_name
    if target.is_file():
        with open(target, encoding="utf-8") as handle:
            for line in handle:
                try:
                    done.add(int(json.loads(line)["id"]))
                except (ValueError, KeyError, TypeError):
                    continue        # eine abgerissene letzte Zeile nach einem Abbruch
    return done


def dump_item_details(
    client: ForeverDBClient,
    item_ids: list[int],
    directory: Path,
    max_requests: int | None = None,
    kind: str = "items",
) -> dict[str, Any]:
    """Holt die Details einzeln - die API gibt sie nicht im Stapel her.

    Jedes Item wird sofort als Zeile angehaengt. Ein Abbruch kostet hoechstens
    das eine, das gerade unterwegs war; der naechste Lauf ueberspringt alles,
    was schon da ist.
    """
    path_template, file_name, missing_key = DETAIL_KINDS[kind]
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / file_name
    done = details_done(directory, kind)
    todo = [item_id for item_id in item_ids if item_id not in done]

    state = _load_state(directory)
    missing: list[int] = list(state.get(missing_key) or [])
    fetched = not_found = requests_made = 0
    stopped: str | None = None

    with open(target, "a", encoding="utf-8") as handle:
        for item_id in todo:
            if max_requests is not None and requests_made >= max_requests:
                stopped = "Grenze fuer diesen Lauf erreicht"
                break
            try:
                response = client.get(path_template.format(id=item_id))
            except ForeverDBQuotaError as exc:
                stopped = str(exc)
                break
            requests_made += 1

            if response.status == 404:
                # Festhalten, sonst fragt jeder Lauf erneut nach demselben Item.
                missing.append(item_id)
                state[missing_key] = missing
                _save_state(directory, state)
                not_found += 1
                continue
            if not response.ok:
                stopped = f"HTTP {response.status} bei Item {item_id}"
                break

            item = (response.data or {}).get("data")
            if not isinstance(item, dict):
                stopped = f"unerwartete Antwort bei Item {item_id}"
                break
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            handle.flush()
            fetched += 1

    return {
        "wanted": len(item_ids),
        "already": len(item_ids) - len(todo),
        "fetched": fetched,
        "not_found": not_found,
        "left": len(todo) - fetched - not_found,
        "requests": requests_made,
        "stopped": stopped,
        "file": target,
    }


def detail_candidates(settings: Settings, scope: str, house: int | None = None) -> list[int]:
    """Welche Items abgezogen werden sollen, die meistgehandelten zuerst.

    gaps    Items im Markt, die Blizzards API nicht kennt
    market  alle Items im Markt
    all     alles, was die Item-Liste von ForeverDB nennt
    """
    from . import names        # hier, um einen Importkreis zu vermeiden

    house = house or settings.house
    listed = dump_dir(settings) / "items.jsonl"
    con = store.connect()
    try:
        if scope == "all":
            if not listed.is_file():
                raise RuntimeError("Erst die Item-Liste abziehen: python -m collector foreverdb items")
            rows = con.execute(
                f"SELECT id FROM read_json('{store.sql_path(listed)}', format = 'newline_delimited', "
                "columns = {'id': 'INTEGER'}) ORDER BY id"
            ).fetchall()
            return [row[0] for row in rows]

        items = store.dataset_glob(settings.warehouse_dir, store.ITEMS, house)
        if items is None:
            raise RuntimeError("Im Warehouse liegt noch kein Stand - erst `git -C data/warehouse pull`.")
        names.load_known(con, settings.warehouse_dir, settings.locale)
        # Reihenfolge nach Angeboten: bricht der Lauf ab, sind die wichtigen Items schon da.
        con.execute(
            f"CREATE TEMP TABLE traded AS SELECT item_id, sum(n_listings) AS listings "
            f"FROM read_parquet('{items}', hive_partitioning = false) GROUP BY item_id"
        )
        where = (
            "WHERE t.item_id NOT IN (SELECT item_id FROM known WHERE status = 200)"
            if scope == "gaps"
            else ""
        )
        rows = con.execute(
            f"SELECT t.item_id FROM traded t {where} ORDER BY t.listings DESC, t.item_id"
        ).fetchall()
        ids = [row[0] for row in rows]

        # Was ForeverDB gar nicht fuehrt, kostet nur Anfragen.
        if listed.is_file():
            known_there = {
                row[0]
                for row in con.execute(
                    f"SELECT id FROM read_json('{store.sql_path(listed)}', format = 'newline_delimited', "
                    "columns = {'id': 'INTEGER'})"
                ).fetchall()
            }
            ids = [item_id for item_id in ids if item_id in known_there]
        return ids
    finally:
        con.close()


def details_main(settings: Settings, scope: str = "gaps", max_requests: int | None = None) -> int:
    ids = detail_candidates(settings, scope)
    directory = dump_dir(settings)
    with ForeverDBClient(settings.foreverdb_key) as client:
        result = dump_item_details(client, ids, directory, max_requests=max_requests)
    print(
        f"{result['wanted']} Items gewuenscht, {result['already']} schon da, "
        f"{result['fetched']} geholt, {result['not_found']} kennt ForeverDB nicht, {result['left']} offen"
    )
    if result["stopped"]:
        print(f"  unterbrochen: {result['stopped']} - der naechste Lauf macht dort weiter")
    print(f"  {result['requests']} Anfragen, nach {result['file']}")
    return 0


def vendor_ids(directory: Path) -> list[int]:
    """Alle Haendler aus der abgezogenen Liste. Die der Allianz zuletzt: gesammelt wird
    das Auktionshaus der Horde, erreichbar sind also zuerst die uebrigen."""
    listed = directory / "vendors.jsonl"
    if not listed.is_file() or listed.stat().st_size == 0:
        return []
    con = store.connect()
    try:
        rows = con.execute(
            f"SELECT id FROM read_json('{store.sql_path(listed)}', format = 'newline_delimited', "
            "columns = {'id': 'INTEGER', 'side': 'VARCHAR'}) "
            f"ORDER BY (side = '{UNREACHABLE_SIDE}'), id"
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        con.close()


def vendors_main(settings: Settings, max_requests: int | None = None) -> int:
    """Erst die Liste der Haendler, dann je Haendler das Sortiment mit Preisen."""
    directory = dump_dir(settings)
    with ForeverDBClient(settings.foreverdb_key) as client:
        listing = dump_list(client, "vendors", directory, max_requests=max_requests)
        print(f"Liste: {listing['rows']} von {listing['total']} Haendlern")
        if not listing["done"]:
            print(f"  unterbrochen: {listing['stopped']}")
            return 0
        budget = None if max_requests is None else max(max_requests - listing["requests"], 0)
        result = dump_item_details(
            client, vendor_ids(directory), directory, max_requests=budget, kind="vendors"
        )
    print(
        f"Sortimente: {result['wanted']} gewuenscht, {result['already']} schon da, "
        f"{result['fetched']} geholt, {result['left']} offen"
    )
    if result["stopped"]:
        print(f"  unterbrochen: {result['stopped']} - der naechste Lauf macht dort weiter")
    print(f"  nach {result['file']}")
    return 0


PROFESSIONS_FILE = "professions.jsonl"
RECIPES_FILE = "recipes.jsonl"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Erst daneben schreiben, dann umbenennen - nie liegt eine halbe Datei."""
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def dump_recipes(
    client: ForeverDBClient, directory: Path, max_requests: int | None = None
) -> dict[str, Any]:
    """Zieht alle Berufe mit ihren Rezepten ab: Zutaten, Ergebnis, Lernquelle.

    Das sind gut 30 Anfragen. Gesammelt wird im Speicher und erst geschrieben, wenn
    alles da ist. Bricht der Lauf ab, bleiben die bisherigen Dateien, wie sie waren.

        professions.jsonl  ein Beruf je Zeile: Raenge, Lehrer
        recipes.jsonl      ein Rezept je Zeile, dazu der Beruf, zu dem es gehoert
    """
    professions: list[dict[str, Any]] = []
    recipes: list[dict[str, Any]] = []
    requests_made = 0

    def result(stopped: str | None) -> dict[str, Any]:
        return {
            "complete": stopped is None,
            "professions": len(professions),
            "recipes": len(recipes),
            "requests": requests_made,
            "stopped": stopped,
            "file": directory / RECIPES_FILE,
        }

    def fetch(path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], str | None]:
        nonlocal requests_made
        if max_requests is not None and requests_made >= max_requests:
            return {}, "Grenze fuer diesen Lauf erreicht"
        try:
            response = client.get(path, params)
        except ForeverDBQuotaError as exc:
            return {}, str(exc)
        requests_made += 1
        if not response.ok:
            return {}, f"HTTP {response.status} bei {path}"
        return response.data or {}, None

    payload, problem = fetch("/professions")
    if problem:
        return result(problem)

    for entry in payload.get("data") or []:
        slug = entry.get("slug")
        if not slug:
            continue
        header = dict(entry)
        offset = 0
        total: int | None = None
        while total is None or offset < total:
            payload, problem = fetch(f"/professions/{slug}", {"limit": PAGE_SIZE, "offset": offset})
            if problem:
                return result(problem)
            data = payload.get("data") or {}
            total = (payload.get("meta") or {}).get("total", total)
            if offset == 0:
                # Raenge und Lehrer stehen auf jeder Seite; einmal genuegt.
                header = {key: value for key, value in data.items() if key != "recipes"} or header
            page = data.get("recipes") or []
            if not page:
                break
            for recipe in page:
                recipes.append({**recipe, "profession": slug, "professionName": header.get("name") or slug})
            offset += len(page)
        professions.append(header)

    directory.mkdir(parents=True, exist_ok=True)
    _write_jsonl(directory / PROFESSIONS_FILE, professions)
    _write_jsonl(directory / RECIPES_FILE, recipes)
    return result(None)


def _print_recipes(result: dict[str, Any]) -> None:
    if result["complete"]:
        print(
            f"{result['recipes']} Rezepte aus {result['professions']} Berufen, "
            f"{result['requests']} Anfragen, nach {result['file']}"
        )
    else:
        print(
            f"Rezepte nicht vollstaendig ({result['stopped']}) - nichts geschrieben, "
            "die bisherigen Dateien gelten weiter."
        )


def recipes_main(settings: Settings, max_requests: int | None = None) -> int:
    with ForeverDBClient(settings.foreverdb_key) as client:
        result = dump_recipes(client, dump_dir(settings), max_requests=max_requests)
    _print_recipes(result)
    return 0


REFRESH_DIR = "refresh"
# Die Listen, die beim Auffrischen neu geholt werden. Die Spell-Liste gehoert dazu,
# weil an ihr die Abklingzeiten der Rezepte haengen.
REFRESH_LISTS = ("items", "vendors", "spells")
# Was am Ende in einem Zug ausgetauscht wird.
REFRESH_FILES = (*(f"{name}.jsonl" for name in REFRESH_LISTS), VENDOR_DETAILS_FILE)


def refresh(
    client: ForeverDBClient, directory: Path, max_requests: int | None = None
) -> dict[str, Any]:
    """Zieht Item-Liste, Haendler, Spell-Liste und Sortimente neu ab, ohne die alten anzutasten.

    Geholt wird in einen eigenen Ordner. Erst wenn alles vollstaendig da ist,
    ersetzen die neuen Dateien die alten. Bis dahin - auch nach einem Abbruch -
    arbeiten Datenbank und Oberflaeche mit dem bisherigen, vollstaendigen Stand.
    Ein erneuter Aufruf setzt im Ordner dort fort, wo der letzte aufgehoert hat.
    """
    staging = directory / REFRESH_DIR
    budget = max_requests
    used = 0
    steps: list[dict[str, Any]] = []

    def remaining() -> int | None:
        return None if budget is None else max(budget - used, 0)

    for name in REFRESH_LISTS:
        result = dump_list(client, name, staging, max_requests=remaining())
        used += result["requests"]
        steps.append({"step": name, "rows": result["rows"], "total": result["total"], "done": result["done"]})
        if not result["done"]:
            return {"complete": False, "steps": steps, "requests": used, "stopped": result["stopped"]}

    details = dump_item_details(
        client, vendor_ids(staging), staging, max_requests=remaining(), kind="vendors"
    )
    used += details["requests"]
    steps.append({
        "step": "vendor_details",
        "rows": details["already"] + details["fetched"],
        "total": details["wanted"],
        "done": details["stopped"] is None and details["left"] == 0,
    })
    if details["stopped"] is not None or details["left"]:
        return {"complete": False, "steps": steps, "requests": used, "stopped": details["stopped"]}

    # Alles da: austauschen. Der Stand der Listen wandert mit, die Fehlanzeigen der
    # Haendler gelten fuer den neuen Abzug neu.
    fresh_state = _load_state(staging)
    state = _load_state(directory)
    for file_name in REFRESH_FILES:
        os.replace(staging / file_name, directory / file_name)
    for key in (*REFRESH_LISTS, DETAIL_KINDS["vendors"][2]):
        if key in fresh_state:
            state[key] = fresh_state[key]
        else:
            state.pop(key, None)
    _save_state(directory, state)
    (staging / "state.json").unlink(missing_ok=True)
    try:
        staging.rmdir()
    except OSError:
        pass
    return {"complete": True, "steps": steps, "requests": used, "stopped": None}


def refresh_main(settings: Settings, max_requests: int | None = None) -> int:
    directory = dump_dir(settings)
    with ForeverDBClient(settings.foreverdb_key) as client:
        result = refresh(client, directory, max_requests=max_requests)
        recipes = None
        if result["complete"]:
            # Ein neuer Spielstand aendert auch Rezepte. Die kosten nur gut 30 Anfragen.
            left = None if max_requests is None else max(max_requests - result["requests"], 0)
            recipes = dump_recipes(client, directory, max_requests=left)
    for step in result["steps"]:
        status = "fertig" if step["done"] else "offen"
        print(f"  {step['step']:<15} {step['rows']:>6} von {step['total']} - {status}")
    if result["complete"]:
        print(f"Ausgetauscht nach {result['requests']} Anfragen: {', '.join(REFRESH_FILES)}")
    else:
        print(
            f"Noch nicht vollstaendig ({result['stopped']}). Die bisherigen Dateien gelten weiter; "
            "ein erneuter Aufruf setzt fort."
        )
    if recipes is not None:
        _print_recipes(recipes)
    return 0


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
