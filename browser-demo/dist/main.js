/* demo/main.js — фронтенд веб-демо Star Wars Battleships.
 *
 * Работает поверх window.swb (WASM-клей, появится позже в demo/pkg/) с контрактом:
 *   swb.create_match(seed, round_limit) -> String (JSON состояния)
 *   swb.legal_actions(state_json)       -> String (JSON-массив команд)
 *   swb.apply_command(state_json, cmd)  -> String {"ok":true,"events":[..],"state":{..}}
 *                                          | {"ok":false,"error":"код"}
 *   swb.state_hash(state_json)          -> String
 * Если window.swb отсутствует (штатная ситуация до сборки WASM), main.js сам
 * подгружает demo/mock_core.js и показывает жёлтую плашку «ДЕМО-МОК».
 * Параметр URL ?mock=1 включает мок принудительно, даже если swb есть.
 *
 * Игрок — команда A (сид A1, A2), бот — команда B (demo/bot.js).
 * Никаких внешних запросов: только локальные файлы и системные шрифты.
 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  const BOARD_RADIUS = 3; // v3.2: поле радиуса 3 — 37 гексов, диаметр 7
  const SECTOR_NAMES = ['F', 'FR', 'BR', 'B', 'BL', 'FL'];
  const DIR_DELTAS = [[0, -1], [1, -1], [1, 0], [0, 1], [-1, 1], [-1, 0]];
  // Полуразмер поля: max|q+r/2| = 3 → 3*sqrt(3) ≈ 5.20 + половина гекса ≈ 0.87, с запасом.
  const HALF_EXTENT = 7.2; // включает стартовые позиции флотов за границей радиуса-3

  const TEAM_COLORS = { A: '#4fa3f7', B: '#f75d5d' };
  const ASSETS = window.SWBAssets || null;

  const SHIP_DB = window.SWBShips.SHIP_DB;
  const ABILITY_LABELS = window.SWBShips.ABILITY_LABELS;
  const GLYPH = window.SWBShips.FACING_GLYPHS;

  let swb = null;
  let mockMode = false;
  let coreError = false;

  let state = null;          // текущий snapshot (объект)
  let legal = [];            // legal_actions(state)
  let logEntries = [];       // журнал, newest first
  let stars = [];
  let botTimer = null;
  let matchEndReason = null;

  let canvas = null;
  let ctx = null;

  // ---------- 3D-сцена ----------
  // Воксельные модели (voxel_ships) -> процедурные (models3d) -> сцена (board3d).
  // При неудаче загрузки — откат на прежний 2D-канвас без изменения логики.
  let Board3D = null;
  const scene3dReady = (async () => {
    try {
      const [b3, vox, m3] = await Promise.all([
        import('./board3d.js'),
        import('./voxel_ships.js'),
        import('./models3d.js'),
      ]);
      try { await m3.loadExternalModels(); } catch (e) { console.warn('Внешние модели не загружены:', e); }
      try { await m3.loadSchemModels(); } catch (e) { console.warn('Schem-модели не загружены:', e); }
      m3.primeVoxelSource(vox);
      Board3D = b3.Board3D;
    } catch (e) {
      console.error('3D-сцена недоступна, откат на 2D:', e);
    }
  })();

  function syncScene() {
    if (!Board3D || !state) return;
    Board3D.setState(state);
    Board3D.setLegal(legal);
  }

  // Эффект урона/взрыва: в 3D — по клетке, в 2D — по пикселям.
  function fxAt(ship, kind) {
    if (Board3D) { Board3D.spawnHit(ship.q, ship.r, kind); return; }
    const cc = cellToPx(ship.q, ship.r, boardParams());
    spawnHit(cc.x, cc.y, kind);
  }

  // ---------- Загрузка ядра ----------

  function loadCore() {
    return new Promise((resolve) => {
      const forceMock = /[?&]mock=1/.test(window.location.search);
      const useReal = () => { swb = window.swb; resolve(); };
      const useMock = () => {
        const script = document.createElement('script');
        script.src = 'mock_core.js';
        script.onload = () => {
          if (window.swb) {
            swb = window.swb;
            mockMode = true;
            const banner = $('mock-banner');
            banner.textContent = forceMock
              ? 'ДЕМО-МОК (включён параметром ?mock=1): работает заглушка mock_core.js вместо WASM-ядра'
              : 'ДЕМО-МОК: WASM-ядро не найдено — работает заглушка mock_core.js';
            banner.classList.remove('hidden');
          }
          resolve();
        };
        script.onerror = () => resolve();
        document.head.appendChild(script);
      };
      if (window.swb && !forceMock) {
        useReal();
        return;
      }
      // pkg-loader.js стартовал импорт WASM-ядра: дожидаемся его, иначе — мок.
      if (window.SWB_READY && !forceMock) {
        const started = Date.now();
        const poll = setInterval(() => {
          if (window.swb) { clearInterval(poll); useReal(); return; }
          if (Date.now() - started > 15000) { clearInterval(poll); useMock(); }
        }, 50);
        window.SWB_READY.catch(() => { clearInterval(poll); useMock(); });
        return;
      }
      useMock();
    });
  }

  function showCoreProblem(message) {
    coreError = true;
    const banner = $('mock-banner');
    banner.textContent = message;
    banner.classList.remove('hidden');
  }

  // ---------- Жизненный цикл матча ----------

  function newMatch() {
    if (!swb) return;
    if (botTimer) { clearTimeout(botTimer); botTimer = null; }
    matchEndReason = null;
    const seed = Math.floor(Math.random() * 2147483647);
    try {
      state = JSON.parse(swb.create_match(seed, 60));
    } catch (e) {
      showCoreProblem('Ошибка create_match: ' + e.message);
      return;
    }
    logEntries = [];
    makeStars(seed);
    makeClouds(seed);
    pushLog({ t: 'round', text: 'Новый матч · seed ' + seed + (mockMode ? ' · МОК' : '') });
    pushLog({ t: 'info', text: 'Флот A (вы): ' + roster('A') });
    pushLog({ t: 'info', text: 'Флот B (бот): ' + roster('B') });
    refreshLegal();
    hideOverlay();
    renderPanel();
    syncScene();
    scheduleBot();
  }

  function roster(team) {
    return state.ships
      .filter((s) => s.team === team)
      .map((s) => (SHIP_DB[s.type_id] ? SHIP_DB[s.type_id].name : s.type_id))
      .join(', ');
  }

  function refreshLegal() {
    try {
      legal = JSON.parse(swb.legal_actions(JSON.stringify(state))) || [];
    } catch (e) {
      legal = [];
      showCoreProblem('Ошибка legal_actions: ' + e.message);
    }
  }

  function applyCommand(cmd) {
    if (!state || state.phase === 'ended') return;
    let res;
    try {
      res = JSON.parse(swb.apply_command(JSON.stringify(state), JSON.stringify(cmd)));
    } catch (e) {
      showCoreProblem('Ошибка apply_command: ' + e.message);
      return;
    }
    if (!res.ok) {
      pushLog({ t: 'bad', text: 'Команда отклонена: ' + (res.error || 'неизвестная ошибка') });
      renderPanel();
      return;
    }
    for (const ev of res.events) {
      if (ev.type === 'MatchEnded') matchEndReason = ev.reason;
      if (ev.type === 'DamageApplied') {
        const t = findShip(ev.target_id);
        if (t) fxAt(t, 'hit');
      }
      if (ev.type === 'ShipDestroyed') {
        const t = findShip(ev.ship_instance_id);
        if (t) {
          fxAt(t, 'boom');
          if (!Board3D) shakeUntil = performance.now() + 240; // в 3D тряска внутри сцены
        }
      }
    }
    const lines = eventsToLog(res.events, state);
    for (const line of lines) pushLog(line);
    state = res.state;
    refreshLegal();
    syncScene();
    renderPanel();
    if (state.phase === 'ended') showOverlay();
    else scheduleBot();
  }

  // ---------- Ходы ----------

  function isBotTurn() {
    return !!state && state.phase === 'activation' && state.active_seat.charAt(0) === 'B';
  }
  function isPlayerTurn() {
    return !!state && state.phase === 'activation' && state.active_seat.charAt(0) === 'A';
  }

  function scheduleBot() {
    if (botTimer) { clearTimeout(botTimer); botTimer = null; }
    if (!isBotTurn()) return;
    botTimer = setTimeout(() => {
      botTimer = null;
      if (!isBotTurn()) return;
      refreshLegal();
      const cmd = window.SWBBot.chooseCommand(state, legal);
      if (!cmd) return; // legal пуст — нечему ходить (не должно случаться)
      applyCommand(cmd);
    }, 550);
  }

  function findShip(id) {
    if (!state) return null;
    for (const s of state.ships) if (s.id === id) return s;
    return null;
  }

  // ---------- Журнал ----------

  function pushLog(entry) {
    logEntries.unshift(entry);
    if (logEntries.length > 60) logEntries.length = 60;
    renderLog();
  }

  function renderLog() {
    const ul = $('log');
    ul.innerHTML = '';
    const n = Math.min(logEntries.length, 8);
    for (let i = 0; i < n; i++) {
      const li = document.createElement('li');
      li.className = 'l-' + logEntries[i].t;
      li.textContent = logEntries[i].text;
      ul.appendChild(li);
    }
  }

  function typeName(typeId) {
    return SHIP_DB[typeId] ? SHIP_DB[typeId].name : typeId;
  }

  function shipLabel(prevState, id) {
    for (const s of prevState.ships) {
      if (s.id === id) return typeName(s.type_id) + ' [' + s.seat + ']';
    }
    return id;
  }

  // Событияapply_command -> русские фразы журнала.
  function eventsToLog(events, prevState) {
    const lines = [];
    let atk = null;          // текущая атака: {attacker, target, sA, sD}
    let pendingCharge = null;

    const label = (id) => shipLabel(prevState, id);

  // Сила стороны по StrengthCalculated (бой v3.1, ADR-014):
  // «2d6 [3+5]+F2−2=8» / «d6 [4]+1+F0=5» — кубики [грани], арка сектора,
  // (плоский бонус защитника), (штраф дистанции «−Ш»), итог.
  // ev.die — сумма граней стороны (совместимость), ev.dice — массив граней.
  const sideText = (ev) => {
    const dice = (ev.dice && ev.dice.length) ? ev.dice : [ev.die];
    let s = (dice.length > 1 ? dice.length + 'd6' : 'd6') + ' [' + dice.join('+') + ']+';
    if (ev.flat_bonus) s += ev.flat_bonus + '+';
    s += sectorArc(ev.sector_index, ev.arc_bonus);
    if (ev.range_penalty) s += '−' + ev.range_penalty;
    return s + '=' + ev.total;
  };

    for (const ev of events) {
      switch (ev.type) {
        case 'RoundStarted':
          lines.push({ t: 'round', text: '— Раунд ' + ev.round + ' —' });
          break;
        case 'ActivationStarted':
          lines.push({ t: 'info', text: 'Ход: ' + label(ev.ship_instance_id) + ' (' + ev.seat + '), заряды: ' + ev.charges });
          break;
        case 'ActivationEnded':
          lines.push({ t: 'info', text: label(ev.ship_instance_id) + ' завершает активацию (заряды: ' + ev.charges + ')' });
          break;
        case 'ChargesRefreshed':
          lines.push({ t: ev.full ? 'good' : 'info', text: label(ev.ship_instance_id) + ': заряды перезаписаны → ' + ev.charges + (ev.full ? ' (полный — не тратил)' : ' (половина с округлением вверх)') });
          break;
        case 'ChargeSpent':
          pendingCharge = ev;
          break;
        case 'ShipMoved':
          lines.push({
            t: 'info',
            text: label(ev.ship_instance_id) + ' летит → (' + ev.to_q + ',' + ev.to_r + ')' +
              (pendingCharge ? ' · зарядов: ' + pendingCharge.charges_left : '')
          });
          pendingCharge = null;
          break;
        case 'ShipRotated':
          lines.push({
            t: 'info',
            text: label(ev.ship_instance_id) + ' поворот ' + (GLYPH[ev.from_facing] || '') + ' → ' + (GLYPH[ev.to_facing] || '') +
              (pendingCharge ? ' · зарядов: ' + pendingCharge.charges_left : '')
          });
          pendingCharge = null;
          break;
        case 'AttackDeclared':
          atk = { attacker: ev.attacker_id, target: ev.target_id, sA: null, sD: null };
          break;
        case 'StrengthCalculated':
          if (atk) {
            if (ev.ship_instance_id === atk.attacker) atk.sA = ev;
            else if (ev.ship_instance_id === atk.target) atk.sD = ev;
          }
          break;
        case 'DamageApplied': {
          if (atk && atk.sA && atk.sD) {
            let prevT = null;
            for (const s of prevState.ships) if (s.id === ev.target_id) { prevT = s; break; }
            const sh0 = prevT ? prevT.shield : ev.shield_left + ev.shield_damage;
            const hp0 = prevT ? prevT.hp : ev.hp_left + ev.hull_damage;
            const dmg = ev.shield_damage + ev.hull_damage;
            const tail = dmg > 0
              ? '→ урон ' + dmg + ' (щит ' + sh0 + '→' + ev.shield_left + ', HP ' + hp0 + '→' + ev.hp_left + ')'
              : '→ урона нет';
            lines.push({
              t: 'combat',
              text: label(atk.attacker) + ' ⚡ ' + label(atk.target) +
                ': атак. ' + sideText(atk.sA) + ', защ. ' + sideText(atk.sD) + ' ' + tail
            });
          } else {
            lines.push({
              t: 'combat',
              text: 'Урон по ' + label(ev.target_id) + ': щит −' + ev.shield_damage +
                ', корпус −' + ev.hull_damage + ' (HP ' + ev.hp_left + ')'
            });
          }
          atk = null;
          break;
        }
        case 'ShipDestroyed':
          atk = null;
          lines.push({ t: 'bad', text: '☠ ' + label(ev.ship_instance_id) + ' уничтожен' });
          break;
        case 'ShipTransformed':
          lines.push({
            t: 'good',
            text: '✦ ' + label(ev.ship_instance_id) + ': ' + typeName(ev.from_type) +
              ' превращается в ' + typeName(ev.to_type) + ' (HP ' + ev.hp + ', щит 0)'
          });
          break;
        case 'ShipRevived':
          lines.push({ t: 'good', text: '✚ ' + label(ev.ship_instance_id) + ' воскресает с HP ' + ev.hp + '!' });
          break;
        case 'MatchEnded':
          lines.push({ t: 'round', text: 'Матч окончен.' });
          break;
        default:
          break; // MatchCreated/ShipPlaced/DieRolled — броски видны в строке боя
      }
    }
    // Атака завершена без DamageApplied (ничья сил).
    if (atk && atk.sA && atk.sD) {
      lines.push({
        t: 'combat',
        text: label(atk.attacker) + ' ⚡ ' + label(atk.target) +
          ': атак. ' + sideText(atk.sA) + ', защ. ' + sideText(atk.sD) + ' → ничья, урона нет'
      });
    }
    return lines;
  }

  // ---------- Панель ----------

  function renderPanel() {
    if (!state) return;
    $('round-info').textContent = 'Раунд ' + state.round + ' / ' + state.round_limit;
    $('score-a').textContent = String(state.ships.filter((s) => s.team === 'A' && s.alive).length).padStart(2, '0');
    $('score-b').textContent = String(state.ships.filter((s) => s.team === 'B' && s.alive).length).padStart(2, '0');
    const turn = $('turn-info');
    if (state.phase === 'ended') {
      turn.textContent = 'Матч завершён';
      turn.className = '';
    } else if (isPlayerTurn()) {
      turn.textContent = 'Ваш ход · сид ' + state.active_seat;
      turn.className = 'turn-a';
    } else {
      turn.textContent = 'Ход бота · сид ' + state.active_seat + '…';
      turn.className = 'turn-b';
    }
    renderShipCard();
    renderActions();
    renderLog();
    drawRadar();
  }

  function renderShipCard() {
    const box = $('ship-info');
    const id = state.active_ship;
    if (!id) {
      box.innerHTML = '<div class="ship-profile"><div class="ship-portrait fleet-scan"></div>' +
        '<div><div class="ship-title">Ожидание приказа<span class="seat">ВЫБЕРИТЕ КОРАБЛЬ НА ПОЛЕ</span></div>' +
        '<div class="meter-row"><span>КАНАЛ</span><div class="meter shield"><i style="width:100%"></i></div><b>ГОТОВ</b></div></div></div>';
      return;
    }
    const s = findShip(id);
    if (!s) { box.innerHTML = ''; return; }
    const def = SHIP_DB[s.type_id] || { name: s.type_id, max_charges: 5, abilities: [], hp: s.hp, shield: s.shield };
    let dots = '';
    for (let i = 0; i < def.max_charges; i++) dots += i < s.charges ? '▰' : '▱';
    const tags = (def.abilities || [])
      .map((a) => '<span>' + (ABILITY_LABELS[a] || a) + '</span>')
      .join('');
    const img = ASSETS ? ASSETS.url('ships', s.type_id) : '';
    const hpPct = Math.max(0, Math.min(100, s.hp / Math.max(1, def.hp) * 100));
    const shieldMax = Math.max(1, def.shield || 1);
    const shPct = Math.max(0, Math.min(100, s.shield / shieldMax * 100));
    const tokenFacing = ['nw', 'ne', 'e', 'se', 'sw', 'w'][((s.facing || 0) % 6 + 6) % 6];
    const tokenTheme = s.team === 'A' ? 'ally' : 'enemy';
    const tokenArcs = (def.arc || [0, 0, 0, 0, 0, 0]).join(',');
    box.innerHTML = '<div class="ship-profile ship-profile-token"><swb-ship-hex class="ship-token-mini"' +
      (img ? ' ship-src="' + img + '"' : '') +
      ' ship-alt="' + def.name + '" label="' + s.seat + '" arcs="' + tokenArcs + '"' +
      ' facing="' + tokenFacing + '" theme="' + tokenTheme + '"' +
      (s.id === state.active_ship ? ' selected' : '') + '></swb-ship-hex><div>' +
      '<div class="ship-title">' + def.name + '<span class="seat">' + s.seat +
      (s.seat.charAt(0) === 'A' ? ' // ВАШ ФЛОТ' : ' // ФЛОТ БОТА') + '</span></div>' +
      '<div class="meter-row"><span>КОРПУС</span><div class="meter"><i style="width:' + hpPct + '%"></i></div><b>' + s.hp + '/' + def.hp + '</b></div>' +
      '<div class="meter-row"><span>ЩИТ</span><div class="meter shield"><i style="width:' + shPct + '%"></i></div><b>' + s.shield + '/' + (def.shield || 0) + '</b></div>' +
      '<div class="ship-meta"><span>ЭНЕРГИЯ <b>' + dots + '</b></span><span>АТАКА <b>' + (s.attack_used ? 'OFF' : 'READY') + '</b></span></div></div></div>' +
      (tags ? '<div class="tags">' + tags + '</div>' : '') +
      (!s.alive ? '<div class="dead">корабль уничтожен — активацию можно только завершить</div>' : '');
  }

  function drawRadar() {
    const radar = $('radar');
    if (!radar || !state) return;
    const rc = radar.getContext('2d');
    const w = radar.width, h = radar.height;
    rc.clearRect(0, 0, w, h);
    const g = rc.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, w * .55);
    g.addColorStop(0, 'rgba(23,73,88,.34)'); g.addColorStop(1, 'rgba(0,7,12,.92)');
    rc.fillStyle = g; rc.fillRect(0, 0, w, h);
    rc.strokeStyle = 'rgba(86,211,235,.12)'; rc.lineWidth = 1;
    for (let i = 1; i < 5; i++) { rc.beginPath(); rc.ellipse(w / 2, h / 2, i * 58, i * 17, 0, 0, Math.PI * 2); rc.stroke(); }
    rc.beginPath(); rc.moveTo(0, h / 2); rc.lineTo(w, h / 2); rc.moveTo(w / 2, 0); rc.lineTo(w / 2, h); rc.stroke();
    for (const s of state.ships) {
      if (!s.alive) continue;
      const x = w / 2 + (s.q + s.r / 2) * 53;
      const y = h / 2 + s.r * 17;
      rc.fillStyle = TEAM_COLORS[s.team] || '#fff';
      rc.shadowColor = rc.fillStyle; rc.shadowBlur = s.id === state.active_ship ? 14 : 5;
      rc.beginPath(); rc.arc(x, y, s.id === state.active_ship ? 5 : 3, 0, Math.PI * 2); rc.fill();
    }
    rc.shadowBlur = 0;
  }

  function addBtn(box, html, cls, onClick) {
    const b = document.createElement('button');
    b.className = 'btn' + (cls ? ' btn-' + cls : '');
    b.innerHTML = html;
    b.addEventListener('click', onClick);
    box.appendChild(b);
    return b;
  }

  function renderActions() {
    const box = $('action-buttons');
    const hint = $('hint');
    box.innerHTML = '';
    if (coreError) { hint.textContent = 'Ядро недоступно — обновите страницу.'; return; }
    if (!state) { hint.textContent = ''; return; }
    if (state.phase === 'ended') {
      hint.textContent = 'Нажмите «Сыграть ещё» или «Новая игра».';
      return;
    }
    if (isBotTurn()) {
      hint.textContent = 'Бот обдумывает ход…';
      return;
    }
    if (!isPlayerTurn()) { hint.textContent = ''; return; }

    if (!state.active_ship) {
      const begins = legal.filter((c) => c.type === 'BeginActivation');
      if (!begins.length) { hint.textContent = 'Нет кораблей для активации.'; return; }
      hint.textContent = 'Выберите свой корабль: клик по подсвеченной клетке или кнопке.';
      for (const c of begins) {
        const s = findShip(c.ship_instance_id);
        if (!s) continue;
        const def = SHIP_DB[s.type_id];
        addBtn(box, 'Выбрать: ' + (def ? def.name : s.type_id) + ' (' + s.seat + ') · клетка (' + s.q + ',' + s.r + ')', 'select', () => applyCommand(c));
      }
      return;
    }

    const s = findShip(state.active_ship);
    if (!s) return;

    if (!s.alive) {
      hint.textContent = 'Корабль уничтожен в бою.';
      addBtn(box, 'Завершить активацию', 'primary', () => applyCommand({ type: 'EndActivation' }));
      return;
    }

    hint.textContent = 'Голубые клетки — полёт (1 заряд, любое направление), дуги у корабля — поворот, красная цель — атака.';

    const GLYPH6 = ['↑', '↗', '↘', '↓', '↙', '↖'];
    for (const c of legal.filter((x) => x.type === 'Move')) {
      addBtn(box, 'Лететь ' + GLYPH6[c.dir] + ' → (' + (s.q + DIR_DELTAS[c.dir][0]) + ',' + (s.r + DIR_DELTAS[c.dir][1]) + ') (−1 заряд)', 'move', () => applyCommand(c));
    }
    if (legal.some((c) => c.type === 'RotateLeft')) {
      addBtn(box, 'Поворот влево ↺ → ' + GLYPH[(s.facing + 5) % 6] + ' (−1 заряд)', 'move', () => applyCommand({ type: 'RotateLeft' }));
    }
    if (legal.some((c) => c.type === 'RotateRight')) {
      addBtn(box, 'Поворот вправо ↻ → ' + GLYPH[(s.facing + 1) % 6] + ' (−1 заряд)', 'move', () => applyCommand({ type: 'RotateRight' }));
    }
    for (const c of legal.filter((x) => x.type === 'DeclareAttack')) {
      const t = findShip(c.target_ship_instance_id);
      if (!t) continue;
      const def = SHIP_DB[t.type_id];
      const name = def ? def.name : t.type_id;
      addBtn(box, 'Атака: ' + name + '<small>' + attackPreview(s, t) + '</small>', 'attack', () => applyCommand(c));
    }
    addBtn(box, 'Завершить активацию', 'primary', () => applyCommand({ type: 'EndActivation' }));
  }

  // ---------- Гекс-математика (как в hex.rs / core-api §1) ----------

  function directionFrom(fq, fr, tq, tr) {
    const dq = tq - fq, dr = tr - fr;
    for (let d = 0; d < 6; d++) {
      if (DIR_DELTAS[d][0] === dq && DIR_DELTAS[d][1] === dr) return d;
    }
    // Луч для дальнобойной атаки: целочисленная проекция (как ray_direction в engine.rs).
    const wx = 2 * dq + dr, wy = dr;
    let best = 0, bestScore = -Infinity;
    for (let d = 0; d < 6; d++) {
      const a = DIR_DELTAS[d][0], b = DIR_DELTAS[d][1];
      const score = wx * (2 * a + b) + 3 * wy * b;
      if (score > bestScore) { bestScore = score; best = d; }
    }
    return best;
  }

  function hexDistance(aq, ar, bq, br) {
    const dq = aq - bq, dr = ar - br;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(-dq - dr)) / 2;
  }

  // Сектор+арка в компактном виде: «F2», «B0», «BL−1».
  function sectorArc(sectorIndex, arc) {
    return SECTOR_NAMES[sectorIndex] + (arc < 0 ? '−' + (-arc) : arc);
  }

  // Превью атаки: кубики и бонусы арок «ты 2d6+F2 · он d6+1+B1» (+ штраф дистанции).
  // Кубики и плоский бонус защитника повторяют data/rulesets/v3/game.json
  // (бой v3.1, ADR-014: combat_attacker_dice=2, combat_defender_dice=1,
  // combat_defender_flat_bonus=1).
  function attackPreview(att, tgt) {
    const ATK_DICE = 2, DEF_DICE = 1, DEF_FLAT = 1;
    const defA = SHIP_DB[att.type_id] || { arc: [0, 0, 0, 0, 0, 0], abilities: [] };
    const defD = SHIP_DB[tgt.type_id] || { arc: [0, 0, 0, 0, 0, 0] };
    const dirA = directionFrom(att.q, att.r, tgt.q, tgt.r);
    const dirD = directionFrom(tgt.q, tgt.r, att.q, att.r);
    const sA = ((dirA - att.facing) % 6 + 6) % 6;
    const sD = ((dirD - tgt.facing) % 6 + 6) % 6;
    const aA = defA.arc[sA], aD = defD.arc[sD];
    const dist = hexDistance(att.q, att.r, tgt.q, tgt.r);
    let text = 'ты ' + (ATK_DICE > 1 ? ATK_DICE + 'd6' : 'd6') + '+' + sectorArc(sA, aA) +
      ' · он ' + (DEF_DICE > 1 ? DEF_DICE + 'd6' : 'd6') +
      (DEF_FLAT ? '+' + DEF_FLAT : '') + '+' + sectorArc(sD, aD);
    if (defA.abilities && defA.abilities.indexOf('ranged_shot') >= 0 && dist > 1) {
      text += ' · дистанция ' + dist + ', штраф −' + 2 * (dist - 1);
    }
    return text;
  }

  // v3.4: движение в любую сторону — все легальные соседние клетки
  function getMoveCells() {
    if (!isPlayerTurn() || !state.active_ship) return [];
    const s = findShip(state.active_ship);
    if (!s) return [];
    return legal
      .filter((c) => c.type === 'Move')
      .map((c) => {
        const d = DIR_DELTAS[c.dir];
        return { q: s.q + d[0], r: s.r + d[1], dir: c.dir };
      });
  }

  function getTargets() {
    if (!isPlayerTurn() || !state.active_ship) return [];
    return legal
      .filter((c) => c.type === 'DeclareAttack')
      .map((c) => findShip(c.target_ship_instance_id))
      .filter(Boolean);
  }

  // ---------- Канвас: псевдо-3D сцена (наклон ~30°, стиль Supercell) ----------

  const TILT = 0.906; // sin(65°): вид сверху под 65° — доска почти без сжатия

  function forEachCell(cb) {
    for (let q = -BOARD_RADIUS; q <= BOARD_RADIUS; q++) {
      for (let r = Math.max(-BOARD_RADIUS, -q - BOARD_RADIUS); r <= Math.min(BOARD_RADIUS, -q + BOARD_RADIUS); r++) {
        cb(q, r);
      }
    }
  }

  function boardParams() {
    const cssWidth = canvas.clientWidth || 600;
    const cssHeight = canvas.clientHeight || cssWidth;
    const cssSize = Math.min(cssWidth, cssHeight);
    const size = cssSize / (2 * HALF_EXTENT);
    return { cssWidth, cssHeight, cssSize, size, cx: cssWidth / 2, cy: cssHeight * 0.50 };
  }

  function cellToPx(q, r, p) {
    return {
      x: p.cx + p.size * Math.sqrt(3) * (q + r / 2),
      y: p.cy + p.size * 1.5 * r * TILT
    };
  }

  // Точная обратная трансформация наклонной доски + округление через cube-координаты.
  function pxToCellExact(mx, my, p) {
    const rf = (my - p.cy) / (1.5 * p.size * TILT);
    const qf = (mx - p.cx) / (Math.sqrt(3) * p.size) - rf / 2;
    let q = Math.round(qf), r = Math.round(rf), s = Math.round(-qf - rf);
    const dq = Math.abs(q - qf), dr = Math.abs(r - rf), ds = Math.abs(s - (-qf - rf));
    if (dq > dr && dq > ds) q = -r - s;
    else if (dr > ds) r = -q - s;
    if (Math.max(Math.abs(q), Math.abs(r), Math.abs(-q - r)) > BOARD_RADIUS) return null;
    return { q, r };
  }

  function hexPath(x, y, s) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 180 * (60 * i - 30);
      const px = x + s * Math.cos(a);
      const py = y + s * Math.sin(a) * TILT;
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }

  function tileFill(q, r) {
    const h = Math.abs((q * 73856093) ^ (r * 19349663)) % 100;
    return 'hsl(223, 44%, ' + (13.5 + (h % 5) * 0.9) + '%)';
  }

  function makeStars(seed) {
    let s = (seed >>> 0) || 1;
    const rnd = () => {
      s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
      return s / 4294967296;
    };
    stars = [];
    for (let i = 0; i < 170; i++) {
      stars.push({ x: rnd(), y: rnd(), r: 0.4 + rnd() * 1.3, a: 0.15 + rnd() * 0.7, tw: rnd() * Math.PI * 2 });
    }
  }

  function makeClouds(seed) {
    let s = (seed >>> 0) || 7;
    const rnd = () => {
      s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
      return s / 4294967296;
    };
    clouds = [];
    for (let i = 0; i < 4; i++) {
      clouds.push({
        x: rnd(), y: rnd(),
        w: 0.22 + rnd() * 0.26,           // ширина в долях канваса
        h: 0.07 + rnd() * 0.08,
        vx: (5 + rnd() * 9) * (rnd() < 0.5 ? -1 : 1),  // px/сек
        vy: (1.5 + rnd() * 2.5) * (rnd() < 0.5 ? -1 : 1),
        a: 0.10 + rnd() * 0.08,
      });
    }
  }

  function drawClouds(time, p) {
    const now = time / 1000;
    for (const c of clouds) {
      const x = (((c.x * p.cssSize + c.vx * now) % (p.cssSize * 1.4)) + p.cssSize * 1.4) % (p.cssSize * 1.4) - p.cssSize * 0.2;
      const y = (((c.y * p.cssSize + c.vy * now) % (p.cssSize * 1.4)) + p.cssSize * 1.4) % (p.cssSize * 1.4) - p.cssSize * 0.2;
      const g = ctx.createRadialGradient(x, y, 0, x, y, c.w * p.cssSize);
      g.addColorStop(0, 'rgba(6,10,22,' + c.a.toFixed(3) + ')');
      g.addColorStop(0.7, 'rgba(6,10,22,' + (c.a * 0.55).toFixed(3) + ')');
      g.addColorStop(1, 'rgba(6,10,22,0)');
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(1, Math.max(0.35, c.h / c.w));
      ctx.translate(-x, -y);
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(x, y, c.w * p.cssSize, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }
  }

  let floatHits = []; // хит-зоны плавающих кнопок активного корабля
  let effects = [];   // визуальные эффекты (вспышки/взрывы)
  let shakeUntil = 0; // тряска камеры после уничтожения
  let clouds = [];    // тени облаков, дрейфующие по полю

  function shipVisualRadius(s, p) {
    const def = SHIP_DB[s.type_id] || { scale: 0.55 };
    const persp = 0.9 + 0.2 * ((s.r + BOARD_RADIUS) / (2 * BOARD_RADIUS));
    return p.size * (def.scale || 0.55) * 1.25 * persp;
  }

  function dirScreenOffset(f, p) {
    const d = DIR_DELTAS[f];
    const a = cellToPx(0, 0, p);
    const b = cellToPx(d[0], d[1], p);
    return { x: b.x - a.x, y: b.y - a.y };
  }

  function draw(time) {
    if (canvas) {
      const dpr = window.devicePixelRatio || 1;
      const cssWidth = canvas.clientWidth || 600;
      const cssHeight = canvas.clientHeight || cssWidth;
      const pxW = Math.max(1, Math.round(cssWidth * dpr));
      const pxH = Math.max(1, Math.round(cssHeight * dpr));
      if (canvas.width !== pxW || canvas.height !== pxH) {
        canvas.width = pxW;
        canvas.height = pxH;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const p = boardParams();
      floatHits = [];
      window.__swbFloat = floatHits;

      // Космический фон
      const space = ASSETS && ASSETS.get('environment', 'deep_space');
      if (space) {
        const scale = Math.max(p.cssWidth / space.naturalWidth, p.cssHeight / space.naturalHeight);
        const dw = space.naturalWidth * scale, dh = space.naturalHeight * scale;
        ctx.drawImage(space, (p.cssWidth - dw) / 2, (p.cssHeight - dh) / 2, dw, dh);
      } else {
        ctx.fillStyle = '#04060c'; ctx.fillRect(0, 0, p.cssWidth, p.cssHeight);
      }
      const grad = ctx.createRadialGradient(p.cx, p.cy, p.cssSize * .06, p.cx, p.cy, p.cssSize * .72);
      grad.addColorStop(0, 'rgba(13,31,53,.16)'); grad.addColorStop(1, 'rgba(1,4,8,.64)');
      ctx.fillStyle = grad; ctx.fillRect(0, 0, p.cssWidth, p.cssHeight);

      // Звёзды
      for (const st of stars) {
        ctx.globalAlpha = st.a * (0.7 + 0.3 * Math.sin(time / 900 + st.tw));
        ctx.fillStyle = '#cfe0ff';
        ctx.beginPath();
        ctx.arc(st.x * p.cssWidth, st.y * p.cssHeight, st.r, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // тряска камеры после уничтожения
      let shakeX = 0, shakeY = 0;
      if (performance.now() < shakeUntil) {
        const k = (shakeUntil - performance.now()) / 240;
        shakeX = (Math.random() * 2 - 1) * 5 * k;
        shakeY = (Math.random() * 2 - 1) * 4 * k;
      }
      ctx.translate(shakeX, shakeY);

      if (state) {
        drawBoard(p);
        drawHighlights(time, p);
        drawClouds(time, p);
        drawShips3d(time, p);
        drawFloatControls(time, p);
        drawEffects(time);
      }
    }
    requestAnimationFrame(draw);
  }

  function spawnHit(x, y, kind) {
    const sparks = [];
    const n = kind === 'boom' ? 11 : 6;
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      sparks.push({ a, sp: 40 + Math.random() * (kind === 'boom' ? 130 : 80), r: 1.4 + Math.random() * 2.2 });
    }
    effects.push({ x, y, t0: performance.now(), kind, sparks });
    if (effects.length > 24) effects.shift();
  }
  window.__swbSpawn = spawnHit; // отладка/тесты

  function drawEffects(now) {
    if (!effects.length) return;
    effects = effects.filter((e) => now - e.t0 < (e.kind === 'boom' ? 780 : 460));
    for (const e of effects) {
      const dur = e.kind === 'boom' ? 780 : 460;
      const t = Math.min(1, (now - e.t0) / dur);
      const big = e.kind === 'boom';
      // белая вспышка
      const fr = (big ? 34 : 18) * (0.3 + t);
      ctx.globalAlpha = (1 - t) * 0.9;
      const fg = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, Math.max(4, fr));
      fg.addColorStop(0, '#ffffff');
      fg.addColorStop(0.4, big ? '#ffd27d' : '#ffe9a8');
      fg.addColorStop(1, 'rgba(255,120,60,0)');
      ctx.fillStyle = fg;
      ctx.beginPath();
      ctx.arc(e.x, e.y, Math.max(4, fr), 0, Math.PI * 2);
      ctx.fill();
      // огненное кольцо
      ctx.globalAlpha = (1 - t) * 0.85;
      ctx.strokeStyle = big ? '#ff8a5c' : '#ffd27d';
      ctx.lineWidth = big ? 4 : 2.5;
      ctx.beginPath();
      ctx.arc(e.x, e.y, (big ? 10 : 6) + t * (big ? 46 : 24), 0, Math.PI * 2);
      ctx.stroke();
      // искры
      for (const sp of e.sparks) {
        const d = sp.sp * t;
        const sx = e.x + Math.cos(sp.a) * d;
        const sy = e.y + Math.sin(sp.a) * d * 0.8;
        ctx.globalAlpha = (1 - t) * 0.95;
        ctx.fillStyle = '#ffcf7d';
        ctx.beginPath();
        ctx.arc(sx, sy, sp.r * (1 - t * 0.6), 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    }
  }

  function drawBoard(p) {
    const D = p.size * 0.34; // толщина «столешницы»
    // 1) боковые грани (видны только у переднего края доски)
    forEachCell((q, r) => {
      const c = cellToPx(q, r, p);
      hexPath(c.x, c.y + D, p.size * 0.84);
      ctx.fillStyle = '#080c18';
      ctx.fill();
    });
    // 2) верхние грани — разреженно: гекс меньше ячейки, граница толще
    forEachCell((q, r) => {
      const c = cellToPx(q, r, p);
      hexPath(c.x, c.y, p.size * 0.84);
      ctx.fillStyle = tileFill(q, r);
      ctx.fill();
      const armor = ASSETS && ASSETS.get('environment', 'hex_armor');
      if (armor) {
        ctx.save();
        hexPath(c.x, c.y, p.size * 0.80);
        ctx.clip();
        ctx.globalAlpha = 0.15;
        ctx.drawImage(armor, c.x - p.size, c.y - p.size * TILT, p.size * 2, p.size * 2 * TILT);
        ctx.restore();
      }
      ctx.strokeStyle = 'rgba(104,211,239,0.38)';
      ctx.lineWidth = 2.4;
      ctx.stroke();
      // координаты гекса — деликатно, в углу клетки
      if (p.size >= 24) {
        ctx.fillStyle = 'rgba(126,201,222,0.13)';
        ctx.font = Math.round(p.size * 0.24) + 'px system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'alphabetic';
        ctx.fillText(q + ',' + r, c.x + p.size * 0.1, c.y + p.size * 0.52 * TILT + 3);
      }
    });
  }

  function drawHighlights(time, p) {
    // Клетки хода — все 6 направлений (v3.4)
    for (const mv of getMoveCells()) {
      const c = cellToPx(mv.q, mv.r, p);
      hexPath(c.x, c.y, p.size * 0.84);
      ctx.fillStyle = 'rgba(64,190,255,0.20)';
      ctx.fill();
      ctx.strokeStyle = 'rgba(80,200,255,0.9)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    // Цели атак
    for (const t of getTargets()) {
      const c = cellToPx(t.q, t.r, p);
      hexPath(c.x, c.y, p.size * 0.96);
      const pulse = 0.16 + 0.09 * Math.sin(time / 260);
      ctx.fillStyle = 'rgba(255,82,82,' + pulse.toFixed(3) + ')';
      ctx.fill();
      ctx.strokeStyle = 'rgba(255,110,110,0.95)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    // Свои неактивированные корабли (фаза выбора)
    if (isPlayerTurn() && !state.active_ship) {
      for (const s of state.ships) {
        if (!s.alive || s.seat !== state.active_seat || s.activated) continue;
        const c = cellToPx(s.q, s.r, p);
        const a = 0.45 + 0.3 * Math.sin(time / 300);
        ctx.strokeStyle = 'rgba(102,187,106,' + a.toFixed(3) + ')';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.ellipse(c.x, c.y, p.size * 0.9, p.size * 0.9 * TILT, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    // Активный корабль: у игрока — жёлтый пунктир, у бота — красное пульсирующее кольцо
    if (state.active_ship) {
      const act = findShip(state.active_ship);
      if (act && act.alive) {
        const c = cellToPx(act.q, act.r, p);
        if (isBotTurn()) {
          const a = 0.55 + 0.35 * Math.sin(time / 200);
          ctx.strokeStyle = 'rgba(255,90,90,' + a.toFixed(3) + ')';
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.ellipse(c.x, c.y, p.size * 1.06, p.size * 1.06 * TILT, 0, 0, Math.PI * 2);
          ctx.stroke();
        } else {
          ctx.strokeStyle = 'rgba(255,213,79,0.95)';
          ctx.lineWidth = 2.5;
          ctx.setLineDash([6, 5]);
          ctx.lineDashOffset = -time / 40;
          ctx.beginPath();
          ctx.ellipse(c.x, c.y, p.size * 1.02, p.size * 1.02 * TILT, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    }
  }

  // Кэш предрендеров фишки: цветной верх + тёмный силуэт для боковых стенок.
  const shipChipCache = new Map();
  function shipChipLayers(type_id, team, unit) {
    const key = type_id + '|' + team + '|' + unit.toFixed(1);
    let e = shipChipCache.get(key);
    if (e) return e;
    const pad = 26;
    const sz = Math.max(32, Math.ceil(70 * unit + pad));
    const top = document.createElement('canvas');
    top.width = sz; top.height = sz;
    const tc = top.getContext('2d');
    tc.translate(sz / 2, sz / 2);
    window.SWBShips3D.drawShip(tc, type_id, { unit, team, t: 0 });
    const side = document.createElement('canvas');
    side.width = sz; side.height = sz;
    const sc = side.getContext('2d');
    sc.translate(sz / 2, sz / 2);
    window.SWBShips3D.drawShip(sc, type_id, { unit, team, t: 0 });
    sc.globalCompositeOperation = 'source-in';
    sc.fillStyle = '#0a0e1c';
    sc.fillRect(-sz, -sz, sz * 2, sz * 2);
    e = { top, side };
    if (shipChipCache.size > 48) shipChipCache.clear();
    shipChipCache.set(key, e);
    return e;
  }

  function drawShips3d(time, p) {
    const list = state.ships
      .filter((s) => s.alive)
      .map((s) => ({ s, c: cellToPx(s.q, s.r, p) }))
      .sort((a, b) => a.c.y - b.c.y);
    for (const { s, c } of list) {
      const def = SHIP_DB[s.type_id] || { hp: s.hp, shield: s.shield };
      const R = shipVisualRadius(s, p);
      const teamColor = TEAM_COLORS[s.team] || '#ffffff';
      const bob = Math.sin(time / 620 + (s.q * 3 + s.r)) * p.size * 0.03;

      // Тень на плоскости
      ctx.fillStyle = 'rgba(2,5,12,0.5)';
      ctx.beginPath();
      ctx.ellipse(c.x, c.y + p.size * 0.1, R * 0.78, R * 0.36, 0, 0, Math.PI * 2);
      ctx.fill();

      // Командное свечение под кораблём
      ctx.strokeStyle = teamColor;
      ctx.globalAlpha = 0.85;
      ctx.lineWidth = 2.2;
      ctx.beginPath();
      ctx.ellipse(c.x, c.y + p.size * 0.1, R * 0.95, R * 0.44, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 0.12;
      ctx.fillStyle = teamColor;
      ctx.fill();
      ctx.globalAlpha = 1;

      // Реалистичный top-down ассет. Процедурный GLM-рендер остаётся как офлайн fallback.
      const shipImage = ASSETS && ASSETS.get('ships', s.type_id);
      const rot = (s.facing * 60) * Math.PI / 180;
      if (shipImage) {
        const imageSize = R * 2.35;
        ctx.save();
        ctx.translate(c.x, c.y + bob);
        ctx.scale(1, TILT);
        ctx.rotate(rot);
        ctx.shadowColor = s.team === 'A' ? 'rgba(65,181,255,.6)' : 'rgba(255,70,66,.55)';
        ctx.shadowBlur = Math.max(5, p.size * .22);
        ctx.drawImage(shipImage, -imageSize / 2, -imageSize / 2, imageSize, imageSize);
        ctx.restore();
      } else if (window.SWBShips3D && typeof window.SWBShips3D.drawShip === 'function') {
        const unit = (R * 2.0) / 70;
        const L = shipChipLayers(s.type_id, s.team, unit);
        const half = L.top.width / 2;
        const layers = 3;
        const step = Math.max(2, p.size * 0.11);
        for (let k = layers; k >= 1; k--) {
          ctx.save();
          ctx.translate(c.x, c.y + bob + k * step);
          ctx.scale(1, TILT);
          ctx.rotate(rot);
          ctx.drawImage(L.side, -half, -half);
          ctx.restore();
        }
        ctx.save();
        ctx.translate(c.x, c.y + bob);
        ctx.scale(1, TILT);
        ctx.rotate(rot);
        ctx.drawImage(L.top, -half, -half);
        ctx.restore();
      } else {
        ctx.save();
        ctx.translate(c.x, c.y + bob);
        ctx.scale(1, TILT);
        ctx.rotate((s.facing * 60 - 30) * Math.PI / 180);
        window.SWBShips.drawShip(ctx, s.type_id, R, '#cfd6de', '#63748a');
        ctx.restore();
      }

      // Компактная телеметрия вместо шести чисел арок и россыпи пипов.
      const maxHp = def.hp || s.hp || 1;
      const maxSh = def.shield || 0;
      const barW = Math.max(30, R * 1.35);
      const barH = Math.max(3, p.size * .08);
      const x0 = c.x - barW / 2;
      const y0 = c.y - R * 1.18 - p.size * .2;
      const frac = s.hp / maxHp;
      ctx.fillStyle = 'rgba(1,5,10,.88)'; ctx.fillRect(x0 - 1, y0 - 1, barW + 2, barH + 2);
      ctx.fillStyle = 'rgba(123,154,168,.2)'; ctx.fillRect(x0, y0, barW, barH);
      ctx.fillStyle = frac > .5 ? '#71eea0' : frac > .3 ? '#f5c86b' : '#ff5c55';
      ctx.fillRect(x0, y0, barW * Math.max(0, frac), barH);
      if (maxSh > 0) {
        const ysh = y0 - barH - 3;
        ctx.fillStyle = 'rgba(1,5,10,.88)'; ctx.fillRect(x0 - 1, ysh - 1, barW + 2, barH + 2);
        ctx.fillStyle = 'rgba(123,154,168,.16)'; ctx.fillRect(x0, ysh, barW, barH);
        ctx.fillStyle = '#5ce5ff'; ctx.fillRect(x0, ysh, barW * Math.max(0, s.shield / maxSh), barH);
      }
      ctx.fillStyle = s.team === 'A' ? '#86cfff' : '#ff918d';
      ctx.font = '700 ' + Math.max(8, Math.round(p.size * .17)) + 'px ui-monospace, monospace';
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.fillText(s.seat, c.x, y0 - (maxSh > 0 ? barH + 5 : 3));

      // Сила флангов на рёбрах гекса: у выбранного корабля — все 6, крупно;
      // у врагов в досягаемости (дистанция ≤3: мой ход + их ход) — тоже.
      const isSelected = state.active_ship === s.id;
      const selShip = state.active_ship ? findShip(state.active_ship) : null;
      const inReach = !isSelected && selShip && selShip.alive && s.team !== selShip.team &&
        hexDistance(selShip.q, selShip.r, s.q, s.r) <= 3;
      if ((isSelected || inReach) && p.size >= 20) {
        const arc = def.arc || [0, 0, 0, 0, 0, 0];
        const fs = Math.round(p.size * (isSelected ? 0.42 : 0.32));
        ctx.font = '700 ' + fs + 'px ui-monospace, monospace';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.lineWidth = 3; ctx.strokeStyle = 'rgba(3,7,14,0.9)';
        for (let d = 0; d < 6; d++) {
          const sector = ((d - s.facing) % 6 + 6) % 6;
          const v = arc[sector] || 0;
          const off = dirScreenOffset(d, p);
          const ex = c.x + off.x * 0.34, ey = c.y + off.y * 0.34;
          const col = v >= 2 ? (isSelected ? '#b8ffc4' : '#8ee6a1')
            : v === 1 ? (isSelected ? '#ffffff' : 'rgba(210,225,250,0.9)')
            : v === 0 ? 'rgba(155,170,200,0.55)' : '#ff9a9a';
          const txt = v > 0 ? '+' + v : String(v);
          ctx.strokeText(txt, ex, ey);
          ctx.fillStyle = col;
          ctx.fillText(txt, ex, ey);
        }
      }
      // Кольцо досягаемости + мой бонус атаки на ребре между нами
      if (inReach && selShip) {
        const d = hexDistance(selShip.q, selShip.r, s.q, s.r);
        const near = d <= 2;
        const pulse = 0.5 + 0.3 * Math.sin(time / (near ? 220 : 400));
        ctx.strokeStyle = near
          ? 'rgba(255,150,64,' + pulse.toFixed(3) + ')'
          : 'rgba(255,213,79,' + (pulse * 0.55).toFixed(3) + ')';
        ctx.lineWidth = near ? 3 : 2;
        ctx.setLineDash([5, 4]);
        ctx.beginPath();
        ctx.ellipse(c.x, c.y, p.size * 1.08, p.size * 1.08 * TILT, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        const arcS = SHIP_DB[selShip.type_id] ? SHIP_DB[selShip.type_id].arc : null;
        if (arcS) {
          const dSE = directionFrom(selShip.q, selShip.r, s.q, s.r);
          const sec = ((dSE - selShip.facing) % 6 + 6) % 6;
          const myBonus = arcS[sec] || 0;
          const dES = directionFrom(s.q, s.r, selShip.q, selShip.r);
          const offES = dirScreenOffset(dES, p);
          const bx = c.x + offES.x * 0.34, by = c.y + offES.y * 0.34;
          ctx.save();
          ctx.translate(bx, by);
          ctx.fillStyle = 'rgba(6,10,20,0.92)';
          roundRect(-15, -11, 30, 22, 6); ctx.fill();
          ctx.strokeStyle = near ? 'rgba(255,150,64,0.95)' : 'rgba(255,213,79,0.7)';
          ctx.lineWidth = 1.5;
          roundRect(-15, -11, 30, 22, 6); ctx.stroke();
          ctx.fillStyle = myBonus >= 2 ? '#8ee6a1' : myBonus === 1 ? '#eaf2ff' : myBonus === 0 ? 'rgba(200,210,230,0.8)' : '#ff9a9a';
          ctx.font = '700 ' + Math.round(p.size * 0.32) + 'px ui-monospace, monospace';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText(myBonus > 0 ? '+' + myBonus : String(myBonus), 0, 1);
          ctx.restore();
        }
      }
    }
  }

  function roundRect(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function drawFloatControls(time, p) {
    if (!isPlayerTurn() || !state.active_ship) return;
    const s = findShip(state.active_ship);
    if (!s || !s.alive) return;
    const c = cellToPx(s.q, s.r, p);
    const R = shipVisualRadius(s, p);
    const off = dirScreenOffset(s.facing, p);
    const len = Math.hypot(off.x, off.y) || 1;
    const hx = off.x / len, hy = off.y / len;
    const canRotate = legal.some((k) => k.type === 'RotateLeft') && legal.some((k) => k.type === 'RotateRight');

    // 1) Стрелка курса — индикатор направления (движение — кликом по голубым клеткам)
    const ax = c.x + hx * p.size * 1.38;
    const ay = c.y + hy * p.size * 1.38;
    const ang = Math.atan2(hy, hx);
    const aCol = '#3ec8ff';
    ctx.save();
    ctx.translate(ax, ay);
    ctx.rotate(ang);
    ctx.shadowColor = 'rgba(0,0,0,0.55)';
    ctx.shadowBlur = 6;
    ctx.shadowOffsetY = 2;
    ctx.fillStyle = aCol;
    ctx.strokeStyle = '#0f1424';
    ctx.lineWidth = 2;
    ctx.beginPath();
    const A = p.size * 0.56;
    ctx.moveTo(A * 0.9, 0);
    ctx.lineTo(-A * 0.35, -A * 0.62);
    ctx.lineTo(-A * 0.1, 0);
    ctx.lineTo(-A * 0.35, A * 0.62);
    ctx.closePath();
    ctx.fill();
    ctx.shadowColor = 'transparent';
    ctx.stroke();
    // белый блик
    ctx.fillStyle = 'rgba(255,255,255,0.35)';
    ctx.beginPath();
    ctx.moveTo(A * 0.55, 0);
    ctx.lineTo(-A * 0.2, -A * 0.34);
    ctx.lineTo(-A * 0.05, 0);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // 2) Дуги поворота — изогнутые стрелки: 10% окружности, начало в 5% круга
    //    от основной стрелки, наконечник по касательной показывает направление.
    const rot = p.size * 1.38;         // радиус дуг = радиус основной стрелки
    const a0 = Math.atan2(hy, hx);
    const arcs = [
      { dir: -1, cmd: { type: 'RotateLeft' },  enabled: legal.some((k) => k.type === 'RotateLeft') },
      { dir: +1, cmd: { type: 'RotateRight' }, enabled: legal.some((k) => k.type === 'RotateRight') },
    ];
    for (const a of arcs) {
      const sweep = (36 * Math.PI) / 180;  // 10% окружности
      const gap = (18 * Math.PI) / 180;    // начало дуг — 5% круга от основной стрелки
      const aS = a0 + a.dir * gap;
      const aE = a0 + a.dir * (gap + sweep);
      const col = a.enabled ? '#3ec8ff' : '#5a6478';
      ctx.lineCap = 'round';
      // тёмная подложка
      ctx.strokeStyle = '#0f1424';
      ctx.lineWidth = 8;
      ctx.beginPath();
      ctx.arc(c.x, c.y, rot, aS, aE, a.dir < 0);
      ctx.stroke();
      // основная дуга
      ctx.strokeStyle = col;
      ctx.lineWidth = 4.5;
      ctx.beginPath();
      ctx.arc(c.x, c.y, rot, aS, aE, a.dir < 0);
      ctx.stroke();
      // наконечник — жирный треугольник по касательной
      const hx2 = c.x + rot * Math.cos(aE);
      const hy2 = c.y + rot * Math.sin(aE);
      const tangent = a.dir < 0
        ? Math.atan2(Math.cos(aE), Math.sin(aE))
        : Math.atan2(-Math.cos(aE), -Math.sin(aE));
      ctx.save();
      ctx.translate(hx2, hy2);
      ctx.rotate(tangent);
      ctx.fillStyle = col;
      ctx.strokeStyle = '#0f1424';
      ctx.lineWidth = 2;
      const A2 = Math.max(13, p.size * 0.34);
      ctx.beginPath();
      ctx.moveTo(A2 * 0.95, 0);
      ctx.lineTo(-A2 * 0.5, -A2 * 0.62);
      ctx.lineTo(-A2 * 0.15, 0);
      ctx.lineTo(-A2 * 0.5, A2 * 0.62);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      ctx.restore();
      floatHits.push({ x: hx2, y: hy2, r: A2 + 12, cmd: a.cmd, enabled: a.enabled });
    }
  }
  function onCanvasClick(e) {
    if (!isPlayerTurn()) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    // 1) Плавающие кнопки (стрелка курса, ↺/↻)
    for (const f of floatHits) {
      if ((mx - f.x) * (mx - f.x) + (my - f.y) * (my - f.y) <= f.r * f.r) {
        if (f.enabled) applyCommand(f.cmd);
        return;
      }
    }

    // 2) Клетки поля
    const p = boardParams();
    const cell = pxToCellExact(mx, my, p);
    if (!cell) return;
    let shipHere = null;
    for (const s of state.ships) {
      if (s.alive && s.q === cell.q && s.r === cell.r) { shipHere = s; break; }
    }

    if (!state.active_ship) {
      if (shipHere && shipHere.seat === state.active_seat && !shipHere.activated) {
        applyCommand({ type: 'BeginActivation', ship_instance_id: shipHere.id });
      }
      return;
    }

    const mv = getMoveCells().find((m) => m.q === cell.q && m.r === cell.r);
    if (mv) {
      applyCommand({ type: 'Move', dir: mv.dir });
      return;
    }
    if (shipHere &&
        legal.some((c) => c.type === 'DeclareAttack' && c.target_ship_instance_id === shipHere.id)) {
      applyCommand({ type: 'DeclareAttack', target_ship_instance_id: shipHere.id });
    }
  }

  function onCanvasHover(e) {
    if (!isPlayerTurn()) { canvas.style.cursor = 'default'; return; }
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    for (const f of floatHits) {
      if ((mx - f.x) * (mx - f.x) + (my - f.y) * (my - f.y) <= f.r * f.r) {
        canvas.style.cursor = f.enabled ? 'pointer' : 'default';
        return;
      }
    }
    const p = boardParams();
    const cell = pxToCellExact(mx, my, p);
    if (!cell) { canvas.style.cursor = 'default'; return; }
    let clickable = false;
    if (!state.active_ship) {
      clickable = state.ships.some((s) =>
        s.alive && s.q === cell.q && s.r === cell.r &&
        s.seat === state.active_seat && !s.activated);
    } else {
      if (getMoveCells().some((m) => m.q === cell.q && m.r === cell.r)) clickable = true;
      else {
        clickable = state.ships.some((s) =>
          s.alive && s.q === cell.q && s.r === cell.r &&
          legal.some((c) => c.type === 'DeclareAttack' && c.target_ship_instance_id === s.id));
      }
    }
    canvas.style.cursor = clickable ? 'pointer' : 'default';
  }

  // ---------- Оверлей конца матча ----------

  function showOverlay() {
    const title = $('overlay-title');
    const reason = $('overlay-reason');
    if (state.winner === 'A') {
      title.textContent = 'Победа команды A!';
      title.className = 'win-a';
      reason.textContent = 'Все корабли команды B уничтожены.';
    } else if (state.winner === 'B') {
      title.textContent = 'Победа команды B';
      title.className = 'win-b';
      reason.textContent = 'Все корабли команды A уничтожены.';
    } else {
      title.textContent = 'Ничья';
      title.className = 'draw';
      reason.textContent = matchEndReason === 'round_limit'
        ? 'Достигнут лимит раундов (' + state.round_limit + ').'
        : 'Обе команды уничтожены в одной цепочке событий.';
    }
    $('overlay').classList.remove('hidden');
  }

  function hideOverlay() {
    $('overlay').classList.add('hidden');
  }

  // ---------- Инициализация ----------

  // Клик по клетке в 3D-сцене — та же логика, что была у канваса (без плавающих кнопок:
  // повороты в 3D кликаются курсорами у самого корабля).
  function onCellClick3d(cell) {
    if (!Board3D || !isPlayerTurn() || !cell) return;
    let shipHere = null;
    for (const s of state.ships) {
      if (s.alive && s.q === cell.q && s.r === cell.r) { shipHere = s; break; }
    }

    if (!state.active_ship) {
      if (shipHere && shipHere.seat === state.active_seat && !shipHere.activated) {
        applyCommand({ type: 'BeginActivation', ship_instance_id: shipHere.id });
      }
      return;
    }

    const mv = getMoveCells().find((m) => m.q === cell.q && m.r === cell.r);
    if (mv) {
      applyCommand({ type: 'Move', dir: mv.dir });
      return;
    }
    if (shipHere &&
        legal.some((c) => c.type === 'DeclareAttack' && c.target_ship_instance_id === shipHere.id)) {
      applyCommand({ type: 'DeclareAttack', target_ship_instance_id: shipHere.id });
    }
  }

  function cellClickable3d(cell) {
    if (!state) return false;
    if (!state.active_ship) {
      return state.ships.some((s) =>
        s.alive && s.q === cell.q && s.r === cell.r &&
        s.seat === state.active_seat && !s.activated);
    }
    if (getMoveCells().some((m) => m.q === cell.q && m.r === cell.r)) return true;
    return state.ships.some((s) =>
      s.alive && s.q === cell.q && s.r === cell.r &&
      legal.some((c) => c.type === 'DeclareAttack' && c.target_ship_instance_id === s.id));
  }

  function init() {
    canvas = $('board');
    ctx = canvas.getContext('2d');

    $('new-game').addEventListener('click', newMatch);
    $('overlay-again').addEventListener('click', newMatch);
    canvas.addEventListener('click', onCanvasClick);
    canvas.addEventListener('mousemove', onCanvasHover);

    Promise.all([loadCore(), scene3dReady]).then(() => {
      if (Board3D) {
        Board3D.init($('board3d'), {
          radius: 3,
          onCellClick: onCellClick3d,
          onCellHover: (cell) => {
            $('board3d').style.cursor = cell && isPlayerTurn() && cellClickable3d(cell) ? 'pointer' : 'default';
          },
          onCommand: (cmd) => applyCommand(cmd),
          shipInfo: (typeId) => (SHIP_DB[typeId] ? { max_hp: SHIP_DB[typeId].hp, arc: SHIP_DB[typeId].arc } : null),
        });
        $('board3d').classList.add('s3d-active');
      } else {
        canvas.classList.remove('hidden');
        requestAnimationFrame(draw);
      }
      if (swb) newMatch();
      else showCoreProblem('Ядро недоступно: нет ни window.swb, ни demo/mock_core.js');
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
