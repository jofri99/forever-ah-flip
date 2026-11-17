"""Das Warehouse: Parquet-Dateien, eine je Stand und Datensatz.

Bewusst keine Datenbankdatei. Parquet laesst sich versionieren, im Browser mit
DuckDB-WASM lesen und von jedem Werkzeug oeffnen, das SQL kann.

Jede Datei wird genau einmal geschrieben und danach nie wieder angefasst:

    items/house=114/dt=2026-11-14/191911.parquet

Das ist Absicht. Das Warehouse liegt in einem Git-Branch, und eine Tagesdatei,
die bei jedem Stand neu geschrieben wird, legt jedes Mal ihren ganzen Inhalt
in die Historie - rund 30 MB am Tag fuer 2,4 MB Daten.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from email.utils import format_datetime
from pathlib import Path

import duckdb

ITEMS = "items"
SALES = "sales"
RUNS = "runs"
LATEST = "latest"
POINTER_FORMAT = "%Y-%m-%dT%H:%M:%S"


def connect() -> duckdb.DuckDBPyConnection:
    """DuckDB laeuft im Arbeitsspeicher, die Wahrheit steht in den Parquet-Dateien."""
    return duckdb.connect()


def sql_path(path: Path) -> str:
    """DuckDB mag Schraegstriche, auch unter Windows."""
    return path.as_posix().replace("'", "''")


def snapshot_path(root: Path, dataset: str, house: int, ts: dt.datetime) -> Path:
    return root / dataset / f"house={house}" / f"dt={ts:%Y-%m-%d}" / f"{ts:%H%M%S}.parquet"


def pointer_path(root: Path, house: int) -> Path:
    return root / LATEST / f"house={house}.json"


def read_pointer(root: Path, house: int) -> dt.datetime | None:
    path = pointer_path(root, house)
    if not path.is_file():
        return None
    try:
        stamp = json.loads(path.read_text(encoding="utf-8"))["snapshot_ts"]
        return dt.datetime.strptime(stamp, POINTER_FORMAT)
    except (ValueError, KeyError, TypeError):
        return None


def write_pointer(root: Path, house: int, ts: dt.datetime) -> Path:
    """Haelt fest, welcher Stand der juengste ist.

    In Actions wird der Branch `data` nur ausschnittsweise ausgecheckt, damit nicht
    bei jedem Lauf der gesamte Bestand heruntergeladen wird. Die Parquet-Dateien
    liegen dann nicht auf der Platte - diese eine kleine Datei schon.
    """
    path = pointer_path(root, house)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "house": house,
        "snapshot_ts": ts.strftime(POINTER_FORMAT),
        "items": snapshot_path(root, ITEMS, house, ts).relative_to(root).as_posix(),
    }
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def latest_snapshot(root: Path, house: int, dataset: str = ITEMS) -> dt.datetime | None:
    """Der juengste Stand im Warehouse: laut Zeigerdatei und laut Dateinamen,
    je nachdem, was weiter reicht. Im Ausschnitt-Checkout gibt es nur den Zeiger."""
    newest = read_pointer(root, house)
    base = root / dataset / f"house={house}"
    if base.is_dir():
        for file in base.glob("dt=*/*.parquet"):
            try:
                stamp = dt.datetime.strptime(file.parent.name[3:] + file.stem, "%Y-%m-%d%H%M%S")
            except ValueError:
                continue
            if newest is None or stamp > newest:
                newest = stamp
    return newest


def http_date(ts: dt.datetime) -> str:
    """UTC-Zeitpunkt als HTTP-Datum, wie es If-Modified-Since erwartet."""
    return format_datetime(ts.replace(tzinfo=dt.timezone.utc), usegmt=True)


def read_parquet(con: duckdb.DuckDBPyConnection, path: Path, into: str) -> int:
    """Liest eine Parquet-Datei in eine temporaere Tabelle. Fehlt sie, kommt 0 zurueck."""
    if not path.exists():
        return 0
    con.execute(f"CREATE OR REPLACE TEMP TABLE {into} AS SELECT * FROM read_parquet('{sql_path(path)}')")
    return con.execute(f"SELECT count(*) FROM {into}").fetchone()[0]


def write_parquet(
    con: duckdb.DuckDBPyConnection,
    relation: str,
    path: Path,
    order_by: str = "",
    compression: str = "zstd",
    row_group_size: int | None = None,
) -> int:
    """Schreibt erst daneben und benennt dann um, damit nie eine halbe Datei liegen bleibt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    order = f" ORDER BY {order_by}" if order_by else ""
    options = f"FORMAT parquet, COMPRESSION {compression}"
    if row_group_size:
        options += f", ROW_GROUP_SIZE {int(row_group_size)}"
    con.execute(f"COPY (SELECT * FROM {relation}{order}) TO '{sql_path(temporary)}' ({options})")
    os.replace(temporary, path)
    return con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]


def dataset_glob(root: Path, dataset: str, house: int) -> str | None:
    """Alle Dateien eines Datensatzes als Muster fuer read_parquet, oder None, wenn es keine gibt."""
    base = root / dataset / f"house={house}"
    if not base.is_dir() or next(base.glob("dt=*/*.parquet"), None) is None:
        return None
    return sql_path(base / "*" / "*.parquet")
