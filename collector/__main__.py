"""Einstiegspunkt: py -m collector <kommando>"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import settings as load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="collector",
        description="Auktionshausdaten aus WoW: Forever ueber die Battle.net-API sammeln.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="mehr Logausgabe")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="zeigt die geladene Konfiguration, ohne Geheimnisse")

    verify = sub.add_parser("verify", help="prueft, welche Forever-Endpunkte Daten liefern")
    verify.add_argument("--ruleset", type=int, default=None, help="Stichprobe aus diesem Ruleset")
    verify.add_argument("--keep-raw", action="store_true", help="heruntergeladene JSONs behalten")

    collect = sub.add_parser("collect", help="holt einen Stand und legt ihn im Warehouse ab")
    collect.add_argument("--house", type=int, default=None, help="Auktionshaus (Vorgabe 114)")
    collect.add_argument("--force", action="store_true", help="auch einen schon bekannten Stand verarbeiten")
    collect.add_argument("--keep-raw", action="store_true", help="heruntergeladene JSONs behalten")

    names = sub.add_parser("names", help="traegt Namen und Stammdaten neuer Items nach")
    names.add_argument("--limit", type=int, default=None, help="hoechstens so viele Items pruefen")
    names.add_argument("--house", type=int, default=None, help="Auktionshaus (Vorgabe 114)")

    foreverdb = sub.add_parser("foreverdb", help="zieht Listen von ForeverDB lokal ab (fortsetzbar)")
    foreverdb.add_argument("lists", nargs="*", default=["items"], help="items, vendors, quests, spells, itemsets")
    foreverdb.add_argument("--max-requests", type=int, default=None, help="hoechstens so viele Anfragen")
    foreverdb.add_argument("--restart", action="store_true", help="von vorn beginnen statt fortsetzen")

    details = sub.add_parser(
        "foreverdb-details", help="zieht die Details einzelner Items von ForeverDB ab (fortsetzbar)"
    )
    details.add_argument(
        "--scope", choices=["gaps", "market", "all"], default="gaps",
        help="gaps: Items im Markt, die Blizzard nicht kennt (Vorgabe); market: alle im Markt; all: alle",
    )
    details.add_argument("--max-requests", type=int, default=None, help="hoechstens so viele Anfragen")

    vendors = sub.add_parser(
        "foreverdb-vendors", help="zieht alle Haendler samt Sortiment und Preisen von ForeverDB ab"
    )
    vendors.add_argument("--max-requests", type=int, default=None, help="hoechstens so viele Anfragen")

    sub.add_parser("db", help="baut die lokale DuckDB-Datei mit Sichten auf alle Daten")

    sql = sub.add_parser("sql", help="fuehrt eine Abfrage gegen die lokale Datenbank aus")
    sql.add_argument("query", nargs="?", default=None, help="SQL; ohne Angabe wird --file gelesen")
    sql.add_argument("--file", type=Path, default=None, help="Datei mit der Abfrage")
    sql.add_argument("--rows", type=int, default=50, help="hoechstens so viele Zeilen zeigen")

    publish = sub.add_parser("publish", help="baut aus dem Warehouse die Dateien fuer die Anzeige")
    publish.add_argument("--days", type=int, default=14, help="Zeitfenster in Tagen (Vorgabe 14)")
    publish.add_argument("--out", type=Path, default=None, help="Zielordner (Vorgabe web/public/data)")
    publish.add_argument("--house", type=int, default=None, help="Auktionshaus (Vorgabe 114)")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    config = load_settings()

    if args.command == "config":
        print(f"Region      {config.region}")
        print(f"Namespace   {config.namespace()}")
        print(f"Locale      {config.locale}")
        print(f"Rulesets    {', '.join(str(r) for r in config.rulesets)}")
        print(f"Gesammelt   Haus {config.house} ueber Ruleset {config.ruleset}")
        print(f"Datenordner {config.data_dir}")
        print(f"Client-ID   {'gesetzt' if config.client_id else 'FEHLT'}")
        print(f"Secret      {'gesetzt' if config.client_secret else 'FEHLT'}")
        return 0

    # ForeverDB hat einen eigenen Schluessel und braucht die von Blizzard nicht.
    if args.command == "foreverdb":
        from . import foreverdb_dump
        from .foreverdb import ForeverDBError

        unknown = [name for name in args.lists if name not in foreverdb_dump.LISTS]
        if unknown:
            print(f"Unbekannte Liste: {', '.join(unknown)}. Moeglich: {', '.join(foreverdb_dump.LISTS)}", file=sys.stderr)
            return 2
        try:
            return foreverdb_dump.main(
                config, args.lists, max_requests=args.max_requests, restart=args.restart
            )
        except ForeverDBError as exc:
            print(exc, file=sys.stderr)
            return 2

    if args.command == "foreverdb-vendors":
        from . import foreverdb_dump
        from .foreverdb import ForeverDBError

        try:
            return foreverdb_dump.vendors_main(config, max_requests=args.max_requests)
        except (ForeverDBError, RuntimeError) as exc:
            print(exc, file=sys.stderr)
            return 2

    if args.command == "foreverdb-details":
        from . import foreverdb_dump
        from .foreverdb import ForeverDBError

        try:
            return foreverdb_dump.details_main(config, scope=args.scope, max_requests=args.max_requests)
        except (ForeverDBError, RuntimeError) as exc:
            print(exc, file=sys.stderr)
            return 2

    # Die Datenbank schaut nur auf vorhandene Dateien und braucht keine Zugangsdaten.
    if args.command == "db":
        from . import db as db_module

        return db_module.main(config)

    if args.command == "sql":
        from . import db as db_module

        statement = args.query or (args.file.read_text(encoding="utf-8") if args.file else None)
        if not statement:
            print("Keine Abfrage angegeben. Beispiel: python -m collector sql \"SELECT * FROM latest LIMIT 5\"", file=sys.stderr)
            return 2
        try:
            db_module.query(config, statement, max_rows=args.rows)
        except Exception as exc:  # SQL-Fehler sollen lesbar ankommen, nicht als Traceback
            print(f"Abfrage fehlgeschlagen: {exc}", file=sys.stderr)
            return 1
        return 0

    # publish liest nur das Warehouse und braucht keine Zugangsdaten.
    if args.command == "publish":
        from . import publish as publish_module

        return publish_module.main(config, out_dir=args.out, house=args.house, days=args.days)

    try:
        config.require_credentials()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.command == "verify":
        from . import verify as verify_module

        return verify_module.main(config, ruleset=args.ruleset, keep_raw=args.keep_raw)

    if args.command == "names":
        from . import names as names_module

        return names_module.main(config, house=args.house, limit=args.limit)

    if args.command == "collect":
        from . import collect as collect_module

        return collect_module.main(
            config, house=args.house, force=args.force, keep_raw=args.keep_raw
        )

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
