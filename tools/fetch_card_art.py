#!/usr/bin/env python3
"""Картинки для карточек: главная иллюстрация статьи Wookieepedia.

Для каждого корабля и героя ruleset v4 берётся главная картинка его статьи на
Wookieepedia (starwars.fandom.com, MediaWiki API: prop=pageimages, оригинал).
Если статьи с таким названием нет — поиск по Вики, первая подходящая статья.
Картинка ужимается до 900 px по длинной стороне и сохраняется в WebP (с
прозрачностью, если она есть — многие рендеры кораблей прозрачные).

Права: изображения принадлежат Lucasfilm Ltd. и авторам; на Вики они
используются как цитата. Проект частный (ADR-001, ADR-020 вариант А):
картинки хранятся в приватном репозитории и не публикуются. Источник каждой
записан в manifest.json.

Запуск:  python3 tools/fetch_card_art.py [id ...] [--force]
Вывод:   demo/assets/card_art/{ships,heroes}/<id>.webp и manifest.json
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "demo" / "assets" / "card_art"
API = "https://starwars.fandom.com/api.php"
AGENT = "Mozilla/5.0 (StarWarsBattleships private family prototype; card art)"
MAX_SIDE = 900
PAUSE = 5.0          # секунд между картинками: Вики блокирует частые загрузки
WIKI_OK = True       # --no-wiki: только база starwars.com
WIKI_FIRST = False   # --wiki-first: сначала Wookieepedia (чистые рендеры кораблей)

# Официальная база starwars.com/databank — основной источник: для id перебираются
# адреса страниц, берётся главная картинка (og:image) первой существующей.
DATABANK = {
    "tie_fighter": ["tie-fighter"], "tie_advanced_x1": ["darth-vader-s-tie-fighter", "tie-advanced-x1", "darth-vaders-tie-fighter"],
    "xwing_t65": ["x-wing-starfighter"], "eta2_actis": ["eta-2-jedi-starfighter", "jedi-interceptor", "eta-2-actis-class-interceptor"],
    "millennium_falcon": ["millennium-falcon"], "star_destroyer": ["imperial-star-destroyer", "star-destroyer"],
    "death_star_1": ["death-star"], "slave_1": ["slave-i", "boba-fetts-starship"],
    "ghost": ["the-ghost", "ghost"], "phantom": ["the-phantom", "phantom", "phantom-ii"],
    "vulture_droid": ["vulture-droid", "droid-starfighter"],
    "delta7_aethersprite": ["jedi-starfighter", "delta-7-jedi-starfighter"],
    "arc170": ["arc-170-starfighter", "arc-170"], "v19_torrent": ["v-19-torrent-starfighter", "v-19-torrent"],
    "laat_gunship": ["republic-attack-gunship", "laat-gunship"],
    "naboo_n1": ["naboo-n-1-starfighter", "naboo-starfighter"], "naboo_royal_cruiser": ["naboo-royal-starship"],
    "venator": ["republic-attack-cruiser", "venator-class-star-destroyer"],
    "tri_fighter": ["droid-tri-fighter", "tri-fighter"], "hyena_bomber": ["hyena-bomber-droid", "hyena-bomber", "hyena-class-droid-bomber"],
    "nantex_fighter": ["geonosian-fighter", "geonosian-starfighter", "nantex-class-starfighter"], "soulless_one": ["soulless-one"],
    "munificent": ["separatist-frigate", "munificent-class-star-frigate", "banking-clan-frigate"],
    "providence": ["invisible-hand", "separatist-destroyer", "providence-class-destroyer"],
    "tie_interceptor": ["tie-interceptor"], "tie_bomber": ["tie-bomber"],
    "lambda_shuttle": ["imperial-shuttle", "lambda-class-shuttle"],
    "interdictor": ["interdictor-cruiser", "imperial-interdictor"], "executor": ["executor", "super-star-destroyer"],
    "ywing_btla4": ["y-wing-starfighter", "y-wing-fighter", "y-wing"], "awing_rz1": ["a-wing-fighter", "a-wing"],
    "bwing": ["b-wing-fighter", "b-wing"], "mc80_home_one": ["home-one", "mon-calamari-star-cruiser"],
    "gr75_transport": ["rebel-transport", "gr-75-medium-transport"], "tie_fo": ["first-order-tie-fighter"],
    "tie_sf": ["first-order-special-forces-tie-fighter", "special-forces-tie-fighter"],
    "tie_silencer": ["tie-silencer"], "upsilon_shuttle": ["kylo-rens-command-shuttle", "upsilon-class-command-shuttle"],
    "resurgent_destroyer": ["first-order-star-destroyer", "resurgent-class-star-destroyer"],
    "xwing_t70": ["t-70-x-wing-fighter", "resistance-x-wing"],
    "rz2_awing": ["resistance-a-wing-fighter", "rz-2-a-wing"],
    "mg100_bomber": ["resistance-bomber", "mg-100-starfortress"], "raddus_cruiser": ["the-raddus", "raddus"],
    "resistance_transport": ["resistance-transport", "u-55-orbital-loadlifter"],
    "punishing_one": ["punishing-one"], "hounds_tooth": ["hounds-tooth"], "z95_headhunter": ["clone-z-95-starfighter", "z-95-headhunter"],
    "pirate_corsair": ["darius-g-class-freighter", "hondo-ohnakas-transport", "fortune-and-glory"],
    "pirate_marauder": ["pirate-frigate", "marauder-class-corvette", "pirate-gunship"],
    "pirate_skiff": ["shydopp-pirate-skiff", "pirate-snubfighter", "weequay-pirate-fighter"],
    # герои
    "obi_wan": ["obi-wan-kenobi"], "darth_vader": ["darth-vader"], "anakin": ["anakin-skywalker"],
    "han_solo": ["han-solo"], "luke": ["luke-skywalker"], "phasma": ["captain-phasma"],
    "jango_fett": ["jango-fett"], "boba_fett": ["boba-fett"], "padme_amidala": ["padme-amidala"],
    "mace_windu": ["mace-windu"], "yoda": ["yoda"], "qui_gon_jinn": ["qui-gon-jinn"],
    "count_dooku": ["count-dooku"], "general_grievous": ["general-grievous"], "nute_gunray": ["nute-gunray"],
    "darth_maul": ["darth-maul"], "emperor_palpatine": ["emperor-palpatine", "darth-sidious"],
    "grand_moff_tarkin": ["grand-moff-tarkin"], "admiral_piett": ["admiral-piett"],
    "leia_organa": ["princess-leia-organa", "leia-organa"], "chewbacca": ["chewbacca"],
    "lando_calrissian": ["lando-calrissian"], "wedge_antilles": ["wedge-antilles"],
    "admiral_ackbar": ["admiral-ackbar"], "kylo_ren": ["kylo-ren"], "general_hux": ["general-hux"],
    "snoke": ["supreme-leader-snoke", "snoke"], "rey": ["rey"], "poe_dameron": ["poe-dameron"],
    "finn": ["finn"], "vice_admiral_holdo": ["vice-admiral-holdo", "amilyn-holdo"], "r2_d2": ["r2-d2"],
}
DATABANK_URL = "https://www.starwars.com/databank/"


def databank(key: str) -> tuple[str, str] | None:
    """(адрес страницы, адрес картинки) первой существующей страницы базы."""
    import re
    for slug in DATABANK.get(key, []):
        url = DATABANK_URL + slug
        try:
            page = fetch(url).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise
            continue                                    # 404 — пробуем следующий адрес
        m = re.search(r'<meta property="og:image" content="([^"]+)"', page)
        if m and "og-generic" not in m.group(1):
            return url, m.group(1).split("?")[0]        # без ?region= — картинка целиком
        time.sleep(PAUSE)
    return None


# id → название статьи Wookieepedia (или поисковая строка, если начинается с «?»)
SHIPS = {
    "tie_fighter": "TIE/ln space superiority starfighter",
    "tie_advanced_x1": "TIE Advanced x1",
    "xwing_t65": "T-65B X-wing starfighter",
    "eta2_actis": "Eta-2 Actis-class light interceptor",
    "millennium_falcon": "Millennium Falcon",
    "star_destroyer": "Imperial I-class Star Destroyer",
    "death_star_1": "DS-1 Death Star Mobile Battle Station",
    "slave_1": "Slave I",
    "ghost": "?Ghost VCX-100 light freighter Syndulla",
    "phantom": "?Phantom VCX-series auxiliary starfighter",
    "vulture_droid": "Variable Geometry Self-Propelled Battle Droid, Mark I",
    "delta7_aethersprite": "Delta-7 Aethersprite-class light interceptor",
    "arc170": "Aggressive ReConnaissance-170 starfighter",
    "v19_torrent": "V-19 Torrent starfighter",
    "laat_gunship": "Low Altitude Assault Transport/infantry",
    "naboo_n1": "N-1 starfighter",
    "naboo_royal_cruiser": "J-type 327 Nubian royal starship",
    "venator": "Venator-class Star Destroyer",
    "tri_fighter": "Droid tri-fighter",
    "hyena_bomber": "Hyena-class bomber",
    "nantex_fighter": "Nantex-class territorial defense starfighter",
    "soulless_one": "Soulless One",
    "munificent": "Munificent-class star frigate",
    "providence": "Providence-class carrier/destroyer",
    "tie_interceptor": "TIE/IN interceptor",
    "tie_bomber": "TIE/sa bomber",
    "lambda_shuttle": "Lambda-class T-4a shuttle",
    "interdictor": "Immobilizer 418 cruiser",
    "executor": "Executor",
    "ywing_btla4": "BTL-A4 Y-wing assault starfighter/bomber",
    "awing_rz1": "RZ-1 A-wing interceptor",
    "bwing": "A/SF-01 B-wing starfighter",
    "mc80_home_one": "Home One",
    "gr75_transport": "GR-75 medium transport",
    "tie_fo": "TIE/fo space superiority fighter",
    "tie_sf": "TIE/sf space superiority fighter",
    "tie_silencer": "TIE/vn space superiority fighter",
    "upsilon_shuttle": "Upsilon-class command shuttle",
    "resurgent_destroyer": "Resurgent-class Star Destroyer",
    "xwing_t70": "T-70 X-wing starfighter",
    "rz2_awing": "RZ-2 A-wing interceptor",
    "mg100_bomber": "MG-100 StarFortress SF-17",
    "raddus_cruiser": "Raddus",
    "resistance_transport": "U-55 orbital loadlifter",
    "punishing_one": "Punishing One",
    "hounds_tooth": "Hound's Tooth",
    "z95_headhunter": "Z-95 Headhunter",
    "pirate_corsair": "Aurore-class freighter",
    "pirate_marauder": "Marauder-class corvette",
    "pirate_skiff": "?Preybird-class starfighter",
}
HEROES = {
    "obi_wan": "Obi-Wan Kenobi", "darth_vader": "Darth Vader", "anakin": "Anakin Skywalker",
    "han_solo": "Han Solo", "luke": "Luke Skywalker", "phasma": "Phasma",
    "jango_fett": "Jango Fett", "boba_fett": "Boba Fett", "padme_amidala": "Padmé Amidala",
    "mace_windu": "Mace Windu", "yoda": "Yoda", "qui_gon_jinn": "Qui-Gon Jinn",
    "count_dooku": "Dooku", "general_grievous": "Grievous", "nute_gunray": "Nute Gunray",
    "darth_maul": "Maul", "emperor_palpatine": "Sheev Palpatine", "grand_moff_tarkin": "Wilhuff Tarkin",
    "admiral_piett": "Firmus Piett", "leia_organa": "Leia Organa", "chewbacca": "Chewbacca",
    "lando_calrissian": "Lando Calrissian", "wedge_antilles": "Wedge Antilles",
    "admiral_ackbar": "Gial Ackbar", "kylo_ren": "Ben Solo", "general_hux": "Armitage Hux",
    "snoke": "Snoke", "rey": "Rey Skywalker", "poe_dameron": "Poe Dameron", "finn": "Finn",
    "vice_admiral_holdo": "Amilyn Holdo", "r2_d2": "R2-D2",
}


def api(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=60) as r:
        return json.load(r)


def resolve(title: str) -> tuple[str, dict] | None:
    """Статья и её главная картинка (оригинал)."""
    if title.startswith("?"):
        hits = api({"action": "query", "list": "search", "srsearch": title[1:], "srlimit": 5})["query"]["search"]
        titles = [h["title"] for h in hits]
    else:
        titles = [title]
    for t in titles:
        pages = api({"action": "query", "titles": t, "prop": "pageimages", "piprop": "original",
                     "redirects": 1})["query"]["pages"]
        for p in pages.values():
            if "original" in p:
                return p["title"], p["original"]
    return None


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=120) as r:
        return r.read()


def main(argv: list[str]) -> int:
    global WIKI_OK
    force = "--force" in argv
    WIKI_OK = "--no-wiki" not in argv
    global WIKI_FIRST
    WIKI_FIRST = "--wiki-first" in argv
    only = {a for a in argv if not a.startswith("--")}
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    bad = []
    for kind, table in (("ships", SHIPS), ("heroes", HEROES)):
        (OUT / kind).mkdir(parents=True, exist_ok=True)
        for key, title in table.items():
            if only and key not in only:
                continue
            dst = OUT / kind / f"{key}.webp"
            if dst.exists() and not force:
                continue
            try:
                # --wiki-first: для кораблей чистый рендер Вики лучше сцены из фильма
                db = None if WIKI_FIRST and WIKI_OK and resolve(title) else databank(key)
                if db:
                    page_url, image_url = db
                    page, orig = page_url.rsplit("/", 1)[-1], {"source": image_url, "width": 0, "height": 0}
                    source = "starwars.com databank"
                elif WIKI_OK:
                    found = resolve(title)
                    if not found:
                        bad.append((key, "нет ни в базе starwars.com, ни на Wookieepedia")); continue
                    page, orig = found
                    page_url = "https://starwars.fandom.com/wiki/" + urllib.parse.quote(page.replace(" ", "_"))
                    source = "Wookieepedia"
                else:
                    bad.append((key, "нет в базе starwars.com; Wookieepedia пропущена (--no-wiki)")); continue
                img = Image.open(io.BytesIO(fetch(orig["source"])))
                if not orig["width"]:
                    orig["width"], orig["height"] = img.size
                if min(img.size) < 200:
                    bad.append((key, f"слишком маленькая картинка {img.size}")); continue
                img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
                img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
                # прозрачный рендер кладётся на звёздный фон карточки, сцена — заполняет окно
                alpha = img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250
                img.save(dst, "WEBP", quality=86, method=6)
                manifest[f"{kind}/{key}"] = {
                    "file": f"{kind}/{key}.webp", "page": page, "source": source, "transparent": bool(alpha),
                    "page_url": page_url,
                    "image_url": orig["source"], "original_size": [orig["width"], orig["height"]],
                    "saved_size": list(img.size), "rights": f"© Lucasfilm Ltd.; через {source}",
                }
                print(f"{kind:6} {key:22} ← {source}: {page} ({orig['width']}×{orig['height']})", flush=True)
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    # Вики ограничивает частоту — останавливаемся сразу, чтобы не продлевать
                    # блокировку. Повторный запуск докачает остальное (готовое пропускается).
                    print(f"\nWookieepedia отвечает {e.code} — остановка. Запустите позже ещё раз.")
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                                                        sort_keys=True) + "\n", encoding="utf-8")
                    return 3
                bad.append((key, str(e)[:120]))
            except Exception as e:                     # одна картинка не валит остальные
                bad.append((key, str(e)[:120]))
            time.sleep(PAUSE)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                             encoding="utf-8")
    print(f"\nГотово: {len(manifest)} картинок; не получилось: {len(bad)}")
    for k, why in bad:
        print(f"  ✗ {k}: {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
