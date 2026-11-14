"""Das Warehouse: Parquet-Dateien, eine je Tag und Datensatz.

Bewusst keine Datenbankdatei. Parquet laesst sich versionieren, im Browser mit
DuckDB-WASM lesen und von jedem Werkzeug oeffnen, das SQL kann.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb

ITEMS = "items"
SALES = "sales"
RUNS = "runs"
SNAPSHOT = "state/snapshot"


def connect() -> duckdb.DuckDBPyConnection:
    """DuckDB laeuft im Arbeitsspeicher, die Wahrheit steht in den Parquet-Dateien."""
    return duckdb.connect()


def dataset_path(root: Path, dataset: str, day: dt.date | None = None) -> Path:
    if day is None:
        return root / f"{dataset}.parquet"
    return root / dataset / f"dt={day:%Y-%m-%d}.parquet"


def sql_path(path: Path) -> str:
    """DuckDB mag Schraegstriche, auch unter Windows."""
    return path.as_posix().replace("'", "''")


def read_parquet(con: duckdb.DuckDBPyConnection, path: Path, into: str) -> int:
    """Liest eine Parquet-Datei in eine temporaere Tabelle. Fehlt sie, bleibt die Tabelle leer."""
    if not path.exists():
        return 0
    con.execute(f"CREATE OR REPLACE TEMP TABLE {into} AS SELECT * FROM read_parquet('{sql_path(path)}')")
    return con.execute(f"SELECT count(*) FROM {into}").fetchone()[0]


def write_parquet(con: duckdb.DuckDBPyConnection, relation: str, path: Path, order_by: str = "") -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    order = f" ORDER BY {order_by}" if order_by else ""
    con.execute(
        f"COPY (SELECT * FROM {relation}{order}) TO '{sql_path(path)}' "
        "(FORMAT parquet, COMPRESSION zstd)"
    )
    return con.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]


def append_parquet(
    con: duckdb.DuckDBPyConnection, relation: str, path: Path, order_by: str = ""
) -> int:
    """Haengt an eine Tagesdatei an, indem sie gelesen und neu geschrieben wird.

    Parquet kann nicht anhaengen. Bei einer Tagesdatei von ein paar MB ist das
    Neuschreiben billiger als eine Datei je Abruf und tausende kleiner Dateien.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        con.execute(
            f"CREATE OR REPLACE TEMP TABLE _merge AS "
            f"SELECT * FROM read_parquet('{sql_path(path)}') "
            f"UNION ALL BY NAME SELECT * FROM {relation}"
        )
    else:
        con.execute(f"CREATE OR REPLACE TEMP TABLE _merge AS SELECT * FROM {relation}")

    rows = write_parquet(con, "_merge", path, order_by)
    con.execute("DROP TABLE _merge")
    return rows


def last_seen_modified(con: duckdb.DuckDBPyConnection, runs_path: Path) -> str | None:
    """Der zuletzt verarbeitete Last-Modified-Wert, fuer bedingte Anfragen."""
    if not runs_path.exists():
        return None
    row = con.execute(
        f"SELECT last_modified FROM read_parquet('{sql_path(runs_path)}') "
        "WHERE NOT skipped AND last_modified IS NOT NULL "
        "ORDER BY snapshot_ts DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def known_snapshots(con: duckdb.DuckDBPyConnection, runs_path: Path) -> set[dt.datetime]:
    """Welche Staende schon verarbeitet sind - damit derselbe nicht zweimal zaehlt."""
    if not runs_path.exists():
        return set()
    rows = con.execute(
        f"SELECT DISTINCT snapshot_ts FROM read_parquet('{sql_path(runs_path)}') "
        "WHERE snapshot_ts IS NOT NULL AND NOT skipped"
    ).fetchall()
    return {row[0] for row in rows}
