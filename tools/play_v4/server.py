"""Партия v4 «за одним компьютером»: драфт из общего каталога и бой на гекс-поле.

Правила считает тот же движок, на котором подбирался баланс (tools/sim_v4): Match, драфт
с эпохой партии, цены героев. Браузер показывает поле в 3D и отправляет ходы в API.

Запуск:   python3 tools/play_v4/server.py            (карточки + лучший патч баланса эпохи)
          python3 tools/play_v4/server.py --cards    (карточки как есть)
Открыть:  http://localhost:8766/

API (JSON):
  GET  /api/state            — всё состояние партии для интерфейса
  POST /api/new   {era}      — новая партия (драфт)
  POST /api/pick  {kind,id}  — взять карточку в драфте
  POST /api/act   {act:[…]}  — действие в бою (как в Match.apply)
  POST /api/undo             — отменить манёвр или активацию (не броски)
  POST /api/unpick           — отменить свой последний выбор в драфте (вместе с ответом компьютера)
  POST /api/moveto {q,r}     — провести активный корабль на клетку по кратчайшему пути (несколько шагов)
  POST /api/act {act, defer_bot:true} + POST /api/bot — ход игрока сразу, ход компьютера отдельным запросом
  GET  /api/history          — история боя для повтора: карточки кораблей и кадр после каждого действия
  POST /api/gif {frames,fps} — собрать GIF повтора из кадров (JPEG dataURL), вернуть ссылку /replays/…
Ответ на POST содержит fx — что произошло за запрос (свои действия и ходы компьютера) по порядку,
со снимком позиций после каждого действия: интерфейс проигрывает это анимацией.
"""

from __future__ import annotations

import argparse
import copy
import random
import json
import math
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from sim_v4 import tune  # noqa: E402
from sim_v4.draft import ORDER, DraftState, apply_pick, legal_picks, in_era, era_heroes  # noqa: E402
from sim_v4.optimize import apply_patch, empty_patch, ship_numbers  # noqa: E402
from sim_v4.rules import DIRS, HEROES, SHIPS, V4, Match, budget_for, dist, expected, in_board, sector  # noqa: E402

ERA_NAMES = {"fall_of_republic": "Падение Республики", "galactic_civil_war": "Галактическая гражданская война",
             "new_order": "Новый порядок"}
PLAYABLE = ["fall_of_republic", "galactic_civil_war", "new_order"]
SEC = ["F", "FR", "BR", "B", "BL", "FL"]
REL = ["вперёд", "вперёд-вправо", "назад-вправо", "назад", "назад-влево", "вперёд-влево"]
ROLE = {"fighter": "истребитель", "interceptor": "перехватчик", "bomber": "бомбардировщик", "support": "поддержка",
        "gunship": "канонерка",
        "transport": "транспорт", "freighter": "грузовик", "corvette": "корвет", "frigate": "фрегат",
        "capital": "крупный корабль", "station": "станция"}
FACTIONS = {f["id"]: f for f in json.loads((V4 / "factions.json").read_text(encoding="utf-8"))["factions"]}
ABIL = {a["id"]: a for a in json.loads((V4 / "ship_abilities.json").read_text(encoding="utf-8"))["abilities"]}
LENGTHS = {k: v for k, v in json.loads((HERE / "ship_lengths.json").read_text(encoding="utf-8")).items()
           if not k.startswith("_")}


def model_size(sid):
    """Длина модели на поле в клетках: логарифм официальной длины × ручная поправка (ship_lengths.json)."""
    e = LENGTHS.get(sid)
    if not e:
        return None
    return round(max(0.5, min(2.1, 0.2 + 0.47 * math.log10(e["length_m"]))) * e.get("adjust", 1.0), 3)
REACT = {"rey": "Рей перебрасывает кубик", "luke": "Люк: «Точный выстрел» — кубик становится 6",
         "obi": "Оби-Ван: «Мимо»", "mace": "Мейс Винду: «Ваапад»"}
SAVE = {"resurrection": "«Воскрешение»: корабль вернулся", "will": "«Воля Силы»: корабль остаётся с 1 HP",
        "phantom": "превращается в «Фантом»", "foundry": "«Дроидная верфь»: корабль вернулся"}
HERO_ACT = {"palpatine": "Неограниченная власть", "grievous": "Четыре клинка", "tarkin": "Огонь по готовности",
            "dooku": "Молнии Силы", "kylo": "Остановка Силой", "quigon": "Живая Сила", "holdo": "Манёвр Холдо",
            "vader": "Путь силы", "anakin": "Путь силы", "han": "Гиперпрыжок", "jango": "Мина", "boba": "Бомба",
            "piett": "Сомкнуть сеть", "snoke": "Нити кукловода", "poe": "Рывок", "hux": "Массированный залп",
            "nute": "Торговая блокада"}
SHIP_ACT = {"carrier": "Ангар", "ion": "Ионная пушка", "tractor": "Тяговый луч", "cloak": "Маскировочное поле",
            "jump": "Гиперпрыжок", "board": "Абордаж", "return": "Возврат из гиперпространства"}


FLAGSHIP = json.loads((V4 / "scenarios" / "flagship_hunt.json").read_text(encoding="utf-8"))
STRAT = json.loads((ROOT / "tools" / "sim_v4" / "strategy.json").read_text(encoding="utf-8"))["strategy"]


class FlagshipDraft:
    """Выбор для «Эскадры против флагмана»: A (Империя) берёт героя, «Палач» у него уже есть;
    B (эскадра) — героя и до N кораблей повстанцев и «вне эпохи» в пределах бюджета."""
    era = "galactic_civil_war"

    def __init__(self):
        self.heroes = [None, None]
        self.ships = [[FLAGSHIP["flagship"]], []]
        self.finished = False
        o = FLAGSHIP["seat_overrides"]["B1"]
        self.budget0, self.max_ships = o["draft_budget"], o["fleet_size"]
        self.cost_add = o.get("ship_cost_add", 0)        # надбавка к цене каждого корабля эскадры
        self.squad_heroes = sorted(h for h, d in HEROES.items() if d["faction"] in FLAGSHIP["squadron_factions"]
                                   and d["era"] in ("galactic_civil_war", "any"))
        self.pool = sorted(x for x, d in SHIPS.items() if d["draftable"] and d["era"] in ("galactic_civil_war", "any")
                           and d["role"] != "capital" and d["faction"] in ("rebels", "bounty_hunters"))

    @property
    def seat(self):
        return 0 if self.heroes[0] is None else 1

    @property
    def step(self):
        return (self.heroes[0] is not None) + (self.heroes[1] is not None) + len(self.ships[1])

    @property
    def done(self):
        return self.finished

    def budget(self):
        return self.budget0 + (P_LANDO() if self.heroes[1] == "lando_calrissian" else 0)

    def legal(self):
        if self.finished:
            return []
        if self.heroes[0] is None:
            return [("hero", h) for h in FLAGSHIP["flagship_heroes"]]
        out = []
        if self.heroes[1] is None:
            out += [("hero", h) for h in self.squad_heroes]
        if len(self.ships[1]) < self.max_ships:
            spent = sum(SHIPS[x]["draft_cost"] + self.cost_add for x in self.ships[1])
            uniq = sum(SHIPS[x]["unique"] for x in self.ships[1])
            fac = HEROES[self.heroes[1]]["faction"] if self.heroes[1] else None
            foreign = sum(SHIPS[x]["faction"] != fac for x in self.ships[1]) if fac else 0
            for x in self.pool:
                d = SHIPS[x]
                if x in self.ships[1] or spent + d["draft_cost"] + self.cost_add > self.budget() or (d["unique"] and uniq):
                    continue
                if fac and d["faction"] != fac and foreign >= 1:
                    continue
                out.append(("ship", x))
        return out

    def can_finish(self):
        return self.heroes[0] is not None and self.heroes[1] is not None and len(self.ships[1]) >= 1

    def apply(self, pick):
        kind, cid = pick
        if kind == "hero":
            self.heroes[self.seat] = cid
        else:
            self.ships[1].append(cid)
        if self.heroes[1] and self.ships[1] and not any(k == "ship" for k, _ in self.legal()):
            self.finished = True               # набран максимум или бюджет исчерпан — к бою


def P_LANDO():
    return tune.P["lando.budget"]


def hit_chance(off, cap=0, shield=0):
    """Вероятность, что атака снимет хоть что-то (щит или корпус)."""
    p = 0.0
    for a in range(1, 7):
        for b in range(1, 7):
            for c in range(1, 7):
                if a + b - c + off > 0:
                    p += 1 / 216
    return p


class Game:
    def __init__(self, patch, patch_name):
        self.patch = patch
        self.patch_name = patch_name
        self.lock = threading.Lock()
        self.new("galactic_civil_war")

    # ------------------------------------------------------------ жизненный цикл
    def new(self, era, mode="duel", bot=None, place="planet"):
        apply_patch(self.patch)
        tune.set_levels(None)
        self.era = era
        self.mode = mode
        self.place = place                               # «planet» или «blackhole» — у чёрной дыры гиперколодец
        self.bot = bot                                   # {"seat": 0/1, "level": easy|medium|strong|max} или None
        self.rng = random.Random()
        self.phase = "draft"
        self.match = None
        if mode == "flagship":
            self.draft = FlagshipDraft()
            self.log = [f"Сценарий «{FLAGSHIP['display_name']}». {FLAGSHIP['victory']} A выбирает героя Империи, "
                        f"затем B — героя и до {self.draft.max_ships} кораблей на {self.draft.budget0} очков."]
        else:
            self.draft = DraftState(era=era)
            self.log = [f"Эпоха партии: {ERA_NAMES[era]}. Драфт «змейкой»: A, B, B, A, A, B, B, A."]
        if bot:
            self.log.append(f"Соперник — компьютер ({self.LEVELS[bot['level']]}), играет за сторону {'AB'[bot['seat']]}.")
        self.last = []
        self.undo = []
        self.pick_undo = None                            # снимок до последнего выбора игрока в драфте
        self.history = []                                # кадры боя для повтора и GIF
        self.fx = []                                     # события для анимации за текущий запрос

    def pick(self, kind, cid, by_bot=False):
        if self.phase != "draft":
            raise ValueError("драфт уже закончен")
        if self.bot and not by_bot and self.draft.seat == self.bot["seat"]:
            raise ValueError("сейчас выбирает компьютер")
        pick = (kind, cid)
        if pick not in self.legal():
            raise ValueError("эту карточку сейчас взять нельзя")
        seat = self.draft.seat
        if not by_bot:
            self.pick_undo = (copy.deepcopy(self.draft), list(self.log), self.phase)
        if self.mode == "flagship":
            self.draft.apply(pick)
        else:
            apply_pick(self.draft, pick)
        name = HEROES[cid]["display_name"] if kind == "hero" else SHIPS[cid]["display_name"]
        self.log.append(f"Драфт: {'AB'[seat]} берёт {'героя ' if kind == 'hero' else ''}{name}.")
        self._skip_full()
        if self.draft.done:
            self.start_battle()
        if not by_bot:
            self.bot_draft()
            self.bot_turn()

    def legal(self):
        return self.draft.legal() if self.mode == "flagship" else legal_picks(self.draft)

    def unpick(self):
        if not self.pick_undo:
            raise ValueError("отменять нечего")
        self.draft, self.log, self.phase = self.pick_undo
        self.match, self.pick_undo, self.undo, self.last = None, None, [], []
        self.log.append("Выбор отменён.")

    def why_not(self):
        """Почему карточку сейчас нельзя взять — короткая подпись на карточке драфта."""
        st, seat = self.draft, self.draft.seat
        legal = set(self.legal())
        taken = {x for k in (0, 1) for x in ([st.heroes[k]] + st.ships[k]) if x}
        mine = st.ships[seat]
        hero = st.heroes[seat]
        if self.mode == "flagship":
            spent = sum(SHIPS[x]["draft_cost"] + st.cost_add for x in mine)
            left = st.budget() - spent if seat == 1 else 0
        else:
            left = (budget_for(hero) if hero else tune.BUDGET_TOTAL - min(tune.hero_cost(h) for h in era_heroes(self.era))) \
                - sum(SHIPS[x]["draft_cost"] for x in mine)
        out = {}
        for kind, ids in (("hero", [h for h in HEROES]), ("ship", [x for x in SHIPS])):
            for cid in ids:
                if (kind, cid) in legal or cid in taken:
                    continue
                if kind == "hero":
                    why = "герой уже выбран" if hero else "не собрать с ним флот"
                else:
                    d = SHIPS[cid]
                    cost = d["draft_cost"] + (st.cost_add if self.mode == "flagship" else 0)
                    if self.mode != "flagship" and len(mine) >= 3 or self.mode == "flagship" and len(mine) >= st.max_ships:
                        why = "флот собран"
                    elif cost > left:
                        why = f"не хватает {cost - left} оч."
                    elif d["role"] == "capital" and any(SHIPS[x]["role"] == "capital" for x in mine):
                        why = "крупный уже есть"
                    elif d["unique"] and any(SHIPS[x]["unique"] for x in mine):
                        why = "именной уже есть"
                    else:
                        why = "не собрать флот в бюджет"
                out[f"{kind}:{cid}"] = why
        return out

    def finish_draft(self):
        if self.mode != "flagship" or not self.draft.can_finish():
            raise ValueError("закончить выбор сейчас нельзя")
        self.pick_undo = None
        self.draft.finished = True
        self.log.append(f"B заканчивает выбор: {len(self.draft.ships[1])} кораблей.")
        self.start_battle()
        self.bot_turn()

    def _skip_full(self):
        st = self.draft
        if self.mode == "flagship":
            return
        while not st.done and st.heroes[st.seat] is not None and len(st.ships[st.seat]) == 3:
            st.step += 1

    def start_battle(self):
        st = self.draft
        self.phase = "battle"
        scen = FLAGSHIP if self.mode == "flagship" else None
        well = getattr(self, "place", "planet") == "blackhole"
        self.match = Match(list(st.heroes), [list(st.ships[0]), list(st.ships[1])],
                           seed=hash(tuple(st.ships[1])) & 0xffff, scen=scen, well=well)
        self.match.events = []
        self.match.on_apply = self._observe
        self.history = [self._frame(None)]
        if well and self.match.well:
            self.log.append(f"У чёрной дыры открылся гиперколодец в клетке {tuple(self.match.well)}: "
                            "в конце раунда все корабли затянет на клетку к нему.")
        self.log.append("Бой начался. Раунд 1, первой ходит сторона A."
                        + (f" Лимит — {self.match.round_limit} раундов." if scen else ""))

    def reachable(self):
        """Клетки, куда активный корабль дойдёт шагами за оставшиеся заряды: {клетка: [направления]}.
        Курс при шагах не меняется; занятые клетки и мины по пути обходятся (на мину можно встать целью)."""
        m = self.match
        s = m.active
        if s is None or not s.alive or s.uses.get("stunned") or s.uses.get("hyper"):
            return {}
        mc = s.d["engine"]["move_cost"]
        if not mc or s.charges < mc:
            return {}
        occupied = {o.pos for o in m.ships if o.alive and o is not s} | ({m.well} if m.well else set())
        mines = {tuple(x["pos"]) for x in m.mines}
        # кратчайший по зарядам путь (у колодца шаг прочь от него дороже — m.step_cost)
        import heapq
        cost = {s.pos: 0}
        best = {s.pos: []}
        heap = [(0, 0, s.pos)]
        n = 0
        while heap:
            c0, _, p = heapq.heappop(heap)
            if c0 > cost.get(p, 1e9) or (p in mines and p != s.pos):
                continue
            for i, (dq, dr) in enumerate(DIRS):
                c = (p[0] + dq, p[1] + dr)
                if c in occupied or not in_board(*c):
                    continue
                nc = c0 + m.step_cost(s, p, c)
                if nc <= s.charges and nc < cost.get(c, 1e9):
                    cost[c] = nc
                    best[c] = best[p] + [i]
                    n += 1
                    heapq.heappush(heap, (nc, n, c))
        best.pop(s.pos)
        self._reach_cost = cost
        return best

    def move_to(self, q, r):
        m = self.match
        if self.phase != "battle" or m.done or m.active is None:
            raise ValueError("сейчас некому ходить")
        if self.bot and m.turn_seat == self.bot["seat"]:
            raise ValueError("сейчас ходит компьютер")
        path = self.reachable().get((q, r))
        if not path:
            raise ValueError("до этой клетки не дойти")
        m.on_apply = None
        self.undo.append((copy.deepcopy(m), len(self.history)))   # весь путь отменяется одним «Отменить»
        m.on_apply = self._observe
        self.last = []
        s = m.active
        for d in path:
            if m.done or m.active is not s or not s.alive or ("move", d) not in m.legal():
                break                                   # мина или способность прервали путь
            m.apply(("move", d))
        self._after_act()

    def act(self, act, defer_bot=False):
        m = self.match
        if self.phase != "battle" or m.done:
            raise ValueError("бой не идёт")
        act = tuple(act)
        if self.bot and m.turn_seat == self.bot["seat"]:
            raise ValueError("сейчас ходит компьютер")
        legal = m.legal() + [tuple(o) for o in m.special_options(m.active)] if m.active is not None else m.legal()
        if act not in legal:
            raise ValueError("такой ход сейчас невозможен")
        self.pick_undo = None
        if act[0] in ("activate", "move", "rot", "boost") or (act[0] == "hero" and act[1] in ("poe",)):
            m.on_apply = None
            self.undo.append((copy.deepcopy(m), len(self.history)))   # с длиной истории — откатить и её
            m.on_apply = self._observe
        else:
            self.undo = []
        self.last = []
        m.apply(act)
        # после броска (атака, способность) делать больше нечего — активация завершается сама:
        # лишний клик «Завершить» не нужен. После манёвра не завершаем — его можно отменить.
        if (not m.done and m.active is not None and act[0] not in ("activate", "move", "rot", "boost")
                and m.legal() == [("end",)] and not m.special_options(m.active)):
            self.last.append("Больше ходов нет — активация завершена.")
            m.apply(("end",))
            self.undo = []
        self._after_act()
        if not defer_bot:                                # интерфейс сначала показывает ход игрока, потом зовёт /api/bot
            self.bot_turn()

    def _observe(self, m, act, ctx):
        """Наблюдатель действий партии: до действия запоминает состояние, после — пишет журнал."""
        if m is not self.match:
            return None
        if ctx is None:
            m.events.clear()
            who = m.active if act[0] != "activate" else (m.ships[act[1]] if act[0] == "activate" else None)
            return (who, m.turn_seat, [(s.hp, s.shield, s.alive) for s in m.ships],
                    {s.uid: self.sname(s.uid) for s in m.ships})
        who, seat, prev, names = ctx
        self._names = names                       # имена кораблей — до действия (Призрак → Фантом)
        lines = self.describe(act, who, seat, prev)
        self._names = None
        ev = self._fx_event(act, who, prev)
        ev["well"] = [e for e in m.events if str(e.get("t", "")).startswith("well")]
        well_lines = []
        for e in ev["well"]:                              # журнал: что сделал гиперколодец
            t = e["t"]
            if t == "well_open":
                line = f"— Гиперколодец открылся в клетке ({e['pos'][0]}, {e['pos'][1]}): в конце раунда все корабли затянет на клетку к нему."
            elif t == "well_pull":
                line = "— Гиперколодец тянет: " + (", ".join(self.sname(u) for u, *_ in e["moves"]) or "никто не сдвинулся") + " — на клетку ближе." \
                    + ("".join(f" {self.sname(u)} провалился и уничтожен!" for u in e["fell"]))
            elif t == "well_bite":
                line = ("— Край колодца: " + ", ".join(f"{self.sname(u)} теряет щиты и половину корпуса (осталось {hp})"
                                                     for u, hp in e["ships"]) + ".") if e["ships"] else "— У края колодца никого нет."
            else:
                line = "— Гиперколодец закрылся. Следующий раунд спокойный."
            well_lines.append(line)
        # события колодца конца раунда — до строки «— Раунд N», открытие нового — после неё
        cut = next((i for i, x in enumerate(lines) if x.startswith("— Раунд")), len(lines))
        opened = next((i for i, e in enumerate(ev["well"]) if e["t"] == "well_open"), len(well_lines))
        lines = lines[:cut] + well_lines[:opened] + lines[cut:] + well_lines[opened:]
        self.last += lines
        self.log += lines
        self.fx.append(ev)
        self.history.append(self._frame(ev))
        return None

    def _frame(self, ev):
        """Кадр истории: позиции и состояние всех кораблей, выстрел, погибшие, колодец, раунд."""
        m = self.match
        return {"round": m.round, "ships": [[s.uid, s.q, s.r, s.facing, s.alive, bool(s.uses.get("hyper")), max(0, s.hp), s.shield]
                                            for s in m.ships],
                "who": ev and ev.get("who"), "target": ev and ev.get("target"), "kind": ev and ev.get("kind"),
                "hit": bool(ev and (ev["hurt"] or ev["shield"] or ev["killed"])), "killed": ev["killed"] if ev else [],
                "well": list(m.well) if getattr(m, "well", None) else None}

    def history_state(self):
        m = self.match
        if not m:
            raise ValueError("боя ещё не было")
        return {"ships": [{"uid": s.uid, "code": self.code(s.uid), "type": s.type, "seat": s.seat, "name": s.d["display_name"],
                           "role_id": s.d["role"], "size": model_size(s.type), "arcs": s.d["arc_modifiers"]} for s in m.ships],
                "frames": self.history, "winner": m.winner, "done": m.done, "era": self.era,
                "place": getattr(self, "place", "planet"), "heroes": m.heroes}

    def _fx_event(self, act, who, prev):
        """Событие для анимации: кто действовал, в кого стрелял, кого задело, кто погиб, и позиции после."""
        m = self.match
        hurt, killed, shield = [], [], []
        for s, (hp, sh, alive) in zip(m.ships, prev):
            if alive and not s.alive:
                killed.append(s.uid)
            elif s.hp < hp:
                hurt.append(s.uid)
            elif s.shield < sh:
                shield.append(s.uid)
        ev = {"kind": act[0], "sub": act[1] if len(act) > 1 and isinstance(act[1], str) else None,
              "who": who.uid if who is not None else None, "target": None,
              "hurt": hurt, "shield": shield, "killed": killed,
              "ships": [[s.uid, s.q, s.r, s.facing, s.alive, bool(s.uses.get("hyper"))] for s in m.ships]}
        if act[0] == "attack":
            ev["target"] = act[1]
        elif act[0] in ("hero", "ship") and len(act) > 2 and isinstance(act[2], int) and act[2] < len(m.ships) \
                and act[1] in ("vader", "dooku", "kylo", "quigon", "carrier", "ion", "tractor", "board"):
            ev["target"] = act[2]
        return ev

    def _after_act(self):
        m = self.match
        if m.done and self.phase != "over":
            self.phase = "over"
            self.log.append("Партия окончена: " + ("ничья." if m.winner is None else f"победа стороны {'AB'[m.winner]}!"))

    # ------------------------------------------------------------ компьютер-соперник
    LEVELS = {"easy": "лёгкий", "medium": "средний", "strong": "сильный", "max": "максимальный"}

    def make_bot(self, seat):
        from sim_v4.arena import AdaptiveBot, MonteCarloBot, load_adaptive
        from sim_v4.bots import GreedyBot, HunterBot, TacticalBot
        lvl = self.bot["level"]
        h = self.match.heroes[seat]
        st = {h: STRAT.get(h, 0.6)}
        role = "duel" if self.mode != "flagship" else ("empire" if seat == 0 else "squad")
        if lvl == "easy":
            return GreedyBot(self.rng.randrange(1 << 30), strat=st)
        if lvl == "medium":
            cls = HunterBot if role == "squad" else TacticalBot
            return cls(self.rng.randrange(1 << 30), strat=st)
        if lvl == "strong":
            return AdaptiveBot(self.rng.randrange(1 << 30), strat=st, w=load_adaptive().get(role))
        return MonteCarloBot(self.rng.randrange(1 << 30), strat=st)

    def bot_draft(self):
        """Выбор компьютера в драфте, пока его очередь."""
        b = self.bot
        while self.bot and self.phase == "draft" and self.draft.seat == b["seat"] and not self.draft.done:
            legal = self.legal()
            if not legal:
                if self.mode == "flagship" and self.draft.can_finish():
                    self.finish_draft()
                return
            if self.mode == "flagship":
                heroes = [p for p in legal if p[0] == "hero"]
                ships = [p for p in legal if p[0] == "ship"]
                if heroes:
                    pick = self.rng.choice(heroes)
                else:                                   # эскадра: самый дорогой доступный корабль
                    pick = max(ships, key=lambda p: (SHIPS[p[1]]["draft_cost"], self.rng.random()))
            elif b["level"] == "easy":
                pick = tuple(self.rng.choice(legal))
            else:                                       # драфт «как у человека»: бюджет тратится почти весь
                from sim_v4.draft import GreedyDrafter
                pick = GreedyDrafter(self.rng.randrange(1 << 30)).pick(self.draft)
            self.pick(pick[0], pick[1], by_bot=True)

    def bot_turn(self):
        """Ход компьютера в бою — пока его очередь (включая возврат из гиперпространства)."""
        if not self.bot or self.phase != "battle":
            return
        m = self.match
        seat = self.bot["seat"]
        bot = self.make_bot(seat)
        guard = 0
        while not m.done and m.turn_seat == seat and guard < 200:
            bot.play_turn(m)
            guard += 1
        if guard:                                        # компьютер сходил — отменять свой ход поздно
            self.undo = []
        self._after_act()

    def do_undo(self):
        if not self.undo:
            raise ValueError("отменять нечего")
        self.match, n = self.undo.pop()
        self.history = self.history[:n]                 # отменённые ходы не попадут в повтор
        self.match.on_apply = self._observe
        self.log.append("Отмена хода.")

    # ------------------------------------------------------------ описания
    def code(self, uid):
        n0 = len(self.match.ships) // 2
        return ("A%d" % (uid + 1)) if uid < n0 else ("B%d" % (uid - n0 + 1))

    def sname(self, uid):
        if getattr(self, "_names", None):
            return self._names[uid]
        return f"{self.code(uid)} {SHIPS[self.match.ships[uid].type]['display_name']}"

    def describe(self, act, who, seat, prev):
        m = self.match
        out = []
        k = act[0]
        if k == "activate":
            out.append(f"{'AB'[seat]}: активирует {self.sname(m.active.uid)} (зарядов {m.active.charges}).")
        elif k == "move":
            out.append(f"{self.sname(who.uid)}: шаг {REL[(act[1] - who.facing) % 6]}.")
        elif k == "rot":
            out.append(f"{self.sname(who.uid)}: поворот {'вправо' if act[1] > 0 else 'влево'}.")
        elif k == "boost":
            out.append(f"{self.sname(who.uid)}: форсаж на 2 клетки.")
        elif k == "attack":
            out.append(f"{self.sname(who.uid)} атакует {self.sname(act[1])}.")
        elif k == "hero":
            out.append(f"{self.sname(who.uid)}: способность героя «{HERO_ACT.get(act[1], act[1])}».")
        elif k == "ship" and act[1] == "return":
            x = m.ships[act[2]]
            out.append(f"{'AB'[x.seat]}: {self.sname(x.uid)} выходит из гиперпространства на клетку ({act[3]}, {act[4]}).")
        elif k == "ship":
            tgt = f" → {self.sname(act[2])}" if len(act) > 2 else ""
            out.append(f"{self.sname(who.uid)}: «{SHIP_ACT.get(act[1], act[1])}»{tgt}.")
        elif k == "end":
            out.append(f"{self.sname(who.uid)} завершает активацию.")
        for e in m.events:
            t = e["t"]
            if t == "roll":
                tot = e["a"][0] + e["a"][1] + e["off"] - e["d"]
                out.append(f"   Кубики: {e['a'][0]}+{e['a'][1]} {e['off']:+d} против {e['d']} → {max(0, tot)} "
                           f"(сектор атаки {SEC[e['a_sec']]}, защиты {SEC[e['d_sec']]}, дистанция {e['dist']}).")
            elif t == "kill":
                out.append(f"   {self.sname(e['uid'])} уничтожен!")
            elif t == "save":
                out.append(f"   {self.sname(e['uid'])}: {SAVE.get(e['how'], e['how'])}.")
            elif t == "react":
                out.append(f"   {REACT.get(e['key'], 'реакция героя')}.")
            elif t == "cancel":
                out.append(f"   {HEROES[e['hero']]['ability']['name']}: атака отменена.")
            elif t == "mine":
                out.append(f"   {self.sname(e['uid'])} подрывается на мине.")
            elif t == "bomb":
                out.append(f"   Бомба попадает в {self.sname(e['uid'])}.")
            elif t == "carrier":
                out.append(f"   Звено истребителей атакует {self.sname(e['uid'])}.")
            elif t == "ion":
                out.append(f"   Ионный удар: {self.sname(e['uid'])} теряет 2 заряда.")
            elif t == "ion_block":
                out.append(f"   {self.sname(e['uid'])} не теряет заряды: защита от иона.")
            elif t == "tractor":
                out.append(f"   Тяговый луч подтягивает {self.sname(e['uid'])} на клетку.")
            elif t == "jump":
                out.append(f"   {self.sname(e['uid'])} уходит в гиперпространство (вернётся в начале следующего хода владельца).")
            elif t == "board":
                out.append(f"   Абордаж {'удался: ' + self.sname(e['uid']) + ' теряет заряды и 1 HP и пропустит активацию' if e['ok'] else 'отбит: атакующий теряет 1 HP'}.")
        dm = []
        for s, (hp, sh, al) in zip(m.ships, prev):
            dh, ds = hp - max(0, s.hp), sh - s.shield
            if (dh > 0 or ds > 0) and al:
                dm.append(f"{self.code(s.uid)} −{ds} щит −{dh} HP".replace("−0 щит ", "").replace(" −0 HP", ""))
        if dm:
            out.append("   Урон: " + ", ".join(dm) + ".")
        elif any(e["t"] == "roll" for e in m.events):
            out.append("   Мимо: защита выдержала.")
        if k == "end" and m.round and not m.done and m.active is None and m.acts_in_round == 0:
            out.append(f"— Раунд {m.round}. Перезарядка: кто не тратил заряды — до максимума, кто тратил — "
                       f"до половины. Первой ходит сторона {'AB'[m.turn_seat]}.")
        return out

    # ------------------------------------------------------------ состояние для интерфейса
    def card_ship(self, sid):
        d = SHIPS[sid]
        base = ship_numbers(sid, {})
        return {
            "id": sid, "name": d["display_name"], "faction": d["faction"],
            "faction_name": FACTIONS[d["faction"]]["short"], "role": ROLE.get(d["role"], d["role"]),
            "era": d["era"], "cost": d["draft_cost"], "base_cost": base["cost"],
            "arcs": d["arc_modifiers"], "base_arcs": base["arcs"], "hp": d["max_hp"], "base_hp": base["hp"],
            "shield": d["max_shield"], "base_shield": base["shield"], "charges": [d["initial_charges"], d["max_charges"]],
            "move": d["engine"]["move_cost"], "pivot": d["engine"]["pivot_cost"], "boost": d["engine"]["boost"],
            "range": d["weapon"]["max_range"], "penalty": d["weapon"]["range_penalty_per_hex"],
            "arc_rule": d["weapon"]["long_range_arc"], "unique": d["unique"],
            "hyper": d["hyperdrive"]["class"] if d["hyperdrive"] else None,
            "abilities": [[ABIL[a["id"]]["display_name"], ABIL[a["id"]]["text"]] for a in d["abilities"] if a["id"] in ABIL],
            "desc": d.get("description", ""),
            "length_m": LENGTHS.get(sid, {}).get("length_m"), "size": model_size(sid),
        }

    def card_hero(self, hid):
        d = HEROES[hid]
        f = FACTIONS[d["faction"]]
        return {"id": hid, "name": d["display_name"], "faction": d["faction"], "faction_name": f["short"],
                "era": d["era"], "cost": tune.hero_cost(hid), "base_cost": d.get("draft_cost", tune.BASE_HERO_COST),
                "ability": [d["ability"]["name"], d["ability"]["text"]],
                "synergy": [d["synergy"]["name"], d["synergy"]["text"]],
                "trait": [f["trait"]["name"], f["trait"]["text"]] if f.get("trait") else None,
                "desc": d.get("description", "")}

    def state(self):
        st = self.draft
        if self.mode == "flagship":
            ships = [FLAGSHIP["flagship"]] + st.pool
            heroes = FLAGSHIP["flagship_heroes"] + st.squad_heroes
            playable = set(heroes)
        else:
            ships = [s for s in SHIPS if SHIPS[s]["draftable"] and in_era(SHIPS[s]["era"], self.era)]
            heroes = [h for h in HEROES if in_era(HEROES[h]["era"], self.era)]
            playable = set(era_heroes(self.era))
        out = {
            "phase": self.phase, "era": self.era, "era_name": ERA_NAMES[self.era], "patch": self.patch_name,
            "budget_total": tune.BUDGET_TOTAL, "eras": [{"id": e, "name": n, "playable": e in PLAYABLE}
                                                        for e, n in ERA_NAMES.items()],
            "catalog": {"ships": [self.card_ship(s) for s in sorted(ships, key=lambda x: (SHIPS[x]["faction"],
                                                                                          SHIPS[x]["draft_cost"]))],
                        "heroes": [dict(self.card_hero(h), playable=h in playable)
                                   for h in sorted(heroes, key=lambda x: HEROES[x]["faction"])]},
            "mode": self.mode, "place": getattr(self, "place", "planet"),
            "bot": ({"seat": self.bot["seat"], "level": self.LEVELS[self.bot["level"]]} if self.bot else None),
            "scenario": ({"name": FLAGSHIP["display_name"], "victory": FLAGSHIP["victory"],
                          "max_ships": st.max_ships, "budget": st.budget(), "cost_add": st.cost_add,
                          "acts": FLAGSHIP.get("flagship_activations", 1)} if self.mode == "flagship" else None),
            "draft": {
                "order": (["A"] + ["B"] * (1 + st.max_ships)) if self.mode == "flagship" else ["AB"[x] for x in ORDER],
                "step": st.step, "seat": st.seat,
                "heroes": st.heroes, "ships": st.ships,
                "budget": [self._budget(k) for k in (0, 1)],
                "legal": [list(p) for p in self.legal()] if self.phase == "draft" else [],
                "can_finish": self.mode == "flagship" and self.phase == "draft" and st.can_finish(),
                "why": self.why_not() if self.phase == "draft" else {},
            },
            "log": self.log[-200:], "last": self.last,
            "can_undo": bool(self.undo),
            "fx": self.fx,
            "can_unpick": bool(self.pick_undo) and (self.phase == "draft" or (self.match and not self.match.done)),
        }
        if self.match:
            out["battle"] = self.battle_state()
        return out

    def _budget(self, seat):
        st = self.draft
        h = st.heroes[seat]
        spent = sum(SHIPS[s]["draft_cost"] for s in st.ships[seat])
        if self.mode == "flagship":
            if seat == 0:
                return {"hero": h, "hero_cost": 0, "ships_budget": spent, "spent": spent, "total": spent, "fixed": True}
            spent = sum(SHIPS[x]["draft_cost"] + st.cost_add for x in st.ships[1])
            return {"hero": h, "hero_cost": 0, "ships_budget": st.budget(), "spent": spent, "total": st.budget()}
        if h is None:
            return {"hero": None, "ships_budget": None, "spent": spent, "total": tune.BUDGET_TOTAL}
        return {"hero": h, "hero_cost": tune.hero_cost(h), "ships_budget": budget_for(h), "spent": spent,
                "total": tune.BUDGET_TOTAL + (budget_for(h) - (tune.BUDGET_TOTAL - tune.hero_cost(h)))}

    def battle_state(self):
        m = self.match
        ships = []
        for s in m.ships:
            ships.append({"uid": s.uid, "code": self.code(s.uid), "type": s.type, "seat": s.seat, "q": s.q, "r": s.r,
                          "facing": s.facing, "hp": max(0, s.hp), "max_hp": s.max_hp, "shield": s.shield,
                          "max_shield": s.max_shield, "charges": s.charges, "max_charges": s.d["max_charges"],
                          "alive": s.alive, "activated": s.activated, "attack_used": s.attack_used,
                          "acts_left": 0 if (s.activated or not s.alive) else
                          m.acts_per_round.get(s.type, 1) - s.uses.get("acts_done", 0),
                          "hyper": bool(s.uses.get("hyper")), "stunned": bool(s.uses.get("stunned")),
                          "name": s.d["display_name"], "arcs": s.d["arc_modifiers"], "range": s.d["weapon"]["max_range"],
                          "penalty": s.d["weapon"]["range_penalty_per_hex"], "arc_rule": s.d["weapon"]["long_range_arc"],
                          "move": s.d["engine"]["move_cost"], "pivot": m.pivot_cost(s), "boost": s.d["engine"]["boost"],
                          "role": ROLE.get(s.d["role"], s.d["role"]), "role_id": s.d["role"],
                          "size": model_size(s.type), "length_m": LENGTHS.get(s.type, {}).get("length_m"),
                          "faction_name": FACTIONS[s.d["faction"]]["short"],
                          "foreign": not m.factions_as(s.seat, s),
                          "abilities": [[ABIL[a["id"]]["display_name"], ABIL[a["id"]]["text"]] for a in s.d["abilities"]
                                        if a["id"] in ABIL]})
        opts = []
        if not m.done:
            legal = m.legal()
            a = m.active
            for act in legal:
                opts.append(self.option(act))
            if a is not None:
                for act in m.special_options(a):
                    opts.append(self.option(tuple(act)))
        human = not (self.bot and m.turn_seat == self.bot["seat"])
        reach = []
        if human and not m.done:
            for c, p in self.reachable().items():
                q, r, path = m.active.q, m.active.r, []
                for d in p:                                # клетки пути — для подсветки маршрута под мышью
                    q, r = q + DIRS[d][0], r + DIRS[d][1]
                    path.append([q, r])
                reach.append({"cell": list(c), "steps": len(p), "cost": self._reach_cost[c],
                              "path": path})
        return {"reach": reach, "round": m.round, "round_limit": m.round_limit if self.mode == "flagship" else None, "turn": m.turn_seat, "active": None if m.active is None else m.active.uid,
                "winner": m.winner, "done": m.done, "ships": ships, "heroes": m.heroes,
                "mines": [list(x["pos"]) for x in m.mines], "bombs": [list(b["pos"]) for b in m.bombs],
                "hero_uses": m.hero_uses, "options": opts,
                "well": list(m.well) if m.well else None, "well_n": m.well_n, "well_mode": m.well_mode,
                "well_safe": [list(c) for c in getattr(m, "well_safe", [])]}

    def option(self, act):
        m = self.match
        s = m.active
        o = {"act": list(act), "kind": act[0]}
        if act[0] == "activate":
            o["uid"] = act[1]
            o["label"] = f"Активировать {self.sname(act[1])}"
        elif act[0] == "move":
            o["cell"] = [s.q + DIRS[act[1]][0], s.r + DIRS[act[1]][1]]
            o["rel"] = (act[1] - s.facing) % 6
            o["label"] = f"Шаг {REL[(act[1] - s.facing) % 6]} ({s.d['engine']['move_cost']} зар.)"
        elif act[0] == "boost":
            dq, dr = DIRS[s.facing]
            o["cell"] = [s.q + 2 * dq, s.r + 2 * dr]
            o["label"] = "Форсаж: 2 клетки вперёд (2 зар.)"
        elif act[0] == "rot":
            o["label"] = f"Поворот {'вправо' if act[1] > 0 else 'влево'} ({m.pivot_cost(s)} зар.)"
        elif act[0] == "attack":
            t = m.ships[act[1]]
            info = m.attack_offset(s, t)
            ev = m.attack_ev(s, t)
            off = info[0] + (2 if s.has("torpedoes") and s.uses.get("torpedoes", 0) < 2 and 1 <= info[1] <= 3 else 0)
            o["uid"] = act[1]
            o.update(off=off, chance=round(hit_chance(off), 3), ev=round(ev[0], 2), kill=round(ev[1], 3),
                     dist=info[1], a_sec=SEC[info[2]], d_sec=SEC[info[3]])
            o["label"] = (f"Атаковать {self.sname(act[1])}: сила {off:+d}, попадание {hit_chance(off):.0%}, "
                          f"ожидаемый урон корпусу {ev[0]:.1f}, шанс уничтожить {ev[1]:.0%}")
        elif act[0] == "hero":
            name = HERO_ACT.get(act[1], act[1])
            o["hero"] = name
            if act[1] in ("han", "jango"):
                o["cell"] = [act[2], act[3]]
                o["label"] = f"«{name}» → клетка ({act[2]}, {act[3]})"
            elif act[1] in ("vader", "dooku", "kylo", "quigon"):
                o["uid"] = act[2]
                o["label"] = f"«{name}» → {self.sname(act[2])}"
            elif act[1] in ("anakin", "piett"):
                t = m.ships[act[2]]
                o["cell"] = [t.q + DIRS[act[3]][0], t.r + DIRS[act[3]][1]]
                o["label"] = f"«{name}»: сдвинуть {self.sname(act[2])}"
            elif act[1] == "boba":
                o["cell"] = [s.q + DIRS[act[2]][0], s.r + DIRS[act[2]][1]]
                o["label"] = f"«{name}» в сторону {REL[(act[2] - s.facing) % 6]}"
            elif act[1] == "snoke":
                o["label"] = f"«{name}»: {self.sname(act[2])} стреляет в {self.sname(act[3])}"
            else:
                o["label"] = f"«{name}»"
        elif act[0] == "ship":
            name = SHIP_ACT.get(act[1], act[1])
            o["ship"] = name
            if act[1] == "return":
                o["cell"] = [act[3], act[4]]
                o["uid"] = act[2]
                o["label"] = f"Выйти из гиперпространства: {self.sname(act[2])} → клетка ({act[3]}, {act[4]})"
            elif act[1] in ("carrier", "ion", "tractor", "board"):
                o["uid"] = act[2]
                extra = {"carrier": " (1d4 урона, раз за матч)", "ion": " (вместо атаки: −2 заряда цели)",
                         "tractor": " (на клетку к себе)", "board": " (2 заряда, вместо атаки)"}[act[1]]
                o["label"] = f"«{name}» → {self.sname(act[2])}{extra}"
            elif act[1] == "jump":
                o["label"] = f"«{name}» за {m.jump_cost(s)} зар. — корабль уйдёт с поля и вернётся в следующем ходе"
            else:
                o["label"] = f"«{name}» — до конца раунда по кораблю нельзя стрелять издали"
        elif act[0] == "end":
            o["label"] = "Завершить активацию"
        return o


GAME: Game | None = None
REPLAYS = HERE / "replays"                              # GIF повторов (в git не входят)


def make_gif(frames, fps):
    """Кадры повтора (JPEG dataURL из браузера) → GIF в tools/play_v4/replays/."""
    import base64, io, time
    from PIL import Image
    if not frames:
        raise ValueError("нет кадров")
    imgs = []
    for f in frames[:1500]:
        raw = base64.b64decode(f.split(",", 1)[1])
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        imgs.append(im.quantize(colors=128, method=Image.Quantize.FASTOCTREE))
    REPLAYS.mkdir(exist_ok=True)
    name = time.strftime("partiya-%Y%m%d-%H%M%S.gif")
    dur = int(1000 / max(1.0, fps))
    imgs[0].save(REPLAYS / name, save_all=True, append_images=imgs[1:], duration=dur, loop=0, optimize=False)
    return {"url": f"/replays/{name}", "file": str((REPLAYS / name).relative_to(ROOT)), "frames": len(imgs),
            "bytes": (REPLAYS / name).stat().st_size}


class Handler(SimpleHTTPRequestHandler):
    ROUTES = {"/models/": ROOT / "demo" / "assets" / "models" / "v4", "/art/": ROOT / "demo" / "assets" / "card_art"}

    def log_message(self, fmt, *args):
        if "/api/" in str(args[0] if args else ""):
            return

    def translate_path(self, path):
        path = path.split("?")[0]
        for pre, base in self.ROUTES.items():
            if path.startswith(pre):
                return str(base / path[len(pre):])
        if path in ("", "/"):
            path = "/index.html"
        return str(HERE / path.lstrip("/"))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store" if not self.path.startswith(("/models/", "/art/")) else "max-age=3600")
        super().end_headers()

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/api/history"):
            try:
                with GAME.lock:
                    return self._json(GAME.history_state())
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
        if self.path.startswith("/api/state"):
            with GAME.lock:
                st = GAME.state()
                st["fx"] = []                            # анимация — только в ответ на действие, не при перезагрузке
                return self._json(st)
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            with GAME.lock:
                GAME.fx = []
                if self.path == "/api/new":
                    era = body.get("era", "galactic_civil_war")
                    if era not in PLAYABLE:
                        raise ValueError("эта эпоха пока не готова")
                    bot = body.get("bot")
                    if bot and bot.get("level") not in Game.LEVELS:
                        raise ValueError("неизвестный уровень компьютера")
                    GAME.new(era, body.get("mode", "duel"),
                             {"seat": int(bot.get("seat", 1)), "level": bot["level"]} if bot else None,
                             "blackhole" if body.get("place") == "blackhole" else "planet")
                    GAME.bot_draft()
                    GAME.bot_turn()
                elif self.path == "/api/finish":
                    GAME.finish_draft()
                elif self.path == "/api/pick":
                    GAME.pick(body["kind"], body["id"])
                elif self.path == "/api/act":
                    GAME.act(body["act"], defer_bot=bool(body.get("defer_bot")))
                elif self.path == "/api/bot":
                    GAME.bot_turn()
                elif self.path == "/api/gif":
                    return self._json(make_gif(body.get("frames") or [], float(body.get("fps") or 8)))
                elif self.path == "/api/undo":
                    GAME.do_undo()
                elif self.path == "/api/unpick":
                    GAME.unpick()
                elif self.path == "/api/moveto":
                    GAME.move_to(int(body["q"]), int(body["r"]))
                else:
                    return self._json({"error": "нет такого запроса"}, 404)
                return self._json(GAME.state())
        except (ValueError, KeyError) as e:
            return self._json({"error": str(e)}, 400)


Handler.extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript; charset=utf-8",
                          ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                          ".glb": "model/gltf-binary", ".webp": "image/webp"}


def main():
    global GAME
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--cards", action="store_true", help="карточки как есть (по умолчанию так и есть)")
    ap.add_argument("--patch", default=None, help="наложить патч оптимизатора поверх карточек (для проверки)")
    args = ap.parse_args()
    patch, name = empty_patch(), "карточки как есть"
    if args.patch and not args.cards and Path(args.patch).exists():
        patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
        name = f"патч баланса: {Path(args.patch).name}"
    GAME = Game(patch, name)
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Игра: http://localhost:{args.port}/  ({name})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
