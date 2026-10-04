/* demo/bot.js — жадный эвристический бот команды B (сида B1, B2).
 *
 * chooseCommand(state, legal) -> ОДНА команда из legal (или null, если legal пуст):
 *   1. BeginActivation: свой корабль с минимальной дистанцией до ближайшего врага;
 *   2. если есть DeclareAttack: цель с максимумом (arc_attacker − arc_defender).
 *      В бою v3.1 (ADR-014) матожидание обмена — (2d6 + arc_att) против
 *      (d6 + 1 + arc_def); константы 2d6 и +1 одинаковы для всех целей,
 *      поэтому ранжирование по разнице арок остаётся корректным;
 *   3. иначе Move — направление, сильнее всего сокращающее дистанцию до ближайшего врага;
 *   4. иначе RotateLeft/RotateRight, если после поворота ближайший враг окажется
 *      в более сильном секторе (arc по новой ориентации больше текущего);
 *   5. иначе EndActivation; на любой нештатной ветке — случайный элемент legal.
 * Бот никогда не выдумывает команды: возврат всегда элемент legal.
 * Гекс-математика и формула сектора повторяют rust/game_core/src/hex.rs (pin).
 */
(function (global) {
  'use strict';

  const SHIPS = (typeof module !== 'undefined' && module.exports)
    ? require('./ships.js')
    : global.SWBShips;

  const DIR_DELTAS = [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 1], [-1, 0]];

  function inBoard(q, r, radius) {
    const s = -q - r;
    return Math.max(Math.abs(q), Math.abs(r), Math.abs(s)) <= radius;
  }

  function distance(aq, ar, bq, br) {
    const dq = aq - bq, dr = ar - br;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(-dq - dr)) / 2;
  }

  // Индекс направления 0..5 луча from->to: точный для соседей и гекс-лучей,
  // иначе — направление с максимальной целочисленной проекцией смещения
  // (та же арифметика, что ray_direction в engine.rs, без float).
  function directionFrom(fq, fr, tq, tr) {
    const dq = tq - fq, dr = tr - fr;
    for (let d = 0; d < 6; d++) {
      if (DIR_DELTAS[d][0] === dq && DIR_DELTAS[d][1] === dr) return d;
    }
    const wx = 2 * dq + dr, wy = dr;
    let best = 0, bestScore = -Infinity;
    for (let d = 0; d < 6; d++) {
      const a = DIR_DELTAS[d][0], b = DIR_DELTAS[d][1];
      const score = wx * (2 * a + b) + 3 * wy * b;
      if (score > bestScore) { bestScore = score; best = d; }
    }
    return best;
  }

  function sectorOf(facing, dir) {
    return ((dir - facing) % 6 + 6) % 6;
  }

  function arcBonus(typeId, sector) {
    const def = SHIPS.SHIP_DB[typeId];
    return def ? def.arc[sector] : 0;
  }

  function findShip(state, id) {
    for (const s of state.ships) if (s.id === id) return s;
    return null;
  }

  function enemiesOf(state, ship) {
    return state.ships.filter(s => s.alive && s.team !== ship.team);
  }

  function nearestEnemy(state, ship) {
    let best = null, bestD = Infinity;
    for (const e of enemiesOf(state, ship)) {
      const d = distance(ship.q, ship.r, e.q, e.r);
      if (d < bestD) { bestD = d; best = e; }
    }
    return best;
  }

  // Разница арок для выбора цели. Ожидаемый исход боя v3.1 (ADR-014):
  // (7 + arc_att − range_penalty) − (4.5 + arc_def) = 2.5 + arc_att − arc_def,
  // поэтому сравнение секторов по (arc_att − arc_def) совпадает со сравнением
  // по ожидаемой силе; предпочтение атаки не менялось.
  function attackScore(attacker, target) {
    const dirA = directionFrom(attacker.q, attacker.r, target.q, target.r);
    const dirD = directionFrom(target.q, target.r, attacker.q, attacker.r);
    return arcBonus(attacker.type_id, sectorOf(attacker.facing, dirA)) -
           arcBonus(target.type_id, sectorOf(target.facing, dirD));
  }

  function inList(legal, cmd) {
    const text = JSON.stringify(cmd);
    return legal.some(c => JSON.stringify(c) === text);
  }

  function fallback(legal) {
    return legal[Math.floor(Math.random() * legal.length)];
  }

  function chooseCommand(state, legal) {
    if (!legal || legal.length === 0) return null;

    // 1) Начало активации: ближайший к врагу корабль.
    const begins = legal.filter(c => c.type === 'BeginActivation');
    if (begins.length > 0) {
      let best = begins[0], bestD = Infinity;
      for (const c of begins) {
        const ship = findShip(state, c.ship_instance_id);
        const enemy = ship ? nearestEnemy(state, ship) : null;
        const d = (ship && enemy) ? distance(ship.q, ship.r, enemy.q, enemy.r) : 999;
        if (d < bestD) { bestD = d; best = c; }
      }
      return inList(legal, best) ? best : fallback(legal);
    }

    // 2) Атака: максимум преимущества арки.
    const attacks = legal.filter(c => c.type === 'DeclareAttack');
    if (attacks.length > 0) {
      const me = findShip(state, state.active_ship);
      let best = attacks[0], bestS = -Infinity;
      for (const c of attacks) {
        const target = findShip(state, c.target_ship_instance_id);
        const s = (me && target) ? attackScore(me, target) : 0;
        if (s > bestS) { bestS = s; best = c; }
      }
      return inList(legal, best) ? best : fallback(legal);
    }

    const me = findShip(state, state.active_ship);

    // 3) Движение, сокращающее дистанцию до ближайшего врага.
    // v3.4: движение в любую сторону — направление, сильнее всего сокращающее
    // дистанцию до ближайшего врага
    const moves = legal.filter(c => c.type === 'Move');
    let move = null, bestD = Infinity;
    for (const m of moves) {
      const tq = me.q + DIR_DELTAS[m.dir][0], tr = me.r + DIR_DELTAS[m.dir][1];
      let dNear = Infinity;
      for (const e of state.ships) {
        if (!e.alive || e.team === me.team) continue;
        dNear = Math.min(dNear, distance(tq, tr, e.q, e.r));
      }
      if (dNear < bestD) { bestD = dNear; move = m; }
    }
    if (move && me) {
      const enemy = nearestEnemy(state, me);
      if (enemy) {
        const d = DIR_DELTAS[me.facing];
        const cur = distance(me.q, me.r, enemy.q, enemy.r);
        const nxt = distance(me.q + d[0], me.r + d[1], enemy.q, enemy.r);
        if (nxt < cur) return move;
      }
    }

    // 4) Поворот: враг в более сильном секторе после разворота.
    const rotLeft = legal.find(c => c.type === 'RotateLeft');
    const rotRight = legal.find(c => c.type === 'RotateRight');
    if ((rotLeft || rotRight) && me) {
      const enemy = nearestEnemy(state, me);
      if (enemy) {
        const dir = directionFrom(me.q, me.r, enemy.q, enemy.r);
        let bestRot = null, bestArc = arcBonus(me.type_id, sectorOf(me.facing, dir));
        if (rotLeft) {
          const a = arcBonus(me.type_id, sectorOf((me.facing + 5) % 6, dir));
          if (a > bestArc) { bestArc = a; bestRot = rotLeft; }
        }
        if (rotRight) {
          const a = arcBonus(me.type_id, sectorOf((me.facing + 1) % 6, dir));
          if (a > bestArc) { bestArc = a; bestRot = rotRight; }
        }
        if (bestRot) return bestRot;
      }
    }

    // 5) Иначе — конец активации; на крайний случай случайная легальная команда.
    const end = legal.find(c => c.type === 'EndActivation');
    if (end) return end;
    return fallback(legal);
  }

  const api = {
    chooseCommand,
    // экспорт утилит для мини-тестов под node:
    distance, directionFrom, sectorOf, arcBonus, nearestEnemy
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.SWBBot = api;
})(typeof window !== 'undefined' ? window : globalThis);
