"""Kleiner lokaler Server fuer die Seite in site/.

Der Server aus Pythons Standardbibliothek kann keine Teilabrufe (HTTP Range).
Genau die braucht die Seite aber, um aus hourly.parquet nur die Zeilengruppe
eines Items zu holen - auf GitHub Pages geht das von Haus aus, lokal nur hiermit.

    python tools/serve.py            # http://127.0.0.1:8777
    python tools/serve.py --port 9000
"""

from __future__ import annotations

import argparse
import os
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    """Wie der Standard-Handler, aber mit Unterstuetzung fuer einen einzelnen Byte-Bereich."""

    def send_head(self):  # noqa: D401 - Signatur der Basisklasse
        header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not header or os.path.isdir(path) or not os.path.isfile(path):
            return super().send_head()

        match = RANGE.match(header.strip())
        size = os.path.getsize(path)
        if not match or (match.group(1) == "" and match.group(2) == ""):
            return super().send_head()

        if match.group(1) == "":                      # bytes=-500: die letzten 500 Bytes
            length = min(int(match.group(2)), size)
            start, end = size - length, size - 1
        else:
            start = int(match.group(1))
            end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1

        if start >= size or start > end:
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        handle = open(path, "rb")
        handle.seek(start)
        self._remaining = end - start + 1

        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._remaining))
        self.end_headers()
        return handle

    def copyfile(self, source, outputfile):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        while remaining > 0:
            chunk = source.read(min(65536, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)
        self._remaining = None

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        # Beim Entwickeln soll immer der frische Stand ankommen.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Lokaler Server fuer site/ mit Teilabrufen.")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--dir", type=Path, default=ROOT / "site")
    args = parser.parse_args()

    handler = partial(RangeHandler, directory=str(args.dir))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"{args.dir} auf http://127.0.0.1:{args.port} - Strg+C beendet", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
