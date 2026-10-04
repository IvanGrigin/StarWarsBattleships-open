/* demo/mock_core.js — МОК window.swb для проверки веб-демо БЕЗ WASM-ядра.
 * Тот же контракт, что у настоящего клея (см. demo/README.md):
 *   create_match(seed, round_limit) -> String (JSON состояния)
 *   legal_actions(state_json)       -> String (JSON-массив команд)
 *   apply_command(state_json, cmd)  -> String {"ok":true,"events":[..],"state":{..}}
 *                                       | {"ok":false,"error":"код"}
 *   state_hash(state_json)          -> String
 *
 * Это упрощённая, но играбельная заглушка: дуэль 3×3, как в сценарии v3,
 * движение/повороты/соседний бой с фейковыми кубиками (LCG). Бой повторяет
 * правила v3.1 (ADR-014): атакующий бросает 2×d6, защитник — d6 + плоский
 * бонус +1; события несут dice (грани стороны), die (сумма) и flat_bonus.
 * Защитный лимит успешных команд можно переопределить через
 * window.SWB_MOCK_ACTION_LIMIT. Поле/арки/HP — упрощённые.
 */
(function (global) {
  'use strict';

  const DIR_DELTAS = [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 1], [-1, 0]];
  const SEATS = ['A1', 'B1'];
  const BOARD_RADIUS = 3;
  const ACTION_LIMIT = (global.SWB_MOCK_ACTION_LIMIT | 0) || 180;

  const TYPES = {
    xwing_t65:       { hp: 4, shield: 0, max_charges: 5, arc: [2, 1, 0, 1, 0, 1] },
    eta2_actis:      { hp: 5, shield: 0, max_charges: 5, arc: [2, 1, 1, 0, 1, 1] },
    tie_fighter:     { hp: 4, shield: 0, max_charges: 5, arc: [2, 1, 0, 0, 0, 1] },
    tie_advanced_x1: { hp: 6, shield: 1, max_charges: 5, arc: [3, 1, 1, 0, 1, 1] },
    millennium_falcon: { hp: 8, shield: 1, max_charges: 5, arc: [2, 1, 2, 0, 2, 1] },
    star_destroyer:    { hp: 8, shield: 1, max_charges: 5, arc: [2, 2, 1, 1, 1, 2] },
    death_star_1:      { hp: 11, shield: 2, max_charges: 5, arc: [7, 0, 0, -1, 0, 0] },
    slave_1:           { hp: 6, shield: 1, max_charges: 5, arc: [3, 1, 0, 2, 0, 1] },
    ghost:             { hp: 6, shield: 1, max_charges: 5, arc: [2, 1, 0, 2, 0, 1] },
    phantom:           { hp: 2, shield: 0, max_charges: 5, arc: [2, 1, 0, -1, 0, 1] },
    vulture_droid:     { hp: 4, shield: 0, max_charges: 5, arc: [1, 1, 1, 0, 1, 1] }
  };

  // Те же стартовые клетки, что в data/rulesets/v3/scenarios/classic_2v2.json.
  // Все шесть координат лежат внутри поля радиуса 3 и не пересекаются.
  const SETUP = [
    { seat: 'A1', team: 'A', type: 'xwing_t65',         q: 0,  r: 3,  facing: 0 },
    { seat: 'A1', team: 'A', type: 'millennium_falcon', q: 0,  r: 2,  facing: 0 },
    { seat: 'A1', team: 'A', type: 'ghost',              q: 1,  r: 2,  facing: 0 },
    { seat: 'B1', team: 'B', type: 'tie_fighter',        q: 0,  r: -3, facing: 3 },
    { seat: 'B1', team: 'B', type: 'tie_advanced_x1',    q: 0,  r: -2, facing: 3 },
    { seat: 'B1', team: 'B', type: 'star_destroyer',     q: -1, r: -2, facing: 3 }
  ];

  let rngState = 1;
  let applyCount = 0;

  function rnd() {
    rngState = (rngState * 1103515245 + 12345) & 0x7fffffff;
    return rngState / 0x7fffffff;
  }
  function die(sides) { return 1 + Math.floor(rnd() * sides); }

  function inBoard(q, r) {
    const s = -q - r;
    return Math.max(Math.abs(q), Math.abs(r), Math.abs(s)) <= BOARD_RADIUS;
  }
  function distance(a, b) {
    const dq = a.q - b.q, dr = a.r - b.r;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(-dq - dr)) / 2;
  }
  function clone(v) { return JSON.parse(JSON.stringify(v)); }
  function canonicalize(v) {
    if (Array.isArray(v)) return v.map(canonicalize);
    if (v && typeof v === 'object') {
      const out = {};
      Object.keys(v).sort().forEach(k => { out[k] = canonicalize(v[k]); });
      return out;
    }
    return v;
  }
  function fail(code) { return JSON.stringify({ ok: false, error: code }); }

  function create_match(seed, round_limit) {
    rngState = ((seed | 0) & 0x7fffffff) || 1;
    applyCount = 0;
    const ships = SETUP.map(s => ({
      id: `${s.seat}_${s.type}_0`,
      type_id: s.type,
      seat: s.seat,
      team: s.team,
      q: s.q, r: s.r, facing: s.facing,
      hp: TYPES[s.type].hp,
      shield: TYPES[s.type].shield,
      charges: 3,
      activated: false,
      attack_used: false,
      alive: true,
      revive_used: false
    }));
    const state = {
      version: 1,
      ruleset_id: 'mock',
      ruleset_hash: 'mock0',
      seed: seed | 0,
      phase: 'activation',
      round: 1,
      round_limit: round_limit || 60,
      active_seat: 'A1',
      active_ship: null,
      rng_counter: 0,
      dice: [],
      winner: null,
      ships
    };
    return JSON.stringify(state);
  }

  function legal_actions(state_json) {
    const st = JSON.parse(state_json);
    const out = [];
    if (st.phase !== 'activation') return JSON.stringify(out);
    if (!st.active_ship) {
      for (const s of st.ships) {
        if (s.seat === st.active_seat && s.alive && !s.activated) {
          out.push({ type: 'BeginActivation', ship_instance_id: s.id });
        }
      }
      return JSON.stringify(out);
    }
    const ship = st.ships.find(s => s.id === st.active_ship);
    if (ship && ship.alive && ship.charges > 0) {
      // v3.4: движение в любую сторону
      for (let dir = 0; dir < 6; dir++) {
        const dd = DIR_DELTAS[dir];
        const tq = ship.q + dd[0], tr = ship.r + dd[1];
        const occupied = st.ships.some(o => o.alive && o.q === tq && o.r === tr);
        if (inBoard(tq, tr) && !occupied) out.push({ type: 'Move', dir });
      }
      out.push({ type: 'RotateLeft' });
      out.push({ type: 'RotateRight' });
    }
    if (ship && ship.alive && !ship.attack_used) {
      for (const o of st.ships) {
        if (o.alive && o.team !== ship.team && distance(ship, o) === 1) {
          out.push({ type: 'DeclareAttack', target_ship_instance_id: o.id });
        }
      }
    }
    out.push({ type: 'EndActivation' });
    return JSON.stringify(out);
  }

  function passTurn(st, events) {
    const idx = SEATS.indexOf(st.active_seat);
    for (let j = 1; j <= SEATS.length; j++) {
      const cand = SEATS[(idx + j) % SEATS.length];
      if (st.ships.some(s => s.seat === cand && s.alive && !s.activated)) {
        st.active_seat = cand;
        return;
      }
    }
    if (st.round + 1 > st.round_limit) {
      st.phase = 'ended';
      st.winner = null;
      events.push({ type: 'MatchEnded', winner: null, reason: 'round_limit' });
      return;
    }
    st.round += 1;
    for (const s of st.ships) { s.activated = false; s.attack_used = false; }
    st.active_seat = SEATS.find(c => st.ships.some(s => s.seat === c && s.alive)) || 'A1';
    events.push({ type: 'RoundStarted', round: st.round });
  }

  function apply_command(state_json, cmd_json) {
    const st = JSON.parse(state_json);
    const cmd = JSON.parse(cmd_json);
    if (st.phase !== 'activation') return fail('wrong_phase');
    const n = clone(st);
    const events = [];

    if (cmd.type === 'BeginActivation') {
      if (n.active_ship) return fail('not_active_ship');
      const s = n.ships.find(x => x.id === cmd.ship_instance_id);
      if (!s) return fail('unknown_ship');
      if (s.seat !== n.active_seat) return fail('not_your_seat');
      if (!s.alive) return fail('ship_dead');
      if (s.activated) return fail('already_activated');
      n.active_ship = s.id;
      events.push({ type: 'ActivationStarted', seat: n.active_seat, ship_instance_id: s.id, charges: s.charges });
    } else {
      if (!n.active_ship) return fail('not_active_ship');
      const s = n.ships.find(x => x.id === n.active_ship);
      if (!s) return fail('unknown_ship');

      switch (cmd.type) {
        case 'Move': {
          if (!s.alive) return fail('ship_dead');
          if (s.charges <= 0) return fail('no_charges');
          const dir = cmd.dir | 0;
          if (dir < 0 || dir > 5) return fail('bad_direction');
          const d = DIR_DELTAS[dir];
          const tq = s.q + d[0], tr = s.r + d[1];
          if (!inBoard(tq, tr)) return fail('out_of_board');
          if (n.ships.some(o => o.alive && o.q === tq && o.r === tr)) return fail('occupied_cell');
          const fq = s.q, fr = s.r;
          s.charges -= 1; s.q = tq; s.r = tr;
          events.push({ type: 'ChargeSpent', ship_instance_id: s.id, reason: 'move', charges_left: s.charges });
          events.push({ type: 'ShipMoved', ship_instance_id: s.id, from_q: fq, from_r: fr, to_q: tq, to_r: tr, dir });
          break;
        }
        case 'RotateLeft':
        case 'RotateRight': {
          if (!s.alive) return fail('ship_dead');
          if (s.charges <= 0) return fail('no_charges');
          const from = s.facing;
          s.charges -= 1;
          s.facing = (s.facing + (cmd.type === 'RotateRight' ? 1 : 5)) % 6;
          events.push({ type: 'ChargeSpent', ship_instance_id: s.id, reason: 'rotate', charges_left: s.charges });
          events.push({ type: 'ShipRotated', ship_instance_id: s.id, from_facing: from, to_facing: s.facing });
          break;
        }
        case 'DeclareAttack': {
          if (!s.alive) return fail('ship_dead');
          if (s.attack_used) return fail('attack_used');
          const t = n.ships.find(x => x.id === cmd.target_ship_instance_id);
          if (!t) return fail('unknown_ship');
          if (!t.alive) return fail('bad_target');
          if (t.team === s.team) return fail('bad_target');
          if (distance(s, t) !== 1) return fail('not_adjacent');
          s.attack_used = true;
          events.push({ type: 'AttackDeclared', attacker_id: s.id, target_id: t.id });

          // Бой v3.1 (ADR-014): атакующий бросает 2×d6, защитник — один d6
          // плюс плоский бонус +1; секторы-арки считаются поверх. В событии
          // StrengthCalculated: dice — грани стороны, die — их сумма,
          // flat_bonus — плоский бонус стороны (у защитника 1, у атакующего 0).
          const DEF_FLAT_BONUS = 1;
          const dirA = DIR_DELTAS.findIndex(d => d[0] === t.q - s.q && d[1] === t.r - s.r);
          const dirD = DIR_DELTAS.findIndex(d => d[0] === s.q - t.q && d[1] === s.r - t.r);
          const arcA = TYPES[s.type_id].arc[(dirA - s.facing + 12) % 6];
          const arcD = TYPES[t.type_id].arc[(dirD - t.facing + 12) % 6];

          // Порядок бросков (ADR-014 §3): d6₁ и d6₂ атакующего, затем d6 защитника.
          const faceA1 = die(6), faceA2 = die(6);
          events.push({ type: 'DieRolled', rng_index: n.rng_counter, sides: 6, value: faceA1, role: 'attacker' });
          n.rng_counter += 1; n.dice.push(6);
          events.push({ type: 'DieRolled', rng_index: n.rng_counter, sides: 6, value: faceA2, role: 'attacker' });
          n.rng_counter += 1; n.dice.push(6);
          // Мок умеет только соседний бой, поэтому штраф дистанции всегда 0.
          const totA = Math.max(0, faceA1 + faceA2 + arcA);
          events.push({ type: 'StrengthCalculated', ship_instance_id: s.id, die: faceA1 + faceA2, dice: [faceA1, faceA2], flat_bonus: 0, sector_index: (dirA - s.facing + 12) % 6, arc_bonus: arcA, total: totA, range_penalty: 0 });

          const faceD = die(6);
          events.push({ type: 'DieRolled', rng_index: n.rng_counter, sides: 6, value: faceD, role: 'defender' });
          n.rng_counter += 1; n.dice.push(6);
          const totD = Math.max(0, faceD + DEF_FLAT_BONUS + arcD);
          events.push({ type: 'StrengthCalculated', ship_instance_id: t.id, die: faceD, dice: [faceD], flat_bonus: DEF_FLAT_BONUS, sector_index: (dirD - t.facing + 12) % 6, arc_bonus: arcD, total: totD, range_penalty: 0 });

          const diff = Math.abs(totA - totD);
          if (diff > 0) {
            const loser = totA > totD ? t : s;
            const shieldDamage = Math.min(loser.shield, diff);
            const hullDamage = Math.min(loser.hp, diff - shieldDamage);
            loser.shield -= shieldDamage;
            loser.hp -= hullDamage;
            events.push({ type: 'DamageApplied', target_id: loser.id, shield_damage: shieldDamage, hull_damage: hullDamage, hp_left: loser.hp, shield_left: loser.shield });
            if (loser.hp <= 0) {
              loser.hp = 0;
              loser.alive = false;
              events.push({ type: 'ShipDestroyed', ship_instance_id: loser.id });
            }
          }
          break;
        }
        case 'EndActivation': {
          // v3.5: восстановления +1 нет — заряды перезаписываются в конце раунда
          s.activated = true;
          n.active_ship = null;
          events.push({ type: 'ActivationEnded', ship_instance_id: s.id, charges: s.charges });
          passTurn(n, events);
          break;
        }
        default:
          return fail('unknown_command');
      }
    }

    // Защитный лимит не даёт мок-матчу продолжаться бесконечно.
    applyCount += 1;
    if (n.phase !== 'ended' && applyCount >= ACTION_LIMIT) {
      n.phase = 'ended';
      const aAlive = n.ships.some(x => x.alive && x.team === 'A');
      const bAlive = n.ships.some(x => x.alive && x.team === 'B');
      n.winner = aAlive && !bAlive ? 'A' : (bAlive && !aAlive ? 'B' : null);
      events.push({ type: 'MatchEnded', winner: n.winner, reason: 'round_limit' });
    }

    return JSON.stringify({ ok: true, events, state: n });
  }

  function state_hash(state_json) {
    const text = JSON.stringify(canonicalize(JSON.parse(state_json)));
    let h = 0x811c9dc5;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    return h.toString(16).toUpperCase().padStart(8, '0');
  }

  global.swb = { create_match, legal_actions, apply_command, state_hash };
})(typeof window !== 'undefined' ? window : globalThis);
