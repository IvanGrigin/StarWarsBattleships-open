#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборка рулбука v4 «Эпохи и фракции» — одна самодостаточная HTML-страница.

Текст правил живёт здесь, справочники (корабли, герои, фракции, местность,
события, сценарии) подставляются из data/rulesets/v4/**: после любой правки
баланса страница пересобирается одной командой и не расходится с данными.

Иллюстраций в репозитории нет намеренно (LICENSES.md, ADR-001): на карточках
стоят слоты со ссылкой на поиск изображения, их заменит собственный арт.

Запуск:  python3 tools/gen_rulebook.py
Вывод:   docs/rulebook/rulebook.html
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "data" / "rulesets" / "v4"
OUT = ROOT / "docs" / "rulebook" / "rulebook.html"


def load(name: str):
    return json.loads((V4 / name).read_text(encoding="utf-8"))


def load_dir(name: str):
    return [json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((V4 / name).glob("*.json"))]


def e(s) -> str:
    return html.escape(str(s), quote=True)


GAME = load("game.json")
BOARD = load("board.json")
FACTIONS = {f["id"]: f for f in load("factions.json")["factions"]}
ERAS = {x["id"]: x for x in load("eras.json")["eras"]}
TERRAIN = load("terrain.json")["terrain"]
EVENTS = load("events.json")
ABIL = {a["id"]: a for a in load("ship_abilities.json")["abilities"]}
PIRATES = load("pirates.json")
SHIPS = load_dir("ships")
HEROES = load_dir("heroes")
SCEN = load_dir("scenarios")

ROLE_RU = {
    "fighter": "истребитель", "interceptor": "перехватчик", "bomber": "бомбардировщик",
    "gunship": "канонерка", "support": "поддержка", "transport": "транспорт",
    "freighter": "фрахтовик", "corvette": "корвет", "capital": "крупный корабль",
    "station": "станция",
}
ERA_SHORT = {
    "fall_of_republic": "I–III", "galactic_civil_war": "IV–VI",
    "new_order": "VII–IX", "any": "вне эпохи",
}
SECTORS = ["F", "FR", "BR", "B", "BL", "FL"]
SECTOR_RU = ["нос", "правый борт", "правая корма", "корма", "левая корма", "левый борт"]


def img_slot(query: str, label: str) -> str:
    url = f"https://duckduckgo.com/?iax=images&ia=images&q={quote_plus(query + ' star wars')}"
    return (f'<a class="slot" href="{e(url)}" target="_blank" rel="noopener noreferrer" '
            f'title="Открыть поиск изображений — картинка не входит в проект">'
            f'<span class="slot-glyph" aria-hidden="true">◫</span>'
            f'<span class="slot-text">{e(label)}</span>'
            f'<span class="slot-hint">найти изображение ↗</span></a>')


def arc_wheel(arcs: list[int], color: str) -> str:
    """Шестиугольная диаграмма: каждое значение стоит на своей стороне."""
    import math
    parts = [f'<svg class="wheel" viewBox="-62 -62 124 124" role="img" '
             f'aria-label="Модификаторы секторов: '
             f'{e(", ".join(f"{SECTORS[i]} {v:+d}" for i, v in enumerate(arcs)))}">']
    radius = 46
    apothem = radius * math.cos(math.radians(30))
    for i, v in enumerate(arcs):
        # Сектор задаётся стороной гекса. Концы стороны отстоят на ±30° от
        # направления к соседней клетке; её середина лежит на апофеме.
        # Игровое поле pointy-top: вершины сверху/снизу, а направления к
        # соседям проходят через стороны. Сектор F при facing=0 — верхняя
        # левая сторона; далее значения идут по часовой стрелке.
        a0 = math.radians(-150 + i * 60)
        a1 = math.radians(-90 + i * 60)
        x0, y0 = radius * math.cos(a0), radius * math.sin(a0)
        x1, y1 = radius * math.cos(a1), radius * math.sin(a1)
        op = 0.16 + max(0, min(v, 4)) * 0.19
        parts.append(f'<path d="M 0 0 L {x0:.1f} {y0:.1f} L {x1:.1f} {y1:.1f} Z" '
                     f'fill="{color}" opacity="{op:.2f}" stroke="var(--line)" stroke-width="0.8"/>')
        am = math.radians(-120 + i * 60)
        tx, ty = apothem * math.cos(am), apothem * math.sin(am)
        parts.append(f'<rect x="{tx - 12:.1f}" y="{ty - 8:.1f}" width="24" height="16" rx="5" '
                     f'class="wheel-badge"/>')
        parts.append(f'<text x="{tx:.1f}" y="{ty + 4:.1f}" text-anchor="middle" '
                     f'class="wheel-num">{v:+d}</text>')
    parts.append('<polygon points="-31,-54 -22,-49 -29,-43" fill="var(--ink)"/>')
    parts.append('</svg>')
    return "".join(parts)


def sector_contact_diagram() -> str:
    """Правило контакта: направление проходит через общую сторону, не угол."""
    return '''<figure class="sector-rule">
<svg viewBox="0 0 660 330" role="img" aria-label="Два соседних pointy-top гекса имеют общую сторону. Модификаторы корабля стоят в серединах шести сторон.">
  <defs><filter id="sideGlow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
  <text x="330" y="20" text-anchor="middle" class="sr-title">ЗНАЧЕНИЯ СТОЯТ НА СТОРОНАХ, НЕ НА ВЕРШИНАХ</text>
  <polygon class="sr-ship" points="200,93 271,134 271,216 200,257 129,216 129,134"/>
  <polygon class="sr-target" points="342,93 413,134 413,216 342,257 271,216 271,134"/>
  <line class="sr-contact" x1="271" y1="134" x2="271" y2="216" filter="url(#sideGlow)"/>
  <path class="sr-course" d="M178 175 L302 175"/><polygon class="sr-arrow" points="322,175 301,166 301,184"/>
  <polygon class="sr-mini" points="246,175 179,152 194,175 179,198"/>
  <polygon class="sr-mini target" points="388,175 321,152 336,175 321,198"/>
  <text x="200" y="183" text-anchor="middle" class="sr-label">КОРАБЛЬ</text>
  <text x="342" y="183" text-anchor="middle" class="sr-label">ЦЕЛЬ</text>
  <g class="sr-value strong"><rect x="255" y="165" width="28" height="20" rx="6"/><text x="269" y="180">+2</text></g>
  <g class="sr-value"><rect x="221" y="226" width="28" height="20" rx="6"/><text x="235" y="241">+1</text></g>
  <g class="sr-value weak"><rect x="151" y="226" width="28" height="20" rx="6"/><text x="165" y="241">0</text></g>
  <g class="sr-value"><rect x="115" y="165" width="28" height="20" rx="6"/><text x="129" y="180">+1</text></g>
  <g class="sr-value weak"><rect x="151" y="104" width="28" height="20" rx="6"/><text x="165" y="119">0</text></g>
  <g class="sr-value"><rect x="221" y="104" width="28" height="20" rx="6"/><text x="235" y="119">+1</text></g>
  <g class="sr-def"><rect x="275" y="166" width="28" height="18" rx="6"/><text x="289" y="179">0</text></g>
  <text x="448" y="139" class="sr-note">общая сторона</text><line class="sr-note-line" x1="438" y1="143" x2="278" y2="165"/>
  <text x="448" y="163" class="sr-note">слева: F +2 атакующего</text>
  <text x="448" y="183" class="sr-note">справа: B 0 защитника</text>
  <text x="448" y="218" class="sr-note">у pointy-top гекса нет</text>
  <text x="448" y="238" class="sr-note">стороны строго сверху или снизу</text>
</svg>
<figcaption><b>Правило стороны.</b> Соседние клетки соприкасаются общей стороной. Для каждого корабля берётся число на его стороне, обращённой к другому кораблю. Угол гекса никогда не является сектором.</figcaption>
</figure>'''


def ship_card(s: dict) -> str:
    f = FACTIONS[s["faction"]]
    hyper = "нет" if s["hyperdrive"] is None else f'класс {s["hyperdrive"]["class"]}'
    rng = ("вплотную" if s["weapon"]["max_range"] == 1
           else f'до {s["weapon"]["max_range"]} кл. (−{s["weapon"]["range_penalty_per_hex"]}/кл.)')
    abils = "".join(
        f'<li><b>{e(ABIL[a["id"]]["display_name"])}.</b> {e(ABIL[a["id"]]["text"])}</li>'
        for a in s["abilities"])
    tags = []
    if s["unique"]:
        tags.append('<span class="tag tag-uniq">именной</span>')
    if s["legacy_v3"]:
        tags.append('<span class="tag">из правил v3</span>')
    if not s["draftable"]:
        tags.append('<span class="tag tag-off">вне драфта</span>')
    return f'''<article class="card" data-faction="{e(s['faction'])}" data-era="{e(s['era'])}"
  data-role="{e(s['role'])}" data-name="{e(s['display_name'].lower())}" style="--fc:{e(f['color'])}">
  <header class="card-head">
    <div class="card-titles">
      <h4>{e(s['display_name'])}</h4>
      <p class="card-sub">{e(f['short'])} · {e(ROLE_RU[s['role']])} · {e(ERA_SHORT[s['era']])}</p>
    </div>
    <div class="cost" title="Стоимость в драфте">{s['draft_cost']}</div>
  </header>
  {img_slot(s['display_name'], s['display_name'])}
  <div class="card-body">
    <div class="stats">
      <div><span>Корпус</span><b>{s['max_hp']}</b></div>
      <div><span>Щит</span><b>{s['max_shield']}</b></div>
      <div><span>Дальность</span><b>{e(rng)}</b></div>
      <div><span>Гипердрайв</span><b>{e(hyper)}</b></div>
      <div><span>Поворот</span><b>{s['engine']['pivot_cost']} зар.</b></div>
      <div><span>Форсаж</span><b>{'да' if s['engine']['boost'] else 'нет'}</b></div>
    </div>
    {arc_wheel(s['arc_modifiers'], f['color'])}
  </div>
  {'<ul class="abils">' + abils + '</ul>' if abils else ''}
  <footer class="tags">{''.join(tags)}</footer>
</article>'''


def hero_card(h: dict) -> str:
    f = FACTIONS[h["faction"]]
    a = h["ability"]
    kind = {"active": "действие", "reaction": "реакция", "passive": "пассивная"}[a["kind"]]
    uses = ("постоянно" if a["uses_per_match"] == 0
            else f'{a["uses_per_match"]} раз(а) за матч')
    charges = a["cost"]["charges"]
    syn = h.get("synergy")
    syn_html = (f'<div class="syn"><h5>Синергия · {e(syn["name"])}</h5><p>{e(syn["text"])}</p></div>'
                if syn else "")
    return f'''<article class="card hero" data-faction="{e(h['faction'])}" data-era="{e(h['era'])}"
  data-role="hero" data-name="{e(h['display_name'].lower())}" style="--fc:{e(f['color'])}">
  <header class="card-head">
    <div class="card-titles">
      <h4>{e(h['display_name'])}</h4>
      <p class="card-sub">{e(f['short'])} · {e(ERA_SHORT[h['era']])}</p>
    </div>
  </header>
  {img_slot(h['display_name'], h['display_name'])}
  <p class="lore">{e(h['description'])}</p>
  <div class="ability">
    <h5>{e(a['name'])}</h5>
    <p>{e(a['text'])}</p>
    <p class="meta">{e(kind)} · {e(uses)}{f' · {charges} зар.' if charges else ' · без зарядов'}</p>
  </div>
  {syn_html}
</article>'''


def rows(header: list[str], data: list[list[str]], cls: str = "") -> str:
    th = "".join(f"<th>{e(c)}</th>" for c in header)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in data)
    return (f'<div class="tablewrap"><table class="{cls}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{tr}</tbody></table></div>')


# ---------------------------------------------------------------------------
# Оформление. Направление — «телеметрия»: холодная бумага с синим уклоном,
# почти чёрные чернила, один акцент (сигнальный янтарь), остальное красят
# цвета фракций из данных. Шрифты: Oswald (узкий гротеск — заголовки и
# подписи), PT Serif (основной текст, кириллица), JetBrains Mono (цифры).
# ---------------------------------------------------------------------------

CSS = """
:root{
  --paper:#e9edf2; --card:#ffffff; --ink:#111823; --muted:#5b6777;
  --line:#ccd5de; --accent:#b0701c; --signal:#2c6b8a; --warn:#8d3320;
  --shadow:0 1px 2px rgba(17,24,35,.06), 0 10px 26px -18px rgba(17,24,35,.4);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --paper:#0c1118; --card:#151c26; --ink:#e3e9f1; --muted:#94a2b4;
    --line:#222c39; --accent:#d9a04a; --signal:#6ba8c6; --warn:#cc6a52;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 12px 30px -20px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"]{
  --paper:#0c1118; --card:#151c26; --ink:#e3e9f1; --muted:#94a2b4;
  --line:#222c39; --accent:#d9a04a; --signal:#6ba8c6; --warn:#cc6a52;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 12px 30px -20px rgba(0,0,0,.9);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font-family:"PT Serif",Georgia,serif; font-size:17px; line-height:1.62;
  -webkit-text-size-adjust:100%;
}
h1,h2,h3,h4,h5,.ui{font-family:Oswald,"Arial Narrow",system-ui,sans-serif; font-weight:500;
  text-wrap:balance; letter-spacing:.01em}
b,strong{font-weight:700}
a{color:var(--signal)}
.wrap{max-width:1180px; margin:0 auto; padding-inline:20px; padding-block:0}

/* Шапка */
.mast{position:relative; overflow:hidden; border-bottom:1px solid var(--line);
  background:linear-gradient(180deg, color-mix(in srgb, var(--signal) 9%, var(--paper)), var(--paper))}
.mast .hexes{position:absolute; inset:0; opacity:.5; pointer-events:none}
.mast-in{position:relative; padding-block:clamp(34px,7vw,74px) clamp(26px,5vw,46px)}
.eyebrow{font-family:Oswald,sans-serif; text-transform:uppercase; letter-spacing:.22em;
  font-size:12px; color:var(--accent); margin:0 0 10px}
h1{font-size:clamp(34px,7.5vw,62px); line-height:1.02; margin:0 0 14px; font-weight:600;
  text-transform:uppercase; letter-spacing:.005em}
.lede{max-width:64ch; font-size:clamp(17px,2.2vw,20px); color:var(--ink); margin:0 0 22px}
.mast-meta{display:flex; flex-wrap:wrap; gap:10px 26px; font-family:Oswald,sans-serif;
  font-size:13px; text-transform:uppercase; letter-spacing:.12em; color:var(--muted)}
.mast-meta b{color:var(--ink); font-weight:500; font-variant-numeric:tabular-nums}

/* Навигация */
nav.toc{position:sticky; top:env(safe-area-inset-top,0px); z-index:20;
  background:color-mix(in srgb, var(--paper) 88%, transparent);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line)}
nav.toc ul{display:flex; gap:2px; overflow-x:auto; list-style:none; margin:0;
  padding:8px 20px; max-width:1180px; margin-inline:auto; scrollbar-width:thin}
nav.toc a{display:block; white-space:nowrap; padding:6px 11px; border-radius:3px;
  font-family:Oswald,sans-serif; font-size:13px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--muted); text-decoration:none}
nav.toc a:hover{color:var(--ink); background:color-mix(in srgb, var(--signal) 12%, transparent)}

/* Секции */
section{padding-block:clamp(30px,5vw,54px); border-bottom:1px solid var(--line)}
section:last-of-type{border-bottom:0}
.sec-head{display:flex; align-items:baseline; gap:14px; margin-bottom:6px}
.sec-num{font-family:"JetBrains Mono",ui-monospace,monospace; font-size:13px; color:var(--accent);
  font-variant-numeric:tabular-nums}
h2{font-size:clamp(24px,4vw,34px); margin:0; text-transform:uppercase; letter-spacing:.02em}
h3{font-size:20px; margin:30px 0 8px}
h4{font-size:17px; margin:22px 0 6px}
p,ul,ol{max-width:68ch}
section > p, section > ul, section > ol{margin-block:0 14px}
ul,ol{padding-left:22px}
li{margin-block:4px}
.note{border-left:3px solid var(--accent); background:color-mix(in srgb, var(--accent) 7%, transparent);
  padding:12px 16px; margin:18px 0; max-width:68ch; font-size:16px}
.note b{font-family:Oswald,sans-serif; font-weight:500; letter-spacing:.04em}

/* Таблицы */
.tablewrap{overflow-x:auto; margin:16px 0; border:1px solid var(--line); border-radius:4px;
  background:var(--card)}
table{border-collapse:collapse; width:100%; font-size:15px;
  font-family:-apple-system,Segoe UI,Roboto,sans-serif}
th{font-family:Oswald,sans-serif; font-weight:500; text-transform:uppercase; font-size:12px;
  letter-spacing:.09em; text-align:left; color:var(--muted); padding:9px 12px;
  border-bottom:1px solid var(--line); white-space:nowrap}
td{padding:9px 12px; border-bottom:1px solid color-mix(in srgb, var(--line) 55%, transparent);
  vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td.num,th.num{text-align:right}
.num,td.num,th.num{font-variant-numeric:tabular-nums; font-family:"JetBrains Mono",ui-monospace,monospace}

/* Плитки состава */
.grid-tiles{display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
  margin:18px 0; max-width:none}
.tile{background:var(--card); border:1px solid var(--line); border-radius:4px; padding:14px 16px}
.tile b{display:block; font-family:Oswald,sans-serif; font-size:28px; font-weight:500;
  line-height:1; font-variant-numeric:tabular-nums}
.tile span{display:block; margin-top:6px; font-size:14px; color:var(--muted)}

/* Фильтры и карточки */
.filters{display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:18px 0 22px}
.filters button{font-family:Oswald,sans-serif; font-size:12px; text-transform:uppercase;
  letter-spacing:.08em; padding:6px 12px; border-radius:99px; cursor:pointer;
  border:1px solid var(--line); background:var(--card); color:var(--muted)}
.filters button[aria-pressed="true"]{background:var(--ink); color:var(--paper); border-color:var(--ink)}
.filters input{flex:1 1 180px; min-width:140px; padding:7px 12px; border-radius:99px;
  border:1px solid var(--line); background:var(--card); color:var(--ink); font:inherit; font-size:15px}
.filters input:focus-visible, .filters button:focus-visible, a:focus-visible{outline:2px solid var(--signal);
  outline-offset:2px}
.deck{display:grid; gap:14px; grid-template-columns:repeat(auto-fill,minmax(258px,1fr))}
.card{background:var(--card); border:1px solid var(--line); border-top:3px solid var(--fc,var(--accent));
  border-radius:4px; padding:14px; box-shadow:var(--shadow); display:flex; flex-direction:column; gap:10px}
.card-head{display:flex; justify-content:space-between; align-items:flex-start; gap:10px}
.card h4{margin:0; font-size:18px; line-height:1.2}
.card-sub{margin:3px 0 0; font-family:Oswald,sans-serif; font-size:11.5px; text-transform:uppercase;
  letter-spacing:.09em; color:var(--muted)}
.cost{font-family:Oswald,sans-serif; font-size:24px; line-height:1; padding:6px 10px; border-radius:3px;
  background:color-mix(in srgb, var(--fc) 16%, transparent); color:var(--ink);
  font-variant-numeric:tabular-nums}
.slot{display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px;
  aspect-ratio:16/9; max-width:100%; border:1px dashed var(--line); border-radius:3px;
  text-decoration:none; color:var(--muted); background:color-mix(in srgb, var(--fc) 5%, transparent)}
.slot-glyph{font-size:22px; opacity:.5}
.slot-text{font-family:Oswald,sans-serif; font-size:12px; letter-spacing:.06em; text-align:center;
  padding-inline:8px; color:var(--ink)}
.slot-hint{font-size:10.5px; letter-spacing:.05em; font-family:Oswald,sans-serif}
.card-body{display:flex; gap:10px; align-items:center}
.stats{flex:1; display:grid; grid-template-columns:1fr; gap:2px; font-size:13.5px;
  font-family:-apple-system,Segoe UI,Roboto,sans-serif}
.stats div{display:flex; justify-content:space-between; gap:8px; border-bottom:1px dotted var(--line)}
.stats span{color:var(--muted)}
.stats b{font-variant-numeric:tabular-nums; font-weight:600}
.wheel{width:96px; height:96px; flex:none}
.wheel-badge{fill:var(--card); stroke:var(--line); stroke-width:1.2}
.wheel-num{font-family:"JetBrains Mono",monospace; font-size:11px; fill:var(--ink)}
.sector-rule{max-width:760px; margin:20px 0; padding:14px 16px 12px; border:1px solid var(--line);
  border-radius:5px; background:var(--card)}
.sector-rule svg{display:block; width:100%; max-height:440px}
.sector-rule figcaption{max-width:66ch; margin:8px auto 0; color:var(--muted); font-size:14px;
  text-align:center}
.sector-rule figcaption b{color:var(--ink)}
.sr-title,.sr-label,.sr-note,.sr-value text,.sr-def text{font-family:Oswald,sans-serif}
.sr-title{font-size:14px; letter-spacing:.12em; fill:var(--ink)}
.sr-label{font-size:11px; letter-spacing:.1em; fill:var(--muted)}
.sr-target{fill:color-mix(in srgb,var(--warn) 7%,var(--paper)); stroke:var(--warn); stroke-width:2}
.sr-ship{fill:color-mix(in srgb,var(--signal) 8%,var(--paper)); stroke:var(--signal); stroke-width:2}
.sr-contact{stroke:var(--accent); stroke-width:6; stroke-linecap:round}
.sr-course{fill:none; stroke:var(--accent); stroke-width:2; stroke-dasharray:6 5}
.sr-arrow{fill:var(--accent)}
.sr-mini{fill:var(--signal); stroke:var(--ink); stroke-width:1.5}
.sr-mini.target{fill:var(--warn)}
.sr-value rect{fill:var(--card); stroke:var(--signal); stroke-width:1.5}
.sr-value text,.sr-def text{font-size:13px; font-weight:600; text-anchor:middle; fill:var(--ink)}
.sr-value.strong rect{stroke:var(--accent); stroke-width:2}
.sr-value.weak rect{stroke:var(--muted)}
.sr-def rect{fill:var(--card); stroke:var(--warn); stroke-width:1.5}
.sr-note{font-size:12px; fill:var(--muted)}
.sr-note-line{stroke:var(--muted); stroke-width:1}
.abils{margin:0; padding-left:18px; font-size:13.5px; color:var(--ink)}
.abils b{font-family:Oswald,sans-serif; font-weight:500}
.lore{margin:0; font-size:14px; color:var(--muted); font-style:italic}
.ability{border-top:1px solid var(--line); padding-top:9px}
.ability h5,.syn h5{margin:0 0 4px; font-size:14px; letter-spacing:.04em; text-transform:uppercase}
.ability p,.syn p{margin:0; font-size:14px; max-width:none}
.ability .meta{margin-top:5px; font-family:Oswald,sans-serif; font-size:11px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--muted)}
.syn{border-top:1px solid var(--line); padding-top:9px}
.syn h5{color:var(--accent)}
.tags{display:flex; flex-wrap:wrap; gap:5px; margin-top:auto}
.tag{font-family:Oswald,sans-serif; font-size:10.5px; letter-spacing:.08em; text-transform:uppercase;
  padding:2px 7px; border-radius:99px; border:1px solid var(--line); color:var(--muted)}
.tag-uniq{border-color:var(--accent); color:var(--accent)}
.tag-off{border-color:var(--warn); color:var(--warn)}
.count{font-family:Oswald,sans-serif; font-size:12px; letter-spacing:.08em; color:var(--muted);
  text-transform:uppercase}
footer.colophon{padding-block:34px; color:var(--muted); font-size:14.5px}
footer.colophon p{max-width:68ch}
@media (max-width:520px){
  body{font-size:16px}
  .card-body{flex-direction:column; align-items:stretch}
  .wheel{align-self:center}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
@media print{
  nav.toc,.filters,.slot-hint{display:none!important}
  body{background:#fff; color:#000; font-size:11pt}
  .card{break-inside:avoid; box-shadow:none}
  section{break-before:page; border:0}
  .mast{border:0}
  a{color:#000; text-decoration:none}
}
"""

JS = """
(function(){
  var deck=document.getElementById('deck');
  if(!deck) return;
  var cards=[].slice.call(deck.querySelectorAll('.card'));
  var search=document.getElementById('q');
  var counter=document.getElementById('deck-count');
  var state={faction:'all', kind:'all', q:''};
  function apply(){
    var shown=0;
    cards.forEach(function(c){
      var okF = state.faction==='all' || c.dataset.faction===state.faction;
      var okK = state.kind==='all'
        || (state.kind==='hero' ? c.dataset.role==='hero' : c.dataset.role!=='hero');
      var okQ = !state.q || c.dataset.name.indexOf(state.q)>-1;
      var vis = okF && okK && okQ;
      c.hidden = !vis;
      if(vis) shown++;
    });
    if(counter) counter.textContent = shown + ' из ' + cards.length;
  }
  [].slice.call(document.querySelectorAll('[data-filter]')).forEach(function(btn){
    btn.addEventListener('click', function(){
      var group=btn.dataset.filter, value=btn.dataset.value;
      state[group]=value;
      [].slice.call(document.querySelectorAll('[data-filter="'+group+'"]')).forEach(function(b){
        b.setAttribute('aria-pressed', String(b===btn));
      });
      apply();
    });
  });
  if(search){
    search.addEventListener('input', function(){
      state.q = search.value.trim().toLowerCase();
      apply();
    });
  }
  apply();
})();
"""


HEX_BG = ('<svg class="hexes" viewBox="0 0 800 260" preserveAspectRatio="xMidYMid slice" '
          'aria-hidden="true"><defs><pattern id="hx" width="52" height="60" '
          'patternUnits="userSpaceOnUse" patternTransform="translate(0 0)">'
          '<path d="M26 2 L50 16 L50 44 L26 58 L2 44 L2 16 Z" fill="none" '
          'stroke="currentColor" stroke-width="1" opacity="0.25"/>'
          '<path d="M78 2 L102 16 L102 44 L78 58 L54 44 L54 16 Z" fill="none" '
          'stroke="currentColor" stroke-width="1" opacity="0.25"/></pattern></defs>'
          '<rect width="800" height="260" fill="url(#hx)" color="var(--signal)"/></svg>')

SECTIONS = [
    ("sostav", "Состав игры"),
    ("podgotovka", "Подготовка"),
    ("hod", "Ход игрока"),
    ("dvizhenie", "Движение"),
    ("boy", "Бой"),
    ("abordazh", "Абордаж и таран"),
    ("giper", "Гиперпространство"),
    ("pole", "Поле и местность"),
    ("sobytiya", "События"),
    ("piraty", "Пираты"),
    ("konec", "Конец игры"),
    ("frakcii", "Фракции"),
    ("scenarii", "Сценарии"),
    ("kartoteka", "Картотека"),
    ("prilozhenie", "Приложение"),
]


def build() -> str:
    draftable = [s for s in SHIPS if s["draftable"]]
    playable_factions = [f for f in FACTIONS.values() if not f["npc"]]
    budget = GAME["draft"]["budget"]
    fleet = GAME["draft"]["fleet_size"]
    deck = EVENTS["deck_size"]

    p: list[str] = []
    p.append('<title>Эпохи и фракции</title>')
    p.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
    p.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
    p.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
             'family=Oswald:wght@400;500;600&family=PT+Serif:ital,wght@0,400;0,700;1,400&'
             'family=JetBrains+Mono:wght@400;600&display=swap&subset=cyrillic,latin">')
    p.append(f"<style>{CSS}</style>")

    # --- шапка -------------------------------------------------------------
    p.append(f'''<header class="mast">{HEX_BG}<div class="wrap mast-in">
  <p class="eyebrow">Звёздные войны · правила v4.0</p>
  <h1>Эпохи и фракции</h1>
  <p class="lede">Настольная космическая стратегия на поле из {BOARD["cell_count"]} гексов:
  флот из {fleet} кораблей, герой во главе, кубики решают бой. Расширение домашних правил
  братьев Григиных — те же корабли и герои, плюс фракции, эпохи, дальний огонь,
  гиперпрыжок, астероиды, события и пираты.</p>
  <div class="mast-meta">
    <span>Игроков <b>2–4</b></span>
    <span>Партия <b>40–70 мин</b></span>
    <span>Возраст <b>10+</b></span>
    <span>Кораблей <b>{len(SHIPS)}</b></span>
    <span>Героев <b>{len(HEROES)}</b></span>
    <span>Фракций <b>{len(playable_factions)}+1</b></span>
  </div>
</div></header>''')

    nav = "".join(f'<li><a href="#{sid}">{e(name)}</a></li>' for sid, name in SECTIONS)
    p.append(f'<nav class="toc" aria-label="Содержание"><ul>{nav}</ul></nav>')
    p.append('<main class="wrap">')

    def sec(idx: int, sid: str, title: str, body: str) -> None:
        p.append(f'<section id="{sid}"><div class="sec-head">'
                 f'<span class="sec-num">{idx:02d}</span><h2>{e(title)}</h2></div>{body}</section>')

    # --- 01 состав ---------------------------------------------------------
    tiles = [
        (BOARD["cell_count"], "клеток поля", "правильный гексагон радиуса 4"),
        (len(SHIPS), "карточек кораблей", f"из них {len(draftable)} доступны в драфте"),
        (len(HEROES), "карточек героев", "все из девяти эпизодов"),
        (deck, "карт событий", f"{len(EVENTS['cards'])} видов"),
        (len(TERRAIN), "типа местности", "астероиды, туманности, обломки"),
        (len(playable_factions), "играбельные фракции", "плюс пираты под управлением поля"),
    ]
    tiles_html = "".join(f'<div class="tile"><b>{n}</b><span><b style="font-size:inherit;'
                         f'font-family:inherit">{e(t)}</b><br>{e(sub)}</span></div>'
                         for n, t, sub in tiles)
    sec(1, "sostav", "Состав игры", f'''
<p>Всё, что нужно для партии. Фигурки кораблей и жетоны — из исходной коробки;
новые корабли и герои печатаются карточками из раздела «Картотека».</p>
<div class="grid-tiles">{tiles_html}</div>
<h3>Кроме того</h3>
<ul>
  <li><b>Кубики:</b> два d6 атакующему, один d6 защищающемуся, один d4 на взрывы мин и бомб.</li>
  <li><b>Жетоны зарядов</b> — до 5 на корабль; удобно считать кубиком d6 рядом с фигуркой.</li>
  <li><b>Жетоны урона и щита</b> — корпус до 14, щит до 3.</li>
  <li><b>Жетоны местности</b> — накладываются на клетки поля при подготовке.</li>
  <li><b>Жетоны мин и бомб</b> — для способностей Джанго и Бобы Фетта.</li>
</ul>''')

    # --- 02 подготовка -----------------------------------------------------
    sec(2, "podgotovka", "Подготовка", f'''
<p>Партию начинает игрок, который последним смотрел «Звёздные войны» — правило
из первой редакции, и оно никуда не делось.</p>
<ol>
  <li><b>Выбор героя.</b> Против часовой стрелки, по одному. Герой задаёт <b>фракцию</b>
  и <b>эпоху</b> вашего флота: республиканскому герою — республиканские корабли,
  имперскому — имперские.</li>
  <li><b>Драфт из общего каталога.</b> Каждая карточка — в одном экземпляре. Игроки берут по
  очереди, каждым ходом — любую из своих четырёх фигурок: героя или корабль, в любом порядке.
  Кораблей — {fleet}, бюджет — <b>{budget} очков</b> (цена — в самоцвете на карточке).</li>
  <li><b>Расстановка местности.</b> {GAME["terrain"]["placement"]}</li>
  <li><b>Расстановка флотов.</b> По клеткам сценария, носом к центру поля.</li>
  <li><b>Колода событий.</b> Перемешивается и кладётся рядом; первая карта открывается
  в начале <b>второго</b> раунда.</li>
  <li><b>Заряды.</b> Каждый корабль начинает с {GAME["initial_charges"]} зарядами,
  максимум — {GAME["max_charges"]}.</li>
</ol>
<h3>Ограничения драфта</h3>
<ul>
  <li>Все корабли — эпохи вашего героя или «вне эпохи».</li>
  <li>Не больше <b>одного</b> корабля чужой фракции: он не получает фракционную черту
  и не считается для синергии героя.</li>
  <li>Не больше <b>одного</b> крупного корабля и <b>одного</b> именного.</li>
  <li>Повторов нет: взятую карточку соперник уже не возьмёт.</li>
  <li>Станции («Звезда Смерти») в драфт не берутся — только сценарий «Осада флагмана».</li>
  <li>«Фантом» не выбирается: он появляется только из взорванного «Призрака».</li>
</ul>
<div class="note"><b>Почему бюджет, а не «группы 1 и 2».</b> В первой редакции корабли делились
на две группы, и это грубо ограничивало перекос. Цена в очках делает то же самое точнее:
сильный корабль просто дороже, и за «Сокол тысячелетия» вы платите двумя истребителями.</div>''')

    # --- 03 ход ------------------------------------------------------------
    sec(3, "hod", "Ход игрока", f'''
<p>Раунд состоит из активаций: каждый живой корабль получает ровно одну активацию за раунд.
Ход переходит по часовой стрелке.</p>
<h3>Активация одного корабля</h3>
<p>Выберите свой неактивированный корабль и тратьте его заряды, пока не остановитесь:</p>
{rows(["Действие", "Стоимость", "Сколько раз"], [
    ["Шаг на соседнюю клетку (в любую из шести сторон)",
     f'{GAME["move_cost"]} заряд', "сколько хватит зарядов"],
    ["Поворот на одну грань вправо или влево",
     f'{GAME["rotate_cost"]} заряд (тяжёлым кораблям — 2)', "сколько хватит зарядов"],
    ["Форсаж: 2 клетки по прямой", "2 заряда", "если корабль его умеет"],
    ["Атака", "бесплатно", f'{GAME["attacks_per_activation"]} раз за активацию'],
    ["Гиперпрыжок", "по классу гипердрайва", "один на активацию"],
    ["Абордаж", f'{GAME["combat"]["boarding"]["cost_charges"]} заряда', "вместо атаки"],
    ["Таран", "все оставшиеся, минимум 2", "завершает активацию"],
])}
<h3>Фаза восстановления</h3>
<p>В конце раунда каждый корабль получает <b>1 заряд</b> (максимум {GAME["max_charges"]}).
Корабль, у которого к концу раунда осталось 0 корпуса, взрывается и убирается с поля —
если у него нет свойства, срабатывающего при взрыве.</p>''')

    # --- 04 движение -------------------------------------------------------
    sec(4, "dvizhenie", "Движение", '''
<p>Корабль ходит на соседнюю клетку в <b>любую</b> из шести сторон за один заряд —
курс при этом не меняется. Поворот стоит отдельный заряд и меняет только то,
каким бортом вы повёрнуты к противнику.</p>
<p>Отсюда главный тактический вопрос игры: тратить заряды на то, чтобы зайти врагу в корму,
или беречь их на выстрел и отход. Нос бьёт сильнее всего, корма защищена хуже всего —
у большинства кораблей.</p>
<h3>Профиль двигателя</h3>
<ul>
  <li><b>Истребители и малые корабли:</b> шаг 1 заряд, поворот 1 заряд, часто доступен форсаж.</li>
  <li><b>Крупные корабли и корветы:</b> шаг 1 заряд, поворот <b>2 заряда</b>, форсажа нет.
  Разворачиваться такой громадине дорого — планируйте курс заранее.</li>
  <li><b>Станции:</b> не двигаются вообще, только поворачиваются.</li>
</ul>
<p>Две фигурки не могут стоять на одной клетке, и никто не выходит за край поля.</p>''')

    # --- 05 бой ------------------------------------------------------------
    sec(5, "boy", "Бой", f'''
<p>Атака бесплатна, но одна за активацию. Атакующий бросает <b>2d6</b> и прибавляет
модификатор того сектора, которым он подлетел к цели. Защищающийся бросает <b>1d6 + 1</b>
и прибавляет модификатор своего сектора, обращённого к атакующему.</p>
<p>Разница сил — это урон. Сначала он снимает <b>щит</b>, остаток уходит в <b>корпус</b>.
Ничья — никто ничего не теряет. Щит в этой редакции <b>не восстанавливается</b>
сам: только способностями.</p>
<div class="note"><b>Пример.</b> X-wing заходит «Звёздному разрушителю» в корму.
Атакующий: 2d6 = 4 + 5 = 9, его носовой сектор +2 → <b>11</b>.
Защищающийся: d6 = 3, плюс 1, кормовой сектор разрушителя +1 → <b>5</b>.
Разница 6: щит разрушителя (1) снимается полностью, корпус теряет 5.</div>
<h3>Сектора</h3>
<p>Шесть секторов по кругу, считая от носа по часовой стрелке: {", ".join(
    f"<b>{s}</b> — {r}" for s, r in zip(SECTORS, SECTOR_RU))}.
Каждый сектор соответствует <b>одной стороне</b> гекса, а не его углу. На карточке
нос всегда сверху, и каждое из шести чисел стоит в середине своей стороны.</p>
<p>При атаке соседнего корабля две клетки обязательно соприкасаются общей стороной.
Атакующий применяет число на своей стороне этого контакта; защищающийся — число на своей
стороне того же контакта. Касание угла не создаёт соседство и не задаёт сектор.</p>
{sector_contact_diagram()}
<h3>Дистанция</h3>
{rows(["Дистанция", "Кто стреляет", "Штраф"], [
    ["1 — вплотную", "любой корабль", "нет"],
    ["2 и дальше, в пределах дальности корабля",
     "только если цель в разрешённом секторе (нос / нос и борта / любой)",
     f"−{GAME['combat']['ranged_default_penalty_per_hex']} за каждую клетку сверх первой"],
    ["Дальше предельной дальности", "никто", "—"],
])}
<p>Для выстрела на дистанции 2+ нужна <b>линия огня</b>: между вами и целью не должно быть
астероидов, туманности, остова станции или чужого крупного корабля.</p>
<p><b>Звезда Смерти</b> работает по тому же правилу: дальность 6, штраф −2 за клетку,
любой сектор. Числа из первой редакции не изменились — изменилась только запись.</p>''')

    b = GAME["combat"]["boarding"]
    sec(6, "abordazh", "Абордаж и таран", f'''
<h3>Абордаж</h3>
<p>Захват вместо расстрела. Доступен поддержке, транспортам, фрахтовикам, корветам
и крупным кораблям, а также любому кораблю с абордажными капсулами.</p>
<ul>
  <li>Дистанция 1, стоимость {b["cost_charges"]} заряда, вместо атаки.</li>
  <li>Бросок: {e(b["roll"])}.</li>
  <li><b>Успех:</b> {e(b["on_success"])}</li>
  <li><b>Неудача:</b> {e(b["on_failure"])}</li>
  <li>Не берутся на абордаж дроидные корабли (некого брать в плен) и станции.</li>
</ul>
<h3>Таран</h3>
<p>Отчаянный размен. Корабль на соседней клетке тратит {e(GAME["combat"]["ram"]["cost_charges"])}
зарядов: {e(GAME["combat"]["ram"]["damage"])} Активация на этом заканчивается.</p>
<div class="note"><b>Гипертаран</b> — не таран, а способность вице-адмирала Холдо:
корабль уходит в прыжок прямо сквозь строй, уничтожается сам и бьёт 1d6 по всем,
кто оказался на линии. Включая ваших.</div>''')

    hj = GAME["hyperspace"]
    cost_rows = [[f"Класс {k}", f"{v} заряд(а)",
                  {"0": "легендарный — «Сокол тысячелетия»", "1": "быстрый",
                   "2": "обычный", "3": "медленный", "4": "аварийный"}[k]]
                 for k, v in hj["charge_cost_by_class"].items()]
    sec(7, "giper", "Гиперпространство", f'''
<p>Прыжок — способ выйти из безнадёжной позиции, перебросить корабль через всё поле
или спасти подбитый корпус. Объявляется в свою активацию; корабль уходит с поля
в её конце.</p>
{rows(["Гипердрайв", "Цена прыжка", "Кто носит"], cost_rows)}
<p><b>Пока корабль в гиперпространстве</b>, его нельзя атаковать, он не занимает клетку
и не считается уничтоженным. В начале вашей следующей активации он возвращается
на любую свободную клетку, <b>не соседнюю с вражеским кораблём</b>, курсом на выбор.</p>
<h3>Когда прыгнуть нельзя</h3>
<ul>
  <li>Из гравитационного колодца и с соседних с ним клеток.</li>
  <li>В радиусе 3 клеток от крейсера «Иммобилайзер» с гравипроекторами.</li>
  <li>Под «Торговой блокадой» Нута Ганрея — весь раунд.</li>
  <li>Кораблям без гипердрайва вообще: СИД, дроид-стервятник, Eta-2, «Дельта-7».
  Их привозит корабль-матка, и удирать им некуда.</li>
</ul>''')

    ter_rows = [[f'<b>{e(t["display_name"])}</b>',
                 "да" if t["passable"] else "нет",
                 "да" if t["blocks_line_of_fire"] else "нет",
                 e(t["text"])] for t in TERRAIN]
    setup_rows = [[e(next(x["display_name"] for x in TERRAIN if x["id"] == it["terrain"])),
                   f'<span class="num">{it["count"]}</span>']
                  for it in GAME["terrain"]["default_setup"]]
    sec(8, "pole", "Поле и местность", f'''
<p>Поле — правильный гексагон радиуса 4: <b>{BOARD["cell_count"]} клетки</b>, как
в самой первой редакции правил. Пустое поле — это дуэль на открытом месте;
местность превращает её в бой за укрытия.</p>
{rows(["Тип", "Проходима", "Перекрывает огонь", "Что делает"], ter_rows)}
<h3>Раскладка по умолчанию</h3>
{rows(["Местность", "Клеток"], setup_rows)}
<p>{e(GAME["terrain"]["placement"])}</p>''')

    ev_rows = [[f'<b>{e(c["display_name"])}</b>', f'<span class="num">{c["copies"]}</span>',
                e(c["text"])] for c in EVENTS["cards"]]
    sec(9, "sobytiya", "События", f'''
<p>В начале каждого раунда, начиная со второго, открывается верхняя карта колоды.
Событие действует на всех одинаково — это единственная случайность в игре, кроме кубиков,
и она симметрична. Когда колода кончается, её перемешивают заново.</p>
{rows(["Карта", "Копий", "Действие"], ev_rows)}''')

    sec(10, "piraty", "Пираты", f'''
<p>Третья сила на поле. Пиратские корабли не принадлежат никому: они ходят
<b>после всех игроков</b> и подчиняются жёсткому алгоритму — спорить не о чем,
считает любой игрок.</p>
<ol>
  {"".join(f"<li>{e(step)}</li>" for step in PIRATES["ai"]["steps"])}
</ol>
<p>{e(PIRATES["loot"]["text"])} {e(PIRATES["victory"]["text"])}</p>
<p>Пираты никогда не прыгают в гиперпространство, не пользуются событиями
и не стреляют друг в друга.</p>''')

    sec(11, "konec", "Конец игры", f'''
<p>Игра заканчивается, когда уничтожены все корабли всех игроков, кроме одного.
Победитель — тот, у кого остался хотя бы один неразрушенный корабль.</p>
<ul>
  <li>Корабли пиратов не считаются: их уничтожение не приближает победу.</li>
  <li>Если корабли последних противников гибнут одновременно — ничья.</li>
  <li>Если за {GAME["round_limit"]} раундов никто не победил — ничья.
  В сценарии «Осада флагмана» лимит свой: 20 раундов, и победа считается по станции.</li>
</ul>''')

    fac_rows = [[f'<b style="color:{e(f["color"])}">{e(f["display_name"])}</b>',
                 e(ERA_SHORT[f["era"]]),
                 f'<b>{e(f["trait"]["name"])}.</b> {e(f["trait"]["text"])}']
                for f in FACTIONS.values()]
    syn_heroes = [h for h in HEROES if h.get("synergy")]
    sec(12, "frakcii", "Фракции", f'''
<p>Фракция даёт <b>черту</b> — она работает всегда, без всяких условий и трат.
Империя давит раненых, повстанцы бьют в хвост, Первый Орден набирает силу на разгоне.</p>
{rows(["Фракция", "Эпоха", "Черта"], fac_rows)}
<h3>Синергия героя</h3>
<p>У {len(syn_heroes)} героев из {len(HEROES)} есть синергия — постоянный эффект,
который работает, пока во флоте есть корабли нужной фракции. Это награда за чистый флот:
смешанный отряд гибче, однофракционный — сильнее.</p>
<div class="note"><b>Сила единства (Падме Амидала).</b> За каждый республиканский корабль
в вашем флоте все ваши республиканские корабли получают +1 к силе атаки (максимум +3).
Если все три корабля республиканские — каждому ещё +1 корпуса и +1 щита.</div>''')

    sc_rows = []
    for sc in SCEN:
        seats = len(sc["seat_order"])
        extras = []
        if sc.get("pirates"):
            extras.append(f'пиратов: {sc["pirates"]}')
        if sc.get("faction_lock"):
            extras.append("фракции закреплены")
        if sc.get("seat_overrides"):
            extras.append("асимметричные бюджеты")
        sc_rows.append([f'<b>{e(sc["display_name"])}</b>',
                        f'<span class="num">{seats}</span>',
                        e(ERA_SHORT.get(sc.get("era", "any"), "—")),
                        e(sc["note"]) + (f' <i>({", ".join(extras)})</i>' if extras else "")])
    sec(13, "scenarii", "Сценарии", f'''
<p>Пять расстановок. «Дуэль эпохи» — базовая; «Классика 2×2» повторяет формат
первой редакции на поле из 61 клетки.</p>
{rows(["Сценарий", "Мест", "Эпоха", "Что в нём особенного"], sc_rows)}''')

    # --- 14 картотека ------------------------------------------------------
    fac_buttons = "".join(
        f'<button type="button" data-filter="faction" data-value="{e(fid)}" '
        f'aria-pressed="false">{e(f["short"])}</button>'
        for fid, f in FACTIONS.items())
    cards_html = "".join(ship_card(s) for s in sorted(
        SHIPS, key=lambda x: (x["faction"], -x["draft_cost"], x["id"])))
    cards_html += "".join(hero_card(h) for h in sorted(
        HEROES, key=lambda x: (x["faction"], x["id"])))
    sec(14, "kartoteka", "Картотека", f'''
<p>Все {len(SHIPS)} кораблей и {len(HEROES)} героев. Шестиугольник на карточке корабля —
модификаторы секторов: нос сверху, дальше по часовой стрелке. Число в рамке справа сверху —
цена в драфте.</p>
<p class="count">Изображений в проекте нет намеренно: слот на карточке открывает поиск
картинки в интернете, потом его заменит собственный рисунок.</p>
<div class="filters">
  <button type="button" data-filter="kind" data-value="all" aria-pressed="true">Всё</button>
  <button type="button" data-filter="kind" data-value="ship" aria-pressed="false">Корабли</button>
  <button type="button" data-filter="kind" data-value="hero" aria-pressed="false">Герои</button>
  <button type="button" data-filter="faction" data-value="all" aria-pressed="true">Все фракции</button>
  {fac_buttons}
  <input id="q" type="search" placeholder="Поиск по названию" aria-label="Поиск по названию">
  <span class="count" id="deck-count"></span>
</div>
<div class="deck" id="deck">{cards_html}</div>''')

    # --- 15 приложение -----------------------------------------------------
    ab_rows = [[f'<b>{e(a["display_name"])}</b>', e(a["text"]),
                f'<span class="num">{a["cost_points"]}</span>'] for a in ABIL.values()]
    sec(15, "prilozhenie", "Приложение", f'''
<h3>Откуда берётся цена корабля</h3>
<p>В первой редакции на карточке стояло «бой + защита» — оценка на глаз. Здесь цена считается
формулой, одинаковой для всех {len(SHIPS)} кораблей, а потом проверяется машинным прогоном
дуэлей.</p>
{rows(["Что считается", "Сколько"], [
    ["Корпус", "+1 за единицу"],
    ["Щит", "+2 за единицу (щит поглощает урон целиком, корпус тратится навсегда)"],
    ["Носовой сектор", "+2 за единицу (носом поворачиваются чаще всего)"],
    ["Остальные сектора", "+1 за единицу"],
    ["Каждая клетка дальности сверх первой", "+3 (право бить первым — самое дорогое в игре)"],
    ["Гипердрайв", "+3 … 0 по классу; −1, если гипердрайва нет"],
    ["Тяжёлый разворот / неподвижность", "−2 / −4"],
    ["Форсаж", "+1"],
    ["Способности", "по таблице ниже"],
    ["Итоговая цена", "сумма ÷ 2,5, округление вверх на половине, минимум 2"],
])}
<p>Проверка: каждый корабль сыграл со всеми остальными по 2000 дуэлей — 1 980 000 боёв.
Связь цены и доли побед — <b>0,95</b> из 1. Разбор отклонений лежит в
<code>reports/balance_v4_duel.md</code>.</p>
<h3>Способности кораблей</h3>
{rows(["Способность", "Что делает", "Очков"], ab_rows)}
<h3>Что изменилось по сравнению с прошлой редакцией</h3>
<ul>
  <li>Все 11 кораблей и 8 героев прошлых правил сохранены: корпус, щит и сектора у них
  те же, тексты способностей героев — дословно прежние.</li>
  <li>Поле вернулось к 61 клетке.</li>
  <li>Бой вплотную не изменился; добавились дальний огонь, абордаж и таран.</li>
  <li>Группы кораблей 1 и 2 заменены ценой в очках и ролями.</li>
</ul>''')

    p.append('</main>')
    p.append(f'''<footer class="colophon wrap">
  <p><b>Создатели игры:</b> братья Григины, Иван и Климентий. Первая редакция правил —
  их; эта редакция расширяет её, ничего не выбрасывая.</p>
  <p>Частный некоммерческий прототип. «Звёздные войны», названия кораблей и персонажей
  принадлежат Lucasfilm Ltd.; изображения в проект не включены. Перед любой публикацией
  игру нужно либо лицензировать, либо перевести на собственный мир — см.
  <code>LICENSES.md</code> и ADR-001.</p>
  <p>Страница собрана из данных <code>data/rulesets/v4/</code> командой
  <code>python3 tools/gen_rulebook.py</code>: правила и цифры на карточках не могут
  разойтись с игрой.</p>
</footer>''')
    p.append(f"<script>{JS}</script>")
    return "\n".join(p)





# ---------------------------------------------------------------------------
# Полное издание: карточки в духе коллекционных карточных игр, с картинками.
# Картинки — demo/assets/card_art (tools/fetch_card_art.py, Wookieepedia).
# Это частное издание (ADR-020, вариант А): файл лежит в репозитории и
# открывается через tools/model_preview/serve.py, публично не выкладывается.
# ---------------------------------------------------------------------------

ART_DIR = ROOT / "demo" / "assets" / "card_art"
FULL_OUT = ROOT / "docs" / "rulebook" / "rulebook_full.html"
ART_REL = "../../demo/assets/card_art/"          # путь от docs/rulebook/

# Собственные геометрические знаки фракций (не официальные логотипы), viewBox 0 0 24 24
EMBLEM = {
    "republic": '<circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" stroke-width="2"/>'
                + "".join(f'<rect x="11" y="1" width="2" height="5" fill="currentColor" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 45))
                + '<circle cx="12" cy="12" r="3" fill="currentColor"/>',
    "separatists": '<polygon points="12,2 21,7 21,17 12,22 3,17 3,7" fill="none" stroke="currentColor" stroke-width="2"/>'
                   '<ellipse cx="12" cy="12" rx="6" ry="3.6" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="#0b0e13"/>',
    "empire": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4"/>'
              + "".join(f'<rect x="10.8" y="3" width="2.4" height="7" fill="currentColor" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 60))
              + '<circle cx="12" cy="12" r="2.4" fill="currentColor"/>',
    "rebels": '<path d="M12 2 L16 12 L12 9.5 L8 12 Z" fill="currentColor"/>'
              '<path d="M4.5 12 A7.5 7.5 0 0 0 19.5 12" fill="none" stroke="currentColor" stroke-width="2.2"/>'
              '<path d="M12 15 L14 21 L10 21 Z" fill="currentColor"/>',
    "first_order": '<polygon points="12,2 20.5,7 20.5,17 12,22 3.5,17 3.5,7" fill="none" stroke="currentColor" stroke-width="1.8"/>'
                   + "".join(f'<rect x="11.3" y="3.5" width="1.4" height="5" fill="currentColor" transform="rotate({a} 12 12)"/>' for a in range(0, 360, 60))
                   + '<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/>',
    "resistance": '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/>'
                  '<path d="M12 4 L17 17 L12 14 L7 17 Z" fill="currentColor"/>',
    "bounty_hunters": '<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="2"/>'
                      '<rect x="11" y="1" width="2" height="6" fill="currentColor"/><rect x="11" y="17" width="2" height="6" fill="currentColor"/>'
                      '<rect x="1" y="11" width="6" height="2" fill="currentColor"/><rect x="17" y="11" width="6" height="2" fill="currentColor"/>'
                      '<circle cx="12" cy="12" r="2" fill="currentColor"/>',
    "pirates": '<rect x="11" y="1.5" width="2" height="21" rx="1" fill="currentColor" transform="rotate(-40 12 12)"/>'
               '<rect x="11" y="1.5" width="2" height="21" rx="1" fill="currentColor" transform="rotate(40 12 12)"/>'
               '<circle cx="12" cy="12" r="3.4" fill="#0b0e13" stroke="currentColor" stroke-width="1.8"/>',
}
# Герой без портрета показывает свой фирменный корабль
SIGNATURE_SHIP = {
    "obi_wan": "delta7_aethersprite", "anakin": "eta2_actis", "luke": "xwing_t65", "han_solo": "millennium_falcon",
    "darth_vader": "tie_advanced_x1", "phasma": "resurgent_destroyer", "jango_fett": "slave_1",
    "boba_fett": "slave_1", "padme_amidala": "naboo_royal_cruiser", "mace_windu": "delta7_aethersprite",
    "yoda": "delta7_aethersprite", "qui_gon_jinn": "naboo_royal_cruiser", "count_dooku": "providence",
    "general_grievous": "soulless_one", "nute_gunray": "munificent", "darth_maul": "vulture_droid",
    "emperor_palpatine": "death_star_1", "grand_moff_tarkin": "death_star_1", "admiral_piett": "executor",
    "leia_organa": "gr75_transport", "chewbacca": "millennium_falcon", "lando_calrissian": "millennium_falcon",
    "wedge_antilles": "xwing_t65", "admiral_ackbar": "mc80_home_one", "kylo_ren": "tie_silencer",
    "general_hux": "resurgent_destroyer", "snoke": "upsilon_shuttle", "rey": "millennium_falcon",
    "poe_dameron": "xwing_t70", "finn": "resistance_transport", "vice_admiral_holdo": "raddus_cruiser",
    "r2_d2": "xwing_t65",
}
SHIP_NAME = {s["id"]: s["display_name"] for s in SHIPS}


def art_path(kind: str, key: str) -> str | None:
    p = ART_DIR / kind / f"{key}.webp"
    return ART_REL + f"{kind}/{key}.webp" if p.exists() else None


_ART_MANIFEST: dict | None = None


def art_class(kind: str, key: str) -> str:
    """«scene» — картинка с фоном (заполняет окно), иначе прозрачный рендер на звёздах."""
    global _ART_MANIFEST
    if _ART_MANIFEST is None:
        mp = ART_DIR / "manifest.json"
        _ART_MANIFEST = json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    info = _ART_MANIFEST.get(f"{kind}/{key}") or {}
    return "" if info.get("transparent", True) else "scene"


def emblem(faction: str, cls: str = "emb") -> str:
    return f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true">{EMBLEM[faction]}</svg>'


def tcg_wheel(arcs: list[int]) -> str:
    """Шестигранник карточки: шесть чисел стоят на шести сторонах."""
    import math
    parts = ['<svg class="tw" viewBox="-50 -50 100 100" role="img" aria-label="Сектора: '
             + e(", ".join(f"{SECTORS[i]} {v:+d}" for i, v in enumerate(arcs))) + '">']
    radius = 40
    apothem = radius * math.cos(math.radians(30))
    for i, v in enumerate(arcs):
        a0, a1 = math.radians(-150 + i * 60), math.radians(-90 + i * 60)
        pts = f"0,0 {radius*math.cos(a0):.1f},{radius*math.sin(a0):.1f} {radius*math.cos(a1):.1f},{radius*math.sin(a1):.1f}"
        if v < 0:
            fill, op = "#e05a4f", 0.55
        else:
            fill, op = "var(--fc)", 0.14 + min(v, 7) * 0.12
        parts.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="{op:.2f}" stroke="#0b0e13" stroke-width="1.2"/>')
        am = math.radians(-120 + i * 60)
        tx, ty = apothem * math.cos(am), apothem * math.sin(am)
        parts.append(f'<rect x="{tx-10.5:.1f}" y="{ty-7:.1f}" width="21" height="14" rx="4" '
                     f'fill="#0b0e13" stroke="#8895a8" stroke-width="0.8"/>')
        parts.append(f'<text x="{tx:.1f}" y="{ty+3.6:.1f}" text-anchor="middle">{v:+d}</text>')
    parts.append('<polygon points="-28,-45 -19,-41 -25,-35" fill="#f0d27a"/>')
    parts.append('<circle r="6" fill="#0b0e13" stroke="#f0d27a" stroke-width="1.2"/></svg>')
    return "".join(parts)


def tcg_ship(s: dict) -> str:
    f = FACTIONS[s["faction"]]
    img = art_path("ships", s["id"])
    art = (f'<img class="{art_class("ships", s["id"])}" src="{img}" alt="{e(s["display_name"])}" loading="lazy">' if img
           else emblem(s["faction"], "emb-big"))
    w = s["weapon"]
    rng = "1" if w["max_range"] == 1 else f'{w["max_range"]} <small>−{w["range_penalty_per_hex"]}/кл</small>'
    hyper = "—" if s["hyperdrive"] is None else f'кл.{s["hyperdrive"]["class"]}'
    abils = "".join(f'<p><b>{e(ABIL[a["id"]]["display_name"])}.</b> {e(ABIL[a["id"]]["text"])}</p>'
                    for a in s["abilities"])
    text = abils or f'<p class="flav">{e(s["description"])}</p>'
    uniq = ' <span class="uniq" title="Именной: один на флот">◆</span>' if s["unique"] else ""
    off = "" if s["draftable"] else ' · <span class="off">вне драфта</span>'
    return f'''<article class="tcg" data-faction="{e(s['faction'])}" data-role="{e(s['role'])}"
  data-name="{e(s['display_name'].lower())}" style="--fc:{e(f['color'])}">
 <div class="tcg-in">
  <header class="tcg-top">{emblem(s['faction'])}<h4>{e(s['display_name'])}{uniq}</h4>
   <span class="gem" title="Цена в драфте">{s['draft_cost']}</span></header>
  <div class="tcg-art">{art}</div>
  <div class="tcg-type"><span>{e(f['short'])} · {e(ROLE_RU[s['role']])}</span><span>{e(ERA_SHORT[s['era']])}{off}</span></div>
  <div class="tcg-body">
   <div class="tcg-stats">{tcg_wheel(s['arc_modifiers'])}
    <dl>
     <div><dt>Корпус</dt><dd>{s['max_hp']}</dd></div>
     <div><dt>Щит</dt><dd>{s['max_shield']}</dd></div>
     <div><dt>Дальн.</dt><dd>{rng}</dd></div>
     <div><dt>Гипер</dt><dd>{hyper}</dd></div>
     <div><dt>Поворот</dt><dd>{s['engine']['pivot_cost'] if s['engine']['move_cost'] is not None else '—'}</dd></div>
    </dl></div>
   <div class="tcg-text">{text}</div>
  </div>
  <footer class="tcg-foot"><span>{'форсаж ✓' if s['engine']['boost'] else ''}</span><span>{e(s['id'])}</span></footer>
 </div>
</article>'''


def tcg_hero(h: dict) -> str:
    f = FACTIONS[h["faction"]]
    a, syn = h["ability"], h["synergy"]
    portrait = art_path("heroes", h["id"])
    ship = SIGNATURE_SHIP.get(h["id"])
    if portrait:
        art = f'<img class="portrait" src="{portrait}" alt="{e(h["display_name"])}" loading="lazy">'
    elif ship and art_path("ships", ship):
        art = (f'<img class="{art_class("ships", ship)}" src="{art_path("ships", ship)}" alt="{e(SHIP_NAME.get(ship, ""))}" loading="lazy">'
               f'<span class="sig">флагман: {e(SHIP_NAME.get(ship, ""))}</span>')
    else:
        art = emblem(h["faction"], "emb-big")
    kind = {"active": "действие", "reaction": "реакция", "passive": "пассивно"}[a["kind"]]
    uses = "постоянно" if a["uses_per_match"] == 0 else f'{a["uses_per_match"]}× за матч'
    cost = f' · {a["cost"]["charges"]} зар.' if a["cost"]["charges"] else ""
    return f'''<article class="tcg hero" data-faction="{e(h['faction'])}" data-role="hero"
  data-name="{e(h['display_name'].lower())}" style="--fc:{e(f['color'])}">
 <div class="tcg-in">
  <header class="tcg-top">{emblem(h['faction'])}<h4>{e(h['display_name'])}</h4><span class="gem hero-gem" title="Герой">★</span></header>
  <div class="tcg-art">{art}</div>
  <div class="tcg-type"><span>Герой · {e(f['short'])}</span><span>{e(ERA_SHORT[h['era']])}</span></div>
  <div class="tcg-hbody">
   <div class="tcg-text"><p><b>{e(a['name'])}</b> <i class="meta">{e(kind)} · {e(uses)}{e(cost)}</i></p><p>{e(a['text'])}</p></div>
   <div class="tcg-syn"><p><b>Синергия · {e(syn['name'])}</b></p><p>{e(syn['text'])}</p></div>
  </div>
  <footer class="tcg-foot"><span class="flav1">{e(h['description'])}</span></footer>
 </div>
</article>'''


TCG_CSS = """
.tcg{width:300px;min-height:420px;border-radius:14px;padding:6px;box-sizing:border-box;
  background:linear-gradient(155deg,#3a404b,#15191f 45%,#23272f);border:1px solid #4a515e;
  box-shadow:0 10px 26px -12px rgba(0,0,0,.7);color:#e8edf4;font-family:"Exo 2",system-ui,sans-serif}
.tcg-in{border-radius:9px;border:2px solid var(--fc);background:#0b0e13;min-height:404px;
  display:flex;flex-direction:column;overflow:hidden}
.tcg-top{display:flex;align-items:center;gap:6px;padding:6px 7px;
  background:linear-gradient(90deg,color-mix(in srgb,var(--fc) 60%,#111) ,#161b23 85%)}
.tcg-top h4{flex:1;margin:0;font-family:"Russo One","Exo 2",sans-serif;font-weight:400;font-size:14.5px;
  line-height:1.1;letter-spacing:.02em;text-shadow:0 1px 2px #000;color:#fff}
.tcg .emb{width:22px;height:22px;flex:none;color:#fff;filter:drop-shadow(0 1px 1px #000)}
.gem{flex:none;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
  font-family:"Russo One",sans-serif;font-size:16px;color:#1d1405;
  background:radial-gradient(circle at 35% 30%,#fff1c4,#e0a93a 58%,#7a5210);
  box-shadow:0 0 0 2px #0b0e13,0 0 0 3px #d9a441}
.hero-gem{background:radial-gradient(circle at 35% 30%,#e9f4ff,#6fa8dc 58%,#1f4c7a);box-shadow:0 0 0 2px #0b0e13,0 0 0 3px #8cc0ee}
.uniq{color:#f0d27a;font-size:11px;vertical-align:2px}
.tcg-art{position:relative;height:152px;display:grid;place-items:center;overflow:hidden;
  background:radial-gradient(1px 1px at 20% 30%,#fff9,transparent),radial-gradient(1px 1px at 70% 20%,#fff8,transparent),
  radial-gradient(1px 1px at 40% 80%,#fff7,transparent),radial-gradient(1px 1px at 85% 65%,#fff9,transparent),
  radial-gradient(1.5px 1.5px at 10% 70%,#fffb,transparent),radial-gradient(1px 1px at 55% 45%,#fff6,transparent),
  radial-gradient(ellipse at 50% 65%,color-mix(in srgb,var(--fc) 38%,#0b0e13),#04060a 78%)}
.tcg-art img{max-width:94%;max-height:142px;object-fit:contain;filter:drop-shadow(0 8px 10px rgba(0,0,0,.65))}
.tcg-art img.scene{max-width:100%;max-height:none;width:100%;height:100%;object-fit:cover;filter:none}
.tcg-art img.portrait{max-width:100%;max-height:none;width:100%;height:100%;object-fit:cover;object-position:50% 18%}
.tcg-art .emb-big{width:92px;height:92px;color:color-mix(in srgb,var(--fc) 70%,#fff);opacity:.85}
.tcg-art .sig{position:absolute;left:6px;bottom:5px;font-size:9.5px;color:#cfd8e6;background:#0b0e13b3;
  padding:1px 6px;border-radius:5px}
.hero .tcg-art{height:168px}
.tcg-type{display:flex;justify-content:space-between;gap:6px;padding:3px 8px;font-size:10px;letter-spacing:.07em;
  text-transform:uppercase;color:#cfd8e6;background:#151a23;border-block:1px solid #2b3240}
.tcg-type .off{color:#e8907f}
.tcg-body{flex:1;display:grid;grid-template-columns:96px 1fr;gap:6px;padding:6px}
.tcg-stats{display:flex;flex-direction:column;gap:3px}
.tw{width:96px;height:96px}
.tw text{font:700 10.5px "Exo 2",sans-serif;fill:#fff;paint-order:stroke;stroke:#0b0e13;stroke-width:2.2px}
.tcg-stats dl{margin:0;display:grid;gap:1px;font-size:10.5px}
.tcg-stats dl div{display:flex;justify-content:space-between;border-bottom:1px dotted #333b48;padding-bottom:1px}
.tcg-stats dt{color:#95a3b7}.tcg-stats dd{margin:0;font-weight:700;font-variant-numeric:tabular-nums}
.tcg-stats dd small{font-weight:400;color:#95a3b7}
.tcg-text,.tcg-syn{background:#ece5d6;color:#1b1c1f;border-radius:6px;padding:6px 7px;font-size:10.8px;line-height:1.32}
.tcg-text p,.tcg-syn p{margin:0 0 4px;max-width:none}.tcg-text p:last-child,.tcg-syn p:last-child{margin:0}
.tcg-text .flav{font-style:italic;color:#4a4a4a}
.tcg-text .meta{font-style:normal;font-size:9.5px;color:#5b5446;text-transform:uppercase;letter-spacing:.04em}
.tcg-hbody{flex:1;display:flex;flex-direction:column;gap:5px;padding:6px}
.tcg-syn{background:linear-gradient(0deg,#e3dccb,#efe9dc);border-left:4px solid var(--fc)}
.tcg-foot{display:flex;justify-content:space-between;gap:8px;padding:3px 8px 5px;font-size:9px;color:#8793a5}
.tcg-foot .flav1{font-style:italic;line-height:1.25}
.tcg-deck{display:grid;gap:16px;grid-template-columns:repeat(auto-fill,300px);justify-content:center}
@media (max-width:640px){.tcg-deck{grid-template-columns:300px}}
@media print{.tcg{zoom:.795;break-inside:avoid;box-shadow:none}.tcg-deck{gap:4mm;justify-content:start}}
"""


def build_full() -> str:
    """Полное издание: весь рулбук, где «Картотека» — карточки с картинками."""
    html_doc = build()
    ships = sorted(SHIPS, key=lambda x: (x["faction"], -x["draft_cost"], x["id"]))
    heroes = sorted(HEROES, key=lambda x: (x["faction"], x["id"]))
    deck = ("".join(tcg_ship(s) for s in ships) + "".join(tcg_hero(h) for h in heroes))
    have_ships = sum(1 for s in SHIPS if art_path("ships", s["id"]))
    have_heroes = sum(1 for h in HEROES if art_path("heroes", h["id"]))
    # заменить сетку карточек публичной версии на карточки с картинками
    start = html_doc.index('<div class="deck" id="deck">')
    end = html_doc.index('</section>', start)
    note = (f'<p class="count">Картинки: кораблей {have_ships} из {len(SHIPS)}, героев {have_heroes} из {len(HEROES)} — '
            'иллюстрации Wookieepedia, © Lucasfilm Ltd. Частное издание, не для распространения.</p>')
    html_doc = html_doc[:start] + note + f'<div class="tcg-deck" id="deck">{deck}</div>' + html_doc[end:]
    html_doc = html_doc.replace('<p class="count">Изображений в проекте нет намеренно: слот на карточке открывает поиск\nкартинки в интернете, потом его заменит собственный рисунок.</p>', '')
    html_doc = html_doc.replace('<title>Эпохи и фракции</title>', '<title>Эпохи и фракции — полное издание</title>')
    fonts = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Russo+One&'
             'family=Exo+2:ital,wght@0,400;0,700;1,400&display=swap&subset=cyrillic,latin">')
    html_doc = html_doc.replace("<style>", fonts + "\n<style>" + TCG_CSS, 1)
    # фильтры картотеки работают по .tcg так же, как по .card
    html_doc = html_doc.replace("deck.querySelectorAll('.card')", "deck.querySelectorAll('.card,.tcg')")
    return html_doc


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"OK: {OUT.relative_to(ROOT)} — {kb:.0f} КБ, "
          f"{len(SHIPS)} кораблей, {len(HEROES)} героев (публичная версия, без картинок)")
    FULL_OUT.write_text(build_full(), encoding="utf-8")
    print(f"OK: {FULL_OUT.relative_to(ROOT)} — полное издание с картинками (частное)")


if __name__ == "__main__":
    main()
