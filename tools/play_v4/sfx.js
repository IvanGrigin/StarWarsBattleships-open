// Звуки игры синтезом Web Audio — без файлов и чужих записей: лазер, щит, попадание, взрыв, щелчок, выбор.
// Браузер разрешает звук только после первого действия игрока; до него вызовы молча ничего не делают.
let ctx = null, master = null, noiseBuf = null;
let muted = true;                                  // по умолчанию без звука (решение владельца); включить — 🔊 или M
try { muted = localStorage.getItem('swb.v4.mute') !== '0'; } catch { /* приватный режим */ }

function ac() {
  if (muted) return null;
  if (!ctx) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
    master = ctx.createGain(); master.gain.value = 0.35; master.connect(ctx.destination);
    noiseBuf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const d = noiseBuf.getChannelData(0);
    for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  }
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}
function env(g, t, a, peak, dur) {
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(peak, t + a);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
}
// Бластер «Звёздных войн»: звук удара по натянутому тросу — дисперсия: высокие частоты приходят
// первыми и быстро уходят вниз («пиу»), с металлическим звоном и коротким эхом. Синтез: несколько
// частичных тонов с экспоненциальным спадом частоты → мягкий перегруз → полосовой фильтр, тоже
// уходящий вниз → «пружинное» эхо. heavy — турболазер крупного корабля: ниже и гулче.
let echo = null, shaper = null;
function blasterBus(c) {
  if (echo) return echo.input;
  const input = c.createGain();
  const dl = c.createDelay(0.5); dl.delayTime.value = 0.047;
  const fb = c.createGain(); fb.gain.value = 0.32;
  const tone = c.createBiquadFilter(); tone.type = 'bandpass'; tone.frequency.value = 1800; tone.Q.value = 0.9;   // звон троса
  const wet = c.createGain(); wet.gain.value = 0.45;
  input.connect(master); input.connect(dl); dl.connect(tone); tone.connect(fb); fb.connect(dl); tone.connect(wet); wet.connect(master);
  echo = { input };
  shaper = c.createWaveShaper();
  const curve = new Float32Array(1024); for (let i = 0; i < 1024; i++) { const x = i / 511.5 - 1; curve[i] = Math.tanh(2.4 * x); }
  shaper.curve = curve;
  return input;
}
function blaster(delay = 0, heavy = false, bright = 1) {
  const c = ac(); if (!c) return;
  const bus = blasterBus(c);
  const t = c.currentTime + delay, dur = heavy ? 0.42 : 0.24;
  const out = c.createGain(); env(out, t, 0.003, heavy ? 0.55 : 0.42, dur);
  const bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 1.2;
  bp.frequency.setValueAtTime(heavy ? 1400 : 3800 * bright, t); bp.frequency.exponentialRampToValueAtTime(heavy ? 160 : 420, t + dur);
  const drive = c.createGain(); drive.gain.value = 1.6;
  const k = heavy ? 0.42 : 1;
  for (const [f0, f1, g, type] of [[3300, 190, 0.5, 'sine'], [2450, 140, 0.35, 'sawtooth'], [4300, 260, 0.2, 'sine'], [1650, 95, 0.25, 'triangle']]) {
    const o = c.createOscillator(), og = c.createGain();
    o.type = type; o.frequency.setValueAtTime(f0 * k * bright, t); o.frequency.exponentialRampToValueAtTime(f1 * k, t + dur);
    o.detune.setValueAtTime((Math.random() - 0.5) * 40, t);
    og.gain.value = g; o.connect(og).connect(drive); o.start(t); o.stop(t + dur + 0.05);
  }
  const ws = c.createWaveShaper(); ws.curve = shaper.curve;           // мягкий перегруз — «грязь» настоящей записи
  drive.connect(ws); ws.connect(bp); bp.connect(out); out.connect(bus);
  noise(0.025, 9000, 3000, heavy ? 0.25 : 0.18, delay);           // «щелчок» выстрела
}

function tone(type, f0, f1, dur, peak = 0.5, delay = 0) {
  const c = ac(); if (!c) return;
  const t = c.currentTime + delay;
  const o = c.createOscillator(), g = c.createGain();
  o.type = type; o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + dur);
  env(g, t, 0.005, peak, dur);
  o.connect(g).connect(master); o.start(t); o.stop(t + dur + 0.05);
}
function noise(dur, f0, f1, peak = 0.6, delay = 0, q = 0.8) {
  const c = ac(); if (!c) return;
  const t = c.currentTime + delay;
  const s = c.createBufferSource(); s.buffer = noiseBuf; s.loop = true;
  const f = c.createBiquadFilter(); f.type = 'lowpass'; f.Q.value = q;
  f.frequency.setValueAtTime(f0, t); f.frequency.exponentialRampToValueAtTime(Math.max(40, f1), t + dur);
  const g = c.createGain(); env(g, t, 0.01, peak, dur);
  s.connect(f).connect(g).connect(master); s.start(t); s.stop(t + dur + 0.05);
}

export const sfx = {
  get muted() { return muted; },
  setMuted(v) {
    muted = v;
    try { localStorage.setItem('swb.v4.mute', v ? '1' : '0'); } catch { /* приватный режим */ }
    if (v && ctx) ctx.suspend();
  },
  laser(shots = 3, side = 0, heavy = false) {  // бластер в духе «Звёздных войн»; у сторон чуть разный тембр
    for (let i = 0; i < shots; i++) blaster(i * (heavy ? 0.16 : 0.1), heavy, side ? 0.88 : 1.06);
  },
  shield() { tone('sine', 520, 980, 0.28, 0.3); tone('triangle', 1040, 1500, 0.2, 0.12, 0.03); },
  hit() { noise(0.22, 3200, 300, 0.5); tone('square', 220, 60, 0.18, 0.2); },
  miss() { tone('sine', 900, 400, 0.12, 0.06); },
  explode() {
    noise(1.8, 2200, 50, 0.95, 0, 0.5);         // раскат
    tone('sine', 95, 26, 1.4, 0.8);             // низкий удар
    noise(0.08, 8000, 1500, 0.5);               // треск в первый миг
    for (let i = 1; i <= 3; i++) noise(0.35, 2500, 200, 0.5, 0.12 * i + Math.random() * 0.08);   // вторичные взрывы
  },
  move() { noise(0.12, 900, 300, 0.12); },
  well() { noise(2.2, 120, 900, 0.7, 0, 3); tone('sine', 40, 90, 2.0, 0.6); tone('sine', 55, 30, 2.4, 0.4, 0.4); },   // гул прорыва колодца
  click() { tone('triangle', 1400, 900, 0.05, 0.12); },
  pick() { tone('triangle', 660, 660, 0.12, 0.25); tone('triangle', 990, 990, 0.22, 0.22, 0.08); },
  win() { [523, 659, 784, 1047].forEach((f, i) => tone('triangle', f, f, 0.35, 0.3, i * 0.13)); },
  lose() { [392, 330, 262].forEach((f, i) => tone('sawtooth', f, f * 0.98, 0.4, 0.18, i * 0.18)); },
};
