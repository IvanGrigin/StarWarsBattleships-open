/* demo/models3d.js — детальные процедурные модели кораблей для 3D-сцены
 * (three.js r160). Замена примитивных «шаров и конусов»: каждая модель —
 * узнаваемый силуэт из множества деталей (обшивка с расшивкой из
 * textures3d.js, гриблы-плашки, антенны, стволы, сопла, стекло, emissive).
 *
 * Контракт (pin, не ломать):
 *   - createShipModel(type_id, team) -> THREE.Group; модель строится НОСОМ
 *     вдоль -Z, вверх +Y; низ итоговой модели всегда приведён к y=0;
 *   - габарит XZ каждой модели равен SHIP3D_FOOTPRINT (константы масштаба
 *     билдеров; scale сцены перезаписывается в cell);
 *   - все меши castShadow = true; receiveShadow=false ставит обёртка сцены;
 *   - team-акцент: A — emissive #38b6ff, B — #ff5d5d (полосы/кольца/глаза),
 *     остальное — канонические цвета корабля;
 *   - полная детерминированность: никакого Math.random, только mulberry32
 *     (seed фиксирован на поле гриблов);
 *   - приоритет источника: внешняя GLB -> Minecraft mesh -> процедурный
 *     BUILDERS -> воксельный фолбэк -> phantom.
 *   - ориентация на поле: group.rotation.y = (30 - 60·facing)·π/180.
 */
import * as THREE from 'three';
import { RoundedBoxGeometry } from './vendor/RoundedBoxGeometry.js';
import {
  mulberry32,
  makeHullMaterial, makeRadialHullMaterial, makeSpherePanelMaterial,
  makePaintedMaterial, makeGlassMaterial, makeEngineMaterial, makeAccentMaterial,
  disposeTextures
} from './textures3d.js';

export const TEAM3D_COLORS = { A: 0x38b6ff, B: 0xff5d5d };

// Максимальный планарный габарит (полная ширина X, полная длина Z) в cell.
// Значения не менять — на них завязаны внешние GLB и воксельный фолбэк.
export const SHIP3D_FOOTPRINT = {
  tie_fighter:       { x: 0.58, z: 0.50 },
  tie_advanced_x1:   { x: 0.60, z: 0.55 },
  xwing_t65:         { x: 0.68, z: 0.75 },
  eta2_actis:        { x: 0.55, z: 0.60 },
  millennium_falcon: { x: 0.64, z: 0.88 },
  star_destroyer:    { x: 0.56, z: 0.84 },
  death_star_1:      { x: 0.64, z: 0.64 },
  slave_1:           { x: 0.62, z: 0.78 },
  ghost:             { x: 0.36, z: 0.86 },
  phantom:           { x: 0.55, z: 0.42 },
  vulture_droid:     { x: 0.50, z: 0.42 }
};

// ---------- материалы кораблей (ленивые, кэш в textures3d.js) ----------

const Mat = {
  // Империя: светло-серый корпус + тёмные панели
  isdHull: () => makeHullMaterial('isdHull', { color: 0xc8ced8, repeat: [3, 3], cell: 56, side: THREE.DoubleSide, flatShading: true }),
  isdDark: () => makeHullMaterial('isdDark', { color: 0x3d4450, repeat: [2, 2], cell: 64 }),
  impDeep: () => makeHullMaterial('impDeep', { color: 0x23262e, cell: 96, streaks: 4 }),
  tieHull: () => makeHullMaterial('tieHull', { color: 0x76828f, repeat: [2, 2], cell: 72 }),
  tieBall: () => makeHullMaterial('tieBall', { color: 0x69737f, repeat: [4, 2], cell: 80 }),
  tieDark: () => makeHullMaterial('tieDark', { color: 0x2e343f, repeat: [2, 2], cell: 80 }),
  tieAdvHull: () => makeHullMaterial('tieAdvHull', { color: 0x8b95a2, repeat: [3, 2], side: THREE.DoubleSide }),
  // X-wing: серый + канонические красные полосы
  xwHull: () => makeHullMaterial('xwHull', { color: 0xb2b8c1, repeat: [2, 2], side: THREE.DoubleSide }),
  xwRed: () => makePaintedMaterial('xwRed', 0xa8232d, { roughness: 0.45, metalness: 0.3 }),
  r2Blue: () => makePaintedMaterial('r2Blue', 0x3e6db0, { roughness: 0.4, metalness: 0.3 }),
  // Джедайский дельта-звёздный истребитель
  etaHull: () => makeHullMaterial('etaHull', { color: 0xc6ccd4, repeat: [2, 2], cell: 56 }),
  // Millennium Falcon: грязный серо-зелёный
  falHull: () => makeRadialHullMaterial('falHull', { color: 0x8f9787, roughness: 0.6, metalness: 0.32 }),
  falFlat: () => makeHullMaterial('falFlat', { color: 0x828a7b, repeat: [2, 1], cell: 72 }),
  falDark: () => makeHullMaterial('falDark', { color: 0x2f3436, repeat: [2, 2], cell: 80 }),
  // Звезда Смерти
  dsHull: () => makeSpherePanelMaterial('dsHull', { color: 0xb4bac3, repeat: [3, 1], roughness: 0.6 }),
  dsDark: () => makeHullMaterial('dsDark', { color: 0x2c313b, cell: 80 }),
  // Slave I: бордово-коричневый + серебро
  slHull: () => makeHullMaterial('slHull', { color: 0x5d2a35, repeat: [2, 2], cell: 60 }),
  slSilver: () => makePaintedMaterial('slSilver', 0xc9ccd2, { roughness: 0.32, metalness: 0.32 }),
  // Ghost / Phantom: серо-зелёные
  ghHull: () => makeHullMaterial('ghHull', { color: 0x99a28f, repeat: [2, 2], cell: 64 }),
  ghNose: () => makeHullMaterial('ghNose', { color: 0x8f9886, repeat: [1, 1], flatShading: true }),
  ghDark: () => makeHullMaterial('ghDark', { color: 0x333940, repeat: [2, 2], cell: 80 }),
  ghOrange: () => makeEngineMaterial(0xff9a3d, 0.5),
  phHull: () => makeHullMaterial('phHull', { color: 0x9aa392, repeat: [2, 2], cell: 64 }),
  // Стервятник: серо-синие панели боевого дроида
  vuHull: () => makeHullMaterial('vuHull', { color: 0x8a9099, repeat: [3, 2], cell: 64 }),
  vuDark: () => makeHullMaterial('vuDark', { color: 0x3a4049, repeat: [2, 2], cell: 80 })
};

// Цвета сопел двигателей
const ENG = {
  imperial: () => makeEngineMaterial(0x7fd0ff),
  pale:     () => makeEngineMaterial(0x8fd4ff),
  orange:   () => makeEngineMaterial(0xff8a5c),
  laser:    () => makeEngineMaterial(0x52ff4d, 1.8)
};

// ---------- геометрические помощники ----------

function mesh(geo, mat, x, y, z) {
  const m = new THREE.Mesh(geo, mat);
  m.position.set(x || 0, y || 0, z || 0);
  m.castShadow = true;
  return m;
}
function box(w, h, d, mat, x, y, z) { return mesh(new THREE.BoxGeometry(w, h, d), mat, x, y, z); }
function rbox(w, h, d, mat, x, y, z, radius) {
  const r = radius != null ? radius : Math.min(w, h, d) * 0.22;
  return mesh(new RoundedBoxGeometry(w, h, d, 2, r), mat, x, y, z);
}
function cylZ(rTop, rBack, len, seg, mat, x, y, z) {
  // цилиндр осью вдоль Z: rTop — радиус со стороны -Z (нос), rBack — +Z (корма)
  const g = new THREE.CylinderGeometry(rBack, rTop, len, seg);
  g.rotateX(Math.PI / 2); // +Y -> +Z
  return mesh(g, mat, x, y, z);
}
function cylX(r, len, seg, mat, x, y, z) {
  const g = new THREE.CylinderGeometry(r, r, len, seg);
  g.rotateZ(Math.PI / 2); // ось Y -> X
  return mesh(g, mat, x, y, z);
}
function cylY(rT, rB, h, seg, mat, x, y, z) { return mesh(new THREE.CylinderGeometry(rT, rB, h, seg), mat, x, y, z); }
function sph(r, mat, x, y, z, sx, sy, sz) {
  const m = mesh(new THREE.SphereGeometry(r, 20, 14), mat, x, y, z);
  if (sx || sy || sz) m.scale.set(sx || 1, sy || 1, sz || 1);
  return m;
}
function hexPlate(r, thick, mat, x, y, z) {
  // шестиугольная панель, нормаль вдоль X; вершины смотрят вперёд/назад (±Z)
  const g = new THREE.CylinderGeometry(r, r, thick, 6);
  g.rotateZ(Math.PI / 2);
  return mesh(g, mat, x, y, z);
}
function torus(r, tube, mat, x, y, z, segs) {
  return mesh(new THREE.TorusGeometry(r, tube, 8, segs || 24), mat, x, y, z);
}
function latheZ(pts, seg, mat) {
  // профиль [радиус, z]: z<0 — к носу; ось вращения -> Z
  const g = new THREE.LatheGeometry(pts.map((p) => new THREE.Vector2(p[0], p[1])), seg);
  g.rotateX(Math.PI / 2); // +Y -> +Z
  return mesh(g, mat, 0, 0, 0);
}
function extrudeShape(shape, depth, bevel, mat) {
  // контур в XY, «нос» контура +Y; после поворота нос -Z, толщина центрирована
  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: depth, steps: 1,
    bevelEnabled: !!bevel, bevelThickness: bevel ? bevel * 0.9 : 0,
    bevelSize: bevel || 0, bevelSegments: bevel ? 2 : 1
  });
  geo.rotateX(-Math.PI / 2);
  geo.translate(0, -depth / 2, 0);
  return mesh(geo, mat, 0, 0, 0);
}
function extrudeFlat(points, depth, bevel, mat) {
  const shape = new THREE.Shape();
  points.forEach((p, i) => { if (i === 0) shape.moveTo(p[0], p[1]); else shape.lineTo(p[0], p[1]); });
  shape.closePath();
  return extrudeShape(shape, depth, bevel, mat);
}
function accentStrip(w, d, team, x, y, z) { return box(w, 0.012, d, makeAccentMaterial(team), x, y, z); }

/** Поле гриблов: детерминированная сетка тонких плашек/рёбер/труб на палубе.
 * opts: { x0,x1,z0,z1, nx,nz, y | yFn(z), seed, mat, mat2, sMin,sMax,
 *         skip, jx, jz, avoid:[{x,z,r}] } */
function greebleField(group, o) {
  const rnd = mulberry32(o.seed >>> 0);
  const yFn = o.yFn || (() => o.y);
  const avoid = o.avoid || [];
  for (let i = 0; i < o.nx; i++) {
    for (let j = 0; j < o.nz; j++) {
      if (rnd() < (o.skip != null ? o.skip : 0.25)) continue;
      const x = o.x0 + (o.x1 - o.x0) * (i + 0.5) / o.nx + (rnd() - 0.5) * (o.jx || 0);
      const z = o.z0 + (o.z1 - o.z0) * (j + 0.5) / o.nz + (rnd() - 0.5) * (o.jz || 0);
      let bad = false;
      for (const a of avoid) {
        if ((x - a.x) * (x - a.x) + (z - a.z) * (z - a.z) < a.r * a.r) { bad = true; break; }
      }
      if (bad) continue;
      const s1 = o.sMin + rnd() * (o.sMax - o.sMin);
      const s2 = o.sMin + rnd() * (o.sMax - o.sMin);
      const kind = rnd();
      const mat = rnd() < 0.5 ? o.mat : (o.mat2 || o.mat);
      let m, h;
      if (kind < 0.14) {          // труба вдоль длинной стороны
        const r = 0.004 + rnd() * 0.005;
        const len = Math.max(s1, s2) * 2.2;
        m = s1 > s2 ? cylX(r, len, 6, mat) : cylZ(r, r, len, 6, mat);
        h = r * 2;
      } else if (kind < 0.32) {   // ребро-фин
        h = 0.013 + rnd() * 0.013;
        m = box(s1 * 0.5, h, s2 * 1.4, mat);
      } else {                    // тонкая плашка
        h = 0.004 + rnd() * 0.007;
        m = box(s1, h, s2, mat);
      }
      m.position.set(x, yFn(z) + h / 2 + (o.lift || 0), z);
      group.add(m);
    }
  }
}

/** Клин Звёздного разрушителя: фрустум из своего BufferGeometry. */
function wedgeGeometry(hx, hz) {
  const NT = [0, 0.035, -hz], NB = [0, -0.035, -hz];
  const RT = [hx, 0.115, hz], LT = [-hx, 0.115, hz];
  const RB = [hx, -0.075, hz], LB = [-hx, -0.075, hz];
  const tris = [
    [NT, LT, RT],            // верхняя палуба (наклонная)
    [NB, RB, LB],            // днище
    [NT, RB, NB], [NT, RT, RB], // правый борт
    [NT, LB, LT], [NT, NB, LB], // левый борт
    [RT, LT, LB], [RT, LB, RB]  // корма
  ];
  const pos = [], uv = [];
  for (const t of tris) {
    for (const v of t) {
      pos.push(v[0], v[1], v[2]);
      uv.push(v[0] / (2 * hx) + 0.5, (v[2] + hz) / (2 * hz));
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geo.computeVertexNormals();
  return geo;
}

// ---------- Модели (нос вдоль -Z, габарит XZ = FOOTPRINT) ----------

// 1. star_destroyer: клин-фрустум + террасы надстройки + мостик с дефлекторами
//    + 3 сопла + поля гриблов на палубе.
function buildStarDestroyer(team) {
  const Fp = SHIP3D_FOOTPRINT.star_destroyer;
  const hx = Fp.x / 2, hz = Fp.z / 2;
  const g = new THREE.Group();
  const model = new THREE.Group();
  model.position.y = -0.08;
  g.add(model);

  model.add(mesh(wedgeGeometry(hx, hz), Mat.isdHull()));

  // террасы надстройки (tapered slabs над палубой)
  const deckY = (z) => 0.035 + 0.0952 * (z + hz); // наклон верхней палубы
  model.add(box(0.20, 0.040, 0.34, Mat.isdHull(), 0, deckY(0.20) + 0.020, 0.20));
  model.add(box(0.155, 0.034, 0.26, Mat.isdHull(), 0, deckY(0.20) + 0.057, 0.24));
  model.add(box(0.11, 0.030, 0.18, Mat.isdHull(), 0, deckY(0.24) + 0.089, 0.28));
  // мостик-башня + горизонтальная планка + 2 дефлектор-сферы
  model.add(box(0.048, 0.056, 0.056, Mat.isdDark(), 0, deckY(0.28) + 0.119, 0.315));
  model.add(box(0.17, 0.014, 0.030, Mat.isdDark(), 0, deckY(0.28) + 0.155, 0.318));
  model.add(sph(0.021, Mat.impDeep(), -0.068, deckY(0.28) + 0.161, 0.318));
  model.add(sph(0.021, Mat.impDeep(), 0.068, deckY(0.28) + 0.161, 0.318));
  // окна моста (стекло) на фасаде башни
  model.add(box(0.036, 0.008, 0.004, makeGlassMaterial(), 0, deckY(0.28) + 0.132, 0.2875));
  // акцент команды на башне и бортах надстройки
  const acc = makeAccentMaterial(team);
  model.add(box(0.036, 0.020, 0.004, acc, 0, deckY(0.28) + 0.119, 0.286));
  model.add(box(0.004, 0.008, 0.12, acc, -0.102, deckY(0.20) + 0.020, 0.20));
  model.add(box(0.004, 0.008, 0.12, acc, 0.102, deckY(0.20) + 0.020, 0.20));

  // 3 сопла с emissive-дисками на корме
  for (const x of [-0.095, 0, 0.095]) {
    model.add(cylZ(0.030, 0.034, 0.020, 10, Mat.impDeep(), x, 0.02 - 0.08, hz - 0.011));
    model.add(cylZ(0.024, 0.024, 0.007, 10, ENG.imperial(), x, 0.02 - 0.08, hz - 0.0045));
  }
  // тёмная посадочная полоса по центральной оси
  model.add(box(0.030, 0.004, 0.30, Mat.isdDark(), 0, deckY(-0.16) + 0.003, -0.16));
  // поля гриблов: носовой и кормовой участки палубы
  greebleField(model, { x0: -0.10, x1: 0.10, z0: -0.34, z1: -0.02, nx: 5, nz: 8, yFn: deckY, seed: 0x51D3, mat: Mat.isdDark(), mat2: Mat.impDeep(), sMin: 0.012, sMax: 0.034, skip: 0.2, jx: 0.012, jz: 0.014 });
  greebleField(model, { x0: -0.10, x1: 0.10, z0: 0.385, z1: 0.415, nx: 4, nz: 2, yFn: deckY, seed: 0x51D4, mat: Mat.isdDark(), sMin: 0.014, sMax: 0.03, skip: 0.25, jx: 0.01 });
  // ангарные ниши на бортах кормы
  model.add(box(0.006, 0.020, 0.09, Mat.impDeep(), -0.223, -0.005, 0.26));
  model.add(box(0.006, 0.020, 0.09, Mat.impDeep(), 0.223, -0.005, 0.26));
  return g;
}

// 2. tie_fighter: две шестигранные панели-крыла с рамкой и спицами, балки,
//    кабина-шар с текстурой + окно + rim-torus + подбородные пушки.
function buildTieFighter(team) {
  const Fp = SHIP3D_FOOTPRINT.tie_fighter;
  const rPanel = Math.min(Fp.z / 2 - 0.002, 0.248);
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);

  // кабина-шар с текстурой панелей
  g.add(sph(0.155, Mat.tieBall(), 0, 0, 0.012));
  // окно: сегмент тёмного стекла + тёмный rim-torus
  g.add(sph(0.072, makeGlassMaterial(), 0, 0.02, -0.118, 1, 0.82, 0.6));
  g.add(torus(0.078, 0.009, Mat.tieDark(), 0, 0.02, -0.132, 20));
  // командное кольцо-акцент по экватору
  const ring = torus(0.158, 0.008, acc, 0, 0, 0.012, 28);
  ring.rotation.x = Math.PI / 2;
  g.add(ring);
  // верхний люк
  g.add(cylY(0.052, 0.060, 0.022, 12, Mat.tieDark(), 0, 0.148, 0.012));
  // подбородные пушки
  for (const s of [-1, 1]) {
    const gun = cylZ(0.007, 0.009, 0.09, 6, Mat.impDeep(), s * 0.042, -0.115, -0.135);
    gun.rotation.x = 0.25;
    g.add(gun);
    g.add(cylZ(0.009, 0.009, 0.010, 6, Mat.tieDark(), s * 0.053, -0.124, -0.176));
  }
  // панели-крылья
  for (const s of [-1, 1]) {
    // балки к кабине: главный пилон + две тяги
    g.add(box(0.105, 0.048, 0.070, Mat.tieDark(), s * 0.205, 0, 0));
    g.add(box(0.09, 0.018, 0.018, Mat.tieDark(), s * 0.205, 0.052, 0));
    g.add(box(0.09, 0.018, 0.018, Mat.tieDark(), s * 0.205, -0.052, 0));
    // панель: тёмная рамка + светлая обшивка
    g.add(hexPlate(rPanel, 0.012, Mat.tieDark(), s * 0.268, 0, 0));
    g.add(hexPlate(rPanel - 0.020, 0.016, Mat.tieHull(), s * 0.270, 0, 0));
    // радиальные спицы (6 шт., от ступицы к вершинам)
    for (let k = 0; k < 6; k++) {
      const phi = -Math.PI / 2 + k * Math.PI / 3;
      const spoke = box(0.010, rPanel - 0.024, 0.008, Mat.tieDark(),
        s * 0.279, Math.cos(phi) * (rPanel - 0.024) / 2, Math.sin(phi) * (rPanel - 0.024) / 2);
      spoke.rotation.x = phi;
      g.add(spoke);
    }
    // акцентное кольцо + тёмная ступица
    g.add(hexPlate(0.070, 0.006, acc, s * 0.280, 0, 0));
    g.add(hexPlate(0.048, 0.008, Mat.tieDark(), s * 0.284, 0, 0));
  }
  return g;
}

// 3. tie_advanced_x1: изогнутые панели ниже и шире, светлая кабина с тёмными
//    панелями, спаренные пушки снизу, 2 кормовых сопла.
function buildTieAdvanced(team) {
  const Fp = SHIP3D_FOOTPRINT.tie_advanced_x1;
  const hx = Fp.x / 2, hz = Fp.z / 2;
  const R = hx;                      // радиус изгиба панели
  const halfArc = Math.asin(Math.min(0.95, (hz - 0.015) / R));
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);

  // кабина: светлая обшивка + окно + кольцо
  g.add(sph(0.170, Mat.tieAdvHull(), 0, 0, 0.02));
  g.add(sph(0.085, makeGlassMaterial(), 0, 0.022, -0.128, 1, 0.8, 0.62));
  g.add(torus(0.092, 0.010, Mat.tieDark(), 0, 0.022, -0.144, 22));
  const ring = torus(0.173, 0.008, acc, 0, 0, 0.02, 28);
  ring.rotation.x = Math.PI / 2;
  g.add(ring);
  g.add(cylY(0.056, 0.065, 0.024, 12, Mat.tieDark(), 0, 0.158, 0.02));
  // кормовые сопла
  for (const s of [-1, 1]) {
    g.add(cylZ(0.030, 0.030, 0.010, 10, ENG.imperial(), s * 0.072, 0.01, 0.176));
  }
  // спаренные пушки снизу
  for (const s of [-1, 1]) {
    const gun = cylZ(0.009, 0.011, 0.15, 6, Mat.impDeep(), s * 0.058, -0.125, -0.15);
    gun.rotation.x = 0.22;
    g.add(gun);
    g.add(cylZ(0.011, 0.011, 0.012, 6, Mat.tieDark(), s * 0.072, -0.136, -0.218));
  }
  // изогнутые панели-крылья: открытый сегмент цилиндра (ось вертикальна)
  const shellGeo = new THREE.CylinderGeometry(R, R, 0.56, 18, 1, true, Math.PI / 2 - halfArc, halfArc * 2);
  for (const s of [-1, 1]) {
    const shell = mesh(shellGeo, Mat.tieAdvHull(), 0, 0, 0);
    if (s === -1) shell.rotation.y = Math.PI;
    g.add(shell);
    // рёбра-стойки по краям панели
    for (const e of [-1, 1]) {
      const alpha = Math.PI / 2 + e * halfArc;
      const ex = s * R * Math.sin(alpha), ez = R * Math.cos(alpha);
      const post = box(0.020, 0.575, 0.026, Mat.tieDark(), ex, 0, ez);
      post.rotation.y = s * e * halfArc;
      g.add(post);
    }
    // акцент-плашка на выпуклой стороне
    g.add(box(0.006, 0.04, 0.09, acc, s * (hx - 0.003), 0.05, 0));
    // балки к кабине (пара, со смещением вперёд/назад)
    const stA = box(0.11, 0.028, 0.028, Mat.tieDark(), s * 0.205, 0, 0.145);
    stA.rotation.y = -s * 0.46;
    const stB = box(0.11, 0.028, 0.028, Mat.tieDark(), s * 0.205, 0, -0.145);
    stB.rotation.y = s * 0.46;
    g.add(stA); g.add(stB);
  }
  return g;
}

// 4. xwing_t65: фюзеляж LatheGeometry, 4 S-foil крыла, 4 двигателя с соплами,
//    4 ствола на законцовках, астромех, фонарь, красные канонические полосы.
function buildXWing(team) {
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);
  const red = Mat.xwRed();

  // фюзеляж: нос-конус, сужение, горб кабины, мотоблок
  g.add(latheZ([
    [0.001, -0.375], [0.020, -0.345], [0.031, -0.29], [0.033, -0.20],
    [0.029, -0.11], [0.031, -0.05], [0.042, 0.01], [0.047, 0.07],
    [0.040, 0.15], [0.038, 0.22], [0.049, 0.30], [0.051, 0.35], [0.044, 0.375]
  ], 14, Mat.xwHull()));
  // фонарь (стекло + рамки)
  g.add(sph(0.031, makeGlassMaterial(), 0, 0.047, -0.105, 1.0, 0.78, 2.1));
  g.add(box(0.054, 0.006, 0.010, Mat.impDeep(), 0, 0.066, -0.13));
  g.add(box(0.054, 0.006, 0.010, Mat.impDeep(), 0, 0.066, -0.08));
  // астромех-полусфера с линзой
  g.add(sph(0.019, Mat.r2Blue(), 0, 0.048, 0.01));
  g.add(cylY(0.006, 0.006, 0.004, 8, Mat.impDeep(), 0, 0.065, 0.01));
  // канонические красные полосы на носу + акцент команды на хребте
  for (const s of [-1, 1]) {
    const st = box(0.016, 0.003, 0.16, red, s * 0.010, 0.0305, -0.25);
    st.rotation.z = s * 0.35;
    g.add(st);
  }
  g.add(box(0.014, 0.004, 0.10, acc, 0, 0.041, 0.14));
  g.add(box(0.014, 0.004, 0.10, acc, 0, 0.048, 0.28));

  // 4 крыла в X-раскладке
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
    const upper = sy > 0;
    const w = new THREE.Group();
    w.position.set(sx * 0.045, sy * 0.035, 0.12);
    w.rotation.z = sx * sy * (upper ? 0.35 : -0.30);
    w.add(rbox(0.28, 0.011, 0.10, Mat.xwHull(), sx * 0.17, 0, 0));
    w.add(box(0.05, 0.003, 0.07, red, sx * 0.26, 0.008, 0));     // красная полоса
    w.add(box(0.03, 0.004, 0.03, acc, sx * 0.10, 0.008, 0.02));  // командный акцент
    // двигатель у корня крыла + emissive сопло
    w.add(cylZ(0.024, 0.027, 0.11, 10, Mat.xwHull(), sx * 0.075, 0.002, 0.045));
    w.add(cylZ(0.020, 0.020, 0.014, 10, Mat.impDeep(), sx * 0.075, 0.002, 0.105));
    w.add(cylZ(0.015, 0.015, 0.010, 10, ENG.orange(), sx * 0.075, 0.002, 0.112));
    // ствол на законцовке
    w.add(cylZ(0.007, 0.009, 0.34, 6, Mat.impDeep(), sx * 0.305, 0, -0.20));
    w.add(cylZ(0.009, 0.009, 0.014, 6, Mat.impDeep(), sx * 0.305, 0, -0.355));
    g.add(w);
  }
  return g;
}

// 5. eta2_actis: плоское дельта-крыло (Extrude с bevel), пузырь кабины,
//    астромех, 2 сопла сзади, тонкие пушки на консолях.
function buildEta2(team) {
  const g = new THREE.Group();
  const model = new THREE.Group();
  model.position.y = -0.02;
  g.add(model);
  const acc = makeAccentMaterial(team);

  // дельта-корпус: узкий нос, стреловидные кромки, усечённая корма
  model.add(extrudeFlat([
    [0, 0.28], [0.25, -0.13], [0.23, -0.282], [0, -0.246],
    [-0.23, -0.282], [-0.25, -0.13]
  ], 0.05, 0.02, Mat.etaHull()));
  // пузырь кабины + тёмный обод
  model.add(sph(0.075, makeGlassMaterial(), 0, 0.052, -0.07, 0.85, 0.72, 1.2));
  const rim = torus(0.076, 0.006, Mat.impDeep(), 0, 0.042, -0.07, 20);
  rim.rotation.x = Math.PI / 2;
  model.add(rim);
  // астромех за кабиной
  model.add(sph(0.034, Mat.r2Blue(), 0, 0.040, 0.045));
  model.add(cylY(0.008, 0.008, 0.005, 8, Mat.impDeep(), 0, 0.070, 0.045));
  // акцентные полосы на крыльях
  model.add(box(0.05, 0.004, 0.09, acc, -0.14, 0.045, 0.03));
  model.add(box(0.05, 0.004, 0.09, acc, 0.14, 0.045, 0.03));
  // 2 сопла сзади
  for (const s of [-1, 1]) {
    model.add(cylZ(0.030, 0.034, 0.056, 10, Mat.impDeep(), s * 0.085, 0, 0.272));
    model.add(cylZ(0.024, 0.024, 0.008, 10, ENG.pale(), s * 0.085, 0, 0.296));
  }
  // тонкие пушки под консолями
  for (const s of [-1, 1]) {
    model.add(cylZ(0.006, 0.008, 0.24, 6, Mat.impDeep(), s * 0.24, -0.05, 0.10));
  }
  return g;
}

// 6. millennium_falcon: диск с радиальными панелями, челюсти, кабина-труба,
//    сенсорная тарелка, центральный жёлоб, 3+2 сопел, гриблы на палубе.
function buildFalcon(team) {
  const Fp = SHIP3D_FOOTPRINT.millennium_falcon;
  const g = new THREE.Group();
  const model = new THREE.Group();
  model.position.y = -0.03;
  g.add(model);
  const acc = makeAccentMaterial(team);

  // диск (низкий цилиндр) с радиальной текстурой на кэпах
  const discGeo = new THREE.CylinderGeometry(0.30, 0.305, 0.075, 40);
  model.add(mesh(discGeo, [Mat.falDark(), Mat.falHull(), Mat.falHull()], 0, 0, 0.05));
  // центральный жёлоб (тёмная вставка сверху и снизу)
  model.add(box(0.585, 0.012, 0.05, Mat.falDark(), 0, 0.0385, 0.05));
  model.add(box(0.585, 0.012, 0.05, Mat.falDark(), 0, -0.0385, 0.05));
  // две «челюсти» спереди
  for (const s of [-1, 1]) {
    model.add(rbox(0.10, 0.075, 0.34, Mat.falFlat(), s * 0.115, 0, -0.26));
    model.add(box(0.102, 0.077, 0.012, Mat.falDark(), s * 0.115, 0, -0.424));
    model.add(box(0.004, 0.030, 0.10, acc, s * 0.1665, 0, -0.33));
  }
  // посадочный пандус в развале челюстей
  model.add(box(0.07, 0.05, 0.05, Mat.falDark(), 0, -0.01, -0.30));
  // кабина-труба справа-спереди + стеклянный колпак
  const cock = new THREE.Group();
  cock.position.set(0.215, 0.052, -0.155);
  cock.rotation.y = -0.55;
  cock.add(cylZ(0.042, 0.047, 0.15, 12, Mat.falFlat(), 0, 0, 0.01));
  cock.add(sph(0.042, makeGlassMaterial(), 0, 0.004, -0.062, 1, 0.72, 0.9));
  cock.add(torus(0.043, 0.007, Mat.falDark(), 0, 0.004, -0.033, 20));
  model.add(cock);
  // сенсорная тарелка сверху-сзади
  model.add(cylY(0.006, 0.008, 0.030, 6, Mat.falDark(), -0.135, 0.052, 0.235));
  model.add(cylY(0.034, 0.008, 0.016, 12, Mat.falDark(), -0.135, 0.075, 0.235));
  model.add(cylY(0.0025, 0.0025, 0.05, 4, Mat.falDark(), -0.135, 0.105, 0.235));
  // полоса сопел сзади: 3 главных + 2 малых
  const mainX = [-0.105, 0, 0.105];
  for (let i = 0; i < 3; i++) {
    const y = i === 1 ? 0 : 0.012;
    const z = i === 1 ? 0.372 : 0.362;
    model.add(cylZ(0.045, 0.050, 0.05, 12, Mat.falDark(), mainX[i], y, z));
    model.add(cylZ(0.036, 0.036, 0.010, 12, ENG.pale(), mainX[i], y, z + 0.028));
  }
  for (const s of [-1, 1]) {
    model.add(cylZ(0.026, 0.026, 0.012, 10, ENG.pale(), s * 0.052, -0.020, 0.348));
  }
  // гриблы на верхней палубе (обходя жёлоб, кабину и тарелку)
  greebleField(model, { x0: -0.24, x1: -0.06, z0: -0.14, z1: 0.30, nx: 4, nz: 8, y: 0.038, seed: 0xFA1C, mat: Mat.falDark(), mat2: Mat.falFlat(), sMin: 0.014, sMax: 0.040, skip: 0.2, jx: 0.014, jz: 0.016, avoid: [{ x: -0.135, z: 0.235, r: 0.05 }] });
  greebleField(model, { x0: 0.04, x1: 0.24, z0: -0.16, z1: 0.26, nx: 4, nz: 8, y: 0.038, seed: 0xFA1D, mat: Mat.falDark(), mat2: Mat.falFlat(), sMin: 0.014, sMax: 0.040, skip: 0.2, jx: 0.014, jz: 0.016, avoid: [{ x: 0.215, z: -0.155, r: 0.07 }] });
  // мелкие акценты
  model.add(box(0.03, 0.004, 0.02, acc, 0.10, 0.040, 0.12));
  model.add(box(0.03, 0.004, 0.02, acc, -0.18, 0.040, -0.02));
  return g;
}

// 7. death_star_1: панельная сфера с экваториальной траншеей, вогнутая тарелка
//    суперлазера с 8 рёбрами и зелёным фокусом, гриблы и окна по поверхности.
function buildDeathStar(team) {
  const Fp = SHIP3D_FOOTPRINT.death_star_1;
  const R = Fp.x / 2 - 0.003; // небольшой запас под траншею/гриблы — габарит = Fp
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);
  const n = new THREE.Vector3(0, 0.42, -1).normalize();

  // сфера с текстурой панелей
  g.add(mesh(new THREE.SphereGeometry(R, 40, 28), Mat.dsHull(), 0, 0, 0));
  // экваториальная траншея
  g.add(mesh(new THREE.CylinderGeometry(R + 0.002, R + 0.002, 0.030, 48, 1, true), Mat.dsDark(), 0, 0, 0));

  // тарелка суперлазера: вогнутый профиль (LatheGeometry), открыта наружу
  const dish = new THREE.Group();
  dish.position.copy(n).multiplyScalar(R + 0.008);
  dish.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), n.clone().negate());
  const bowlPts = [[0.055, 0], [0.040, 0.013], [0.025, 0.022], [0.010, 0.027], [0.0, 0.030]];
  dish.add(mesh(new THREE.LatheGeometry(bowlPts.map((p) => new THREE.Vector2(p[0], p[1])), 20), Mat.dsDark(), 0, 0, 0));
  // монтажное кольцо по кромке
  const mount = torus(0.052, 0.008, Mat.dsDark(), 0, 0.004, 0, 28);
  mount.rotation.x = Math.PI / 2;
  dish.add(mount);
  // 8 рёбер-трейллис от кромки к фокусу
  for (let k = 0; k < 8; k++) {
    const ribG = new THREE.Group();
    ribG.rotation.y = k * Math.PI / 4;
    const rib = box(0.005, 0.060, 0.005, Mat.impDeep(), 0.0278, 0.014, 0);
    rib.rotation.z = 1.072;
    ribG.add(rib);
    dish.add(ribG);
  }
  // зелёный emissive-фокус
  const lens = mesh(new THREE.CircleGeometry(0.018, 16), ENG.laser(), 0, 0.031, 0);
  lens.rotation.x = Math.PI / 2;
  dish.add(lens);
  dish.add(sph(0.010, ENG.laser(), 0, 0.026, 0));
  g.add(dish);

  // окна-стёкла в траншее
  for (const a of [-1.2, -0.6, 0.6, 1.2, 2.4, -2.4]) {
    const w = box(0.012, 0.010, 0.006, makeGlassMaterial(), Math.sin(a) * (R + 0.002), 0, Math.cos(a) * (R + 0.002));
    w.rotation.y = a;
    g.add(w);
  }
  // гриблы по поверхности (равномерная сфера, обходя тарелку и траншею)
  const rnd = mulberry32(0xD347);
  const added = [];
  let guard = 0;
  while (added.length < 46 && guard++ < 400) {
    const lat = Math.asin(2 * rnd() - 1), lon = rnd() * Math.PI * 2;
    const dir = new THREE.Vector3(Math.cos(lat) * Math.sin(lon), Math.sin(lat), Math.cos(lat) * Math.cos(lon));
    if (dir.dot(n) > 0.90) continue;                 // зона тарелки
    if (Math.abs(lat) < 0.14) continue;              // траншея
    const s = 0.006 + rnd() * 0.010;
    const m = box(s, s, 0.005, rnd() < 0.5 ? Mat.dsDark() : Mat.impDeep(), 0, 0, 0);
    m.position.copy(dir).multiplyScalar(R - 0.005);
    m.lookAt(m.position.clone().multiplyScalar(2));
    g.add(m);
    added.push(1);
  }
  // командные огни-акценты в траншее
  for (const a of [0.3, 1.5, -0.9, 2.8]) {
    g.add(box(0.010, 0.006, 0.008, acc, Math.sin(a) * (R + 0.0015), 0.006, Math.cos(a) * (R + 0.0015)));
  }
  return g;
}

// 8. slave_1: плоский вытянутый корпус (Extrude скруглённый контур), широкая
//    платформа, спаренные носовые пушки, высокий кормовой блок с 2 соплами,
//    кабина-фонарь, серебристые панели на бордово-коричневой обшивке.
function buildSlave1(team) {
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);
  const shape = new THREE.Shape();
  shape.moveTo(0, 0.37);
  shape.quadraticCurveTo(0.10, 0.35, 0.112, 0.235);
  shape.lineTo(0.132, -0.19);
  shape.quadraticCurveTo(0.138, -0.345, 0, -0.362);
  shape.quadraticCurveTo(-0.138, -0.345, -0.132, -0.19);
  shape.lineTo(-0.112, 0.235);
  shape.quadraticCurveTo(-0.10, 0.35, 0, 0.37);
  g.add(extrudeShape(shape, 0.055, 0.016, Mat.slHull()));

  // широкая платформа-крыло с серебристыми вставками
  g.add(rbox(0.60, 0.022, 0.30, Mat.slHull(), 0, 0, 0.02));
  g.add(box(0.15, 0.004, 0.20, Mat.slSilver(), -0.175, 0.011, 0.02));
  g.add(box(0.15, 0.004, 0.20, Mat.slSilver(), 0.175, 0.011, 0.02));
  g.add(box(0.18, 0.004, 0.016, acc, 0, 0.012, -0.128));
  // спаренные носовые пушки
  for (const s of [-1, 1]) {
    g.add(cylZ(0.013, 0.015, 0.30, 8, Mat.impDeep(), s * 0.048, -0.042, -0.235));
    g.add(cylZ(0.015, 0.015, 0.012, 8, Mat.slSilver(), s * 0.048, -0.042, -0.376));
  }
  // кабина-фонарь спереди сверху
  g.add(sph(0.046, makeGlassMaterial(), 0, 0.052, -0.195, 0.85, 0.6, 1.5));
  const rim = torus(0.047, 0.006, Mat.slSilver(), 0, 0.042, -0.195, 18);
  rim.rotation.x = Math.PI / 2;
  g.add(rim);
  // высокий кормовой двигательный блок с 2 соплами
  g.add(box(0.17, 0.10, 0.11, Mat.slHull(), 0, 0.015, 0.305));
  for (const s of [-1, 1]) {
    g.add(cylZ(0.032, 0.036, 0.024, 10, Mat.impDeep(), s * 0.048, 0.015, 0.372));
    g.add(cylZ(0.026, 0.026, 0.008, 10, ENG.pale(), s * 0.048, 0.015, 0.383));
    g.add(box(0.004, 0.03, 0.06, acc, s * 0.087, 0.015, 0.30));
  }
  // серебристый хребет и бортовые панели
  g.add(box(0.03, 0.012, 0.34, Mat.slSilver(), 0, 0.048, 0.03));
  g.add(box(0.004, 0.026, 0.16, Mat.slSilver(), -0.1475, 0, -0.02));
  g.add(box(0.004, 0.026, 0.16, Mat.slSilver(), 0.1475, 0, -0.02));
  // посадочные лыжи
  g.add(rbox(0.018, 0.035, 0.10, Mat.impDeep(), -0.095, -0.055, 0.12));
  g.add(rbox(0.018, 0.035, 0.10, Mat.impDeep(), 0.095, -0.055, 0.12));
  return g;
}

// 9. ghost: крупный «кирпич» + скошенная носовая кабина с широкой полосой
//    стекла, челюсти-пилоны, верхняя турель, оранжевые полосы, 2 двигателя.
function buildGhost(team) {
  const Fp = SHIP3D_FOOTPRINT.ghost;
  const hz = Fp.z / 2;
  const g = new THREE.Group();
  const acc = makeAccentMaterial(team);
  const orange = Mat.ghOrange();

  // основной корпус
  g.add(rbox(0.30, 0.155, 0.56, Mat.ghHull(), 0, 0, 0.12));
  // скошенная носовая секция (tapered box)
  const noseGeo = new THREE.CylinderGeometry(0.125, 0.185, 0.24, 4, 1);
  noseGeo.rotateY(Math.PI / 4);
  noseGeo.rotateX(-Math.PI / 2);
  const nose = mesh(noseGeo, Mat.ghNose(), 0, 0.002, -0.27);
  nose.scale.y = 0.62;
  g.add(nose);
  // надстройка кабины + широкая полоса стекла
  g.add(rbox(0.17, 0.045, 0.12, Mat.ghHull(), 0, 0.088, -0.28));
  g.add(box(0.145, 0.034, 0.014, makeGlassMaterial(), 0, 0.090, -0.338));
  g.add(box(0.16, 0.006, 0.016, Mat.ghDark(), 0, 0.110, -0.337));
  // передние челюсти-пилоны
  for (const s of [-1, 1]) {
    g.add(rbox(0.055, 0.05, 0.20, Mat.ghDark(), s * 0.115, -0.015, -0.30));
    g.add(box(0.057, 0.052, 0.012, Mat.impDeep(), s * 0.115, -0.015, -0.394));
  }
  // верхняя турель: основание + траверса + 2 ствола
  g.add(cylY(0.042, 0.048, 0.022, 12, Mat.ghDark(), 0, 0.088, 0.02));
  g.add(box(0.12, 0.013, 0.018, Mat.ghDark(), 0, 0.105, 0.02));
  for (const s of [-1, 1]) {
    g.add(cylZ(0.006, 0.007, 0.085, 6, Mat.impDeep(), s * 0.042, 0.105, -0.028));
  }
  // оранжевые канонические полосы + командные акценты
  g.add(box(0.006, 0.045, 0.38, orange, -0.152, 0.005, 0.14));
  g.add(box(0.006, 0.045, 0.38, orange, 0.152, 0.005, 0.14));
  g.add(box(0.04, 0.004, 0.30, orange, 0, 0.0797, 0.20));
  g.add(box(0.014, 0.006, 0.05, acc, -0.05, 0.0805, -0.06));
  g.add(box(0.014, 0.006, 0.05, acc, 0.05, 0.0805, -0.06));
  // 2 двигателя сзади + emissive сопла
  for (const s of [-1, 1]) {
    g.add(rbox(0.095, 0.095, 0.08, Mat.ghDark(), s * 0.075, 0, hz - 0.04));
    g.add(cylZ(0.034, 0.034, 0.010, 10, ENG.pale(), s * 0.075, 0, hz - 0.0055));
  }
  // гриблы на палубе
  greebleField(g, { x0: -0.12, x1: 0.12, z0: 0.26, z1: 0.38, nx: 4, nz: 3, y: 0.078, seed: 0x68057, mat: Mat.ghDark(), sMin: 0.012, sMax: 0.03, skip: 0.3, jx: 0.015, jz: 0.02, avoid: [{ x: -0.075, z: hz - 0.04, r: 0.06 }, { x: 0.075, z: hz - 0.04, r: 0.06 }] });
  // посадочные лыжи
  g.add(rbox(0.022, 0.045, 0.16, Mat.impDeep(), -0.105, -0.098, 0.12));
  g.add(rbox(0.022, 0.045, 0.16, Mat.impDeep(), 0.105, -0.098, 0.12));
  return g;
}

// 10. phantom: маленький челнок — скруглённый корпус, каплевидный нос, плоские
//     крылья, киль, 2 сопла, фонарь.
function buildPhantom(team) {
  const g = new THREE.Group();
  const model = new THREE.Group();
  model.position.y = -0.01;
  g.add(model);
  const acc = makeAccentMaterial(team);

  model.add(rbox(0.15, 0.105, 0.30, Mat.phHull(), 0, 0, 0.03));
  // каплевидный нос (сплюснутая полусфера)
  model.add(sph(0.075, Mat.phHull(), 0, 0, -0.12, 1, 0.72, 1.15));
  // фонарь + тёмный обод
  model.add(sph(0.046, makeGlassMaterial(), 0, 0.052, -0.045, 0.85, 0.68, 1.5));
  const rim = torus(0.047, 0.005, Mat.ghDark(), 0, 0.042, -0.045, 18);
  rim.rotation.x = Math.PI / 2;
  model.add(rim);
  // плоские крылья со скосом + законцовочные обтекатели
  for (const s of [-1, 1]) {
    const w = rbox(0.19, 0.014, 0.16, Mat.phHull(), s * 0.155, -0.008, 0.06);
    w.rotation.y = -s * 0.22;
    model.add(w);
    model.add(cylY(0.017, 0.019, 0.030, 8, Mat.phHull(), s * 0.245, -0.008, 0.081));
    model.add(box(0.05, 0.004, 0.06, acc, s * 0.16, -0.001, 0.03));
  }
  // киль
  const fin = box(0.012, 0.055, 0.10, Mat.phHull(), 0, 0.078, 0.115);
  fin.rotation.x = -0.25;
  model.add(fin);
  // 2 сопла
  for (const s of [-1, 1]) {
    model.add(rbox(0.052, 0.052, 0.06, Mat.ghDark(), s * 0.055, 0, 0.18));
    model.add(cylZ(0.021, 0.021, 0.008, 10, ENG.pale(), s * 0.055, 0, 0.207));
  }
  // гриблы-плашки на палубе
  greebleField(model, { x0: -0.05, x1: 0.05, z0: 0.02, z1: 0.15, nx: 2, nz: 4, y: 0.0535, seed: 0x0F40, mat: Mat.ghDark(), sMin: 0.010, sMax: 0.022, skip: 0.3, jz: 0.01 });
  // посадочные лыжи
  model.add(rbox(0.016, 0.035, 0.09, Mat.impDeep(), -0.055, -0.068, 0.06));
  model.add(rbox(0.016, 0.035, 0.09, Mat.impDeep(), 0.055, -0.068, 0.06));
  return g;
}

// 11. vulture_droid: сферический корпус с текстурой, лицевая пластина с
//     светящимися глазами, сложенные крылья-манипуляторы с когтями, антенна.
function buildVulture(team) {
  const g = new THREE.Group();
  const model = new THREE.Group();
  model.position.y = -0.05;
  g.add(model);
  const acc = makeAccentMaterial(team);

  // корпус-сфера с текстурой панелей
  model.add(sph(0.135, Mat.vuHull(), 0, 0.02, -0.03));
  // лицевая пластина + светящиеся глаза-акценты + сенсорное стекло
  model.add(cylZ(0.078, 0.088, 0.035, 14, Mat.vuDark(), 0, 0.035, -0.145));
  for (const s of [-1, 1]) {
    const eye = cylZ(0.017, 0.017, 0.012, 10, acc, s * 0.033, 0.052, -0.160);
    eye.rotation.x = -0.12;
    model.add(eye);
  }
  model.add(box(0.05, 0.008, 0.012, makeGlassMaterial(), 0, 0.02, -0.163));
  // подбородочная пушка
  const chin = cylZ(0.012, 0.014, 0.10, 8, Mat.vuDark(), 0, -0.075, -0.12);
  chin.rotation.x = 0.35;
  model.add(chin);
  // антенна сверху
  model.add(cylY(0.0028, 0.0028, 0.085, 4, Mat.vuDark(), 0, 0.19, 0.03));
  model.add(sph(0.006, acc, 0, 0.235, 0.03));
  // 2 сложенных крыла-манипулятора: плечо -> звено -> локоть -> звено -> коготь
  for (const s of [-1, 1]) {
    model.add(sph(0.046, Mat.vuDark(), s * 0.100, 0.02, 0.02));
    const arm = new THREE.Group();
    arm.position.set(s * 0.100, 0.02, 0.02);
    arm.rotation.y = s * 0.75;
    arm.rotation.z = -s * 0.55;
    arm.add(rbox(0.09, 0.016, 0.075, Mat.vuHull(), s * 0.050, 0, 0));
    arm.add(sph(0.028, Mat.vuDark(), s * 0.090, 0, 0));
    arm.add(rbox(0.075, 0.012, 0.055, Mat.vuHull(), s * 0.130, 0, 0.004));
    arm.add(box(0.045, 0.005, 0.026, acc, s * 0.130, 0.009, 0.004));
    const claw = mesh(new THREE.ConeGeometry(0.024, 0.065, 6), Mat.vuHull(), s * 0.160, 0, 0.004);
    claw.rotation.z = -s * Math.PI / 2;
    arm.add(claw);
    const fang = mesh(new THREE.ConeGeometry(0.013, 0.045, 6), Mat.vuDark(), s * 0.160, -0.018, 0.018);
    fang.rotation.z = -s * (Math.PI / 2 - 0.5);
    fang.rotation.x = 0.4;
    arm.add(fang);
    model.add(arm);
  }
  // 2 кормовых двигателя с emissive-дисками
  for (const s of [-1, 1]) {
    model.add(cylZ(0.028, 0.033, 0.055, 8, Mat.vuDark(), s * 0.062, 0.01, 0.095));
    model.add(cylZ(0.022, 0.022, 0.008, 8, ENG.imperial(), s * 0.062, 0.01, 0.120));
  }
  return g;
}

// ---------- реестр билдеров ----------

const BUILDERS = {
  tie_fighter: buildTieFighter,
  tie_advanced_x1: buildTieAdvanced,
  xwing_t65: buildXWing,
  eta2_actis: buildEta2,
  millennium_falcon: buildFalcon,
  star_destroyer: buildStarDestroyer,
  death_star_1: buildDeathStar,
  slave_1: buildSlave1,
  ghost: buildGhost,
  phantom: buildPhantom,
  vulture_droid: buildVulture
};

// Воксельные модели (voxel_ships.js) подгружаются основным источником;
// процедурные билдеры ниже — фолбэк, если импорт не удался.
let voxelSource = null;
export function primeVoxelSource(mod) { voxelSource = mod; }

// ---------- Внешние модели (GLB/GLTF) ----------
// Импортёр из мастер-плана: постройка из Minecraft -> Mineways -> GLB ->
// demo/assets/models/<file>, подключённая в index.json (см. README там же).
// Файл кладётся только легально: своя постройка или разрешение автора.
const externalModels = new Map();   // type_id -> { scene, cfg }
let schemSource = null;
export function primeSchemSource(mod) { schemSource = mod; }

// Загрузка мешей из Minecraft-схематиков (конвейер tools/schem_to_mesh.py).
export async function loadSchemModels() {
  try {
    const mod = await import('./schem_models.js');
    const n = await mod.loadSchemModels(SHIP3D_FOOTPRINT, new Set(externalModels.keys()));
    if (n > 0) schemSource = mod;
    return n;
  } catch (e) {
    console.warn('schem-модели не загрузились:', e);
    return 0;
  }
}

export async function loadExternalModels() {
  let manifest;
  try {
    const res = await fetch('assets/models/index.json');
    if (!res.ok) return 0;
    manifest = await res.json();
  } catch { return 0; }
  const entries = Object.entries(manifest || {}).filter(([k, v]) => v && v.file && !k.startsWith('_'));
  if (!entries.length) return 0;
  const { GLTFLoader } = await import('./vendor/GLTFLoader.js');
  const loader = new GLTFLoader();
  let loaded = 0;
  await Promise.all(entries.map(async ([typeId, cfg]) => {
    try {
      const gltf = await loader.loadAsync('assets/models/' + cfg.file);
      externalModels.set(typeId, { scene: gltf.scene, cfg });
      loaded += 1;
    } catch (e) {
      console.error('Внешняя модель не загрузилась: ' + cfg.file, e);
    }
  }));
  return loaded;
}

// Приводим внешнюю модель к соглашению сцены: нос -Z (задаётся rotationY),
// габарит XZ = FOOTPRINT, центр по XZ в нуле, низ в y=0.
function prepareExternal(typeId, src, cfg) {
  const model = src.clone(true);
  if (Array.isArray(cfg.excludeNodes) && cfg.excludeNodes.length) {
    const excluded = new Set(cfg.excludeNodes);
    const remove = [];
    model.traverse((o) => { if (excluded.has(o.name)) remove.push(o); });
    remove.forEach((o) => o.removeFromParent());
  }
  const calibrated = new THREE.Group();
  calibrated.add(model);
  calibrated.rotation.order = 'XYZ';
  calibrated.rotation.set(
    THREE.MathUtils.degToRad(cfg.rotationX || 0),
    THREE.MathUtils.degToRad(cfg.rotationY || 0),
    THREE.MathUtils.degToRad(cfg.rotationZ || 0)
  );
  calibrated.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(calibrated);
  const size = box.getSize(new THREE.Vector3());
  const fp = SHIP3D_FOOTPRINT[typeId] || { x: 0.8, z: 0.8 };
  const want = Math.max(fp.x, fp.z) * (cfg.scale != null ? cfg.scale : 1);
  const s = want / Math.max(size.x, size.z, 1e-4);
  calibrated.scale.setScalar(s);
  calibrated.updateMatrixWorld(true);
  const box2 = new THREE.Box3().setFromObject(calibrated);
  const c = box2.getCenter(new THREE.Vector3());
  calibrated.position.set(
    -c.x + (cfg.offsetX || 0),
    -box2.min.y + (cfg.offsetY || 0),
    -c.z + (cfg.offsetZ || 0)
  );
  calibrated.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
  const group = new THREE.Group();
  group.add(calibrated);
  group.userData.external = {
    typeId, file: cfg.file,
    canonical: { nose: '-Z', up: '+Y', floorY: 0 }
  };
  return group;
}

// Последний общий шаг для любого источника. Процедурные, GLB, Minecraft и
// voxel-модели раньше имели разное начало координат по высоте, из-за чего
// часть флота парила, а часть проваливалась в плиту. Теперь сцена всегда
// получает один контракт: центр XZ находится в (0,0), нижняя точка — на y=0.
function floorModel(group, typeId, source) {
  if (!group) return group;
  group.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(group);
  const wrapper = new THREE.Group();
  if (!box.isEmpty() && Number.isFinite(box.min.y)) {
    const center = box.getCenter(new THREE.Vector3());
    group.position.x -= center.x;
    group.position.y -= box.min.y;
    group.position.z -= center.z;
  }
  wrapper.add(group);
  wrapper.updateMatrixWorld(true);
  wrapper.userData.canonical = { nose: '-Z', up: '+Y', centerXZ: [0, 0], floorY: 0 };
  wrapper.userData.modelSource = source;
  wrapper.userData.typeId = typeId;
  wrapper.userData.sourceMeta = group.userData;
  return wrapper;
}

/**
 * createShipModel(type_id, team) -> THREE.Group
 * Группа в единицах cell, нос вдоль -Z; ориентацию задаёт сцена через rotation.y.
 * Приоритет: внешняя GLB -> Minecraft mesh -> процедурная -> воксельная.
 */
export function createShipModel(type_id, team) {
  const ext = externalModels.get(type_id);
  if (ext) return floorModel(prepareExternal(type_id, ext.scene, ext.cfg), type_id, 'glb');
  if (schemSource) {
    const schemGroup = schemSource.createShipModel(type_id);
    if (schemGroup) return floorModel(schemGroup, type_id, 'minecraft'); // масштаб уже запечён
  }
  if (BUILDERS[type_id]) {
    const group = BUILDERS[type_id](team === 'B' ? 'B' : 'A');
    group.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
    return floorModel(group, type_id, 'procedural');
  }
  if (voxelSource) {
    const voxelGroup = voxelSource.createShipModel(type_id, { team });
    if (voxelGroup) {
      // Воксельная модель нормализована своим масштабом; запекаем размер под
      // соглашение сцены (геометрия в мировых единицах FOOTPRINT, центр по Y),
      // потому что board3d делает model.scale.setScalar(cell).
      const v = voxelGroup.userData.voxel;
      const fp = SHIP3D_FOOTPRINT[type_id];
      if (v && fp) {
        const maxDim = Math.max(v.dims[0], v.dims[1], v.dims[2]);
        const bake = Math.max(fp.x, fp.z) / maxDim; // геометрия -> мировые единицы FOOTPRINT
        voxelGroup.traverse((o) => {
          if (o.isMesh) {
            o.geometry.scale(bake, bake, bake);
            o.geometry.translate(0, -(v.dims[1] * bake) / 2, 0); // центр высоты, как у процедурных
          }
        });
        voxelGroup.scale.setScalar(1);
      }
      voxelGroup.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
      return floorModel(voxelGroup, type_id, 'voxel');
    }
  }
  const build = BUILDERS[type_id] || buildPhantom;
  const group = build(team === 'B' ? 'B' : 'A');
  group.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = true;
      o.receiveShadow = false;
    }
  });
  return floorModel(group, type_id, 'fallback');
}

/** Освободить кэшированные материалы/текстуры (при завершении работы со сценой). */
export function disposeModelMaterials() {
  disposeTextures();
}
