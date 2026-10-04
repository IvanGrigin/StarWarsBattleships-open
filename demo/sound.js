/* demo/sound.js — процедурный звук боя + оригинальная фоновая музыка (Web Audio API).
 *
 * ВАЖНО (IP): никакой музыки/звуков «Звёздных войн» здесь НЕТ и быть не может —
 * они принадлежат Disney/Lucasfilm. Весь звук синтезируется на лету
 * (OscillatorNode + GainNode + BiquadFilter + AudioBuffer с белым шумом),
 * музыкальный луп — собственная гармония «в духе космической оперы»
 * (торжественные медленные «медные» аккорды + маршевый бас), это НЕ тема ЗВ.
 *
 * Классический скрипт (без модулей), определяет window.SWBSound:
 *   init()        — ленивое создание AudioContext; вызывать снаружи по первому
 *                   жесту пользователя (pointerdown/click). До init() все
 *                   методы — безопасные no-op.
 *   setMuted(b)   — выключить/включить звук; isMuted() — текущее состояние.
 *   SFX: laser(pan), explosion(big), move, rotate, hyper, flip, place,
 *        win, lose, draw, ui
 *   Музыка: startMusic() / stopMusic() — луп на lookahead-планировщике
 *           (setInterval-помпа + планирование по AudioContext.currentTime).
 *
 * Подключение: <script src="sound.js"></script> в index.html до main.js
 * (или после — порядок не важен, файл самодостаточен).
 */
(function (global) {
  'use strict';

  if (!global) return; // нет глобального объекта — ничего не делаем

  /* ======================= МАСТЕР-ЦЕПОЧКА ======================= */

  const MASTER_GAIN = 0.5;   // общий мастер-громкость
  const COMP_THRESH = -18;   // порог компрессора, дБ
  const COMP_KNEE = 20;      // «колено» компрессора, дБ
  const COMP_RATIO = 4;      // ratio компрессора
  const COMP_ATTACK = 0.004; // атака компрессора, с
  const COMP_RELEASE = 0.2;  // восстановление компрессора, с

  const RAMP_FLOOR = 0.0001; // «пол» экспоненциальных огибающих (нельзя 0)

  /* ======================= ПАРАМЕТРЫ SFX ======================= */
  /* MIDI-ноты: 60 = C4, 62 = D4, 64 = E4, 67 = G4, 72 = C5 и т.д. */

  const SFX_P = {
    // laser(pan): свип sawtooth 900→200 Гц за 0.12 c + шумовой щелчок
    laser: { f0: 900, f1: 200, dur: 0.12, peak: 0.32,
             clickHz: 2200, clickDur: 0.04, clickPeak: 0.18 },

    // explosion(big): шумовой удар с lowpass-спадом (big — дольше, громче, ниже)
    explosion: { dur: 0.5, durBig: 0.9,
                 lpHz: 2600, lpHzBig: 1500, lpEndHz: 90,
                 peak: 0.6, peakBig: 0.85,
                 subF0: 150, subF1: 55, subF0Big: 110, subF1Big: 35,
                 subPeak: 0.3, subPeakBig: 0.5 },

    // move(): мягкий whoosh — шум через bandpass вверх
    move: { f0: 320, f1: 1500, dur: 0.28, peak: 0.28, attack: 0.05, q: 1.1 },

    // rotate(): короткий клик-тик
    rotate: { hz: 1500, dur: 0.03, peak: 0.12,
              clickHz: 4000, clickDur: 0.02, clickPeak: 0.08 },

    // hyper(): восходящий свип sine 200→900 Гц за 0.4 c (+ лёгкое «мерцание» октавой выше)
    hyper: { f0: 200, f1: 900, dur: 0.4, peak: 0.4, attack: 0.18,
             shimmerF: 2, shimmerPeak: 0.1 },

    // flip(): «магический» двойной тик — два восходящих блипа
    flip: { f0a: 600, f1a: 1250, f0b: 900, f1b: 1870,
            dur: 0.065, gap: 0.085, peak: 0.22 },

    // place(): щелчок установки (мина/бомба) — низкий блимп + глухой щелчок
    place: { hz: 230, dur: 0.05, peak: 0.22,
             clickHz: 1100, clickDur: 0.035, clickPeak: 0.2 },

    // win(): мажорная фанфара — восходящее арпеджио до-мажор (C4 E4 G4 C5)
    win: { notes: [60, 64, 67, 72], gap: 0.09, dur: 0.8, peak: 0.13,
           lp: 1900, type: 'sawtooth' },

    // lose(): минорная, нисходящая (E4 C4 A3) с лёгкой «просадкой» строя
    lose: { notes: [64, 60, 57], gap: 0.14, dur: 0.95, peak: 0.13,
            lp: 900, type: 'triangle', sag: 0.94 },

    // draw(): нейтральная кварта D4–G4 (без мажора/минора)
    draw: { notes: [62, 67], gap: 0.12, dur: 0.7, peak: 0.12,
            lp: 1200, type: 'triangle' },

    // ui(): тихий клик кнопки
    ui: { hz: 850, dur: 0.03, peak: 0.07 }
  };

  /* ======================= ПАРАМЕТРЫ МУЗЫКИ ======================= */

  const MUSIC_BPM = 96;              // темп марша
  const STEP_DUR = 30 / MUSIC_BPM;   // восьмая доля, с (60/BPM/2 = 0.3125)
  const BAR_STEPS = 8;               // восьмых в такте 4/4
  const LOOP_BARS = 4;               // тактов в лупе
  const LOOP_STEPS = BAR_STEPS * LOOP_BARS; // 32 шага ≈ 10 c

  const MUSIC_DB = -18;                          // музыка тише SFX на 18 дБ
  const MUSIC_GAIN = Math.pow(10, MUSIC_DB / 20); // ≈ 0.126

  const SCHED_INTERVAL_MS = 30; // помпа планировщика
  const SCHED_AHEAD = 0.15;     // горизонт планирования, с (lookahead)

  /* Гармония лупа — 4-тактовый эолийский оборот в ре миноре: D – A – F – C
   * (i – v – III – VII). Собственная последовательность, «в духе космической
   * оперы»: медленные торжественные «медные» аккорды + маршевый бас root–fifth.
   * bass — MIDI корня баса; chord — 3 ноты аккорда для «медных» (sawtooth). */
  const MUSIC_BARS = [
    { bass: 38, chord: [50, 53, 57] }, // D2 · ре-минор   (D3 F3 A3)
    { bass: 45, chord: [45, 48, 52] }, // A2 · ля-минор   (A2 C3 E3)
    { bass: 41, chord: [41, 45, 48] }, // F2 · фа-мажор   (F2 A2 C3)
    { bass: 36, chord: [48, 52, 55] }  // C2 · до-мажор   (C3 E3 G3)
  ];
  const BASS_FIFTH = 7;      // квинта вверх: бас чередует root–fifth (марш)

  const HAT = { hz: 6200, dur: 0.05, peak: 0.045, q: 0.7 }; // хай-хэт: шум+highpass
  const BASS = { peak: 0.24, lp: 900, durSteps: 1.7 };      // triangle-бас
  const BRASS = {
    holdSteps: 3.6, stabSteps: 1.6,   // аккорд на долю 1 (держим) и долю 3 (стаб)
    peak: 0.13, stabPeak: 0.16,       // суммарная огибающая аккорда
    attack: 0.09, stabAttack: 0.02,   // «медленная огибающая» медных
    lpHold: 800, lpStab: 1300,        // lowpass, формирующий тембр «меди»
    detune: 4                          // расстройка голосов, центы (толща тембра)
  };

  /* ======================= СОСТОЯНИЕ ======================= */

  let ctx = null;       // AudioContext (создаётся в init())
  let master = null;    // мастер-gain (0.5, при mute — 0)
  let comp = null;      // DynamicsCompressor на мастере
  let sfxBus = null;    // шина эффектов (1.0)
  let musicBus = null;  // шина музыки (−18 дБ)
  let noiseBuf = null;  // общий буфер белого шума (1 c)
  let muted = false;

  const music = { playing: false, timer: null, step: 0, nextTime: 0 };

  /* ======================= УТИЛИТЫ ======================= */

  // MIDI → частота, Гц
  function midiToHz(m) { return 440 * Math.pow(2, (m - 69) / 12); }

  // Небольшой сдвиг вперёд, чтобы не планировать «в прошлое»
  function now() { return ctx.currentTime + 0.005; }

  // Экспоненциальная огибающая: attack до peak, спад до пола за dur
  function env(g, t, peak, attack, dur) {
    g.setValueAtTime(RAMP_FLOOR, t);
    g.exponentialRampToValueAtTime(Math.max(peak, RAMP_FLOOR * 2),
                                   t + Math.max(attack, 0.003));
    g.exponentialRampToValueAtTime(RAMP_FLOOR, t + Math.max(dur, attack + 0.01));
  }

  // Подключение к шине SFX со стерео-панорамой (pan ∈ [-1..1], опционально)
  function route(node, pan) {
    if (pan && ctx.createStereoPanner) {
      const p = ctx.createStereoPanner();
      p.pan.value = Math.max(-1, Math.min(1, pan));
      node.connect(p);
      p.connect(sfxBus);
    } else {
      node.connect(sfxBus);
    }
  }

  // Тон: осциллятор → [lowpass] → gain-огибающая → шина
  function tone(o) {
    const osc = ctx.createOscillator();
    osc.type = o.type || 'sine';
    osc.frequency.setValueAtTime(o.midi ? midiToHz(o.midi) : o.f0, o.t);
    if (o.f1) osc.frequency.exponentialRampToValueAtTime(o.f1, o.t + o.dur);

    const g = ctx.createGain();
    env(g.gain, o.t, o.peak, o.attack || 0.005, o.dur);

    let head = osc;
    if (o.lp) {
      const f = ctx.createBiquadFilter();
      f.type = 'lowpass';
      f.frequency.value = o.lp;
      f.Q.value = 0.6;
      osc.connect(f);
      head = f;
    }
    head.connect(g);

    if (o.dest) g.connect(o.dest);
    else route(g, o.pan);

    osc.start(o.t);
    osc.stop(o.t + o.dur + 0.08);
  }

  // Шум: BufferSource(белый шум) → фильтр → gain-огибающая → шина
  function noiseHit(o) {
    const src = ctx.createBufferSource();
    src.buffer = noiseBuf;
    src.loop = true;

    const f = ctx.createBiquadFilter();
    f.type = o.ftype || 'bandpass';
    f.frequency.setValueAtTime(o.f0, o.t);
    if (o.f1) f.frequency.exponentialRampToValueAtTime(o.f1, o.t + o.dur);
    f.Q.value = o.q != null ? o.q : 0.8;

    const g = ctx.createGain();
    env(g.gain, o.t, o.peak, o.attack || 0.004, o.dur);

    src.connect(f);
    f.connect(g);

    if (o.dest) g.connect(o.dest);
    else route(g, o.pan);

    src.start(o.t);
    src.stop(o.t + o.dur + 0.05);
  }

  // Аккордовая фанфара: ноты через gap, каждая — огибающая через общий lowpass
  function fanfare(p) {
    const t0 = now();
    const bus = ctx.createGain();
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = p.lp;
    filter.Q.value = 0.5;
    bus.connect(filter);
    filter.connect(sfxBus);

    p.notes.forEach(function (midi, i) {
      const t = t0 + i * p.gap;
      const osc = ctx.createOscillator();
      osc.type = p.type;
      const f = midiToHz(midi);
      osc.frequency.setValueAtTime(f, t);
      if (p.sag) osc.frequency.linearRampToValueAtTime(f * p.sag, t + p.dur);

      const g = ctx.createGain();
      env(g.gain, t, p.peak, 0.02, p.dur);

      osc.connect(g);
      g.connect(bus);
      osc.start(t);
      osc.stop(t + p.dur + 0.05);
    });
  }

  /* ======================= SFX ======================= */

  function laserSfx(pan) {
    const t = now();
    const p = SFX_P.laser;
    // свип-писк «пью»: sawtooth 900 → 200 Гц
    tone({ type: 'sawtooth', f0: p.f0, f1: p.f1, t: t,
           dur: p.dur, peak: p.peak, attack: 0.006, pan: pan });
    // шумовой щелчок
    noiseHit({ ftype: 'highpass', f0: p.clickHz, t: t,
               dur: p.clickDur, peak: p.clickPeak, pan: pan });
  }

  function explosionSfx(big) {
    const t = now();
    const p = SFX_P.explosion;
    const dur = big ? p.durBig : p.dur;
    // шумовой удар с lowpass-спадом
    noiseHit({ ftype: 'lowpass', f0: big ? p.lpHzBig : p.lpHz, f1: p.lpEndHz,
               t: t, dur: dur, peak: big ? p.peakBig : p.peak, q: 0.4 });
    // низкий «удар» для веса
    tone({ type: 'sine', f0: big ? p.subF0Big : p.subF0,
           f1: big ? p.subF1Big : p.subF1, t: t, dur: dur,
           peak: big ? p.subPeakBig : p.subPeak, attack: 0.01 });
  }

  function moveSfx() {
    const p = SFX_P.move;
    noiseHit({ ftype: 'bandpass', f0: p.f0, f1: p.f1, t: now(),
               dur: p.dur, peak: p.peak, attack: p.attack, q: p.q });
  }

  function rotateSfx() {
    const t = now();
    const p = SFX_P.rotate;
    tone({ type: 'square', f0: p.hz, t: t, dur: p.dur, peak: p.peak,
           attack: 0.002, lp: 3000 });
    noiseHit({ ftype: 'highpass', f0: p.clickHz, t: t,
               dur: p.clickDur, peak: p.clickPeak });
  }

  function hyperSfx() {
    const t = now();
    const p = SFX_P.hyper;
    tone({ type: 'sine', f0: p.f0, f1: p.f1, t: t,
           dur: p.dur, peak: p.peak, attack: p.attack });
    // «мерцание» октавой выше — ощущение разгоняющегося гиперпривода
    tone({ type: 'sine', f0: p.f0 * p.shimmerF, f1: p.f1 * p.shimmerF, t: t,
           dur: p.dur, peak: p.shimmerPeak, attack: p.attack });
  }

  function flipSfx() {
    const t = now();
    const p = SFX_P.flip;
    tone({ type: 'triangle', f0: p.f0a, f1: p.f1a, t: t,
           dur: p.dur, peak: p.peak, attack: 0.004 });
    tone({ type: 'triangle', f0: p.f0b, f1: p.f1b, t: t + p.gap,
           dur: p.dur, peak: p.peak, attack: 0.004 });
  }

  function placeSfx() {
    const t = now();
    const p = SFX_P.place;
    tone({ type: 'square', f0: p.hz, t: t, dur: p.dur, peak: p.peak,
           attack: 0.002, lp: 900 });
    noiseHit({ ftype: 'lowpass', f0: p.clickHz, t: t,
               dur: p.clickDur, peak: p.clickPeak });
  }

  function winSfx()  { fanfare(SFX_P.win); }
  function loseSfx() { fanfare(SFX_P.lose); }
  function drawSfx() { fanfare(SFX_P.draw); }

  function uiSfx() {
    const p = SFX_P.ui;
    tone({ type: 'sine', f0: p.hz, t: now(), dur: p.dur, peak: p.peak,
           attack: 0.002 });
  }

  /* ======================= МУЗЫКА (луп) ======================= */
  /* Lookahead-планировщик: setInterval-помпа каждые ~30 мс планирует шаги
   * секвенсора (восьмые доли) через AudioContext.currentTime с запасом 150 мс.
   * Схема такта: бас на четвертях (root–fifth), хай-хэт на слабых восьмых,
   * «медные» аккорды — держка на долю 1 и стаб на долю 3. */

  function bassNote(midi, t) {
    tone({ type: 'triangle', midi: midi, t: t,
           dur: STEP_DUR * BASS.durSteps, peak: BASS.peak, attack: 0.012,
           lp: BASS.lp, dest: musicBus });
  }

  function hat(t) {
    noiseHit({ ftype: 'highpass', f0: HAT.hz, t: t,
               dur: HAT.dur, peak: HAT.peak, attack: 0.002, q: HAT.q,
               dest: musicBus });
  }

  // «Медный» аккорд: 3 sawtooth через общий lowpass с медленной огибающей
  function brass(chord, t, dur, stab) {
    const filter = ctx.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.setValueAtTime(stab ? BRASS.lpStab : BRASS.lpHold, t);
    filter.Q.value = 0.8;

    const bus = ctx.createGain();
    env(bus.gain, t, stab ? BRASS.stabPeak : BRASS.peak,
        stab ? BRASS.stabAttack : BRASS.attack, dur);
    filter.connect(bus);
    bus.connect(musicBus);

    chord.forEach(function (midi, i) {
      const osc = ctx.createOscillator();
      osc.type = 'sawtooth';
      osc.frequency.value = midiToHz(midi);
      osc.detune.value = (i - 1) * BRASS.detune; // ±4 цента — «толща» меди
      osc.connect(filter);
      osc.start(t);
      osc.stop(t + dur + 0.1);
    });
  }

  // Один шаг секвенсора (восьмая доли) в момент t
  function scheduleStep(step, t) {
    if (muted) return; // при mute шаги пропускаются, фаза лупа сохраняется

    const bar = Math.floor(step / BAR_STEPS) % LOOP_BARS;
    const pos = step % BAR_STEPS;
    const cell = MUSIC_BARS[bar];

    // хай-хэт на слабых (нечётных) восьмых — лёгкий маршевый ритм
    if (pos % 2 === 1) hat(t);

    // бас на четвертях: чередование root–fifth
    if (pos % 2 === 0) {
      const quarter = pos / 2;
      const midi = quarter % 2 === 0 ? cell.bass : cell.bass + BASS_FIFTH;
      bassNote(midi, t);
    }

    // «медные»: держка на сильную долю 1, короткий акцент-стаб на долю 3
    if (pos === 0) brass(cell.chord, t, STEP_DUR * BRASS.holdSteps, false);
    if (pos === 4) brass(cell.chord, t, STEP_DUR * BRASS.stabSteps, true);
  }

  function musicTick() {
    if (!ctx || !music.playing) return;

    // если вкладка спала и помпа дросселировалась — выравниваем фазу,
    // не заваливая граф пачкой просроченных событий
    if (music.nextTime < ctx.currentTime - 0.05) {
      music.nextTime = ctx.currentTime + 0.05;
    }

    const horizon = ctx.currentTime + SCHED_AHEAD;
    while (music.nextTime < horizon) {
      scheduleStep(music.step, music.nextTime);
      music.step = (music.step + 1) % LOOP_STEPS;
      music.nextTime += STEP_DUR;
    }
  }

  function startMusic() {
    if (!ctx || music.playing) return;
    music.playing = true;
    music.step = 0;
    music.nextTime = ctx.currentTime + 0.08;
    music.timer = setInterval(musicTick, SCHED_INTERVAL_MS);
  }

  function stopMusic() {
    music.playing = false;
    if (music.timer) {
      clearInterval(music.timer);
      music.timer = null;
    }
    // уже запланированные ноты доиграют (~до секунды хвоста) — это нормально
  }

  /* ======================= ИНИЦИАЛИЗАЦИЯ / MUTE ======================= */

  function buildGraph() {
    master = ctx.createGain();
    master.gain.value = muted ? 0 : MASTER_GAIN;

    comp = ctx.createDynamicsCompressor();
    comp.threshold.value = COMP_THRESH;
    comp.knee.value = COMP_KNEE;
    comp.ratio.value = COMP_RATIO;
    comp.attack.value = COMP_ATTACK;
    comp.release.value = COMP_RELEASE;

    master.connect(comp);
    comp.connect(ctx.destination);

    sfxBus = ctx.createGain();
    sfxBus.gain.value = 1;
    sfxBus.connect(master);

    musicBus = ctx.createGain();
    musicBus.gain.value = MUSIC_GAIN; // −18 дБ относительно SFX
    musicBus.connect(master);

    // общий буфер белого шума (1 секунда, моно)
    const len = Math.max(1, Math.floor(ctx.sampleRate)) | 0;
    noiseBuf = ctx.createBuffer(1, len, ctx.sampleRate);
    const data = noiseBuf.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  }

  function init() {
    if (ctx) { // повторный вызов — просто «разбудить» контекст
      try { ctx.resume(); } catch (e) { /* ignore */ }
      return;
    }
    try {
      const AC = global.AudioContext || global.webkitAudioContext;
      if (!AC) return; // Web Audio недоступен — остаёмся в режиме no-op
      ctx = new AC();
      buildGraph();
      try { ctx.resume(); } catch (e) { /* авто-политика — resume позже */ }
    } catch (e) {
      ctx = null; // любая ошибка — все методы продолжат работать как no-op
    }
  }

  function setMuted(v) {
    muted = !!v;
    if (ctx && master) {
      try {
        master.gain.setTargetAtTime(muted ? 0 : MASTER_GAIN,
                                    ctx.currentTime, 0.02);
      } catch (e) { /* ignore */ }
    }
  }

  function isMuted() { return muted; }

  /* ======================= ПУБЛИЧНОЕ API ======================= */
  /* Обёртка sfx(): до init() / при mute — тихий no-op, любые runtime-ошибки
   * синтеза не должны ронять игровой цикл. */

  function sfx(fn) {
    return function () {
      if (!ctx || muted) return;
      try { fn.apply(null, arguments); } catch (e) { /* звук не критичен */ }
    };
  }

  global.SWBSound = {
    init: init,
    setMuted: setMuted,
    isMuted: isMuted,

    // боевые и интерфейсные эффекты
    laser: sfx(laserSfx),       // laser(pan=-1..1)
    explosion: sfx(explosionSfx), // explosion(big=true|false)
    move: sfx(moveSfx),
    rotate: sfx(rotateSfx),
    hyper: sfx(hyperSfx),
    flip: sfx(flipSfx),
    place: sfx(placeSfx),
    win: sfx(winSfx),
    lose: sfx(loseSfx),
    draw: sfx(drawSfx),
    ui: sfx(uiSfx),

    // фоновая музыка
    startMusic: startMusic,
    stopMusic: stopMusic
  };
})(typeof window !== 'undefined' ? window
   : typeof globalThis !== 'undefined' ? globalThis
   : this);
