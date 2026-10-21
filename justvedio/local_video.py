import html
import mimetypes
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class LocalVideoServer:
    """Serve one selected file on loopback; no filesystem browsing or identity data."""
    def __init__(self, filename):
        self.path = Path(filename).resolve(strict=True)
        self.token = secrets.token_urlsafe(24)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.serve(False)
            def do_HEAD(self):
                self.serve(True)
            def serve(self, head):
                route = self.path.split('?', 1)[0]
                if route == f"/{owner.token}/player":
                    title = html.escape(owner.path.name)
                    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>本地视频观看测试</title>
                    <style>body{{background:#102033;color:#eaf0f7;font:18px sans-serif;margin:32px}}video{{width:min(100%,960px);display:block;margin:20px 0}}button{{padding:12px 30px;background:#71e2b4;border:0;border-radius:6px}}#completed{{color:#71e2b4}}</style>
                    <h1>本地视频观看测试</h1><p>{title}</p><video controls preload="auto" src="/{owner.token}/media"></video><button id="play">播放视频</button><p id="completed" hidden>视频播放完成</p>
                    <script>const v=document.querySelector('video');document.querySelector('#play').onclick=()=>v.play();v.onended=()=>document.querySelector('#completed').hidden=false;</script></html>'''.encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    if not head:
                        self.wfile.write(body)
                elif route == f"/{owner.token}/media":
                    size = owner.path.stat().st_size
                    start, end, partial = 0, size - 1, False
                    range_header = self.headers.get('Range')
                    if range_header:
                        try:
                            unit, span = range_header.split('=', 1)
                            a, b = span.split('-', 1)
                            if unit != 'bytes' or ',' in span:
                                raise ValueError
                            start = int(a) if a else max(0, size - int(b))
                            end = min(int(b), size - 1) if a and b else size - 1
                            if start < 0 or start > end or start >= size:
                                raise ValueError
                            partial = True
                        except ValueError:
                            self.send_response(416)
                            self.send_header('Content-Range', f'bytes */{size}')
                            self.end_headers()
                            return
                    self.send_response(206 if partial else 200)
                    self.send_header('Content-Type', mimetypes.guess_type(str(owner.path))[0] or 'application/octet-stream')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Length', str(max(0, end - start + 1)))
                    if partial:
                        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.end_headers()
                    if not head:
                        try:
                            with owner.path.open('rb') as stream:
                                stream.seek(start)
                                remaining = end - start + 1
                                while remaining > 0:
                                    block = stream.read(min(65536, remaining))
                                    if not block:
                                        break
                                    self.wfile.write(block)
                                    remaining -= len(block)
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                            pass
                else:
                    self.send_error(404)
            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/{self.token}/player"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
