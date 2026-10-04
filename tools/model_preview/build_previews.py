#!/usr/bin/env python3
"""Облегчённые копии моделей для страницы ориентации (tools/model_preview).

Зачем: среди скачанных моделей есть файлы до 965 МБ, с текстурами 8192 px
(≈8 ГБ видеопамяти после распаковки), с 4,9 млн треугольников и с 4062
отдельными мешами. Для выставления ориентации всё это не нужно, а браузер
на такой модели встаёт колом.

Копия делается gltf-transform optimize:
  * текстуры — не больше 512 px, формат WebP: для ориентации хватает, а
    группа из 9 самых тяжёлых моделей занимает ~310 МБ видеопамяти, а не ~880;
  * меши слиты (меньше вызовов отрисовки), геометрия упрощена с допуском
    0,2 % от габарита модели, сжата meshopt.
Поворот корня модели сохраняется: ориентация, найденная на копии, в точности
подходит к оригиналу.

Оригиналы не меняются. Копии лежат в raw_candidates/_preview/<тот же путь>.glb
(каталог исключён из git вместе с raw_candidates). Копия пересобирается, если
оригинал новее; готовые пропускаются — повторный запуск дешёвый.

Запуск:  python3 tools/model_preview/build_previews.py [--jobs 3] [--force]
Нужен Node.js; gltf-transform берётся через npx (версия закреплена ниже).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "assets_source" / "external_models" / "raw_candidates"
PREVIEW = RAW / "_preview"
REPORT = Path(__file__).resolve().parent / "previews_report.json"
GLTF_TRANSFORM = ["npx", "--yes", "@gltf-transform/cli@4.1.1"]
OPTIONS = ["--texture-size", "512", "--texture-compress", "webp",
           "--compress", "meshopt", "--simplify-error", "0.002"]


def sources() -> list[Path]:
    out = []
    for p in sorted(RAW.rglob("*")):
        if p.suffix.lower() not in (".glb", ".gltf") or not p.is_file():
            continue
        rel = p.relative_to(RAW).as_posix()
        if rel.startswith("_preview/") or any(s.startswith("backup") for s in rel.split("/")):
            continue
        out.append(p)
    return out


def preview_path(src: Path) -> Path:
    return (PREVIEW / src.relative_to(RAW)).with_suffix(".glb")


def build(src: Path, force: bool) -> dict:
    dst = preview_path(src)
    rel = src.relative_to(RAW).as_posix()
    if not force and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return {"file": rel, "status": "skip", "src_mb": src.stat().st_size / 1e6,
                "dst_mb": dst.stat().st_size / 1e6}
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.glb")
    t0 = time.time()
    proc = subprocess.run(GLTF_TRANSFORM + ["optimize", str(src), str(tmp)] + OPTIONS,
                          capture_output=True, text=True)
    took = time.time() - t0
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        err = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["?"]
        return {"file": rel, "status": "error", "error": err[0][:300], "seconds": round(took, 1)}
    tmp.replace(dst)
    return {"file": rel, "status": "ok", "seconds": round(took, 1),
            "src_mb": round(src.stat().st_size / 1e6, 2), "dst_mb": round(dst.stat().st_size / 1e6, 2)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not RAW.is_dir():
        # сами модели в git не входят: их нет, например, в git worktree
        print(f"Нет каталога с моделями: {RAW}\n"
              "Запускайте из основной папки проекта, где лежат скачанные модели:\n"
              "  cd <корень репозитория> && "
              "python3 tools/model_preview/build_previews.py", file=sys.stderr)
        return 2
    files = sources()
    # крупные первыми: они дольше всех, пусть идут параллельно с мелкими
    files.sort(key=lambda p: -p.stat().st_size)
    print(f"Моделей: {len(files)}; копии → {PREVIEW.relative_to(ROOT)}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(build, f, args.force): f for f in files}
        for i, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            results.append(r)
            if r["status"] == "ok":
                print(f"[{i}/{len(files)}] {r['src_mb']:8.1f} → {r['dst_mb']:6.1f} МБ  "
                      f"{r['seconds']:5.1f} с  {r['file']}", flush=True)
            elif r["status"] == "error":
                print(f"[{i}/{len(files)}] ОШИБКА {r['file']}: {r['error']}", flush=True)

    ok = [r for r in results if r["status"] in ("ok", "skip")]
    errors = [r for r in results if r["status"] == "error"]
    src_total = sum(r.get("src_mb", 0) for r in ok)
    dst_total = sum(r.get("dst_mb", 0) for r in ok)
    summary = {"built_or_fresh": len(ok), "errors": len(errors),
               "source_mb": round(src_total), "preview_mb": round(dst_total)}
    REPORT.write_text(json.dumps({"summary": summary, "errors": errors},
                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nГотово: {len(ok)} копий, ошибок {len(errors)}; "
          f"{src_total:.0f} МБ → {dst_total:.0f} МБ. Отчёт: {REPORT.relative_to(ROOT)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
