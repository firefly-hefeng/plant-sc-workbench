"""Serve the bundled, read-only demonstration. Python standard library only."""
import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "share" / "demo"
WEB = ROOT / "web"


def route_key(path, query):
    return path + "?" + urlencode(sorted((k, v) for k, v in query.items() if v and not (k == "scope" and v == "project")))


class PublicDemo(BaseHTTPRequestHandler):
    def __init__(self, *args, catalog, assets, **kwargs):
        self.catalog, self.assets = catalog, assets
        super().__init__(*args, **kwargs)

    def reply(self, status, data, mime, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (ConnectionError, BrokenPipeError):
                pass

    def json(self, status, value):
        self.reply(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        uri = urlsplit(self.path)
        path, params = unquote(uri.path), dict(parse_qsl(uri.query))
        if path == "/" and not params:
            return self.reply(302, b"", "text/plain", {"Location":self.catalog["start"]})
        if path in {"/", "/panes", "/plots", "/jobs", "/files"}:
            path = "/index.html"
        if path in self.assets:
            return self.deliver(self.assets[path])
        if path == "/api/file" or path == "/api/native-preview":
            if params.get("scope", "project") != "project":
                return self.missing()
            published = "/published/" + params.get("project", "") + "/" + params.get("path", "")
            if published not in self.files:
                return self.missing()
            if path == "/api/native-preview":
                return self.json(200, {"url":quote(published, safe="/")})
            return self.deliver(self.files[published], params.get("download") == "1", published=True)
        if path in self.files:
            return self.deliver(self.files[path], published=True)
        key = route_key(path, params)
        if key in self.catalog["routes"]:
            return self.json(200, self.catalog["routes"][key])
        return self.missing()

    def missing(self):
        self.json(404, {"error":"当前演示中没有这项文件或记录。"})

    @property
    def files(self):
        return self.server.published

    def deliver(self, file, download=False, published=False):
        mime = {".js":"text/javascript", ".svg":"image/svg+xml", ".md":"text/plain"}.get(
            file.suffix, mimetypes.guess_type(file.name)[0] or "application/octet-stream")
        headers = {}
        if published and file.suffix == ".html":
            # Only reviewed, immutable example reports are present on this origin.
            headers["Content-Security-Policy"] = ("default-src 'none'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src data: 'self'; "
                "connect-src 'self' blob: data:; worker-src blob:; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")
        if download:
            headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(file.name)
        if mime.startswith("text/"):
            mime += "; charset=utf-8"
        self.reply(200, file.read_bytes(), mime, headers)

    do_HEAD = do_GET

    def do_POST(self):
        self.reply(405, '{"error":"共享演示仅供浏览。运行分析请使用本地工作台。"}'.encode(),
                   "application/json; charset=utf-8", {"Allow":"GET, HEAD"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18976)
    args = parser.parse_args()
    catalog = json.loads((DEMO / "catalog.json").read_text(encoding="utf-8"))
    assets = {"/" + p.relative_to(WEB).as_posix(): p for p in WEB.rglob("*")
              if p.is_file() and p.suffix in {".css", ".js", ".html"} and p.resolve().is_relative_to(WEB)}
    handler = partial(PublicDemo, catalog=catalog, assets=assets)
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        server.published = {}
        for rel in catalog["files"]:
            source = (DEMO / "files" / rel).resolve()
            if not source.is_relative_to(DEMO / "files") or not source.is_file():
                raise ValueError("Invalid demonstration file: " + rel)
            server.published["/published/" + rel] = source
        print(f"Read-only frontend on http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

