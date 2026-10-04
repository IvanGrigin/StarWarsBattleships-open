#!/usr/bin/env python3
"""Сервер страницы ориентации моделей (tools/model_preview/index.html).

Зачем свой сервер, а не `python3 -m http.server`:
  * GET  /api/models  — список ВСЕХ скачанных моделей на диске (.glb/.gltf/
    .stl/.obj в raw_candidates, кроме backup_*), а не только прописанных
    в странице руками и в liked/manifest.json;
  * GET  /api/reviews — оценки и повороты из tools/model_preview/model_reviews.json;
  * POST /api/reviews — {"changes": {key: отзыв | null}}: сохранить изменённые
    записи в тот же файл. Так поворот, сделанный с планшета, сразу лежит на
    Маке и попадает в git, а не остаётся в памяти браузера.

Раздаются только два каталога: tools/model_preview/ и
assets_source/external_models/ — остальной репозиторий в сеть не отдаётся.

Запуск:  python3 tools/model_preview/serve.py [порт]      (по умолчанию 8765)
Страница: http://<адрес-мака>:8765/tools/model_preview/index.html
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
STORE = Path(__file__).resolve().parent / "model_reviews.json"
SEED = RAW / "model_reviews.json"          # старая выгрузка из браузера
NUMBERS = Path(__file__).resolve().parent / "model_numbers.json"
ALLOWED = ("/tools/model_preview/", "/assets_source/external_models/",
           "/demo/assets/v4_art/",           # эталонные картинки кораблей для турнира
           "/demo/assets/card_art/",         # картинки карточек (fetch_card_art.py)
           "/docs/rulebook/",                # рулбук и полное издание с картинками
           "/demo/")                         # воксельные модели и их построитель (вкладка «Воксельные»)
VOXELS = ROOT / "demo" / "assets" / "models" / "meshes"


def list_voxels():
    """Воксельные модели demo/assets/models/meshes/*.json и их настройки из index.json."""
    try:
        cfg = json.loads((VOXELS / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    by_file = {v.get("file"): k for k, v in cfg.items() if isinstance(v, dict)}
    out = []
    for f in sorted(VOXELS.glob("*.json")):
        if f.name == "index.json":
            continue
        tid = by_file.get(f.name)
        out.append({"file": f.name, "bytes": f.stat().st_size, "type_id": tid,
                    "cfg": cfg.get(tid, {}) if tid else {}, "mtime": f.stat().st_mtime})
    return out
HERE = Path(__file__).resolve().parent
V4_SHIPS = ROOT / "data" / "rulesets" / "v4" / "ships"
V4_ART = ROOT / "demo" / "assets" / "v4_art"
# Документы, которые страница читает и правит целиком по ключам:
#   classes    — тип корабля ростера для каждой модели (classify_models.py + ручные правки);
#   tournament — выборы в турнире на выбывание и победитель по каждому типу.
DOCS = {
    "classes": (HERE / "ship_classes.json", "classes"),
    "tournament": (HERE / "tournament.json", "types"),
}
KINDS = {".glb": "gltf", ".gltf": "gltf", ".stl": "stl", ".obj": "obj"}
PREVIEW = RAW / "_preview"                 # облегчённые копии (build_previews.py)
LOCK = threading.Lock()


def load_store() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    # Первый запуск: перенести оценки из прежней выгрузки, ничего не теряя.
    reviews = {}
    if SEED.exists():
        reviews = json.loads(SEED.read_text(encoding="utf-8")).get("reviews", {})
    return {"note": "Оценки и повороты моделей из tools/model_preview. "
                    "orientation — кватернион [x, y, z, w], применяется к корню модели; "
                    "запечь в файл: tools/model_preview/patch_glb_rotation.py --quat.",
            "reviews": reviews}


def save_store(store: dict) -> None:
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, STORE)                   # атомарно: файл не бывает недописанным


def load_doc(name: str) -> dict:
    path, key = DOCS[name]
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {key: {}}


def save_doc(name: str, doc: dict) -> None:
    path, _ = DOCS[name]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def roster() -> list[dict]:
    """Корабли ростера v4 с эталонной картинкой из demo/assets/v4_art."""
    art = {}
    manifest = V4_ART / "manifest.json"
    if manifest.exists():
        art = json.loads(manifest.read_text(encoding="utf-8"))
    out = []
    for p in sorted(V4_SHIPS.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        a = (art.get(d["id"]) or {}).get("ships") or {}
        out.append({"id": d["id"], "name": d["display_name"], "faction": d["faction"],
                    "era": d["era"], "role": d["role"],
                    "art": ("/demo/assets/v4_art/" + a["file"]) if a.get("file") else None,
                    "art_title": a.get("title"), "art_url": a.get("url"),
                    "art_placeholder": bool(a.get("placeholder"))})
    return out


def ship_of(rel: str) -> str:
    name = rel.split("/")[-1].rsplit(".", 1)[0]
    if rel.startswith("liked/") and "__" in name:
        return name.split("__")[0]
    if "/" in rel:                            # scene.gltf внутри каталога модели
        return rel.split("/")[-2] if rel.split("/")[0] != "converted_glb" else name
    return name


def load_numbers() -> dict:
    if NUMBERS.exists():
        return json.loads(NUMBERS.read_text(encoding="utf-8"))
    return {}


def list_models() -> list[dict]:
    """Все модели на диске. У каждой постоянный номер: он выдаётся один раз и
    больше не меняется — новые файлы получают следующие номера, номера
    удалённых файлов не переиспользуются. Так «#37» всегда одна и та же модель."""
    out = []
    for p in sorted(RAW.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in KINDS:
            continue
        rel = p.relative_to(RAW).as_posix()
        if rel.startswith("_preview/") or any(part.startswith("backup") for part in rel.split("/")):
            continue
        item = {"file": rel, "kind": KINDS[p.suffix.lower()], "ship": ship_of(rel),
                "bytes": p.stat().st_size}
        # облегчённая копия — только если она не старше оригинала
        pv = (PREVIEW / rel).with_suffix(".glb")
        if pv.exists() and pv.stat().st_mtime >= p.stat().st_mtime:
            item["preview"] = pv.relative_to(RAW).as_posix()
            item["preview_bytes"] = pv.stat().st_size
        out.append(item)
    with LOCK:
        numbers = load_numbers()
        fresh = [m["file"] for m in out if m["file"] not in numbers]
        if fresh:
            nxt = max(numbers.values(), default=0) + 1
            for f in fresh:                   # out уже отсортирован по пути
                numbers[f] = nxt
                nxt += 1
            tmp = NUMBERS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(numbers, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
            os.replace(tmp, NUMBERS)
    for m in out:
        m["num"] = numbers[m["file"]]
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    # без charset браузер читает кириллицу в HTML как Windows-1252
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
                      ".md": "text/markdown; charset=utf-8", ".webp": "image/webp"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/models":
            return self._json(200, list_models())
        if path == "/api/reviews":
            with LOCK:
                return self._json(200, load_store())
        if path == "/api/roster":
            return self._json(200, roster())
        if path == "/api/voxels":
            return self._json(200, list_voxels())
        if path.startswith("/api/doc/") and path[len("/api/doc/"):] in DOCS:
            with LOCK:
                return self._json(200, load_doc(path[len("/api/doc/"):]))
        if path in ("/", "/tools/model_preview"):
            self.send_response(302)
            self.send_header("Location", "/tools/model_preview/index.html")
            self.end_headers()
            return
        if not unquote(path).startswith(ALLOWED):
            # статусная строка HTTP — только latin-1, поэтому пояснение по-английски
            return self.send_error(404, "Only tools/model_preview and external_models are served")
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/doc/") and path[len("/api/doc/"):] in DOCS:
            return self._post_doc(path[len("/api/doc/"):])
        if path != "/api/reviews":
            return self.send_error(404)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            changes = data["changes"]
            assert isinstance(changes, dict)
        except Exception:
            return self._json(400, {"ok": False, "error": "ожидается {\"changes\": {...}}"})
        with LOCK:
            store = load_store()
            for key, review in changes.items():
                if review is None:
                    store["reviews"].pop(key, None)
                else:
                    store["reviews"][key] = review
            save_store(store)
            total = len(store["reviews"])
        return self._json(200, {"ok": True, "saved": len(changes), "total": total})

    def _post_doc(self, name: str):
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            changes = data["changes"]
            assert isinstance(changes, dict)
        except Exception:
            return self._json(400, {"ok": False, "error": "ожидается {\"changes\": {...}}"})
        _, key = DOCS[name]
        with LOCK:
            doc = load_doc(name)
            for k, v in changes.items():
                if v is None:
                    doc[key].pop(k, None)
                else:
                    doc[key][k] = v
            save_doc(name, doc)
        return self._json(200, {"ok": True, "saved": len(changes)})

    def end_headers(self):
        # Страница и API — всегда свежие. Файлы моделей браузер кэширует и
        # перед повтором только спрашивает «изменился ли?» (304 Not Modified):
        # раньше каждое открытие заново качало модель по Wi-Fi, до 965 МБ.
        path = urlparse(self.path).path
        if path.startswith("/api/") or path.endswith((".html", ".json")):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):       # без шума по каждому файлу модели
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), Handler) as srv:
        n = len(list_models())
        print(f"Моделей на диске: {n}. Повороты пишутся в {STORE.relative_to(ROOT)}")
        print(f"С этого Мака:  http://localhost:{port}/tools/model_preview/index.html")
        print(f"С планшета:    http://{lan_ip()}:{port}/tools/model_preview/index.html", flush=True)
        srv.serve_forever()


if __name__ == "__main__":
    main()
