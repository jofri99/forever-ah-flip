"""Client fuer die API von ForeverDB (https://foreverdb.net/developers).

Drei Regeln des Anbieters praegen diesen Client:

- Der Schluessel gehoert in den Kopf der Anfrage und nie in ausgelieferten Code.
- Im kostenlosen Tarif sind 30 Anfragen je Minute und 5.000 am Tag erlaubt.
  Der Client bremst selbst, statt sich bremsen zu lassen.
- Ein persoenlicher oder Plugin-Schluessel darf nicht auf einer Website benutzt
  werden. Dieser Client laeuft nur lokal oder in einem Skript.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import requests

from .blizzard import ApiResponse
from .config import USER_AGENT

BASE_URL = "https://foreverdb.net/api/v1"

# 30 je Minute waeren 2,0 s Abstand. Etwas mehr Luft, damit ein zweites Werkzeug
# mit demselben Schluessel nicht gleich ans Limit stoesst.
MIN_INTERVAL = 2.2

log = logging.getLogger(__name__)


class ForeverDBError(RuntimeError):
    """Antwort der API war nicht brauchbar."""


class ForeverDBAuthError(ForeverDBError):
    """Der Schluessel fehlt oder wird nicht akzeptiert."""


class ForeverDBQuotaError(ForeverDBError):
    """Das Kontingent ist aufgebraucht - heute geht nichts mehr."""


class ForeverDBClient:
    def __init__(
        self,
        key: str,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_INTERVAL,
    ) -> None:
        if not key:
            raise ForeverDBAuthError(
                "FOREVERDB_API_KEY fehlt. In die .env eintragen - siehe .env.example."
            )
        self.session = session or requests.Session()
        # Laut Anbieter soll ein Skript sagen, wer es ist.
        self.session.headers.update({"X-API-Key": key, "User-Agent": USER_AGENT})
        self._sleep = sleep
        self._now = now
        self._min_interval = min_interval
        self._last_request: float | None = None
        self.requests_made = 0

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self._min_interval - (self._now() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._now()

    def get(self, path: str, params: dict[str, Any] | None = None, retries: int = 3) -> ApiResponse:
        """Ein GET. 404 kommt zurueck, Sperren und Kontingent werden geworfen."""
        url = f"{BASE_URL}{path}"
        attempt = 0
        while True:
            attempt += 1
            self._throttle()
            started = time.perf_counter()
            response = self.session.get(url, params=params, timeout=60)
            self.requests_made += 1
            status = response.status_code

            if status in (401, 403):
                raise ForeverDBAuthError(
                    f"ForeverDB lehnt den Schluessel ab ({status}). "
                    "Ist er richtig eingetragen und fuer diesen Zweck freigegeben?"
                )
            if status == 402:
                raise ForeverDBQuotaError("Das Tageskontingent bei ForeverDB ist aufgebraucht.")
            if status == 429:
                if attempt > retries:
                    raise ForeverDBQuotaError("ForeverDB bremst auch nach mehreren Versuchen (429).")
                delay = _retry_after(response)
                log.warning("429 von ForeverDB, neuer Versuch in %.0fs", delay)
                self._sleep(delay)
                continue
            if status >= 500 and attempt <= retries:
                self._sleep(min(2.0 ** attempt, 30.0))
                continue

            data: Any = None
            if 200 <= status < 300:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise ForeverDBError(f"Antwort von {path} ist kein JSON: {exc}") from exc
            return ApiResponse(
                status=status,
                url=url,
                headers=dict(response.headers),
                elapsed=time.perf_counter() - started,
                size=len(response.content),
                data=data,
            )

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ForeverDBClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _retry_after(response: requests.Response) -> float:
    value = response.headers.get("Retry-After")
    try:
        return min(float(value), 120.0) if value else 10.0
    except ValueError:
        return 10.0
