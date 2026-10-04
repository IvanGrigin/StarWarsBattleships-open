/* demo/board3d.js — настоящее 3D-поле боя на three.js (r160) для веб-демо.
 *
 * API:
 *   Board3D.init(container, opts) — создать рендерер/сцену/37 тайлов.
 *       opts: {
 *         cell        = 1.0,   // размер гекса в мировых единицах
 *         radius      = 3,     // полуразмер поля (37 гексов)
 *         onCellClick(cell|null),          // клик по тайлу (или мимо)
 *         onCellHover(cell|null),          // смена наведённой клетки
 *         onCommand(cmd),                  // {type:'RotateLeft'|'RotateRight'} — курсоры поворота
 *         shipInfo(type_id)                // опц.: {max_hp, arc[6]}; иначе SWBShips/встроенная копия
 *       }
 *   Board3D.setState(state)   — snapshot матча (тот же JSON-объект, что в main.js) или null.
 *   Board3D.setLegal(legal)   — массив legal_actions.
 *   Board3D.spawnHit(q, r, kind) — 'hit' | 'boom' в клетке (вспышка/взрыв, boom трясёт камеру).
 *   Board3D.dispose()         — освободить всё.
 *
 * Геометрия (pin):
 *   worldX = cell·√3·(q + r/2); worldZ = cell·1.5·r; Y — вверх; X — восток; Z — юг.
 *   Направления 0..5 по часовой; мировое направление соседа f = нормализованный вектор
 *   (√3·(dq + dr/2), 1.5·dr) из DIR_DELTAS (f0 = северо-запад, экранно «вверх-влево»).
 *   Корабль: nose вдоль -Z; group.rotation.y = (30 − 60·facing)·π/180.
 *   Камера: elevation 65°, позиция = центр + (0, sin65·D, cos65·D).
 *
 * DOM-оверлей (pointer-events:none): HP-пипсы + сид над кораблём; у выбранного корабля —
 * 6 чисел флангов на рёбрах гекса; у врагов в дистанции ≤3 — кольцо и бейдж бонуса атаки.
 */
import * as THREE from 'three';
import { createShipModel } from './models3d.js';
import { DIR_DELTAS, SQRT3, axialToWorld, directionOffset, facingRotY } from './orientation.js';
const ELEV_MIN = 10, ELEV_MAX = 85;      // диапазон угла камеры, градусы
let elevDeg = 65;                        // текущий угол (изменяется слайдером)
try {
  const saved = Number(localStorage.getItem('swb_elev'));
  if (saved >= ELEV_MIN && saved <= ELEV_MAX) elevDeg = saved;
} catch (e) {}
let ELEV = elevDeg * Math.PI / 180;

// Минимальная копия data/rulesets/v3/ships/*.json (max_hp + arc) — только для оверлея,
// когда недоступны opts.shipInfo и window.SWBShips.
const FALLBACK_DB = {
  tie_fighter:       { max_hp: 4,  arc: [2, 1, 0, 0, 0, 1] },
  tie_advanced_x1:   { max_hp: 6,  arc: [3, 1, 1, 0, 1, 1] },
  xwing_t65:         { max_hp: 4,  arc: [2, 1, 0, 1, 0, 1] },
  eta2_actis:        { max_hp: 5,  arc: [2, 1, 1, 0, 1, 1] },
  millennium_falcon: { max_hp: 8,  arc: [2, 1, 2, 0, 2, 1] },
  star_destroyer:    { max_hp: 8,  arc: [2, 2, 1, 1, 1, 2] },
  death_star_1:      { max_hp: 11, arc: [7, 0, 0, -1, 0, 0] },
  slave_1:           { max_hp: 6,  arc: [3, 1, 0, 2, 0, 1] },
  ghost:             { max_hp: 6,  arc: [2, 1, 0, 2, 0, 1] },
  phantom:           { max_hp: 2,  arc: [2, 1, 0, -1, 0, 1] },
  vulture_droid:     { max_hp: 4,  arc: [1, 1, 1, 0, 1, 1] }
};

// Высота подписи над моделью (в единицах cell) — под высокие модели больше.
const LABEL_Y = { death_star_1: 1.55, star_destroyer: 0.85, ghost: 0.7 };
// Все источники моделей нормализуются к floorY=0 в models3d.js. Поэтому
// посадка одинакова для каждого корабля: чуть выше верхней плоскости гекса.
const SHIP_CLEARANCE = 0.06;

export const Board3D = (() => {
  // ---- состояние сцены (синглтон) ----
  let container = null, opts = {};
  let renderer = null, scene = null, camera = null;
  let overlay = null;
  let cell = 1, radius = 3;
  let tiles = [];                 // пикаемые тайлы (userData.s3dCell)
  let shipLayer = null, hlLayer = null, fxLayer = null, ctrlLayer = null;
  let state = null, legal = [], dirty = false;
  let ships = new Map();          // id -> entry
  let hoverCell = null;
  let rafId = 0, prevT = 0, disposed = false;
  let resizeObs = null;
  let distBase = 16, distScale = 1, azimuth = 0;
  let shakeT0 = -1;
  let effects = [];
  let arrow = null, cursorL = null, cursorR = null, activeRing = null;
  let selectedFlankId = null;
  let flankWrap = null;
  const enemyDeco = new Map();    // id -> {ring, badge}

  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const tmpV = new THREE.Vector3();
  let downInfo = null;            // {x, y, button, moved}

  // Общие ассеты подсветок (геометрии/материалы не пересоздаются при rebuild).
  const A = {};

  // ---------- геометрия (pin) ----------

  function cellToWorld(q, r) {
    return axialToWorld(q, r, cell);
  }
  // Полное смещение к соседу f (DIR_DELTAS), масштаб k (0.5 = середина ребра).
  function dirOffset(f, k) {
    return directionOffset(f, cell, k);
  }
  function worldAngle(x, z) { return Math.atan2(z, x); }
  function hexDistance(aq, ar, bq, br) {
    const dq = aq - bq, dr = ar - br;
    return (Math.abs(dq) + Math.abs(dr) + Math.abs(-dq - dr)) / 2;
  }
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

  // ---------- данные кораблей ----------

  function shipInfo(type_id) {
    if (opts.shipInfo) {
      const i = opts.shipInfo(type_id);
      if (i) return { max_hp: i.max_hp || i.hp || 4, arc: i.arc || [0, 0, 0, 0, 0, 0] };
    }
    if (typeof window !== 'undefined' && window.SWBShips && window.SWBShips.SHIP_DB) {
      const d = window.SWBShips.SHIP_DB[type_id];
      if (d) return { max_hp: d.hp || d.max_hp || 4, arc: d.arc || [0, 0, 0, 0, 0, 0] };
    }
    return FALLBACK_DB[type_id] || { max_hp: 4, arc: [0, 0, 0, 0, 0, 0] };
  }
  function findShip(id) {
    if (!state || !id) return null;
    for (const s of state.ships) if (s.id === id) return s;
    return null;
  }
  function activeShip() { return state ? findShip(state.active_ship) : null; }
  function isBotTurn() { return !!state && typeof state.active_seat === 'string' && state.active_seat.charAt(0) === 'B'; }

  // ---------- построение статической сцены ----------

  function makeStars() {
    const n = 750;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      // почти полная сфера: звёзды есть и у нижнего края кадра
      const a = Math.random() * Math.PI * 2;
      const y = Math.random() * 1.25 - 0.15;
      const rr = 70 + Math.random() * 30;
      const s = Math.sqrt(Math.max(0, 1 - y * y));
      pos[i * 3] = Math.cos(a) * s * rr;
      pos[i * 3 + 1] = y * rr;
      pos[i * 3 + 2] = Math.sin(a) * s * rr;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    const mat = new THREE.PointsMaterial({
      color: 0xcfe0ff, size: 0.85, sizeAttenuation: true,
      transparent: true, opacity: 0.85, depthWrite: false
    });
    const pts = new THREE.Points(geo, mat);
    scene.add(pts);
  }

  function makeEnvironment() {
    // Мягкий градиент -> PMREM, чтобы металл имел что отражать.
    const cv = document.createElement('canvas');
    cv.width = 64; cv.height = 64;
    const g = cv.getContext('2d');
    const grad = g.createLinearGradient(0, 0, 0, 64);
    grad.addColorStop(0, '#7e9cc8');
    grad.addColorStop(0.45, '#24354f');
    grad.addColorStop(1, '#05080f');
    g.fillStyle = grad;
    g.fillRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(cv);
    tex.mapping = THREE.EquirectangularReflectionMapping;
    tex.colorSpace = THREE.SRGBColorSpace;
    const pmrem = new THREE.PMREMGenerator(renderer);
    scene.environment = pmrem.fromEquirectangular(tex).texture;
    pmrem.dispose();
    tex.dispose();
  }

  function makeLights() {
    scene.add(new THREE.HemisphereLight(0x9db8ff, 0x1c2436, 1.7));
    const sun = new THREE.DirectionalLight(0xfff1dd, 5.2);
    sun.position.set(5.5 * cell, 10.5 * cell, 4.5 * cell);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const ext = 1.7 * radius * cell + 1.5;
    sun.shadow.camera.left = -ext; sun.shadow.camera.right = ext;
    sun.shadow.camera.top = ext; sun.shadow.camera.bottom = -ext;
    sun.shadow.camera.near = 1; sun.shadow.camera.far = 40 * cell + 20;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.02;
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0x8fb0ff, 1.6);
    fill.position.set(-6 * cell, 5 * cell, -7 * cell);
    scene.add(fill);
  }

  function makeTiles() {
    const topR = 0.73 * cell;
    const geo = new THREE.CylinderGeometry(topR, topR, 0.18 * cell, 6);
    // ВАЖНО: rotation.y не нужен — при стандартном thetaStart CylinderGeometry
    // даёт ВЕРШИНУ шестигранника на север (-Z), что совпадает с pointy-top
    // раскладкой worldX = √3·(q + r/2), worldZ = 1.5·r (поворот π/6 сломал бы сетку).
    const sideMat = new THREE.MeshStandardMaterial({ color: 0x0d1322, metalness: 0.35, roughness: 0.8 });
    const bottomMat = sideMat;
    const topMats = [];
    for (let i = 0; i < 4; i++) {
      topMats.push(new THREE.MeshStandardMaterial({
        color: new THREE.Color(0x232c4a).offsetHSL(0, 0, -0.012 * i),
        metalness: 0.3, roughness: 0.72
      }));
    }
    for (let q = -radius; q <= radius; q++) {
      for (let r = Math.max(-radius, -q - radius); r <= Math.min(radius, -q + radius); r++) {
        const h = Math.abs((q * 73856093) ^ (r * 19349663)) % 4;
        const mesh = new THREE.Mesh(geo, [sideMat, topMats[h], bottomMat]);
        const w = cellToWorld(q, r);
        mesh.position.set(w.x, -0.09 * cell, w.z);
        mesh.receiveShadow = true;
        mesh.userData.s3dCell = { q, r };
        scene.add(mesh);
        tiles.push(mesh);
      }
    }
  }

  function makeHighlightAssets() {
    A.plateGeo = new THREE.CylinderGeometry(0.64 * cell, 0.64 * cell, 0.05 * cell, 6);
    A.moveMat = new THREE.MeshBasicMaterial({ color: 0x40beff, transparent: true, opacity: 0.38, depthWrite: false });
    A.attackMat = new THREE.MeshBasicMaterial({ color: 0xff5252, transparent: true, opacity: 0.40, depthWrite: false });
    const ringGeo = new THREE.RingGeometry(0.6 * cell, 0.72 * cell, 6);
    ringGeo.rotateX(-Math.PI / 2);
    A.beginGeo = ringGeo;
    A.beginMat = new THREE.MeshBasicMaterial({ color: 0x66bb6a, transparent: true, opacity: 0.7, side: THREE.DoubleSide, depthWrite: false });
    const torus = new THREE.TorusGeometry(0.82 * cell, 0.032 * cell, 8, 48);
    torus.rotateX(Math.PI / 2);
    A.ringGeo = torus;
    A.ringYellowMat = new THREE.MeshBasicMaterial({ color: 0xffd54f, transparent: true, opacity: 0.95 });
    A.ringRedMat = new THREE.MeshBasicMaterial({ color: 0xff5a5a, transparent: true, opacity: 0.8 });
    A.flashGeo = new THREE.SphereGeometry(1, 14, 10);
    A.sparkGeo = new THREE.BoxGeometry(0.05, 0.05, 0.05);
    A.sparkBase = new THREE.MeshBasicMaterial({ color: 0xffcf7d, transparent: true, opacity: 1 });
  }

  function makeControls() {
    // Facing-стрелка — приплюснутый конус на середине ребра к соседу facing.
    A.cursorOnMat = new THREE.MeshBasicMaterial({ color: 0x3ec8ff, transparent: true, opacity: 0.9 });
    A.cursorOffMat = new THREE.MeshBasicMaterial({ color: 0x5a6478, transparent: true, opacity: 0.55 });
    const coneGeo = new THREE.ConeGeometry(0.20, 0.46, 4);
    arrow = new THREE.Group();
    const cone = new THREE.Mesh(coneGeo, A.cursorOnMat);
    cone.castShadow = false;
    cone.rotation.x = Math.PI / 2;   // +Y -> +Z внутри обёртки
    cone.scale.z = 0.5;              // приплюснуть по мировой вертикали (локальная Z)
    arrow.add(cone);
    arrow.userData.cone = cone;
    ctrlLayer.add(arrow);

    const curGeo = new THREE.ConeGeometry(0.16, 0.34, 4);
    function makeCursor(cmd) {
      const wrap = new THREE.Group();
      const cone = new THREE.Mesh(curGeo, A.cursorOffMat);
      cone.rotation.x = Math.PI / 2;
      cone.scale.z = 0.55;
      wrap.add(cone);
      wrap.userData = { s3dCmd: cmd, enabled: false, cone };
      ctrlLayer.add(wrap);
      return wrap;
    }
    cursorL = makeCursor({ type: 'RotateLeft' });
    cursorR = makeCursor({ type: 'RotateRight' });

    // кольцо активного корабля
    activeRing = new THREE.Mesh(A.ringGeo, A.ringYellowMat);
    activeRing.visible = false;
    hlLayer.add(activeRing);
  }

  // ---------- корабли ----------

  function disposeObject3D(root) {
    root.traverse((o) => {
      if (o.isMesh && o.geometry) o.geometry.dispose();
    });
  }

  function shipEntry(s) {
    const model = createShipModel(s.type_id, s.team);
    model.scale.setScalar(cell);
    const group = new THREE.Group();
    group.add(model);
    // командное кольцо-подсветка под кораблём
    const glow = new THREE.Mesh(
      new THREE.TorusGeometry(0.7 * cell, 0.022 * cell, 6, 36).rotateX(Math.PI / 2),
      new THREE.MeshBasicMaterial({
        color: s.team === 'B' ? 0xff5d5d : 0x38b6ff,
        transparent: true, opacity: 0.5
      })
    );
    glow.position.y = 0.03 * cell;
    group.add(glow);
    shipLayer.add(group);

    const w = cellToWorld(s.q, s.r);
    const el = document.createElement('div');
    el.className = 's3d-tag s3d-team-' + (s.team === 'B' ? 'b' : 'a');
    overlay.appendChild(el);

    return {
      id: s.id, type_id: s.type_id, team: s.team,
      group, model, glow,
      tx: w.x, tz: w.z, trot: facingRotY(s.facing),
      cx: w.x, cz: w.z, crot: facingRotY(s.facing),
      bobPhase: (s.q * 3 + s.r) * 0.7,
      tagEl: el, lastHp: -1, lastMax: -1
    };
  }

  function tagContent(s, maxHp) {
    let pips = '';
    const frac = maxHp > 0 ? s.hp / maxHp : 0;
    const cls = frac > 0.5 ? 'hi' : frac > 0.3 ? 'mid' : 'low';
    for (let i = 0; i < maxHp; i++) {
      pips += '<i class="s3d-pip ' + (i < s.hp ? 'on ' + cls : '') + '"></i>';
    }
    return '<span class="s3d-seat">' + s.seat + '</span><span class="s3d-pips">' + pips + '</span>';
  }

  function syncShips() {
    const alive = state ? state.ships.filter((s) => s.alive) : [];
    const ids = new Set(alive.map((s) => s.id));
    for (const [id, e] of ships) {
      if (!ids.has(id)) {
        shipLayer.remove(e.group);
        disposeObject3D(e.group);
        e.tagEl.remove();
        ships.delete(id);
      }
    }
    for (const s of alive) {
      let e = ships.get(s.id);
      if (!e) {
        e = shipEntry(s);
        ships.set(s.id, e);
      } else if (e.type_id !== s.type_id) {
        // ShipTransformed (Ghost -> Phantom и т.п.): пересобрать модель
        e.model.removeFromParent();
        disposeObject3D(e.model);
        e.model = createShipModel(s.type_id, s.team);
        e.model.scale.setScalar(cell);
        e.group.add(e.model);
        e.type_id = s.type_id;
      }
      const w = cellToWorld(s.q, s.r);
      e.tx = w.x; e.tz = w.z;
      e.trot = facingRotY(s.facing);
      const maxHp = shipInfo(s.type_id).max_hp;
      if (e.lastHp !== s.hp || e.lastMax !== maxHp) {
        e.tagEl.innerHTML = tagContent(s, maxHp);
        e.lastHp = s.hp; e.lastMax = maxHp;
      }
    }
  }

  // ---------- подсветки ----------

  function clearLayer(layer) {
    while (layer.children.length) layer.remove(layer.children[0]);
  }

  function rebuildHighlights() {
    clearLayer(hlLayer);
    hlLayer.add(activeRing); // clearLayer снимает и его — возвращаем
    if (!state || state.phase === 'ended') { activeRing.visible = false; return; }
    const act = activeShip();

    // клетки Move — голубые пластинки
    if (act && act.alive) {
      for (const c of legal) {
        if (c.type !== 'Move') continue;
        const d = DIR_DELTAS[c.dir];
        addPlate(act.q + d[0], act.r + d[1], A.moveMat);
      }
      // цели атак — красные пульсирующие
      for (const c of legal) {
        if (c.type !== 'DeclareAttack') continue;
        const t = findShip(c.target_ship_instance_id);
        if (t && t.alive) addPlate(t.q, t.r, A.attackMat);
      }
    }
    // Begin-варианты — зелёные кольца (фаза выбора)
    if (!state.active_ship && !isBotTurn()) {
      for (const c of legal) {
        if (c.type !== 'BeginActivation') continue;
        const s = findShip(c.ship_instance_id);
        if (!s || !s.alive) continue;
        const m = new THREE.Mesh(A.beginGeo, A.beginMat);
        const w = cellToWorld(s.q, s.r);
        m.position.set(w.x, 0.02 * cell, w.z);
        hlLayer.add(m);
      }
    }
    // кольцо активного корабля: игрок — жёлтое, бот — красное пульсирующее
    if (act && act.alive) {
      const w = cellToWorld(act.q, act.r);
      activeRing.position.set(w.x, 0.1 * cell, w.z);
      activeRing.material = isBotTurn() ? A.ringRedMat : A.ringYellowMat;
      activeRing.visible = true;
    } else {
      activeRing.visible = false;
    }
  }

  function addPlate(q, r, mat) {
    const m = new THREE.Mesh(A.plateGeo, mat);
    const w = cellToWorld(q, r);
    m.position.set(w.x, 0.055 * cell, w.z);
    hlLayer.add(m);
  }

  // ---------- стрелка курса и курсоры поворота ----------

  function aimWrapper(wrap, worldAngleA) {
    wrap.rotation.y = Math.PI / 2 - worldAngleA;
  }

  function syncControls() {
    const act = activeShip();
    const show = !!act && act.alive && state && state.phase !== 'ended';
    arrow.visible = !!show;
    const cursorsVisible = !!show && !isBotTurn();
    cursorL.visible = cursorsVisible;
    cursorR.visible = cursorsVisible;
    if (!show) return;

    const w = cellToWorld(act.q, act.r);
    const f = act.facing;
    const off = dirOffset(f, 0.5);
    arrow.position.set(w.x + off.x, 0.12 * cell, w.z + off.z);
    aimWrapper(arrow, worldAngle(off.x, off.z));
    arrow.userData.cone.material = isBotTurn() ? A.ringRedMat : A.cursorOnMat;

    const canL = legal.some((c) => c.type === 'RotateLeft');
    const canR = legal.some((c) => c.type === 'RotateRight');
    placeCursor(cursorL, act, (f + 5) % 6, canL);
    placeCursor(cursorR, act, (f + 1) % 6, canR);
  }

  function placeCursor(wrap, ship, edgeDir, enabled) {
    const w = cellToWorld(ship.q, ship.r);
    const off = dirOffset(edgeDir, 0.5);
    wrap.position.set(w.x + off.x, 0.12 * cell, w.z + off.z);
    const a = worldAngle(off.x, off.z);
    // курсор показывает направление поворота: касательная ±90°
    const side = wrap === cursorL ? -1 : 1;
    aimWrapper(wrap, a + side * Math.PI / 2);
    wrap.userData.enabled = enabled;
    wrap.userData.cone.material = enabled ? A.cursorOnMat : A.cursorOffMat;
  }

  // ---------- DOM-оверлей ----------

  function el(cls, parent) {
    const d = document.createElement('div');
    d.className = cls;
    (parent || overlay).appendChild(d);
    return d;
  }

  function rebuildOverlayStatic() {
    // Фланговые числа выбранного корабля
    const act = activeShip();
    const selId = act && act.alive ? act.id : null;
    if (flankWrap && selId !== selectedFlankId) {
      flankWrap.remove(); flankWrap = null;
      selectedFlankId = null;
    }
    if (act && act.alive && !flankWrap) {
      flankWrap = el('s3d-flank-wrap');
      for (let d = 0; d < 6; d++) flankWrap.appendChild(el('s3d-flank', flankWrap));
      selectedFlankId = act.id;
    }
    if (flankWrap && act) {
      const arc = shipInfo(act.type_id).arc;
      const spans = flankWrap.children;
      for (let d = 0; d < 6; d++) {
        const sector = ((d - act.facing) % 6 + 6) % 6;
        const v = arc[sector] | 0;
        const sp = spans[d];
        sp.textContent = v > 0 ? '+' + v : String(v);
        sp.className = 's3d-flank ' + (v >= 2 ? 'v2' : v === 1 ? 'v1' : v === 0 ? 'v0' : 'vn');
      }
    }
    // Враги в дистанции ≤3 от выбранного: кольцо + бейдж бонуса атаки
    const wanted = new Set();
    if (act && act.alive) {
      const arcSel = shipInfo(act.type_id).arc;
      for (const s of state.ships) {
        if (!s.alive || s.team === act.team) continue;
        if (hexDistance(act.q, act.r, s.q, s.r) > 3) continue;
        wanted.add(s.id);
        let deco = enemyDeco.get(s.id);
        if (!deco) {
          deco = { ring: el('s3d-ring'), badge: el('s3d-badge') };
          enemyDeco.set(s.id, deco);
        }
        const dirSE = directionFrom(act.q, act.r, s.q, s.r);
        const sector = ((dirSE - act.facing) % 6 + 6) % 6;
        const bonus = arcSel[sector] | 0;
        deco.badge.textContent = bonus > 0 ? '+' + bonus : String(bonus);
        deco.badge.className = 's3d-badge ' + (bonus >= 2 ? 'v2' : bonus === 1 ? 'v1' : bonus === 0 ? 'v0' : 'vn');
        deco.ring.className = 's3d-ring' + (hexDistance(act.q, act.r, s.q, s.r) <= 2 ? ' near' : ' far');
      }
    }
    for (const [id, deco] of enemyDeco) {
      if (!wanted.has(id)) {
        deco.ring.remove(); deco.badge.remove();
        enemyDeco.delete(id);
      }
    }
  }

  function projectToScreen(v3) {
    tmpV.copy(v3).project(camera);
    const w = renderer.domElement.clientWidth || 1;
    const h = renderer.domElement.clientHeight || 1;
    return { x: (tmpV.x * 0.5 + 0.5) * w, y: (-tmpV.y * 0.5 + 0.5) * h, behind: tmpV.z > 1 };
  }

  function placeEl(elm, sx, sy, hidden, extra) {
    if (hidden) { elm.style.display = 'none'; return; }
    elm.style.display = '';
    elm.style.transform = 'translate(' + sx.toFixed(1) + 'px,' + sy.toFixed(1) + 'px)' + (extra || ' translate(-50%,-50%)');
  }

  function updateOverlay() {
    for (const e of ships.values()) {
      const p = projectToScreen(tmpV.set(e.group.position.x, e.group.position.y + (LABEL_Y[e.type_id] || 0.75) * cell, e.group.position.z));
      placeEl(e.tagEl, p.x, p.y, p.behind, ' translate(-50%,-110%)');
    }
    // фланги выбранного
    const act = activeShip();
    if (flankWrap && act && act.alive) {
      const w = cellToWorld(act.q, act.r);
      const spans = flankWrap.children;
      for (let d = 0; d < 6; d++) {
        const off = dirOffset(d, 0.34); // число остаётся внутри гекса у середины стороны
        const p = projectToScreen(tmpV.set(w.x + off.x, 0.12 * cell, w.z + off.z));
        placeEl(spans[d], p.x, p.y, p.behind);
      }
    }
    // кольца/бейджи врагов
    if (act && act.alive) {
      for (const [id, deco] of enemyDeco) {
        const s = findShip(id);
        if (!s || !s.alive) { deco.ring.style.display = 'none'; deco.badge.style.display = 'none'; continue; }
        const w = cellToWorld(s.q, s.r);
        const c = projectToScreen(tmpV.set(w.x, 0.2 * cell, w.z));
        const edge = projectToScreen(tmpV.set(w.x + cell, 0.2 * cell, w.z));
        const rpx = Math.abs(edge.x - c.x) * 1.06;
        if (c.behind) { deco.ring.style.display = 'none'; }
        else {
          deco.ring.style.display = '';
          deco.ring.style.transform = 'translate(' + c.x.toFixed(1) + 'px,' + c.y.toFixed(1) + 'px) translate(-50%,-50%)';
          deco.ring.style.width = (rpx * 2).toFixed(0) + 'px';
          deco.ring.style.height = (rpx * 2).toFixed(0) + 'px';
        }
        // бейдж на ребре врага, обращённом к выбранному
        const dx = act.q - s.q, dr = act.r - s.r;
        const wx = SQRT3 * (dx + dr / 2), wz = 1.5 * dr;
        const len = Math.hypot(wx, wz) || 1;
        const half = 0.5 * SQRT3 * cell;
        const b = projectToScreen(tmpV.set(w.x + (wx / len) * half, 0.12 * cell, w.z + (wz / len) * half));
        placeEl(deco.badge, b.x, b.y, b.behind);
      }
    }
  }

  // ---------- эффекты ----------

  function spawnHit(q, r, kind) {
    if (!scene) return;
    const boom = kind === 'boom';
    const w = cellToWorld(q, r);
    const now = performance.now();
    const flashMat = new THREE.MeshBasicMaterial({ color: boom ? 0xffd27d : 0xffe9b0, transparent: true, opacity: 0.95, depthWrite: false });
    const flash = new THREE.Mesh(A.flashGeo, flashMat);
    flash.position.set(w.x, 0.3 * cell, w.z);
    fxLayer.add(flash);

    const sparkMat = A.sparkBase.clone();
    const n = boom ? 13 : 7;
    const sparks = [];
    for (let i = 0; i < n; i++) {
      const sp = new THREE.Mesh(A.sparkGeo, sparkMat);
      sp.position.copy(flash.position);
      const a = Math.random() * Math.PI * 2;
      const up = 0.5 + Math.random() * 1.2;
      const sp2 = (boom ? 2.4 : 1.6) * cell * (0.5 + Math.random());
      sp.userData.vel = new THREE.Vector3(Math.cos(a) * sp2, up * sp2 * 0.7, Math.sin(a) * sp2);
      sp.scale.setScalar(cell);
      fxLayer.add(sp);
      sparks.push(sp);
    }
    let light = null;
    if (boom) {
      light = new THREE.PointLight(0xffa050, 0, 9 * cell, 2);
      light.position.set(w.x, 0.9 * cell, w.z);
      fxLayer.add(light);
      shakeT0 = now;
    }
    effects.push({ t0: now, dur: boom ? 800 : 420, flash, flashMat, sparkMat, sparks, light, boom });
    if (effects.length > 24) {
      const old = effects.shift();
      killEffect(old);
    }
  }

  function killEffect(e) {
    e.flash.removeFromParent();
    e.flashMat.dispose();
    for (const sp of e.sparks) sp.removeFromParent();
    e.sparkMat.dispose();
    if (e.light) e.light.removeFromParent();
  }

  function updateEffects(now, dt) {
    for (let i = effects.length - 1; i >= 0; i--) {
      const e = effects[i];
      const t = (now - e.t0) / e.dur;
      if (t >= 1) { killEffect(e); effects.splice(i, 1); continue; }
      const base = (e.boom ? 1.8 : 1) * cell;
      e.flash.scale.setScalar((0.25 + 1.55 * t) * base);
      e.flashMat.opacity = 0.95 * (1 - t) * (1 - t * 0.25);
      e.sparkMat.opacity = 1 - t;
      for (const sp of e.sparks) {
        sp.position.addScaledVector(sp.userData.vel, dt);
        sp.userData.vel.y -= 3.6 * cell * dt;
        sp.scale.setScalar(cell * (1 - t * 0.55));
        sp.rotation.x += dt * 7;
        sp.rotation.y += dt * 5;
      }
      if (e.light) e.light.intensity = 42 * (1 - t) * cell * cell;
    }
  }

  // ---------- камера / ввод ----------

  function fitCamera() {
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    camera.aspect = w / h;
    const halfW = SQRT3 * (radius + 0.7) * cell;
    const halfD = 1.5 * radius * cell + 1.0 * cell;
    const vTan = Math.tan((camera.fov / 2) * Math.PI / 180);
    const hTan = vTan * camera.aspect;
    const dV = (halfD * Math.sin(ELEV)) / vTan;
    const dH = halfW / hTan;
    // Запас нужен не только тайлам, но и моделям/подписям на крайних гексах.
    distBase = 1.28 * Math.max(dV, dH, 7 * cell);
    camera.updateProjectionMatrix();
  }

  function updateCamera(now) {
    const D = distBase * distScale;
    const horiz = D * Math.cos(ELEV);
    let sx = 0, sy = 0, sz = 0;
    if (shakeT0 > 0 && now - shakeT0 < 250) {
      const k = 1 - (now - shakeT0) / 250;
      sx = (Math.random() - 0.5) * 0.16 * cell * k;
      sy = (Math.random() - 0.5) * 0.1 * cell * k;
      sz = (Math.random() - 0.5) * 0.16 * cell * k;
    } else {
      shakeT0 = -1;
    }
    camera.position.set(
      Math.sin(azimuth) * horiz + sx,
      D * Math.sin(ELEV) + sy,
      Math.cos(azimuth) * horiz + sz
    );
    camera.lookAt(0, 0, 0);
  }

  function setNDC(x, y) {
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.x = ((x - rect.left) / rect.width) * 2 - 1;
    ndc.y = -((y - rect.top) / rect.height) * 2 + 1;
  }

  function pickTile(x, y) {
    setNDC(x, y);
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObjects(tiles, false);
    return hits.length ? hits[0].object.userData.s3dCell : null;
  }

  function pickCursor(x, y) {
    setNDC(x, y);
    raycaster.setFromCamera(ndc, camera);
    const objs = [cursorL, cursorR].filter((c) => c.visible);
    if (!objs.length) return null;
    const hits = raycaster.intersectObjects(objs, true);
    if (!hits.length) return null;
    let o = hits[0].object;
    while (o && !o.userData.s3dCmd) o = o.parent;
    return o;
  }

  function onPointerDown(ev) {
    downInfo = { x: ev.clientX, y: ev.clientY, button: ev.button, moved: false, lastX: ev.clientX, lastY: ev.clientY };
  }

  function onPointerMove(ev) {
    if (downInfo) {
      const dx = ev.clientX - downInfo.x, dy = ev.clientY - downInfo.y;
      if (dx * dx + dy * dy > 25) downInfo.moved = true; // > 5px — это уже drag
      if (downInfo.moved && (downInfo.button === 2 || ev.buttons & 2)) {
        azimuth -= (ev.clientX - downInfo.lastX) * 0.006; // правый-drag орбит
        if (azimuth > Math.PI) azimuth -= Math.PI * 2;
        if (azimuth < -Math.PI) azimuth += Math.PI * 2;
      }
      downInfo.lastX = ev.clientX;
      downInfo.lastY = ev.clientY;
      return;
    }
    // hover
    if (!renderer) return;
    const cur = pickCursor(ev.clientX, ev.clientY);
    if (cur) {
      renderer.domElement.style.cursor = cur.userData.enabled ? 'pointer' : 'default';
      setHover(null);
      return;
    }
    const c = pickTile(ev.clientX, ev.clientY);
    renderer.domElement.style.cursor = c ? 'pointer' : 'default';
    setHover(c);
  }

  function setHover(c) {
    const next = c ? { q: c.q, r: c.r } : null;
    const changed = (!next !== !hoverCell) || (next && hoverCell && (next.q !== hoverCell.q || next.r !== hoverCell.r));
    hoverCell = next;
    if (changed && opts.onCellHover) opts.onCellHover(next);
  }

  function onPointerUp(ev) {
    if (!downInfo) return;
    const d = downInfo;
    downInfo = null;
    if (d.button !== 0 || d.moved) return;      // клик = ЛКМ без сдвига >5px
    if (!renderer) return;
    const cur = pickCursor(ev.clientX, ev.clientY);
    if (cur) {
      if (cur.userData.enabled && opts.onCommand) opts.onCommand(cur.userData.s3dCmd);
      return;
    }
    const c = pickTile(ev.clientX, ev.clientY);
    if (opts.onCellClick) opts.onCellClick(c ? { q: c.q, r: c.r } : null);
  }

  function onWheel(ev) {
    ev.preventDefault();
    distScale *= 1 + ev.deltaY * 0.0011;
    distScale = Math.min(2.2, Math.max(0.45, distScale));
  }

  function onResize() {
    if (!renderer || !container) return;
    const w = container.clientWidth || 800;
    const h = container.clientHeight || 600;
    renderer.setSize(w, h, false);
    fitCamera();
  }

  // ---------- главный цикл ----------

  function tick(now) {
    if (disposed) return;
    rafId = requestAnimationFrame(tick);
    const dt = Math.min(0.05, (now - prevT) / 1000 || 0.016);
    prevT = now;

    if (dirty) {
      syncShips();
      rebuildHighlights();
      syncControls();
      rebuildOverlayStatic();
      dirty = false;
    }

    // корабли: плавное движение + покачивание
    const k = 1 - Math.exp(-dt * 9);
    for (const e of ships.values()) {
      e.cx += (e.tx - e.cx) * k;
      e.cz += (e.tz - e.cz) * k;
      let dr = e.trot - e.crot;
      while (dr > Math.PI) dr -= Math.PI * 2;
      while (dr < -Math.PI) dr += Math.PI * 2;
      e.crot += dr * k;
      const bob = Math.sin(now / 620 + e.bobPhase) * 0.03 * cell;
      e.group.position.set(e.cx, SHIP_CLEARANCE * cell + bob, e.cz);
      e.group.rotation.y = e.crot;
    }

    // пульс подсветок
    const t01 = now / 1000;
    A.attackMat.opacity = 0.16 + 0.1 * (0.5 + 0.5 * Math.sin(t01 * 7.5));
    A.moveMat.opacity = 0.18 + 0.08 * Math.sin(t01 * 4);
    A.beginMat.opacity = 0.55 + 0.25 * Math.sin(t01 * 5);
    if (activeRing.visible) {
      activeRing.rotation.y = t01 * 0.8;
      const s = 1 + 0.035 * Math.sin(t01 * 6);
      activeRing.scale.set(s, 1, s);
    }
    cursorL.userData.cone.material.opacity = 0.65 + 0.3 * Math.sin(t01 * 5);
    cursorR.userData.cone.material.opacity = 0.65 + 0.3 * Math.sin(t01 * 5);

    updateEffects(now, dt);
    updateCamera(now);
    updateOverlay();
    renderer.render(scene, camera);
  }

  // ---------- публичный API ----------

  function init(containerEl, initOpts) {
    if (renderer) dispose();
    container = containerEl;
    opts = initOpts || {};
    cell = opts.cell || 1.0;
    radius = opts.radius || 3;
    disposed = false;
    state = null; legal = [];
    ships = new Map(); effects = []; enemyDeco.clear();
    tiles = []; hoverCell = null; selectedFlankId = null; flankWrap = null;
    azimuth = 0; distScale = 1; shakeT0 = -1;

    container.classList.add('s3d-stage');
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.85;
    renderer.domElement.className = 's3d-canvas';
    container.appendChild(renderer.domElement);

    overlay = document.createElement('div');
    overlay.className = 's3d-overlay';
    container.appendChild(overlay);

    // Регулятор угла обзора (10..85°)
    const elevBox = document.createElement('div');
    elevBox.className = 's3d-elev';
    elevBox.innerHTML = '<span class="s3d-elev-label">УГОЛ ' + Math.round(elevDeg) + '°</span>' +
      '<input type="range" min="' + ELEV_MIN + '" max="' + ELEV_MAX + '" step="1" value="' + Math.round(elevDeg) + '" aria-label="Угол обзора">';
    container.appendChild(elevBox);
    const elevRange = elevBox.querySelector('input');
    const elevLabel = elevBox.querySelector('.s3d-elev-label');
    elevRange.addEventListener('input', () => {
      const v = setElevation(Number(elevRange.value));
      elevLabel.textContent = 'УГОЛ ' + Math.round(v) + '°';
    });

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x04060c);
    camera = new THREE.PerspectiveCamera(42, 1, 0.1, 300);

    window.__b3d = { scene, renderer, camera }; // отладка света/материалов из консоли

    makeEnvironment();
    makeLights();
    makeStars();
    makeTiles();

    shipLayer = new THREE.Group();
    hlLayer = new THREE.Group();
    fxLayer = new THREE.Group();
    ctrlLayer = new THREE.Group();
    scene.add(shipLayer, hlLayer, fxLayer, ctrlLayer);

    makeHighlightAssets();
    makeControls();

    // ввод
    const cv = renderer.domElement;
    cv.addEventListener('pointerdown', onPointerDown);
    cv.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);
    cv.addEventListener('wheel', onWheel, { passive: false });
    cv.addEventListener('contextmenu', (e) => e.preventDefault());

    resizeObs = new ResizeObserver(onResize);
    resizeObs.observe(container);
    onResize();

    prevT = performance.now();
    rafId = requestAnimationFrame(tick);
    return api;
  }

  function setElevation(deg) {
    elevDeg = Math.min(ELEV_MAX, Math.max(ELEV_MIN, deg));
    ELEV = elevDeg * Math.PI / 180;
    fitCamera();
    dirty = true;
    try { localStorage.setItem('swb_elev', String(Math.round(elevDeg))); } catch (e) {}
    if (opts.onElevation) opts.onElevation(elevDeg);
    return elevDeg;
  }
  function getElevation() { return elevDeg; }

  function setState(s) {
    state = s || null;
    dirty = true;
  }

  function setLegal(l) {
    legal = Array.isArray(l) ? l : [];
    dirty = true;
  }

  function dispose() {
    disposed = true;
    cancelAnimationFrame(rafId);
    if (resizeObs) { resizeObs.disconnect(); resizeObs = null; }
    if (renderer) {
      const cv = renderer.domElement;
      cv.removeEventListener('pointerdown', onPointerDown);
      cv.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      cv.removeEventListener('wheel', onWheel);
      if (overlay) overlay.remove();
      cv.remove();
      renderer.dispose();
      renderer = null;
    }
    if (container) container.classList.remove('s3d-stage');
    scene = null; camera = null; overlay = null;
    ships = new Map(); effects = []; enemyDeco.clear(); tiles = [];
    flankWrap = null; selectedFlankId = null; state = null; legal = [];
  }

  const api = { init, setState, setLegal, spawnHit, dispose, setElevation, getElevation };
  return api;
})();

export default Board3D;
