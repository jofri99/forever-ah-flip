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
        print(f"Datenordner {config.data_dir}")
        print(f"Client-ID   {'gesetzt' if config.client_id else 'FEHLT'}")
        print(f"Secret      {'gesetzt' if config.client_secret else 'FEHLT'}")
        return 0

    if args.command == "verify":
        try:
            config.require_credentials()
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 2

        from . import verify as verify_module

        return verify_module.main(config, ruleset=args.ruleset, keep_raw=args.keep_raw)

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
