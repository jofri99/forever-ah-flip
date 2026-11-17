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
import os
from email.utils import format_datetime
from pathlib import Path

import duckdb

ITEMS = "items"
SALES = "sales"
RUNS = "runs"


def connect() -> duckdb.DuckDBPyConnection:
    """DuckDB laeuft im Arbeitsspeicher, die Wahrheit steht in den Parquet-Dateien."""
    return duckdb.connect()


def sql_path(path: Path) -> str:
    """DuckDB mag Schraegstriche, auch unter Windows."""
    return path.as_posix().replace("'", "''")


def snapshot_path(root: Path, dataset: str, house: int, ts: dt.datetime) -> Path:
    return root / dataset / f"house={house}" / f"dt={ts:%Y-%m-%d}" / f"{ts:%H%M%S}.parquet"


def latest_snapshot(root: Path, house: int, dataset: str = ITEMS) -> dt.datetime | None:
    """Der juengste Stand, der schon im Warehouse liegt - abgelesen am Dateinamen."""
    base = root / dataset / f"house={house}"
    if not base.is_dir():
        return None
    newest: dt.datetime | None = None
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


def write_parquet(con: duckdb.DuckDBPyConnection, relation: str, path: Path, order_by: str = "") -> int:
    """Schreibt erst daneben und benennt dann um, damit nie eine halbe Datei liegen bleibt."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    order = f" ORDER BY {order_by}" if order_by else ""
    con.execute(
        f"COPY (SELECT * FROM {relation}{order}) TO '{sql_path(temporary)}' "
        "(FORMAT parquet, COMPRESSION zstd)"
    )
    os.replace(temporary, path)
    return con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
