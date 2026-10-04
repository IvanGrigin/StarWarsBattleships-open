#!/usr/bin/env python3
"""Поиск скачиваемых моделей для кораблей игры, у которых моделей нет.

Ищет через открытый поиск Sketchfab (без токена): только модели с разрешённой
загрузкой и открытой лицензией (CC …). Для каждого корабля — несколько
запросов; результат проверяется по ключевым словам в названии, чтобы
«Nantex» не нашёл «NantexzStudios» и пряничный домик.

Найденное дописывается в assets_source/external_models/sketchfab_candidates.json
под запросом «v4:<корабль>» — кандидаты появляются во вкладке «Каталог
Sketchfab» страницы моделей (3D-просмотр, лайк/дизлайк). Скачивание — отдельно:
fetch_models.py (Objaverse, без токена) или download_selected_models.py
(официальный Download API, нужен токен владельца).

Запуск:  python3 tools/model_preview/find_models.py [корабль ...]
         без аргументов — все корабли ростера, у которых нет годных моделей.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CANDIDATES = ROOT / "assets_source" / "external_models" / "sketchfab_candidates.json"
REPORT = HERE / "missing_models_report.json"
AGENT = "Mozilla/5.0 (StarWarsBattleships model search)"

# корабль → (поисковые запросы, обязательные слова в названии — хотя бы одно)
SEARCH: dict[str, tuple] = {   # (запросы, слова «хотя бы одно», [слова-исключения])
    "nantex_fighter": (["nantex", "geonosian starfighter", "geonosian fighter"], ["nantex", "geonosian"]),
    "providence": (["providence class", "invisible hand star wars", "providence carrier destroyer"],
                   ["providence-class", "providence class", "invisible hand"]),
    "interdictor": (["interdictor star destroyer", "immobilizer 418", "interdictor cruiser"],
                    ["interdictor", "immobilizer"], ["leviathan", "old republic"]),
    "mg100_bomber": (["starfortress bomber", "resistance bomber", "mg-100", "starfortress",
                      "last jedi bomber", "resistance heavy bomber"],
                     ["starfortress", "resistance bomber", "mg-100", "mg100"]),
    "raddus_cruiser": (["raddus", "mc85 star cruiser", "mc85"], ["raddus", "mc85", "mc-85"]),
    "tie_sf": (["tie sf", "tie special forces", "tie/sf"], ["tie/sf", "tie sf", "special forces", "tie-sf"],
               ["interceptor"]),
    "upsilon_shuttle": (["upsilon shuttle", "kylo ren shuttle", "command shuttle first order"],
                        ["upsilon", "kylo"]),
    "punishing_one": (["punishing one", "jumpmaster 5000", "dengar ship", "jumpmaster", "punishing one star wars"],
                      ["punishing", "jumpmaster"]),
    "hounds_tooth": (["hound's tooth", "hounds tooth", "yv-666", "bossk ship"],
                     ["hound", "yv-666", "yv666", "bossk"]),
    "pirate_corsair": (["star wars pirate ship", "hondo ohnaka ship", "aurore class freighter",
                        "star wars freighter"], ["pirate", "hondo", "aurore", "freighter", "corsair"]),
    "pirate_marauder": (["kimogila", "star wars corvette pirate", "marauder corvette",
                         "star wars gunship"], ["kimogila", "marauder", "pirate", "corellian gunship", "corvette"],
                        ["laat", "republic gunship"]),        # LAAT — отдельный тип игры
    "pirate_skiff": (["scurrg", "pirate snub fighter", "star wars pirate fighter", "kihraxz", "scyk",
                      "starviper", "preybird"],
                     ["scurrg", "pirate", "snub", "kihraxz", "scyk", "starviper", "preybird"]),
}


def search(q: str, count: int = 24) -> list[dict]:
    url = "https://api.sketchfab.com/v3/search?" + urllib.parse.urlencode(
        {"type": "models", "q": q, "downloadable": "true", "count": count, "sort_by": "-likeCount"})
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("results", [])


def license_of(m: dict) -> str:
    lic = m.get("license")
    return (lic.get("label") if isinstance(lic, dict) else lic) or ""


def relevant(name: str, words: list[str]) -> bool:
    n = name.lower()
    if not any(w in n for w in words):
        return False
    # родня по слову, но явно не корабль
    return not re.search(r"studio|house|lobby|globe|figure|helmet|character|lego minifig", n)


def main(argv: list[str]) -> int:
    ships = argv or list(SEARCH)
    unknown = [s for s in ships if s not in SEARCH]
    if unknown:
        print(f"Нет поисковых запросов для: {unknown}", file=sys.stderr)
        return 1
    found: dict[str, list[dict]] = {}
    for ship in ships:
        queries, words, *rest = SEARCH[ship]
        exclude = rest[0] if rest else []
        seen, hits = set(), []
        for q in queries:
            try:
                results = search(q)
            except Exception as e:                       # сеть/лимит — не валим весь прогон
                print(f"  ! {ship}: запрос «{q}» не выполнен: {e}", file=sys.stderr)
                continue
            for m in results:
                if m["uid"] in seen or not m.get("isDownloadable"):
                    continue
                seen.add(m["uid"])
                lic = license_of(m)
                if not lic.lower().startswith("cc") or not relevant(m["name"], words) \
                        or any(x in m["name"].lower() for x in exclude):
                    continue
                hits.append({"uid": m["uid"], "name": m["name"],
                             "author": (m.get("user") or {}).get("displayName") or (m.get("user") or {}).get("username"),
                             "license": lic, "likes": m.get("likeCount"),
                             "faces": m.get("faceCount"), "vertices": m.get("vertexCount"),
                             "animated": bool(m.get("animationCount")),
                             "url": f"https://sketchfab.com/3d-models/{m['uid']}", "query": q})
            time.sleep(0.6)                                  # вежливо к открытому API
        hits.sort(key=lambda h: -(h["likes"] or 0))
        found[ship] = hits
        print(f"{ship:20} найдено {len(hits):2d}" + (f" — лучший: {hits[0]['name'][:45]} ({hits[0]['license']}, ♥{hits[0]['likes']})" if hits else ""))

    # в индекс каталога — отдельными запросами «v4:<корабль>»
    idx = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    for ship, hits in found.items():
        if hits:
            idx["queries"][f"v4:{ship}"] = [{k: h[k] for k in ("uid", "name", "author", "license", "likes",
                                                            "vertices", "animated", "url")} for h in hits]
    CANDIDATES.write_text(json.dumps(idx, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    REPORT.write_text(json.dumps(found, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    none = [s for s, h in found.items() if not h]
    print(f"\nС кандидатами: {len(found) - len(none)} из {len(found)}. Без скачиваемых моделей: {none or '—'}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}; каталог дополнен: {CANDIDATES.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
