"""Serve report documents and their local assets on a separate, read-only loopback origin."""
from collections import OrderedDict
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import secrets
import shutil
from threading import Lock, Thread
from urllib.parse import quote, unquote, urlsplit

DOCUMENTS = {".html", ".htm", ".pdf"}
ASSETS = DOCUMENTS | set(".css .js .mjs .png .jpg .jpeg .gif .webp .svg .bmp .ico .woff .woff2 .ttf .otf .json .csv .tsv .txt .map".split())


# FastQC's fixed 18-em sidebar leaves nearly no content area in a split pane.
FASTQC_STYLE = b"""<style>@media screen and (max-width:760px){
body{overflow-x:hidden}div.header,div.summary,div.main,div.footer{position:static;width:auto;height:auto;box-sizing:border-box}
div.header{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:17px;padding:6px}
#header_title,#header_filename{float:none;margin:0;overflow-wrap:anywhere}#header_title img{width:24px;height:auto}
div.summary{margin:0;padding:3px 8px;background:#fafafa}div.summary h2{display:none}div.summary ul{display:flex;gap:10px;overflow-x:auto;margin:0;padding:5px 0}
div.summary li{white-space:nowrap;font-size:12px}div.summary li img{width:14px;margin:0 3px 0 0;vertical-align:middle}
div.main{padding:0 10px;border:0;overflow:visible}div.module{padding:5px 0 12px;overflow-x:auto}
div.module h2{font-size:18px}div.module h2 img{width:20px}div.module table{margin:8px 0;font-size:12px}
div.module img.indented{max-width:100%;height:auto;margin:0}div.footer{font-size:12px}
}</style>"""


class ReportServer(ThreadingHTTPServer):
    def __init__(self, app_port):
        super().__init__(("127.0.0.1", 0), ReportHandler)
        self.app_port = app_port
        self.directories = OrderedDict()
        self.lock = Lock()

    def document(self, path):
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() not in DOCUMENTS:
            raise ValueError("请选择 HTML 报告或 PDF 文档。")
        with self.lock:
            token = next((k for k, folder in self.directories.items() if folder == path.parent), None)
            if token:
                self.directories.move_to_end(token)
            else:
                token = secrets.token_urlsafe(24)
                self.directories[token] = path.parent
                if len(self.directories) > 512:
                    self.directories.popitem(last=False)
        return {"url": f"http://127.0.0.1:{self.server_port}/r/{token}/{quote(path.name)}"}

    def resolve_asset(self, url):
        prefix, token, *parts = unquote(urlsplit(url).path).lstrip("/").split("/")
        with self.lock:
            root = self.directories.get(token)
        if prefix != "r" or not root or not parts or any(
            not s or s.startswith(".") or any(c in s for c in "\\:\0") for s in parts
        ):
            raise ValueError
        path = root.joinpath(*parts).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in ASSETS or not path.is_file():
            raise FileNotFoundError
        return path


class ReportHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        server = self.server
        if self.headers.get("Host") != f"127.0.0.1:{server.server_port}":
            return self.send_error(403)
        try:
            path = server.resolve_asset(self.path)
            stream = path.open("rb")
        except (ValueError, OSError):
            return self.send_error(404)
        with stream:
            mime = {".js": "text/javascript", ".mjs": "text/javascript", ".svg": "image/svg+xml"}.get(
                path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            head = b""
            extra = 0
            if path.name.lower().endswith("_fastqc.html"):
                head = stream.read(16384)
                if b"</head>" in head and b"FastQC Report" in head:
                    if b"charset=" not in head.lower():
                        try:
                            head.decode("utf-8")
                            mime += "; charset=utf-8"
                        except UnicodeDecodeError:
                            mime += "; charset=gb18030"
                    head = head.replace(b"</head>", FASTQC_STYLE + b"</head>", 1)
                    extra = len(FASTQC_STYLE)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(path.stat().st_size + extra))
            ancestors = f"frame-ancestors http://127.0.0.1:{server.app_port} http://localhost:{server.app_port}"
            policy = ("sandbox allow-scripts allow-same-origin allow-downloads; default-src 'none'; "
                      "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                      "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' data: blob:; "
                      "worker-src blob:; form-action 'none'; base-uri 'self'; ")
            self.send_header("Content-Security-Policy", ("" if mime == "application/pdf" else policy) + ancestors)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            try:
                if head:
                    self.wfile.write(head)
                shutil.copyfileobj(stream, self.wfile, 128 * 1024)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def log_message(self, *_):
        pass


@contextmanager
def report_service(app_port):
    with ReportServer(app_port) as reports:
        thread = Thread(target=reports.serve_forever, daemon=True)
        thread.start()
        try:
            yield reports
        finally:
            reports.shutdown()
            thread.join()

