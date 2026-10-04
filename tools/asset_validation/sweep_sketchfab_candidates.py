#!/usr/bin/env python3
"""Index downloadable Sketchfab candidates for the ship expansion catalog.

Search API is public (no auth); downloads still require OAuth — that stays
with tools/download_pending_sketchfab_models.py. Output:
  assets_source/external_models/sketchfab_candidates.json
  assets_source/external_models/sketchfab_candidates.md
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "assets_source" / "external_models"

# (раздел каталога, поисковый запрос) — по ship_expansion_catalog.md
QUERIES: list[tuple[str, str]] = [
    # боевой ростер v3 и починка кандидатов
    ("roster", "vulture droid starfighter"),
    ("roster", "ghost vcx-100"),
    ("roster", "sheathipede shuttle"),
    ("roster", "eta-2 actis"),
    ("roster", "tie advanced x1"),
    ("roster", "slave 1 firespray"),
    # истребители и малые корабли
    ("fighters", "y-wing starfighter"),
    ("fighters", "a-wing interceptor"),
    ("fighters", "b-wing starfighter"),
    ("fighters", "u-wing"),
    ("fighters", "z-95 headhunter"),
    ("fighters", "arc-170"),
    ("fighters", "v-wing starfighter"),
    ("fighters", "delta-7 aethersprite"),
    ("fighters", "t-6 jedi shuttle"),
    ("fighters", "n-1 starfighter"),
    ("fighters", "v-19 torrent"),
    ("fighters", "droid tri-fighter"),
    ("fighters", "hyena bomber"),
    ("fighters", "belbullab-22"),
    ("fighters", "nantex starfighter"),
    ("fighters", "soulless one"),
    ("fighters", "rogue class porax-38"),
    ("fighters", "sith infiltrator scimitar"),
    ("fighters", "fang fighter"),
    ("fighters", "e-wing"),
    ("fighters", "rz-2 a-wing"),
    ("fighters", "tie silencer"),
    ("fighters", "fireball resistance"),
    # имперские TIE и шаттлы
    ("imperial", "tie interceptor"),
    ("imperial", "tie bomber"),
    ("imperial", "tie defender"),
    ("imperial", "tie striker"),
    ("imperial", "outland tie fighter"),
    ("imperial", "tie reaper"),
    ("imperial", "lambda shuttle"),
    ("imperial", "sentinel landing craft"),
    ("imperial", "upsilon shuttle"),
    ("imperial", "gozanti cruiser"),
    ("imperial", "interdictor cruiser"),
    ("imperial", "quasar fire carrier"),
    ("imperial", "razer crest"),
    # транспортники и фрахтовики
    ("transports", "yt-2400 freighter"),
    ("transports", "gr-75 transport"),
    ("transports", "laat gunship"),
    ("transports", "nu-class shuttle"),
    ("transports", "komrk gauntlet"),
    ("transports", "hondo shuttle ss-54"),
    # крейсера и флагманы
    ("capitals", "cr90 corvette"),
    ("capitals", "nebulon-b frigate"),
    ("capitals", "hammerhead corvette"),
    ("capitals", "mc75 star cruiser"),
    ("capitals", "mc80 mon calamari cruiser"),
    ("capitals", "venator star destroyer"),
    ("capitals", "acclamator"),
    ("capitals", "arquitens cruiser"),
    ("capitals", "pelta frigate"),
    ("capitals", "executor super star destroyer"),
    ("capitals", "resurgent star destroyer"),
    ("capitals", "lucrehulk battleship"),
    ("capitals", "munificent frigate"),
    ("capitals", "recusant destroyer"),
    ("capitals", "providence destroyer invisible hand"),
    ("capitals", "malevolence"),
    ("capitals", "xyston star destroyer"),
    ("capitals", "fulminatrix dreadnought"),
]

# Волна 2: покрытие всего ship_expansion_catalog.md (то, чего нет в первой волне)
QUERIES += [
    ("republic", "polan 717 transport"),
    ("republic", "consular class cruiser"),
    ("republic", "charger c70 retrofit"),
    ("republic", "nubian royal starship"),
    ("republic", "nubian diplomatic barge"),
    ("republic", "h-type nubian yacht"),
    ("republic", "naboo star skiff"),
    ("republic", "delta-7b aethersprite"),
    ("republic", "theta class shuttle"),
    ("republic", "rho class shuttle"),
    ("republic", "eta class supply barge"),
    ("republic", "ipv-2c stealth corvette"),
    ("republic", "paladin class crucible"),
    ("republic", "twilight g9 rigger"),
    ("republic", "havoc marauder shuttle"),
    ("republic", "justifier cad bane ship"),
    ("republic", "silver angel ship"),
    ("cis", "c-9979 landing craft"),
    ("cis", "hardcell class transport"),
    ("cis", "core ship separatist"),
    ("cis", "dh-omni support vessel"),
    ("cis", "trident class assault ship"),
    ("cis", "droch class boarding ship"),
    ("cis", "solar sailer dooku"),
    ("cis", "ginivex fanblade starfighter"),
    ("empire", "imperial class star destroyer"),
    ("empire", "imperial arquitens command cruiser"),
    ("empire", "class 546 cruiser gideon"),
    ("empire", "cantwell arrestor cruiser"),
    ("empire", "tie fighter imperial"),
    ("empire", "tie advanced v1 inquisitor"),
    ("empire", "tie defender elite"),
    ("empire", "tie rb brute"),
    ("empire", "tie avenger andor"),
    ("empire", "mining guild tie"),
    ("empire", "zeta class cargo shuttle"),
    ("empire", "delta class t-3c shuttle"),
    ("empire", "scythe transport inquisitor"),
    ("rebels", "x-wing t-65 starfighter"),
    ("rebels", "millennium falcon yt-1300"),
    ("rebels", "blade wing prototype"),
    ("rebels", "mc80 liberty cruiser"),
    ("rebels", "dornean gunship brahatok"),
    ("rebels", "auzituck gunship"),
    ("hunters", "lancer class shadow caster"),
    ("hunters", "c-roc gozanti cruiser"),
    ("hunters", "ss-54 assault ship"),
    ("hunters", "first light dryden yacht"),
    ("hunters", "fondor haulcraft"),
    ("hunters", "pirate corsair gore"),
    ("hunters", "onyx cinder"),
    ("resistance", "t-70 x-wing"),
    ("resistance", "t-85 x-wing"),
    ("resistance", "bta-nr2 y-wing"),
    ("resistance", "mg-100 starfortress bomber"),
    ("resistance", "resistance transport"),
    ("resistance", "u-55 orbital loadlifter"),
    ("resistance", "mc85 raddus"),
    ("resistance", "ninka bunkerbuster"),
    ("resistance", "nebulon-c frigate"),
    ("resistance", "vakbeor cargo frigate"),
    ("resistance", "fireball racing starfighter"),
    ("resistance", "supremacy mega star destroyer"),
    ("resistance", "maxima-a heavy cruiser"),
    ("resistance", "tie fo first order"),
    ("resistance", "tie sf special forces"),
    ("resistance", "tie whisper"),
    ("resistance", "tie dagger"),
    ("resistance", "xi class light shuttle"),
    ("resistance", "aal 1971 troop transport"),
    ("resistance", "first order landing craft"),
    ("resistance", "bestoon legacy"),
    ("resistance", "night buzzard"),
    ("resistance", "libertine yacht"),
    ("unique", "eye of sion"),
    ("unique", "chimaera star destroyer"),
    ("stations", "death star ii"),
]

# Волна 3: повтор пустых классов другими формулировками
QUERIES += [
    ("retry", "razor crest"),
    ("retry", "invisible hand star wars"),
    ("retry", "providence class destroyer"),
    ("retry", "sheathipede"),
    ("retry", "upsilon class command shuttle"),
    ("retry", "kom'rk gauntlet"),
    ("retry", "gauntlet starfighter mandalorian"),
    ("retry", "outland tie moff gideon"),
    ("retry", "mining guild tie fighter"),
    ("retry", "first order tie fighter"),
    ("retry", "resistance bomber"),
    ("retry", "nantex"),
    ("retry", "fanblade starfighter"),
    ("retry", "krennic shuttle"),
    ("retry", "zeta class shuttle"),
    ("retry", "tie v1 inquisitor"),
    ("retry", "nebulon c"),
    ("retry", "padme star skiff"),
    ("retry", "naboo royal starship"),
    ("retry", "dornean gunship"),
    ("retry", "shadow caster ketsu"),
    ("retry", "havoc marauder bad batch"),
    ("retry", "chimera thrawn"),
    ("retry", "c-roc"),
    ("retry", "republic cruiser consular"),
]


def search(query: str) -> list[dict]:
    url = ("https://api.sketchfab.com/v3/search?type=models&downloadable=true"
           "&sort=-likeCount&count=4&q=" + urllib.parse.quote(query))
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "StarWarsBattleships-catalog-sweep/1.0",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    out = []
    for r in data.get("results", []):
        license_info = r.get("license") or {}
        out.append({
            "uid": r.get("uid"),
            "name": r.get("name"),
            "author": (r.get("user") or {}).get("username"),
            "license": license_info.get("label") if isinstance(license_info, dict) else license_info,
            "likes": r.get("likeCount"),
            "vertices": r.get("vertexCount"),
            "animated": bool(r.get("animationCount")),
            "url": "https://sketchfab.com/3d-models/" + r.get("uid", ""),
        })
    return out


def main() -> int:
    # мердж: не перезапрашиваем то, что уже есть в прошлых запусках
    prev = {}
    prev_path = OUT_DIR / "sketchfab_candidates.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text()).get("queries", {})
        except Exception:  # noqa: BLE001 — битый файл не блокирует обкачку
            prev = {}
    results: dict[str, list] = {k: v for k, v in prev.items() if v}
    failures: list[str] = []
    pending = [(s, q) for s, q in QUERIES if q not in results]
    print(f"total={len(QUERIES)} cached={len(results)} to_query={len(pending)}")
    for i, (section, query) in enumerate(pending):
        for attempt in range(3):
            try:
                results[query] = search(query)
                break
            except Exception as error:  # noqa: BLE001 — простой CLI-скрипт
                if attempt == 2:
                    failures.append(query)
                    print("FAIL", query, error)
                else:
                    time.sleep(3 * (attempt + 1))
        time.sleep(1.2)
        done = i + 1
        if done % 10 == 0:
            print(f"progress {done}/{len(pending)}")

    (OUT_DIR / "sketchfab_candidates.json").write_text(
        json.dumps({"generated_by": __doc__.splitlines()[0],
                    "queries": results, "failures": failures},
                   ensure_ascii=False, indent=1))

    lines = ["# Кандидаты Sketchfab по каталогу кораблей (анонимный поиск)",
             "",
             "Поиск публичный, скачивание — после регистрации через",
             "`tools/download_pending_sketchfab_models.py` (добавить UID в MODELS).",
             "Дата: 2026-09-17. Сортировка по популярности, только downloadable.",
             ""]
    for section, query in QUERIES:
        hits = results.get(query) or []
        lines.append(f"## {query}  ({section})")
        if not hits:
            lines.append("*ничего downloadable не найдено*")
        for h in hits:
            lines.append(
                "- [{name}]({url}) — {license}, автор {author}, ♥{likes}"
                .format(name=h["name"], url=h["url"], license=h["license"] or "license?",
                        author=h["author"], likes=h["likes"]))
        lines.append("")
    if failures:
        lines.append("Не удалось запросить: " + ", ".join(failures))
    (OUT_DIR / "sketchfab_candidates.md").write_text("\n".join(lines))

    total = sum(len(v) for v in results.values())
    print(f"DONE queries={len(QUERIES)} candidates={total} failures={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
