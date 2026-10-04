#!/usr/bin/env python3
"""Batch-download the user's liked Sketchfab candidates (model_reviews.json).

Official Download API only: requires SKETCHFAB_TOKEN (OAuth, registered user).
Anonymous extraction from the viewer is not used and will not be added.

For every review with source=sketchfab_index and verdict=like:
  download glTF zip -> extract safely -> Blender: orient + convert to GLB
  -> assets_source/external_models/raw_candidates/liked/<nn>_<name>.glb
and refresh liked/manifest.json for the viewer tab.

Resumable: existing .glb artifacts are skipped. Re-run after new likes.

Usage:
  SKETCHFAB_TOKEN=... python3 tools/download_selected_models.py [--limit N] [--all-v4]

--all-v4 — дополнительно скачать всех кандидатов, найденных find_models.py для
кораблей игры, у которых моделей не было (запросы «v4:<корабль>»), без лайков.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
LIKED = RAW / "liked"
# отзывы теперь пишет сервер страницы моделей; старая выгрузка браузера — запасной вариант
REVIEWS = ROOT / "tools" / "model_preview" / "model_reviews.json"
if not REVIEWS.exists():
    REVIEWS = RAW / "model_reviews.json"
CANDIDATES = ROOT / "assets_source" / "external_models" / "sketchfab_candidates.json"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
ORIENT = ROOT / "tools" / "model_preview" / "import_and_orient.py"

AGENT = "StarWarsBattleships-batch-downloader/1.0"


def request_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Token {token}", "Accept": "application/json",
        "User-Agent": AGENT,
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def download(url: str, target: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                shutil.copyfileobj(r, tmp)
            os.replace(tmp_path, target)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise


def extract_safe(package: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in package.infolist():
        member_path = (destination / member.filename).resolve()
        if member_path != root and root not in member_path.parents:
            raise RuntimeError(f"unsafe archive path: {member.filename}")
    package.extractall(destination)


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "model"


def main() -> int:
    token = os.environ.get("SKETCHFAB_TOKEN", "").strip()
    if not token:
        print("SKETCHFAB_TOKEN is not set; nothing downloaded.", file=sys.stderr)
        print("Регистрация: https://sketchfab.com/register → токен: "
              "https://sketchfab.com/settings/password → 'API token'.", file=sys.stderr)
        return 2

    limit = 10 ** 9
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    reviews = json.loads(REVIEWS.read_text())["reviews"]
    cand = json.loads(CANDIDATES.read_text())["queries"]
    uid2info = {h["uid"]: {"query": q, **h} for q, hits in cand.items() for h in hits}

    liked = []
    for key, r in reviews.items():
        if key.startswith("sf:") and r.get("verdict") == "like":
            uid = key[3:]
            info = uid2info.get(uid)
            if info:
                liked.append((r, uid, info))
    # --all-v4: все кандидаты, найденные find_models.py для кораблей игры без моделей
    # (запросы «v4:<корабль>»), без лайка по каждому; дизлайкнутые пропускаются
    if "--all-v4" in sys.argv:
        chosen = {uid for _, uid, _ in liked}
        for uid, info in uid2info.items():
            if info["query"].startswith("v4:") and uid not in chosen \
                    and reviews.get("sf:" + uid, {}).get("verdict") != "dislike":
                liked.append(({}, uid, info))
    liked.sort(key=lambda t: -(t[2].get("likes") or 0))
    print(f"liked candidates: {len(liked)}")

    LIKED.mkdir(parents=True, exist_ok=True)
    manifest_path = LIKED / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []

    done = failures = skipped = 0
    manifest_keys = {m.get("uid") for m in manifest}
    for r, uid, info in liked:
        if uid in manifest_keys:
            continue
        if done >= limit:
            break
        name = f"{sanitize(info['query'])}__{sanitize(info['name'])}"
        glb = LIKED / f"{name}.glb"
        if glb.exists():
            manifest.append({"uid": uid, "ship": info["query"], "label": info["name"],
                             "file": f"liked/{glb.name}", "kind": "gltf",
                             "license": info.get("license"), "url": info.get("url")})
            skipped += 1
            continue
        workdir = LIKED / f"_work_{uid}"
        try:
            meta = request_json(f"https://api.sketchfab.com/v3/models/{uid}/download", token)
            gltf = meta.get("gltf") or {}
            if not gltf.get("url"):
                raise RuntimeError("no glTF archive for this model")
            archive = workdir / "model.zip"
            print(f"DOWNLOAD {info['name']} ({info.get('license')})")
            download(gltf["url"], archive)
            with zipfile.ZipFile(archive) as z:
                if z.testzip():
                    raise RuntimeError("damaged archive")
                extract_safe(z, workdir)
            scene = workdir / "scene.gltf"
            if not scene.exists():
                cand_gltf = sorted(workdir.rglob("*.gltf"))
                if not cand_gltf:
                    raise RuntimeError("no .gltf in archive")
                scene = cand_gltf[0]
            res = subprocess.run(
                [BLENDER, "--background", "--python", str(ORIENT), "--",
                 str(scene), str(glb)],
                capture_output=True, text=True, timeout=600)
            if not glb.exists():
                raise RuntimeError(f"blender failed: {res.stderr[-300:]}")
            mark = "rotated" if "ORIENT rotated" in res.stdout else "as-is"
            print(f"OK {glb.name} ({mark})")
            manifest.append({"uid": uid, "ship": info["query"], "label": info["name"],
                             "file": f"liked/{glb.name}", "kind": "gltf",
                             "license": info.get("license"), "url": info.get("url")})
            done += 1
        except Exception as error:  # noqa: BLE001 — пакетный скрипт, ошибку логируем и идём дальше
            failures += 1
            print(f"ERROR {uid} {info['name']}: {error}", file=sys.stderr)
        finally:
            if workdir.exists():
                shutil.rmtree(workdir, ignore_errors=True)
        time.sleep(1.2)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"DONE downloaded={done} skipped_existing={skipped} failures={failures} "
          f"manifest={len(manifest)}")
    return 1 if failures and not done else 0


if __name__ == "__main__":
    raise SystemExit(main())
