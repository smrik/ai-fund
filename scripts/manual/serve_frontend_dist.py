from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


class SpaRequestHandler(SimpleHTTPRequestHandler):
    """Serve a built SPA and fall back to index.html for client routes."""

    def __init__(self, *args, directory: str, api_base_url: str, **kwargs):
        self._spa_root = Path(directory).resolve()
        self._api_base_url = api_base_url.rstrip("/")
        super().__init__(*args, directory=directory, **kwargs)

    def _proxy_api_request(self) -> bool:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api"):
            return False

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else None
        proxy_url = urljoin(f"{self._api_base_url}/", parsed.path.lstrip("/"))
        if parsed.query:
            proxy_url = f"{proxy_url}?{parsed.query}"

        upstream_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        request = Request(proxy_url, data=body, headers=upstream_headers, method=self.command)

        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() in {"transfer-encoding", "connection", "server", "date"}:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                self._write_payload(payload)
                return True
        except HTTPError as error:
            payload = error.read()
            self.send_response(error.code)
            for key, value in error.headers.items():
                if key.lower() in {"transfer-encoding", "connection", "server", "date"}:
                    continue
                self.send_header(key, value)
            self.end_headers()
            self._write_payload(payload)
            return True
        except URLError as error:
            message = f"API proxy error: {error.reason}\n".encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self._write_payload(message)
            return True

    def _write_payload(self, payload: bytes) -> None:
        if self.command == "HEAD" or not payload:
            return
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _serve_spa(self, head_only: bool) -> None:
        parsed = urlparse(self.path)
        requested = parsed.path.lstrip("/")
        candidate = (self._spa_root / requested).resolve() if requested else self._spa_root / "index.html"

        try:
            candidate.relative_to(self._spa_root)
        except ValueError:
            self.send_error(404)
            return

        if requested and candidate.exists() and candidate.is_file():
            if head_only:
                return super().do_HEAD()
            return super().do_GET()

        original_path = self.path
        self.path = "/index.html"
        try:
            if head_only:
                return super().do_HEAD()
            return super().do_GET()
        finally:
            self.path = original_path

    def do_GET(self) -> None:  # noqa: N802 - inherited API
        if self._proxy_api_request():
            return
        self._serve_spa(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802 - inherited API
        if self._proxy_api_request():
            return
        self._serve_spa(head_only=True)

    def do_POST(self) -> None:  # noqa: N802 - inherited API
        if self._proxy_api_request():
            return
        self.send_error(405)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve frontend dist with SPA fallback")
    parser.add_argument("--root", required=True, help="Built frontend directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000", help="Base URL for proxied /api requests")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"Missing frontend dist directory: {root}")

    handler = partial(SpaRequestHandler, directory=str(root), api_base_url=args.api_base_url)
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
