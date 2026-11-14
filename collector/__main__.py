"""Einstiegspunkt: py -m collector <kommando>"""

from __future__ import annotations

import argparse
import logging
import sys

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

    try:
        config.require_credentials()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.command == "verify":
        from . import verify as verify_module

        return verify_module.main(config, ruleset=args.ruleset, keep_raw=args.keep_raw)

    if args.command == "collect":
        from . import collect as collect_module

        return collect_module.main(
            config, house=args.house, force=args.force, keep_raw=args.keep_raw
        )

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
