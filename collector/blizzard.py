"""Kleiner Client fuer die Battle.net Game-Data-API, zugeschnitten auf Forever.

Besonderheit der API: ohne gueltigen Token antwortet sie auf *jeden* Pfad mit 404,
auch auf solche, die es sicher gibt. Ein 404 sagt also nur dann etwas ueber den
Endpunkt aus, wenn der Token steht.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from .config import USER_AGENT, Settings

TOKEN_URL = "https://oauth.battle.net/token"
TOKEN_SAFETY_MARGIN = 60.0          # Sekunden vor Ablauf schon erneuern
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
CHUNK = 1 << 16

log = logging.getLogger(__name__)


class BlizzardError(RuntimeError):
    """Antwort der API war nicht brauchbar."""


class AuthError(BlizzardError):
    """Client-ID oder Secret werden nicht akzeptiert."""


@dataclass
class ApiResponse:
    status: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    elapsed: float = 0.0
    size: int = 0
    data: Any = None
    path: Path | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("Last-Modified")


class BlizzardClient:
    """Holt sich selbst einen Token und wiederholt Anfragen bei 429 und 5xx."""

    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._sleep = sleep
        self._now = now
        self._token: str | None = None
        self._token_expires_at = 0.0

    # -- Token ----------------------------------------------------------

    def token(self, force: bool = False) -> str:
        if not force and self._token and self._now() < self._token_expires_at:
            return self._token

        self.settings.require_credentials()
        response = self.session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self.settings.client_id, self.settings.client_secret),
            timeout=30,
        )
        if response.status_code in (400, 401, 403):
            raise AuthError(
                f"Token abgelehnt ({response.status_code}). "
                "Stimmen BLIZZARD_CLIENT_ID und BLIZZARD_CLIENT_SECRET?"
            )
        if response.status_code != 200:
            raise BlizzardError(f"Token-Endpunkt antwortete mit {response.status_code}")

        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = self._now() + float(payload.get("expires_in", 3600)) - TOKEN_SAFETY_MARGIN
        log.debug("Token geholt, gueltig fuer %ss", payload.get("expires_in"))
        return self._token

    # -- Anfragen -------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        namespace: str = "dynamic",
        params: dict[str, Any] | None = None,
        stream_to: Path | None = None,
        retries: int = 3,
        timeout: float = 120.0,
    ) -> ApiResponse:
        """Ein GET gegen die API. 404 wird zurueckgegeben, nicht geworfen."""
        url = f"{self.settings.api_host}{path}"
        query = {
            "namespace": self.settings.namespace(namespace),
            "locale": self.settings.locale,
        }
        if params:
            query.update(params)

        attempt = 0
        refreshed = False
        while True:
            attempt += 1
            headers = {"Authorization": f"Bearer {self.token()}"}
            started = time.perf_counter()
            response = self.session.get(
                url, params=query, headers=headers, timeout=timeout, stream=stream_to is not None
            )
            status = response.status_code

            if status == 401 and not refreshed:
                refreshed = True
                self.token(force=True)
                response.close()
                continue

            if status in RETRY_STATUS and attempt <= retries:
                delay = self._retry_delay(response, attempt)
                log.warning("%s auf %s, neuer Versuch in %.1fs", status, path, delay)
                response.close()
                self._sleep(delay)
                continue

            elapsed = time.perf_counter() - started
            headers_out = dict(response.headers)

            if not 200 <= status < 300:
                body = response.text[:200] if not stream_to else ""
                response.close()
                return ApiResponse(status=status, url=url, headers=headers_out, elapsed=elapsed, data=body)

            if stream_to is not None:
                stream_to.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with open(stream_to, "wb") as handle:
                    for chunk in response.iter_content(CHUNK):
                        handle.write(chunk)
                        size += len(chunk)
                response.close()
                return ApiResponse(
                    status=status, url=url, headers=headers_out,
                    elapsed=time.perf_counter() - started, size=size, path=stream_to,
                )

            raw = response.content
            response.close()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise BlizzardError(f"Antwort von {path} ist kein JSON: {exc}") from exc
            return ApiResponse(
                status=status, url=url, headers=headers_out, elapsed=elapsed, size=len(raw), data=data
            )

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), 60.0)
            except ValueError:
                pass
        return min(2.0 ** attempt, 30.0)

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "BlizzardClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Forever-Endpunkte ----------------------------------------------
    # Pfade sind von der Community kartiert, nicht von Blizzard dokumentiert.

    def ruleset_index(self) -> ApiResponse:
        return self.get("/data/wow/ruleset/index")

    def ruleset(self, ruleset_id: int) -> ApiResponse:
        return self.get(f"/data/wow/ruleset/{ruleset_id}")

    def auction_houses(self, ruleset_id: int) -> ApiResponse:
        # Der Schraegstrich am Ende ist noetig, ohne ihn kommt 404.
        return self.get(f"/data/wow/ruleset/{ruleset_id}/auctions/")

    def auctions(self, ruleset_id: int, house_id: int, stream_to: Path | None = None) -> ApiResponse:
        return self.get(f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}", stream_to=stream_to)

    def commodities(self, ruleset_id: int, house_id: int, stream_to: Path | None = None) -> ApiResponse:
        return self.get(
            f"/data/wow/ruleset/{ruleset_id}/auctions/{house_id}/commodities", stream_to=stream_to
        )
