"""Перенос утверждённого патча баланса в датасет v4.

Берёт патч оптимизатора (tools/sim_v4/patches/*.json: {"ships": {id: {F, sides, rear, B, hp, shield,
cost}}, "heroes": {id: цена}}), записывает data/balance/v4_patch.json с пометкой источника,
пересобирает датасет (tools/gen_v4_dataset.py) и проверяет его (tools/validate_v4.py).
После переноса числа живут в карточках; игре патч поверх карточек больше не нужен.

Запуск:  python3 tools/apply_balance_patch.py tools/sim_v4/patches/final.json --note "…"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "balance" / "v4_patch.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patch")
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    p = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    ships = {k: {kk: vv for kk, vv in v.items() if vv} for k, v in p.get("ships", {}).items()}
    ships = {k: v for k, v in ships.items() if v}
    out = {"source": f"{Path(args.patch).name}: {args.note}".strip(": "), "ships": ships,
           "heroes": {k: int(v) for k, v in p.get("heroes", {}).items()}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"записан {OUT.relative_to(ROOT)}: {len(ships)} кораблей, {len(out['heroes'])} цен героев")
    for cmd in (["tools/gen_v4_dataset.py"], ["tools/validate_v4.py"]):
        r = subprocess.run([sys.executable, *cmd], cwd=ROOT)
        if r.returncode:
            sys.exit(r.returncode)


if __name__ == "__main__":
    main()
