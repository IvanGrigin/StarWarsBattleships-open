#!/usr/bin/env python3
"""Статический сервер демо без кэширования (Cache-Control: no-store),
чтобы браузер всегда брал свежие файлы. Плюс POST /api/mesh-index — запись
demo/assets/models/meshes/index.json (инспектор ориентации schem_test.html)."""
import http.server
import json
import os
import socketserver
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8901
DIRECTORY = "demo"

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_POST(self):
        if self.path != "/api/mesh-index":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            assert isinstance(data, dict)
        except Exception:
            self.send_error(400, "bad json")
            return
        target = os.path.join(DIRECTORY, "assets/models/meshes/index.json")
        with open(target, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print(f"serving demo on {PORT}, no-store")
    httpd.serve_forever()
