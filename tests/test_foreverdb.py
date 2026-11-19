"""Tests fuer den ForeverDB-Client und den Abzug - gefaelschte Session, kein Netz."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector import foreverdb_dump, store
from collector.config import Settings
from collector.foreverdb import (
    ForeverDBAuthError,
    ForeverDBClient,
    ForeverDBQuotaError,
)


class FakeResponse:
    def __init__(self, status: int, payload: object = None, headers: dict | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload

    @property
    def content(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def json(self) -> object:
        return self._payload


class FakeCatalog:
    """Eine Liste von 250 Items, seitenweise ausgeliefert wie von der API."""

    def __init__(self, total: int = 250) -> None:
        self.headers: dict[str, str] = {}
        self.total = total
        self.calls: list[dict] = []
        self.fail_at_offset: int | None = None
        self.queued: list[FakeResponse] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if self.queued:
            return self.queued.pop(0)
        offset = int((params or {}).get("offset", 0))
        limit = int((params or {}).get("limit", 25))
        if self.fail_at_offset is not None and offset >= self.fail_at_offset:
            return FakeResponse(402, {"error": {"code": "subscription_required"}})
        rows = [{"id": i, "name": f"Item {i}"} for i in range(offset + 1, min(offset + limit, self.total) + 1)]
        return FakeResponse(200, {"data": rows, "meta": {"total": self.total, "limit": limit, "offset": offset}})

    def close(self) -> None:
        pass


def make_client(session: FakeCatalog, waits: list[float] | None = None, clock: list[float] | None = None) -> ForeverDBClient:
    waits = waits if waits is not None else []
    clock = clock if clock is not None else [0.0]

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    return ForeverDBClient("fdb_test", session=session, sleep=sleep, now=lambda: clock[0])


def test_key_goes_into_the_header_and_never_into_the_url() -> None:
    session = FakeCatalog()
    client = make_client(session)

    client.get("/items", {"limit": 1})

    assert session.headers["X-API-Key"] == "fdb_test"
    assert session.headers["User-Agent"].startswith("forever-ah-flip")
    call = session.calls[0]
    assert call["url"] == "https://foreverdb.net/api/v1/items"
    assert "fdb_test" not in json.dumps(call)


def test_missing_key_is_a_clear_error() -> None:
    with pytest.raises(ForeverDBAuthError, match="FOREVERDB_API_KEY"):
        ForeverDBClient("")


def test_requests_keep_their_distance() -> None:
    waits: list[float] = []
    client = make_client(FakeCatalog(), waits)

    client.get("/items")
    client.get("/items")
    client.get("/items")

    # 30 je Minute sind erlaubt; der Client bleibt mit 2,2 s Abstand darunter.
    assert waits == [2.2, 2.2]


def test_429_waits_as_told_and_then_gives_up() -> None:
    waits: list[float] = []
    session = FakeCatalog()
    session.queued = [FakeResponse(429, headers={"Retry-After": "7"})]
    client = make_client(session, waits)

    assert client.get("/items").ok
    assert 7.0 in waits

    session.queued = [FakeResponse(429) for _ in range(5)]
    with pytest.raises(ForeverDBQuotaError):
        client.get("/items", retries=2)


def test_402_and_401_are_not_retried() -> None:
    session = FakeCatalog()
    client = make_client(session)

    session.queued = [FakeResponse(402)]
    with pytest.raises(ForeverDBQuotaError, match="Tageskontingent"):
        client.get("/items")

    session.queued = [FakeResponse(401)]
    with pytest.raises(ForeverDBAuthError):
        client.get("/items")
    assert len(session.calls) == 2


def read_ids(path: Path) -> list[int]:
    return [json.loads(line)["id"] for line in path.read_text(encoding="utf-8").splitlines()]


def test_dump_pages_through_the_whole_list(tmp_path: Path) -> None:
    session = FakeCatalog(total=250)
    result = foreverdb_dump.dump_list(make_client(session), "items", tmp_path)

    assert (result["rows"], result["total"], result["done"], result["requests"]) == (250, 250, True, 3)
    assert [c["params"]["offset"] for c in session.calls] == [0, 100, 200]
    assert read_ids(tmp_path / "items.jsonl") == list(range(1, 251))


def test_dump_resumes_where_it_stopped(tmp_path: Path) -> None:
    session = FakeCatalog(total=250)
    client = make_client(session)

    # Das Kontingent reicht nur fuer die erste Seite.
    session.fail_at_offset = 100
    first = foreverdb_dump.dump_list(client, "items", tmp_path)
    assert (first["rows"], first["done"]) == (100, False)
    assert "Tageskontingent" in first["stopped"]

    # Am naechsten Tag geht es dort weiter - ohne die erste Seite erneut zu holen.
    session.fail_at_offset = None
    session.calls.clear()
    second = foreverdb_dump.dump_list(client, "items", tmp_path)

    assert (second["rows"], second["done"]) == (250, True)
    assert [c["params"]["offset"] for c in session.calls] == [100, 200]
    assert read_ids(tmp_path / "items.jsonl") == list(range(1, 251))

    # Ein fertiger Abzug kostet beim erneuten Aufruf keine Anfrage.
    session.calls.clear()
    third = foreverdb_dump.dump_list(client, "items", tmp_path)
    assert third["done"] and session.calls == []


def test_dump_respects_the_request_budget_and_restart(tmp_path: Path) -> None:
    session = FakeCatalog(total=250)
    client = make_client(session)

    limited = foreverdb_dump.dump_list(client, "items", tmp_path, max_requests=1)
    assert (limited["rows"], limited["done"], limited["requests"]) == (100, False, 1)

    again = foreverdb_dump.dump_list(client, "items", tmp_path, restart=True)
    assert (again["rows"], again["done"]) == (250, True)
    assert read_ids(tmp_path / "items.jsonl") == list(range(1, 251))


def test_english_names_fill_only_the_gaps(tmp_path: Path) -> None:
    settings = Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "x", "BLIZZARD_CLIENT_SECRET": "x", "AH_DATA_DIR": str(tmp_path / "data")}
    )
    con = store.connect()
    try:
        assert foreverdb_dump.english_names(con, settings) == {}

        directory = foreverdb_dump.dump_dir(settings)
        directory.mkdir(parents=True)
        (directory / "items.jsonl").write_text(
            '{"id":2589,"name":"Linen Cloth","quality":"Common"}\n{"id":7,"name":"Bent Staff"}\n{"id":8,"name":""}\n',
            encoding="utf-8",
        )
        english = foreverdb_dump.english_names(con, settings)
    finally:
        con.close()

    assert english == {"2589": "Linen Cloth", "7": "Bent Staff"}
    # So fuegt publish zusammen: der deutsche Name gewinnt, der englische fuellt die Luecke.
    assert {**english, **{"2589": "Leinenstoff"}} == {"2589": "Leinenstoff", "7": "Bent Staff"}
    # Der Abzug liegt ausserhalb des Warehouse, also ausserhalb des oeffentlichen Branches.
    assert settings.warehouse_dir not in directory.parents


class FakeDetails(FakeCatalog):
    """Kennt die Items 1 bis 5, ausser der 3."""

    def get(self, url, params=None, timeout=None):
        if "/items/" not in url:
            return super().get(url, params, timeout)
        self.calls.append({"url": url, "params": {}})
        if self.queued:
            return self.queued.pop(0)
        item_id = int(url.rsplit("/", 1)[1])
        if item_id == 3 or item_id > 5:
            return FakeResponse(404, {"error": "not found"})
        return FakeResponse(200, {"data": {"id": item_id, "name": f"Item {item_id}", "sellPrice": item_id * 10}, "meta": {"client": "dev-0000"}})


def asked(session: FakeCatalog) -> list[int]:
    return [int(c["url"].rsplit("/", 1)[1]) for c in session.calls]


def test_details_are_fetched_one_by_one_and_written_at_once(tmp_path: Path) -> None:
    session = FakeDetails()
    result = foreverdb_dump.dump_item_details(make_client(session), [5, 1, 3], tmp_path)

    # In der gewuenschten Reihenfolge - die meistgehandelten zuerst.
    assert asked(session) == [5, 1, 3]
    assert (result["fetched"], result["not_found"], result["left"], result["stopped"]) == (2, 1, 0, None)

    lines = (tmp_path / foreverdb_dump.DETAILS_FILE).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == [5, 1]
    # Nur das Item selbst wird abgelegt, nicht der Umschlag mit der Entwickler-ID.
    assert "meta" not in json.loads(lines[0]) and "dev-0000" not in lines[0]


def test_details_resume_skips_what_is_there_and_what_does_not_exist(tmp_path: Path) -> None:
    session = FakeDetails()
    client = make_client(session)

    first = foreverdb_dump.dump_item_details(client, [1, 2, 3, 4, 5], tmp_path, max_requests=3)
    assert asked(session) == [1, 2, 3]
    assert (first["fetched"], first["not_found"], first["left"]) == (2, 1, 2)
    assert "Grenze" in first["stopped"]

    # Der zweite Lauf fragt weder die vorhandenen noch die Fehlanzeige erneut.
    session.calls.clear()
    second = foreverdb_dump.dump_item_details(client, [1, 2, 3, 4, 5], tmp_path)
    assert asked(session) == [4, 5]
    assert (second["already"], second["fetched"], second["left"], second["stopped"]) == (3, 2, 0, None)

    session.calls.clear()
    third = foreverdb_dump.dump_item_details(client, [1, 2, 3, 4, 5], tmp_path)
    assert asked(session) == [] and third["already"] == 5


def test_details_stop_cleanly_when_the_quota_runs_out(tmp_path: Path) -> None:
    session = FakeDetails()
    client = make_client(session)
    session.queued = [FakeResponse(200, {"data": {"id": 1, "name": "Item 1"}}), FakeResponse(402)]

    result = foreverdb_dump.dump_item_details(client, [1, 2, 4], tmp_path)

    assert (result["fetched"], result["left"]) == (1, 2)
    assert "Tageskontingent" in result["stopped"]
    # Was bis dahin kam, ist gesichert.
    assert foreverdb_dump.details_done(tmp_path) == {1}


def test_a_torn_last_line_does_not_break_the_resume(tmp_path: Path) -> None:
    (tmp_path / foreverdb_dump.DETAILS_FILE).write_text('{"id":1,"name":"Item 1"}\n{"id":2,"na', encoding="utf-8")

    assert foreverdb_dump.details_done(tmp_path) == {1}


class FakeVendors(FakeCatalog):
    """Drei Haendler in der Liste; die Details nennen das Sortiment."""

    SIDES = {1: "Alliance", 2: "Horde", 3: "Neutral"}

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if url.endswith("/vendors"):
            rows = [{"id": i, "name": f"Vendor {i}", "side": side} for i, side in self.SIDES.items()]
            return FakeResponse(200, {"data": rows, "meta": {"total": 3}})
        vendor_id = int(url.rsplit("/", 1)[1])
        return FakeResponse(200, {"data": {"id": vendor_id, "name": f"Vendor {vendor_id}", "sells": [{"itemId": 2589, "pricePerItem": 20.0}]}})


def test_vendors_are_listed_then_fetched_with_the_alliance_last(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings.from_env(
        {"BLIZZARD_CLIENT_ID": "x", "BLIZZARD_CLIENT_SECRET": "x", "AH_DATA_DIR": str(tmp_path / "data")}
    )
    session = FakeVendors()
    client = make_client(session)
    directory = foreverdb_dump.dump_dir(settings)

    foreverdb_dump.dump_list(client, "vendors", directory)
    # Gesammelt wird das Auktionshaus der Horde: deren Haendler und die neutralen zuerst.
    assert foreverdb_dump.vendor_ids(directory) == [2, 3, 1]

    session.calls.clear()
    result = foreverdb_dump.dump_item_details(
        client, foreverdb_dump.vendor_ids(directory), directory, kind="vendors"
    )
    assert [c["url"].rsplit("/", 2)[-2:] for c in session.calls] == [["vendors", "2"], ["vendors", "3"], ["vendors", "1"]]
    assert result["fetched"] == 3
    assert foreverdb_dump.details_done(directory, "vendors") == {1, 2, 3}
    # Die Details der Haendler liegen getrennt von denen der Items.
    assert foreverdb_dump.details_done(directory, "items") == set()
    assert (directory / foreverdb_dump.VENDOR_DETAILS_FILE).is_file()


class FakeWorld(FakeCatalog):
    """Items, Haendler und Spells zusammen, mit einer Version: nach einem neuen Build heisst alles anders."""

    def __init__(self, version: str = "v1") -> None:
        super().__init__(total=150)
        self.version = version
        self.fail_vendor: int | None = None

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if url.endswith("/items"):
            offset = int((params or {}).get("offset", 0))
            rows = [{"id": i, "name": f"Item {i} {self.version}"} for i in range(offset + 1, min(offset + 100, 150) + 1)]
            return FakeResponse(200, {"data": rows, "meta": {"total": 150}})
        if url.endswith("/vendors"):
            rows = [{"id": i, "name": f"Vendor {i}", "side": "Horde"} for i in (1, 2, 3)]
            return FakeResponse(200, {"data": rows, "meta": {"total": 3}})
        if url.endswith("/spells"):
            rows = [{"id": 17187, "name": f"Transmute {self.version}", "cooldownMs": 169200000}]
            return FakeResponse(200, {"data": rows, "meta": {"total": 1}})
        vendor_id = int(url.rsplit("/", 1)[1])
        if vendor_id == self.fail_vendor:
            return FakeResponse(402)
        return FakeResponse(200, {"data": {"id": vendor_id, "name": f"Vendor {vendor_id} {self.version}", "sells": []}})


def names_in(path: Path) -> list[str]:
    return [json.loads(line)["name"] for line in path.read_text(encoding="utf-8").splitlines()]


def test_refresh_keeps_the_old_files_until_everything_is_there(tmp_path: Path) -> None:
    old = FakeWorld("v1")
    client = make_client(old)
    foreverdb_dump.dump_list(client, "items", tmp_path)
    foreverdb_dump.dump_list(client, "vendors", tmp_path)
    foreverdb_dump.dump_item_details(client, foreverdb_dump.vendor_ids(tmp_path), tmp_path, kind="vendors")
    assert names_in(tmp_path / "items.jsonl")[0] == "Item 1 v1"

    # Ein neuer Build. Das Kontingent reisst mitten in den Sortimenten ab.
    new = FakeWorld("v2")
    new.fail_vendor = 3
    result = foreverdb_dump.refresh(make_client(new), tmp_path)

    assert result["complete"] is False
    assert "Tageskontingent" in result["stopped"]
    # Die bisherigen Dateien sind unberuehrt und vollstaendig.
    assert names_in(tmp_path / "items.jsonl")[0] == "Item 1 v1"
    assert len(names_in(tmp_path / "items.jsonl")) == 150
    assert names_in(tmp_path / foreverdb_dump.VENDOR_DETAILS_FILE) == ["Vendor 1 v1", "Vendor 2 v1", "Vendor 3 v1"]
    assert (tmp_path / foreverdb_dump.REFRESH_DIR / "items.jsonl").is_file()

    # Am naechsten Tag: nur der fehlende Haendler wird noch geholt, dann wird getauscht.
    new.fail_vendor = None
    new.calls.clear()
    result = foreverdb_dump.refresh(make_client(new), tmp_path)

    assert result["complete"] is True
    assert [c["url"].rsplit("/", 1)[1] for c in new.calls] == ["3"]
    assert names_in(tmp_path / "items.jsonl")[0] == "Item 1 v2"
    assert names_in(tmp_path / foreverdb_dump.VENDOR_DETAILS_FILE) == ["Vendor 1 v2", "Vendor 2 v2", "Vendor 3 v2"]
    # Die Spell-Liste kommt mit: an ihr haengen die Abklingzeiten der Rezepte.
    assert names_in(tmp_path / "spells.jsonl") == ["Transmute v2"]
    assert not (tmp_path / foreverdb_dump.REFRESH_DIR).exists()
    # Die Listen gelten als fertig: ein normaler Abzug holt nichts erneut.
    new.calls.clear()
    assert foreverdb_dump.dump_list(make_client(new), "items", tmp_path)["done"] and new.calls == []


def test_refresh_does_not_touch_the_item_details(tmp_path: Path) -> None:
    world = FakeWorld("v1")
    (tmp_path / foreverdb_dump.DETAILS_FILE).write_text('{"id":7,"name":"kept"}\n', encoding="utf-8")

    result = foreverdb_dump.refresh(make_client(world), tmp_path)

    assert result["complete"] is True
    assert foreverdb_dump.details_done(tmp_path, "items") == {7}
    # zwei Seiten Items, eine Seite Haendler, eine Seite Spells, drei Sortimente
    assert result["requests"] == 2 + 1 + 1 + 3


class FakeProfessions(FakeCatalog):
    """Zwei Berufe: Alchemie mit 150 Rezepten auf zwei Seiten, Kochen mit zweien."""

    COUNTS = {"alchemy": 150, "cooking": 2}

    def __init__(self) -> None:
        super().__init__()
        self.fail_slug: str | None = None

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        if url.endswith("/professions"):
            rows = [{"slug": slug, "name": slug.title(), "recipeCount": count} for slug, count in self.COUNTS.items()]
            return FakeResponse(200, {"data": rows, "meta": {"total": len(rows)}})
        slug = url.rsplit("/", 1)[1]
        if slug == self.fail_slug:
            return FakeResponse(402)
        total = self.COUNTS[slug]
        offset = int((params or {}).get("offset", 0))
        limit = int((params or {}).get("limit", 25))
        recipes = [
            {"spellId": 1000 * len(slug) + i, "name": f"{slug} {i}", "reagents": [{"itemId": i, "count": 1}]}
            for i in range(offset + 1, min(offset + limit, total) + 1)
        ]
        data = {"slug": slug, "name": slug.title(), "ranks": [{"rank": "Apprentice", "maxSkill": 75}], "recipes": recipes}
        return FakeResponse(200, {"data": data, "meta": {"total": total, "limit": limit, "offset": offset}})


def test_recipes_are_paged_per_profession_and_tagged_with_it(tmp_path: Path) -> None:
    session = FakeProfessions()

    result = foreverdb_dump.dump_recipes(make_client(session), tmp_path)

    assert result["complete"] is True
    assert (result["professions"], result["recipes"]) == (2, 152)
    assert result["requests"] == 1 + 2 + 1        # die Uebersicht, zwei Seiten Alchemie, eine Seite Kochen
    assert [c["params"].get("offset") for c in session.calls] == [None, 0, 100, 0]

    recipes = [json.loads(line) for line in (tmp_path / foreverdb_dump.RECIPES_FILE).read_text(encoding="utf-8").splitlines()]
    assert len(recipes) == 152
    assert {r["profession"] for r in recipes} == {"alchemy", "cooking"}
    assert recipes[-1]["professionName"] == "Cooking" and recipes[-1]["reagents"] == [{"itemId": 2, "count": 1}]

    # Der Beruf steht einmal da, mit seinen Raengen, aber ohne die Rezepte.
    professions = [json.loads(line) for line in (tmp_path / foreverdb_dump.PROFESSIONS_FILE).read_text(encoding="utf-8").splitlines()]
    assert [p["slug"] for p in professions] == ["alchemy", "cooking"]
    assert professions[0]["ranks"][0]["maxSkill"] == 75 and "recipes" not in professions[0]


def test_recipes_are_only_written_when_complete(tmp_path: Path) -> None:
    (tmp_path / foreverdb_dump.RECIPES_FILE).write_text('{"spellId":1,"name":"kept"}\n', encoding="utf-8")
    session = FakeProfessions()
    session.fail_slug = "cooking"

    result = foreverdb_dump.dump_recipes(make_client(session), tmp_path)

    assert result["complete"] is False
    assert "Tageskontingent" in result["stopped"]
    # Der bisherige Abzug ist unberuehrt, und es liegt keine halbe Datei daneben.
    assert names_in(tmp_path / foreverdb_dump.RECIPES_FILE) == ["kept"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [foreverdb_dump.RECIPES_FILE]

    # Auch eine Grenze fuer den Lauf bricht ab, ohne etwas zu schreiben.
    result = foreverdb_dump.dump_recipes(make_client(FakeProfessions()), tmp_path, max_requests=2)
    assert result["complete"] is False and result["requests"] == 2
    assert names_in(tmp_path / foreverdb_dump.RECIPES_FILE) == ["kept"]
