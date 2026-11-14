"""Tests fuer den API-Client - ohne Netz, mit einer gefaelschten Session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from collector.blizzard import AuthError, BlizzardClient
from collector.config import Settings

CONFIG = Settings.from_env({"BLIZZARD_CLIENT_ID": "id", "BLIZZARD_CLIENT_SECRET": "secret"})


class FakeResponse:
    def __init__(self, status: int, payload: object = None, headers: dict | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self.closed = False

    @property
    def content(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    @property
    def text(self) -> str:
        return json.dumps(self._payload)

    def json(self) -> object:
        return self._payload

    def iter_content(self, chunk_size: int = 0):
        yield self.content

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Gibt der Reihe nach vorbereitete Antworten zurueck und merkt sich die Aufrufe."""

    def __init__(self, token_responses: list[FakeResponse], get_responses: list[FakeResponse]) -> None:
        self.headers: dict[str, str] = {}
        self._token_responses = list(token_responses)
        self._get_responses = list(get_responses)
        self.token_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url, data=None, auth=None, timeout=None):
        self.token_calls.append({"url": url, "data": data, "auth": auth})
        return self._token_responses.pop(0)

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.get_calls.append({"url": url, "params": params, "headers": headers, "stream": stream})
        return self._get_responses.pop(0)

    def close(self) -> None:
        pass


def token_ok(value: str = "token-1", expires_in: int = 3600) -> FakeResponse:
    return FakeResponse(200, {"access_token": value, "expires_in": expires_in})


def make_client(session: FakeSession, delays: list[float] | None = None) -> BlizzardClient:
    recorded = delays if delays is not None else []
    return BlizzardClient(CONFIG, session=session, sleep=recorded.append)


def test_token_is_requested_once_and_reused() -> None:
    session = FakeSession([token_ok()], [FakeResponse(200, {"rulesets": []}) for _ in range(2)])
    client = make_client(session)

    client.ruleset_index()
    client.ruleset_index()

    assert len(session.token_calls) == 1
    assert session.token_calls[0]["auth"] == ("id", "secret")
    assert session.token_calls[0]["data"] == {"grant_type": "client_credentials"}


def test_request_carries_namespace_and_locale() -> None:
    session = FakeSession([token_ok()], [FakeResponse(200, {"rulesets": [{"id": 2}]})])
    client = make_client(session)

    response = client.ruleset_index()

    call = session.get_calls[0]
    assert call["url"] == "https://eu.api.blizzard.com/data/wow/ruleset/index"
    assert call["params"]["namespace"] == "dynamic-forever-eu"
    assert call["params"]["locale"] == "de_DE"
    assert call["headers"]["Authorization"] == "Bearer token-1"
    assert response.ok and response.data == {"rulesets": [{"id": 2}]}


def test_auction_house_index_keeps_trailing_slash() -> None:
    session = FakeSession([token_ok()], [FakeResponse(200, {"auctions": []})])
    client = make_client(session)

    client.auction_houses(2)

    assert session.get_calls[0]["url"].endswith("/data/wow/ruleset/2/auctions/")


def test_expired_token_is_refreshed_once() -> None:
    session = FakeSession(
        [token_ok("alt"), token_ok("neu")],
        [FakeResponse(401), FakeResponse(200, {"id": 2})],
    )
    client = make_client(session)

    response = client.ruleset(2)

    assert response.ok
    assert len(session.token_calls) == 2
    assert session.get_calls[1]["headers"]["Authorization"] == "Bearer neu"


def test_retries_on_429_and_honours_retry_after() -> None:
    delays: list[float] = []
    session = FakeSession(
        [token_ok()],
        [FakeResponse(429, headers={"Retry-After": "3"}), FakeResponse(200, {"id": 2})],
    )
    client = make_client(session, delays)

    response = client.ruleset(2)

    assert response.ok
    assert delays == [3.0]


def test_gives_up_after_retries() -> None:
    delays: list[float] = []
    session = FakeSession([token_ok()], [FakeResponse(503) for _ in range(5)])
    client = make_client(session, delays)

    response = client.get("/data/wow/ruleset/index", retries=2)

    assert response.status == 503
    assert len(delays) == 2


def test_404_is_returned_not_raised() -> None:
    session = FakeSession([token_ok()], [FakeResponse(404, {"detail": "Not Found"})])
    client = make_client(session)

    response = client.auctions(2, 999)

    assert response.status == 404
    assert not response.ok


def test_bad_credentials_raise_auth_error() -> None:
    session = FakeSession([FakeResponse(401, {"error": "invalid_client"})], [])
    client = make_client(session)

    with pytest.raises(AuthError, match="BLIZZARD_CLIENT_ID"):
        client.token()


def test_stream_writes_file_and_reports_size(tmp_path: Path) -> None:
    payload = {"auctions": [{"id": 1, "item": {"id": 2589}, "buyout": 400, "quantity": 20}]}
    session = FakeSession([token_ok()], [FakeResponse(200, payload, {"Last-Modified": "Fri, 14 Nov 2026 18:00:00 GMT"})])
    client = make_client(session)
    destination = tmp_path / "haus" / "110.json"

    response = client.auctions(2, 110, stream_to=destination)

    assert response.ok
    assert response.path == destination
    assert response.size == len(json.dumps(payload).encode("utf-8"))
    assert response.last_modified == "Fri, 14 Nov 2026 18:00:00 GMT"
    assert json.loads(destination.read_text(encoding="utf-8")) == payload
    assert session.get_calls[0]["stream"] is True
