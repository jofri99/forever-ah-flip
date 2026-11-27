"""Prueft, was die Battle.net-API fuer Forever wirklich herausgibt.

Die Endpunkte sind von der Community kartiert und nicht dokumentiert. Dieses
Kommando fragt sie der Reihe nach ab und schreibt einen Bericht, damit der
Sammler auf gemessenen Tatsachen aufsetzt statt auf Forenposts.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .blizzard import ApiResponse, BlizzardClient
from .config import Settings

OK = "[ok]"
BAD = "[xx]"
INFO = "[--]"


def _size(size: int) -> str:
    return f"{size / 1024:.0f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"


def _line(marker: str, text: str) -> None:
    print(f"{marker} {text}", flush=True)


def _record(report: dict[str, Any], key: str, response: ApiResponse) -> None:
    report["calls"][key] = {
        "status": response.status,
        "size": response.size,
        "seconds": round(response.elapsed, 2),
        "last_modified": response.last_modified,
    }


def _localized(value: Any, locale: str) -> Any:
    if isinstance(value, dict):
        return value.get(locale) or value.get("type") or next(iter(value.values()), None)
    return value


def run(settings: Settings, ruleset_hint: int | None = None, keep_raw: bool = False) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "started": started.isoformat(timespec="seconds"),
        "region": settings.region,
        "namespace": settings.namespace(),
        "calls": {},
        "rulesets": {},
        "notes": [],
    }

    print(f"Region {settings.region}, Namespace {settings.namespace()}")
    print("-" * 72)

    with BlizzardClient(settings) as client:
        client.token()
        _line(OK, "Token geholt")

        index = client.ruleset_index()
        _record(report, "ruleset/index", index)
        if not index.ok:
            _line(BAD, f"/data/wow/ruleset/index -> {index.status}")
            report["notes"].append(
                "Ruleset-Index nicht erreichbar. Mit gueltigem Token heisst 404 hier "
                "wirklich, dass es den Endpunkt nicht gibt."
            )
            return report

        listed = [entry.get("id") for entry in (index.data or {}).get("rulesets", []) if entry.get("id")]
        if not listed:
            listed = list(settings.rulesets)
            report["notes"].append("Der Index enthielt keine Liste, daher FOREVER_RULESETS benutzt.")
        _line(OK, f"/data/wow/ruleset/index -> Rulesets {listed}")
        report["ruleset_ids"] = listed

        houses_per_ruleset: dict[int, list[int]] = {}

        for ruleset_id in listed:
            detail = client.ruleset(ruleset_id)
            _record(report, f"ruleset/{ruleset_id}", detail)
            name = _localized((detail.data or {}).get("name"), settings.locale) if detail.ok else None
            status = _localized((detail.data or {}).get("status"), settings.locale) if detail.ok else None

            houses_response = client.auction_houses(ruleset_id)
            _record(report, f"ruleset/{ruleset_id}/auctions/", houses_response)
            houses: list[int] = []
            if houses_response.ok:
                for entry in (houses_response.data or {}).get("auctions", []):
                    if entry.get("id"):
                        houses.append(entry["id"])
            houses_per_ruleset[ruleset_id] = houses

            report["rulesets"][str(ruleset_id)] = {
                "name": name,
                "status": status,
                "houses": houses,
            }
            _line(
                OK if houses else BAD,
                f"Ruleset {ruleset_id} ({name or '?'}): {len(houses)} Auktionshaeuser {houses}",
            )

        # Liefern verschiedene Rulesets dieselben Haeuser? Davon haengt ab, ob der
        # Sammler eines abfragt oder alle.
        distinct = {tuple(value) for value in houses_per_ruleset.values() if value}
        report["identical_house_lists"] = len(distinct) <= 1
        _line(
            INFO,
            "Alle Rulesets melden dieselbe Haeuserliste"
            if len(distinct) <= 1
            else "Die Rulesets melden verschiedene Haeuserlisten - jedes einzeln sammeln",
        )

        target = ruleset_hint or next((r for r, h in houses_per_ruleset.items() if h), None)
        if target is None:
            report["notes"].append("Kein Ruleset mit Auktionshaeusern gefunden.")
            return report

        print("-" * 72)
        print(f"Stichprobe aus Ruleset {target}")

        raw_dir = settings.raw_dir / "verify"
        sample_houses = houses_per_ruleset.get(target, [])[:3]
        report["sample"] = {}

        for house_id in sample_houses:
            destination = raw_dir / f"ruleset{target}_house{house_id}.json"
            response = client.auctions(target, house_id, stream_to=destination)
            _record(report, f"ruleset/{target}/auctions/{house_id}", response)

            if not response.ok:
                _line(BAD, f"Haus {house_id} -> {response.status}")
                report["sample"][str(house_id)] = {"status": response.status}
                continue

            payload = json.loads(destination.read_text(encoding="utf-8"))
            auctions = payload.get("auctions") or []
            example = auctions[0] if auctions else None
            house_name = _localized(payload.get("name"), settings.locale)
            quantities = sorted({a.get("quantity") for a in auctions})[:4]

            report["sample"][str(house_id)] = {
                "status": response.status,
                "name": house_name,
                "bytes": response.size,
                "auctions": len(auctions),
                "items": len({a["item"]["id"] for a in auctions if isinstance(a.get("item"), dict)}),
                "quantities": quantities,
                "last_modified": response.last_modified,
                "fields": sorted(example) if isinstance(example, dict) else None,
                "example": example,
            }
            _line(
                OK,
                f"Haus {house_id} ({house_name or '?'}): {len(auctions):>6} Auktionen, "
                f"{_size(response.size)}, {response.elapsed:.1f}s",
            )
            _line(INFO, f"     Stand {response.last_modified or '?'}, Mengen {quantities}")
            if isinstance(example, dict):
                _line(INFO, "     Felder: " + ", ".join(sorted(example)))
                _line(INFO, "     Beispiel: " + json.dumps(example, ensure_ascii=False)[:160])

            if not keep_raw:
                destination.unlink(missing_ok=True)

        # Stapelware liegt nicht im Hausdokument, dort steht nur ein Link darauf.
        if sample_houses:
            house_id = sample_houses[0]
            separate = client.commodities(target, house_id)
            _record(report, f"ruleset/{target}/auctions/{house_id}/commodities", separate)
            if separate.ok:
                rows = (separate.data or {}).get("auctions") or []
                example = rows[0] if rows else None
                report["commodities"] = {
                    "house": house_id,
                    "rows": len(rows),
                    "fields": sorted(example) if isinstance(example, dict) else None,
                    "example": example,
                }
                _line(OK, f"Commodity-Endpunkt Haus {house_id}: {len(rows)} Zeilen")
                if isinstance(example, dict):
                    _line(INFO, "     Felder: " + ", ".join(sorted(example)))
                    _line(INFO, "     Beispiel: " + json.dumps(example, ensure_ascii=False)[:160])
            else:
                _line(INFO, f"Commodity-Endpunkt -> {separate.status}")

    report["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


def main(settings: Settings, ruleset: int | None = None, keep_raw: bool = False) -> int:
    report = run(settings, ruleset_hint=ruleset, keep_raw=keep_raw)

    out_dir = settings.data_dir / "verify"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"verify-{settings.region}-{stamp}.json"
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("-" * 72)
    print(f"Bericht: {out_file}")
    for note in report.get("notes", []):
        print(f"Hinweis: {note}")
    return 0 if report.get("rulesets") else 1
