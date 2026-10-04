/* demo/textures3d.js — тулкит процедурных текстур и материалов для 3D-моделей
 * кораблей (three.js r160). Детерминированный: вся случайность только через
 * seeded PRNG (mulberry32) с фиксированным seed на ключ материала.
 *
 * Ленивая генерация: canvas-текстуры строятся при ПЕРВОМ вызове make*Material
 * (то есть из createShipModel), а не при импорте модуля — поэтому импорт
 * безопасен вне браузера (node/тесты): без DOM материалы возвращаются
 * однотонными, без map/roughnessMap.
 *
 * Кэш: материалы переиспользуются между моделями; disposeTextures() вызывается
 * из disposeModelMaterials() (models3d.js) при разборке сцены.
 */
import * as THREE from 'three';

const TEX_SIZE = 512;

// ---------- детерминированный PRNG ----------

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function seedFromString(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// ---------- canvas (лениво и безопасно вне DOM) ----------

function makeCanvas(size) {
  if (typeof document === 'undefined' || !document || !document.createElement) return null;
  try {
    const c = document.createElement('canvas');
    c.width = c.height = size;
    return c;
  } catch (e) {
    return null;
  }
}

function texFromCanvas(cv, srgb, repeat) {
  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(repeat[0], repeat[1]);
  t.anisotropy = 4;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// ---------- цветовые помощники ----------

function lerpCol(base, k) {
  // k>0 — к белому, k<0 — к чёрному (детерминированная вариация яркости)
  const c = base.clone();
  if (k >= 0) c.lerp(new THREE.Color(0xffffff), Math.min(1, k));
  else c.lerp(new THREE.Color(0x000000), Math.min(1, -k));
  return c;
}
function rgbCss(c) {
  const r = Math.round(Math.min(1, Math.max(0, c.r)) * 255);
  const g = Math.round(Math.min(1, Math.max(0, c.g)) * 255);
  const b = Math.round(Math.min(1, Math.max(0, c.b)) * 255);
  return 'rgb(' + r + ',' + g + ',' + b + ')';
}
function grayCss01(v) {
  const g = Math.round(Math.min(1, Math.max(0, v)) * 255);
  return 'rgb(' + g + ',' + g + ',' + g + ')';
}

// ---------- кэш материалов ----------

const matCache = new Map();

function cached(key, make) {
  let m = matCache.get(key);
  if (!m) {
    m = make();
    matCache.set(key, m);
  }
  return m;
}

// ---------- общие рисовальщики ----------

function addNoise(ctx, size, rnd, amt) {
  if (!amt) return;
  const N = 128;
  const nc = makeCanvas(N);
  if (!nc) return;
  const nctx = nc.getContext('2d');
  if (!nctx) return;
  const img = nctx.createImageData(N, N);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 118 + (rnd() * 2 - 1) * 60;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  nctx.putImageData(img, 0, 0);
  // 'overlay' — 128 остаётся нейтральным, шум лишь модулирует яркость
  ctx.globalCompositeOperation = 'overlay';
  ctx.globalAlpha = 0.55;
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(nc, 0, 0, size, size);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = 1;
}

// Сетка панелей: ячейки с вариацией яркости ±panelJitter, швы, вставные плиты.
function genCells(size, rnd, o) {
  const cells = [];
  const cs = Math.max(16, o.cell || 64);
  let row = 0;
  for (let y = 0; y < size; y += cs, row++) {
    const off = (o.brick !== false && row % 2 === 1) ? cs * 0.5 : 0;
    for (let x = -off; x < size; x += cs) {
      const d = (rnd() * 2 - 1) * (o.panelJitter != null ? o.panelJitter : 0.06);
      const plate = rnd() < (o.plateChance != null ? o.plateChance : 0.07);
      cells.push({ x, y, w: cs, h: cs, d, plate });
    }
  }
  return cells;
}

// Рисует карту панелей; mono=true — версия для roughnessMap (оттенки серого).
function paintPanels(ctx, size, cells, rnd, o, mono) {
  const base = mono
    ? new THREE.Color(o.roughBase, o.roughBase, o.roughBase)
    : new THREE.Color(o.color);
  ctx.fillStyle = mono ? grayCss01(o.roughBase) : rgbCss(base);
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    const k = c.d + (c.plate ? (mono ? 0.10 : -(o.plateDarken != null ? o.plateDarken : 0.16)) : 0);
    ctx.fillStyle = mono ? grayCss01(o.roughBase + k) : rgbCss(lerpCol(base, k));
    ctx.fillRect(c.x, c.y, c.w, c.h);
  }
  // швы
  ctx.strokeStyle = mono
    ? 'rgba(255,255,255,0.30)'
    : 'rgba(9,11,15,' + (o.seamAlpha != null ? o.seamAlpha : 0.5) + ')';
  ctx.lineWidth = Math.max(2, size / 220);
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    ctx.strokeRect(c.x + 1, c.y + 1, c.w - 2, c.h - 2);
  }
  // кромка вставных плит
  ctx.lineWidth = 2;
  for (let i = 0; i < cells.length; i++) {
    const c = cells[i];
    if (!c.plate) continue;
    ctx.strokeStyle = mono ? 'rgba(0,0,0,0.25)' : 'rgba(255,255,255,0.10)';
    ctx.strokeRect(c.x + 5, c.y + 5, c.w - 10, c.h - 10);
  }
  // вертикальные потёки-weathering
  const n = mono ? Math.round((o.streaks != null ? o.streaks : 12) * 0.6) : (o.streaks != null ? o.streaks : 12);
  for (let i = 0; i < n; i++) {
    const x = rnd() * size, w = 2 + rnd() * 8;
    const a = mono ? 0.10 + rnd() * 0.12 : 0.05 + rnd() * 0.10;
    const g = ctx.createLinearGradient(x, 0, x, size);
    const col = mono ? '255,255,255' : '13,15,19';
    g.addColorStop(0, 'rgba(' + col + ',0)');
    g.addColorStop(0.3, 'rgba(' + col + ',' + a.toFixed(3) + ')');
    g.addColorStop(1, 'rgba(' + col + ',0)');
    ctx.fillStyle = g;
    ctx.fillRect(x, 0, w, size);
  }
  addNoise(ctx, size, rnd, o.noise != null ? o.noise : 0.05);
}

// Концентрические панели (диск «Сокола»); UV-кэп цилиндра — круг в центре UV.
function paintRadial(ctx, size, rnd, o, mono) {
  const base = mono
    ? new THREE.Color(o.roughBase, o.roughBase, o.roughBase)
    : new THREE.Color(o.color);
  const c = size / 2, rMax = size / 2;
  ctx.fillStyle = mono ? grayCss01(o.roughBase) : rgbCss(base);
  ctx.fillRect(0, 0, size, size);
  const rings = o.rings || 9, sectors = o.sectors || 18;
  const jitter = o.panelJitter != null ? o.panelJitter : 0.07;
  for (let i = 0; i < rings; i++) {
    const r0 = (i / rings) * rMax, r1 = ((i + 1) / rings) * rMax;
    for (let j = 0; j < sectors; j++) {
      const a0 = (j / sectors) * Math.PI * 2, a1 = ((j + 1) / sectors) * Math.PI * 2;
      const plate = rnd() < 0.05;
      const k = plate ? (mono ? 0.12 : -0.26) : (rnd() * 2 - 1) * jitter;
      ctx.beginPath();
      ctx.arc(c, c, r1, a0, a1);
      ctx.arc(c, c, r0, a1, a0, true);
      ctx.closePath();
      ctx.fillStyle = mono ? grayCss01(o.roughBase + k) : rgbCss(lerpCol(base, k));
      ctx.fill();
    }
  }
  // швы: кольца и спицы
  ctx.strokeStyle = mono ? 'rgba(255,255,255,0.30)' : 'rgba(10,12,16,0.5)';
  ctx.lineWidth = Math.max(2, size / 220);
  for (let i = 1; i <= rings; i++) {
    ctx.beginPath();
    ctx.arc(c, c, (i / rings) * rMax, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let j = 0; j < sectors; j++) {
    const a = (j / sectors) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(c, c);
    ctx.lineTo(c + Math.cos(a) * rMax, c + Math.sin(a) * rMax);
    ctx.stroke();
  }
  // центральный волок
  ctx.fillStyle = mono ? grayCss01(o.roughBase + 0.08) : rgbCss(lerpCol(base, -0.18));
  ctx.beginPath();
  ctx.arc(c, c, rMax * 0.055, 0, Math.PI * 2);
  ctx.fill();
  // редкие радиальные потёки
  const n = mono ? 5 : (o.streaks != null ? Math.round(o.streaks * 0.7) : 8);
  for (let i = 0; i < n; i++) {
    const a = rnd() * Math.PI * 2, w = 3 + rnd() * 7;
    const a0 = a - w / size, a1 = a + w / size;
    ctx.beginPath();
    ctx.moveTo(c, c);
    ctx.arc(c, c, rMax, a0, a1);
    ctx.closePath();
    ctx.fillStyle = mono ? 'rgba(255,255,255,0.10)' : 'rgba(13,15,19,0.09)';
    ctx.fill();
  }
  addNoise(ctx, size, rnd, o.noise != null ? o.noise : 0.05);
}

// Панельная сфера («Звезда Смерти»): поля панелей разных оттенков, светлые
// ангары, тёмная экваториальная полоса-траншея, россыпь светящихся окон.
function paintSpherePanels(ctx, size, rnd, o, mono) {
  const base = mono
    ? new THREE.Color(o.roughBase, o.roughBase, o.roughBase)
    : new THREE.Color(o.color);
  const cs = Math.max(16, o.cell || 42);
  ctx.fillStyle = mono ? grayCss01(o.roughBase) : rgbCss(base);
  ctx.fillRect(0, 0, size, size);
  const jitter = o.panelJitter != null ? o.panelJitter : 0.08;
  for (let y = 0; y < size; y += cs) {
    for (let x = 0; x < size; x += cs) {
      const r = rnd();
      let k = (rnd() * 2 - 1) * jitter;
      if (r < 0.05) k = mono ? 0.12 : -0.30;          // тёмные вставные плиты
      else if (r < 0.09) k = mono ? -0.06 : 0.24;     // светлые ангары
      ctx.fillStyle = mono ? grayCss01(o.roughBase + k) : rgbCss(lerpCol(base, k));
      ctx.fillRect(x, y, cs, cs);
    }
  }
  ctx.strokeStyle = mono ? 'rgba(255,255,255,0.28)' : 'rgba(9,11,15,0.45)';
  ctx.lineWidth = Math.max(2, size / 256);
  for (let x = 0; x <= size; x += cs) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, size); ctx.stroke();
  }
  for (let y = 0; y <= size; y += cs) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(size, y); ctx.stroke();
  }
  // окна (только в цветовую карту)
  if (!mono) {
    const dots = o.windows != null ? o.windows : 260;
    for (let i = 0; i < dots; i++) {
      const x = rnd() * size, y = rnd() * size;
      const a = 0.25 + rnd() * 0.45;
      ctx.fillStyle = 'rgba(205,228,255,' + a.toFixed(3) + ')';
      ctx.fillRect(x, y, rnd() < 0.25 ? 3 : 2, 2);
    }
  }
  // экваториальная траншея (v=0.5)
  const bh = Math.round(size * (o.bandHeight != null ? o.bandHeight : 0.075));
  ctx.fillStyle = mono ? grayCss01(o.roughBase + 0.14) : rgbCss(new THREE.Color(o.bandColor != null ? o.bandColor : 0x2b313c));
  ctx.fillRect(0, size / 2 - bh / 2, size, bh);
  ctx.fillStyle = mono ? 'rgba(0,0,0,0.2)' : 'rgba(255,255,255,0.10)';
  ctx.fillRect(0, size / 2 - bh / 2 - 3, size, 3);
  ctx.fillRect(0, size / 2 + bh / 2, size, 3);
  addNoise(ctx, size, rnd, o.noise != null ? o.noise : 0.05);
}

// ---------- материалы ----------

function buildDualMapMaterial(key, o, painter) {
  return cached(key, () => {
    o.seed = o.seed != null ? o.seed : seedFromString(key);
    const params = {
      color: o.color,
      metalness: o.metalness != null ? o.metalness : 0.28,
      roughness: o.roughness != null ? o.roughness : 0.62,
      side: o.side || THREE.FrontSide,
      flatShading: !!o.flatShading
    };
    o.roughBase = Math.round(((o.roughness != null ? o.roughness : 0.55)) * 255) / 255;
    const cv = makeCanvas(TEX_SIZE);
    if (cv) {
      const ctx = cv.getContext('2d');
      const rnd = mulberry32(o.seed);
      painter(ctx, TEX_SIZE, rnd, o, false);
      params.map = texFromCanvas(cv, true, o.repeat || [1, 1]);
      const rc = makeCanvas(TEX_SIZE);
      if (rc) {
        const rnd2 = mulberry32(o.seed ^ 0x9e3779b9);
        painter(rc.getContext('2d'), TEX_SIZE, rnd2, o, true);
        params.roughnessMap = texFromCanvas(rc, false, o.repeat || [1, 1]);
      }
    }
    return new THREE.MeshStandardMaterial(params);
  });
}

/** Корпусная обшивка: сетка панелей ±6% яркости, швы, вставные плиты, потёки, шум.
 * opts: { color, repeat:[rx,ry], cell, panelJitter, plateChance, plateDarken,
 *         seamAlpha, streaks, noise, brick, roughness, metalness, side,
 *         flatShading, seed } */
export function makeHullMaterial(key, opts = {}) {
  const o = Object.assign({}, opts);
  return buildDualMapMaterial(key, o, (ctx, size, rnd, oo, mono) => {
    paintPanels(ctx, size, genCells(size, rnd, oo), rnd, oo, mono);
  });
}

/** Радиальные концентрические панели (диск Millennium Falcon). */
export function makeRadialHullMaterial(key, opts = {}) {
  const o = Object.assign({ rings: 9, sectors: 18 }, opts);
  return buildDualMapMaterial(key, o, paintRadial);
}

/** Панельная сфера с экваториальной траншеей (Звезда Смерти). */
export function makeSpherePanelMaterial(key, opts = {}) {
  const o = Object.assign({ cell: 42, bandHeight: 0.075, bandColor: 0x2b313c, windows: 260 }, opts);
  return buildDualMapMaterial(key, o, paintSpherePanels);
}

/** Крашеная поверхность без расшивки: лёгкая пятнистость + шум
 * (красные полосы X-wing, серебро Slave I, купола астромехов). */
export function makePaintedMaterial(key, color, opts = {}) {
  const o = Object.assign({ color, repeat: [1, 1], roughness: 0.5, metalness: 0.35, noise: 0.04, mottle: 0.06 }, opts);
  return buildDualMapMaterial(key, o, (ctx, size, rnd, oo, mono) => {
    const base = mono
      ? new THREE.Color(oo.roughBase, oo.roughBase, oo.roughBase)
      : new THREE.Color(oo.color);
    ctx.fillStyle = mono ? grayCss01(oo.roughBase) : rgbCss(base);
    ctx.fillRect(0, 0, size, size);
    const n = 7;
    for (let i = 0; i < n; i++) {
      const x = rnd() * size, y = rnd() * size, r = size * (0.08 + rnd() * 0.16);
      const k = (rnd() * 2 - 1) * (mono ? 0.08 : (oo.mottle || 0.06));
      const gr = ctx.createRadialGradient(x, y, 0, x, y, r);
      const col = mono ? grayCss01(oo.roughBase + k) : rgbCss(lerpCol(base, k));
      gr.addColorStop(0, col);
      gr.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = gr;
      ctx.fillRect(x - r, y - r, r * 2, r * 2);
    }
    addNoise(ctx, size, rnd, oo.noise != null ? oo.noise : 0.04);
  });
}

/** Тёмное стекло кокпитов/окон. */
export function makeGlassMaterial() {
  return cached('glass', () => new THREE.MeshPhysicalMaterial({
    color: 0x0a121e,
    metalness: 0,
    envMapIntensity: 1.9,
    roughness: 0.06,
    envMapIntensity: 2,
    clearcoat: 0.8,
    clearcoatRoughness: 0.1,
    transparent: true,
    opacity: 0.92
  }));
}

/** Сопло двигателя: emissive того же цвета, emissiveIntensity 1.6. */
export function makeEngineMaterial(color, intensity = 1.6) {
  return cached('engine:' + color + ':' + intensity, () => new THREE.MeshStandardMaterial({
    color: new THREE.Color(color).lerp(new THREE.Color(0xffffff), 0.25),
    emissive: color,
    emissiveIntensity: intensity,
    metalness: 0.3,
    envMapIntensity: 1.9,
    roughness: 0.4
  }));
}

/** Командный акцент: A — #38b6ff, B — #ff5d5d (emissive-полосы/кольца). */
export function makeAccentMaterial(team) {
  const c = team === 'B' ? 0xff5d5d : 0x38b6ff;
  return cached('accent:' + team, () => new THREE.MeshStandardMaterial({
    color: new THREE.Color(c).multiplyScalar(0.3),
    metalness: 0.4,
    envMapIntensity: 1.9,
    roughness: 0.5,
    emissive: c,
    emissiveIntensity: 1.2
  }));
}

/** Освободить все кэшированные материалы и их текстуры. */
export function disposeTextures() {
  matCache.forEach((m) => {
    if (m.map) m.map.dispose();
    if (m.roughnessMap) m.roughnessMap.dispose();
    m.dispose();
  });
  matCache.clear();
}
