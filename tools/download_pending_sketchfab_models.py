#!/usr/bin/env python3
"""Download the remaining ship candidates through Sketchfab's official API.

Set SKETCHFAB_TOKEN to an OAuth access token created for the signed-in user.
The script never prints the token and does not overwrite an existing archive.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets_source" / "external_models" / "raw_candidates"

MODELS = {
    "ghost_vcx100_cgitutorials": "8740b94179ba43a7ac6476973ca0c577",
    "phantom_klgaming": "fc54544abbd2405f9a1ad2c48640d5c2",
    "eta2_actis_petri_liuhto": "0b641c2f2b854f1f9ae7f2a731e44dbd",
    "tie_advanced_x1_mimmus": "83654f360e1e4c72b716a2a60ed09031",
}


def request_json(url: str, token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "User-Agent": "StarWarsBattleships-model-downloader/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "StarWarsBattleships-model-downloader/1.0"}
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                shutil.copyfileobj(response, temporary)
            os.replace(temporary_path, target)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


def extract_safe(package: zipfile.ZipFile, destination: Path) -> None:
    root = destination.resolve()
    for member in package.infolist():
        member_path = (destination / member.filename).resolve()
        if member_path != root and root not in member_path.parents:
            raise RuntimeError(f"unsafe archive path: {member.filename}")
    package.extractall(destination)


def main() -> int:
    token = os.environ.get("SKETCHFAB_TOKEN", "").strip()
    if not token:
        print("SKETCHFAB_TOKEN is not set; no downloads were attempted.", file=sys.stderr)
        return 2

    OUTPUT.mkdir(parents=True, exist_ok=True)
    failures = 0

    for name, uid in MODELS.items():
        archive = OUTPUT / f"{name}.zip"
        destination = OUTPUT / name
        if archive.exists() or destination.exists():
            print(f"SKIP {name}: target already exists")
            continue

        try:
            metadata = request_json(
                f"https://api.sketchfab.com/v3/models/{uid}/download", token
            )
            gltf = metadata.get("gltf")
            if not isinstance(gltf, dict) or not gltf.get("url"):
                raise RuntimeError("API response does not contain a glTF archive URL")

            print(f"DOWNLOAD {name}")
            download(str(gltf["url"]), archive)
            with zipfile.ZipFile(archive) as package:
                damaged = package.testzip()
                if damaged:
                    raise RuntimeError(f"damaged archive member: {damaged}")
                extract_safe(package, destination)
            print(f"OK {name}: {archive.name} and {destination.name}/")
        except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
            failures += 1
            print(f"ERROR {name}: {error}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
