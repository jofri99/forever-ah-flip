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
    assert foreverdb_dump.vendor_ids(settings) == [2, 3, 1]

    session.calls.clear()
    result = foreverdb_dump.dump_item_details(
        client, foreverdb_dump.vendor_ids(settings), directory, kind="vendors"
    )
    assert [c["url"].rsplit("/", 2)[-2:] for c in session.calls] == [["vendors", "2"], ["vendors", "3"], ["vendors", "1"]]
    assert result["fetched"] == 3
    assert foreverdb_dump.details_done(directory, "vendors") == {1, 2, 3}
    # Die Details der Haendler liegen getrennt von denen der Items.
    assert foreverdb_dump.details_done(directory, "items") == set()
    assert (directory / foreverdb_dump.VENDOR_DETAILS_FILE).is_file()
