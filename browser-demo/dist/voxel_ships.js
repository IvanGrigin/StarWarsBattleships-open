// Воксельные модели кораблей («майнкрафт»-стиль, по мотивам фан-построек,
// но АВТОРСКИЕ: собственная палитра блоков и собственные сетки).
// Конвейер: сетка вокселей -> мешинг граней (только видимые) -> THREE.BufferGeometry.
// Ориентация: нос корабля смотрит в -Z, y — вверх, корабль лежит в плоскости поля.
// Подключение: import { createShipModel } from './voxel_ships.js'

import * as THREE from './vendor/three.module.js';

// ---------- Палитра блоков ----------
const BLOCKS = {
  W: { color: 0xe9eef7 },              // светлый корпус
  M: { color: 0xb4c0cf },              // средний корпус
  D: { color: 0x66748a },              // тёмный корпус
  K: { color: 0x262e3d },              // почти чёрные детали
  G: { color: 0xa8dcff, glass: true }, // кабины, стёкла
  R: { color: 0xd24a43 },              // красный акцент
  O: { color: 0xe08b3a },              // оранжевый акцент
  Y: { color: 0xd9c26a },              // золотой акцент
  E: { color: 0x74d9ff, glow: true },  // свечение двигателей
  V: { color: 0x55e07f, glow: true },  // зелёное оружие
};

// ---------- Сетка вокселей ----------
function Grid(nx, ny, nz) {
  const cells = new Array(nx * ny * nz).fill('.');
  const inside = (x, y, z) => x >= 0 && y >= 0 && z >= 0 && x < nx && y < ny && z < nz;
  const g = {
    nx, ny, nz, cells,
    set(x, y, z, ch) {
      x = Math.round(x); y = Math.round(y); z = Math.round(z);
      if (inside(x, y, z)) cells[(y * nz + z) * nx + x] = ch;
    },
    get(x, y, z) { return inside(x, y, z) ? cells[(y * nz + z) * nx + x] : '.'; },
    box(x0, y0, z0, x1, y1, z1, ch) {
      for (let z = z0; z <= z1; z++) for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) g.set(x, y, z, ch);
    },
    ell(cx, cy, cz, rx, ry, rz, ch) {
      for (let z = Math.floor(cz - rz); z <= Math.ceil(cz + rz); z++)
        for (let y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y++)
          for (let x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x++) {
            const dx = (x + 0.5 - cx) / rx, dy = (y + 0.5 - cy) / ry, dz = (z + 0.5 - cz) / rz;
            if (dx * dx + dy * dy + dz * dz <= 1) g.set(x, y, z, ch);
          }
    },
    cylY(cx, cz, r, y0, y1, ch) {
      for (let y = y0; y <= y1; y++)
        for (let z = Math.floor(cz - r); z <= Math.ceil(cz + r); z++)
          for (let x = Math.floor(cx - r); x <= Math.ceil(cx + r); x++) {
            const dx = x + 0.5 - cx, dz = z + 0.5 - cz;
            if (dx * dx + dz * dz <= r * r) g.set(x, y, z, ch);
          }
    },
  };
  return g;
}

// ---------- Постройки (нос = z0, корма = zN) ----------
const BUILDERS = {
  tie_fighter: {
    target: 1.4,
    build(g) {
      // две панели-крыла
      for (const px of [0, 14]) {
        for (let y = 0; y <= 15; y++) for (let z = 1; z <= 14; z++) {
          const dy = y - 7.5, dz = z - 7.5;
          if (dy * dy + dz * dz > 6.9 * 6.9) continue;
          const frame = y <= 1 || y >= 14 || z <= 2 || z >= 13 || (dy * dy + dz * dz < 1.8 * 1.8);
          g.set(px, y, z, frame ? 'M' : 'D');
        }
      }
      // пилоны к кабине
      g.box(2, 6, 6, 3, 9, 9, 'M');
      g.box(12, 6, 6, 13, 9, 9, 'M');
      // кабина-шар
      g.ell(7.5, 7.5, 7.5, 2.7, 2.7, 2.7, 'M');
      g.ell(7.5, 7.5, 5.2, 1.7, 1.7, 1.0, 'G'); // окно
      g.ell(7.5, 9.4, 7.5, 2.0, 0.7, 2.0, 'W'); // верхняя панель
    },
  },

  tie_advanced_x1: {
    target: 1.45,
    build(g) {
      // изогнутые панели: верх/низ подтянуты к носу
      for (const px of [0, 14]) {
        for (let y = 0; y <= 15; y++) for (let z = 1; z <= 14; z++) {
          const dy = y - 7.5, dz = z - 7.5;
          if (dy * dy + dz * dz > 6.9 * 6.9) continue;
          const bend = Math.abs(dy) > 4.2 ? 1 : 0;
          const zz = z - bend;
          const frame = y <= 1 || y >= 14 || zz <= 2 || zz >= 13 || (dy * dy + dz * dz < 1.8 * 1.8);
          g.set(px, y, zz, frame ? 'M' : 'D');
        }
      }
      g.box(2, 6, 6, 3, 9, 9, 'M');
      g.box(12, 6, 6, 13, 9, 9, 'M');
      // корпус кабины светлее, с тёмными линиями
      g.ell(7.5, 7.5, 7.5, 2.7, 2.7, 2.7, 'W');
      g.ell(7.5, 7.5, 5.2, 1.7, 1.7, 1.0, 'G');
      g.box(7, 5, 9, 8, 5, 10, 'K');
      // спаренные пушки снизу
      g.box(6, 5, 2, 6, 6, 5, 'K');
      g.box(9, 5, 2, 9, 6, 5, 'K');
    },
  },

  xwing_t65: {
    target: 1.6,
    build(g) {
      // фюзеляж
      g.box(6, 3, 2, 9, 5, 15, 'M');
      g.box(7, 4, 0, 8, 4, 1, 'M');  // нос
      g.set(7, 4, 0, 'W'); g.set(8, 4, 0, 'W');
      g.box(7, 5, 6, 8, 5, 9, 'G');  // фонарь кабины
      g.box(7, 5, 11, 8, 5, 12, 'W'); // астромех
      // S-foils: X с фронта
      g.box(0, 1, 4, 5, 2, 11, 'M');   // нижние
      g.box(10, 1, 4, 15, 2, 11, 'M');
      g.box(0, 6, 6, 5, 7, 13, 'M');   // верхние (отнесены назад)
      g.box(10, 6, 6, 15, 7, 13, 'M');
      // красные полосы на нижних крыльях
      g.box(1, 2, 8, 5, 2, 9, 'R');
      g.box(10, 2, 8, 14, 2, 9, 'R');
      // двигатели у корней крыльев
      g.box(4, 1, 2, 5, 2, 3, 'E');
      g.box(10, 1, 2, 11, 2, 3, 'E');
      g.box(4, 6, 4, 5, 7, 5, 'E');
      g.box(10, 6, 4, 11, 7, 5, 'E');
      // четыре ствола
      g.box(0, 2, 1, 0, 2, 12, 'K');
      g.box(15, 2, 1, 15, 2, 12, 'K');
      g.box(0, 7, 3, 0, 7, 14, 'K');
      g.box(15, 7, 3, 15, 7, 14, 'K');
    },
  },

  eta2_actis: {
    target: 1.2,
    build(g) {
      // дельта-крыло, расширяющееся к корме
      for (let z = 0; z <= 13; z++) {
        const hw = Math.max(1, Math.round(z * 0.3));
        g.box(6 - hw, 2, z, 6 + hw, 3, z, z % 3 === 0 ? 'W' : 'M');
      }
      g.box(6, 2, 0, 7, 3, 1, 'W'); // нос
      g.ell(6.5, 3.6, 3.4, 1.4, 1.2, 1.6, 'G'); // кабина
      g.box(4, 2, 12, 4, 3, 13, 'E'); // двигатели
      g.box(9, 2, 12, 9, 3, 13, 'E');
    },
  },

  millennium_falcon: {
    target: 1.95,
    build(g) {
      g.cylY(8.5, 8.5, 8.2, 2, 4, 'M');
      // кольцевые панели
      for (let z = 0; z <= 16; z++) for (let x = 0; x <= 17; x++) {
        const dx = x + 0.5 - 8.5, dz = z + 0.5 - 8.5, d = Math.sqrt(dx * dx + dz * dz);
        if (d > 6.4 && d < 7.4) g.set(x, 4, z, 'W');
        if (d > 7.7) g.set(x, 3, z, 'D');
      }
      // челюсти
      g.box(3, 2, 0, 5, 4, 4, 'M');
      g.box(12, 2, 0, 14, 4, 4, 'M');
      // кабина справа-спереди
      g.ell(13.5, 3.5, 3.0, 1.4, 1.4, 1.2, 'M');
      g.ell(13.5, 3.5, 1.9, 0.9, 0.9, 0.6, 'G');
      // центральный желоб и погрузочный отсек
      g.box(6, 2, 6, 11, 2, 11, 'D');
      g.box(7, 2, 13, 10, 4, 15, 'K');
      g.box(7, 3, 15, 10, 3, 15, 'E');
      // сенсорная тарелка
      g.box(2, 5, 11, 3, 5, 12, 'K');
      g.set(2, 4, 11, 'K');
    },
  },

  death_star_1: {
    target: 1.95,
    build(g) {
      g.ell(8, 8, 8, 7.6, 7.6, 7.6, 'M');
      // панельные вариации и экваториальная траншея
      for (let z = 0; z <= 16; z++) for (let y = 0; y <= 16; y++) for (let x = 0; x <= 16; x++) {
        if (g.get(x, y, z) !== 'M') continue;
        if (y === 8) g.set(x, y, z, 'D');
        else if ((x * 7 + y * 3 + z * 5) % 11 === 0) g.set(x, y, z, 'D');
        else if ((x * 3 + z) % 7 === 0) g.set(x, y, z, 'W');
      }
      // суперлазерная блюдце (в нос, -z)
      for (let z = 1; z <= 3; z++) for (let y = 4; y <= 12; y++) for (let x = 4; x <= 12; x++) {
        const dx = x + 0.5 - 8, dy = y + 0.5 - 8, d = Math.sqrt(dx * dx + dy * dy);
        if (d <= 3.8) g.set(x, y, z, 'K');
        if (d <= 1.4 && z >= 2) g.set(x, y, z, 'V');
      }
    },
  },

  slave_1: {
    target: 1.75,
    build(g) {
      g.box(6, 5, 1, 8, 8, 11, 'W');   // узкий корпус
      g.box(6, 6, 0, 7, 7, 0, 'W');    // нос
      g.ell(7, 7.9, 2.4, 0.9, 0.8, 1.3, 'G'); // кабина спереди сверху
      g.box(1, 6, 5, 13, 7, 8, 'M');   // широкие крылья
      g.box(0, 8, 7, 1, 9, 8, 'M');    // приподнятые законцовки
      g.box(13, 8, 7, 13, 9, 8, 'M');
      g.box(1, 6, 5, 1, 7, 5, 'R');    // полосы на крыльях
      g.box(13, 6, 5, 13, 7, 5, 'R');
      g.box(5, 5, 0, 5, 5, 3, 'K');    // парные пушки
      g.box(9, 5, 0, 9, 5, 3, 'K');
      g.box(6, 6, 12, 8, 7, 12, 'D');  // двигательный блок
      g.set(6, 6, 12, 'E'); g.set(8, 6, 12, 'E');
    },
  },

  star_destroyer: {
    target: 2.05,
    build(g) {
      // клин: к корме шире
      for (let z = 0; z <= 16; z++) {
        const hw = 2 + Math.round(z * 0.44);
        g.box(11 - hw, 2, z, 11 + hw, 4, z, 'M');
        g.box(11 - hw, 5, z, 11 + hw, 5, z, 'W');
        const hw2 = Math.max(1, hw - 4);
        if (z >= 2) g.box(11 - hw2, 6, z, 11 + hw2, 6, z, 'W');
      }
      // мостик
      g.box(8, 7, 12, 14, 9, 15, 'W');
      g.box(9, 9, 13, 13, 9, 15, 'K');
      g.ell(8, 9.6, 14, 1.1, 1.1, 1.1, 'M');  // дефлекторы
      g.ell(14, 9.6, 14, 1.1, 1.1, 1.1, 'M');
      // двигатели
      for (const ex of [7, 11, 15]) g.box(ex, 3, 16, ex, 4, 16, 'E');
    },
  },

  ghost: {
    target: 1.9,
    build(g) {
      g.box(5, 3, 2, 13, 7, 13, 'M');  // основной корпус
      for (let z = 3; z <= 12; z += 3) g.box(5, 5, z, 13, 5, z, 'O'); // оранжевые полосы
      g.box(6, 5, 0, 9, 7, 3, 'M');    // носовая кабина
      g.box(6, 6, 0, 9, 6, 1, 'G');
      g.box(2, 4, 0, 4, 6, 6, 'W');    // передние пилоны
      g.box(14, 4, 0, 16, 6, 6, 'W');
      g.box(8, 8, 7, 10, 9, 9, 'K');   // турель
      g.box(5, 4, 14, 6, 6, 15, 'E');  // двигатели
      g.box(12, 4, 14, 13, 6, 15, 'E');
    },
  },

  phantom: {
    target: 1.05,
    build(g) {
      g.box(3, 2, 2, 7, 4, 8, 'M');
      g.box(4, 2, 0, 6, 3, 1, 'M');    // скошенный нос
      g.box(4, 3, 0, 6, 3, 0, 'G');
      g.box(0, 2, 4, 2, 3, 7, 'M');    // плоские крылья
      g.box(8, 2, 4, 10, 3, 7, 'M');
      g.box(4, 2, 9, 6, 4, 9, 'D');
      g.set(4, 3, 9, 'E'); g.set(6, 3, 9, 'E');
    },
  },

  vulture_droid: {
    target: 1.35,
    build(g) {
      g.ell(6, 6, 6, 2.1, 2.1, 2.7, 'M');  // тело
      g.ell(6, 6, 3.4, 1.3, 1.3, 1.3, 'D'); // голова
      g.box(5, 5, 2, 5, 6, 2, 'G');        // глаза
      g.box(7, 5, 2, 7, 6, 2, 'G');
      // сложенные вниз-вперёд крылья-манипуляторы
      g.box(3, 4, 3, 4, 6, 6, 'D');
      g.box(1, 2, 2, 2, 4, 5, 'D');
      g.box(8, 4, 3, 9, 6, 6, 'D');
      g.box(10, 2, 2, 11, 4, 5, 'D');
      g.box(1, 1, 1, 2, 1, 2, 'K');        // когти
      g.box(10, 1, 1, 11, 1, 2, 'K');
    },
  },
};

// ---------- Мешинг: только видимые грани, затенение сторон ----------
const FACES = [
  { n: [1, 0, 0], shade: 0.80, v: [[1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 1, 1]] },
  { n: [-1, 0, 0], shade: 0.80, v: [[0, 0, 0], [0, 0, 1], [0, 1, 1], [0, 1, 0]] },
  { n: [0, 1, 0], shade: 1.00, v: [[0, 1, 1], [1, 1, 1], [1, 1, 0], [0, 1, 0]] },
  { n: [0, -1, 0], shade: 0.55, v: [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]] },
  { n: [0, 0, 1], shade: 0.90, v: [[0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]] },
  { n: [0, 0, -1], shade: 0.86, v: [[1, 0, 0], [0, 0, 0], [0, 1, 0], [1, 1, 0]] },
];

const colorCache = {};
function blockColor(ch, overrideHex) {
  const key = overrideHex != null ? ch + '_' + overrideHex : ch;
  if (!colorCache[key]) colorCache[key] = new THREE.Color(overrideHex != null ? overrideHex : BLOCKS[ch].color);
  return colorCache[key];
}

function meshGrid(g, overrides = {}) {
  const buckets = { solid: { pos: [], nrm: [], col: [] }, glass: { pos: [], nrm: [], col: [] }, glow: { pos: [], nrm: [], col: [] } };
  const c = new THREE.Color();
  for (let y = 0; y < g.ny; y++) for (let z = 0; z < g.nz; z++) for (let x = 0; x < g.nx; x++) {
    const ch = g.get(x, y, z);
    if (ch === '.') continue;
    const def = BLOCKS[ch];
    const bucket = buckets[def.glass ? 'glass' : def.glow ? 'glow' : 'solid'];
    const base = blockColor(ch, overrides[ch]);
    const checker = ((x + y + z) % 2) ? 0.94 : 1.0; // лёгкая «блочная» текстура
    for (const f of FACES) {
      if (g.get(x + f.n[0], y + f.n[1], z + f.n[2]) !== '.') continue;
      c.copy(base).multiplyScalar(f.shade * checker);
      const i0 = bucket.pos.length / 3;
      for (const vi of [0, 1, 2, 0, 2, 3]) {
        const p = f.v[vi];
        bucket.pos.push(x + p[0], y + p[1], z + p[2]);
        bucket.nrm.push(f.n[0], f.n[1], f.n[2]);
        bucket.col.push(c.r, c.g, c.b);
      }
    }
  }
  const geos = {};
  for (const key of Object.keys(buckets)) {
    const b = buckets[key];
    if (!b.pos.length) continue;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(b.pos, 3));
    geo.setAttribute('normal', new THREE.Float32BufferAttribute(b.nrm, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(b.col, 3));
    geos[key] = geo;
  }
  return geos;
}

// ---------- Публичный API ----------
const materials = {
  solid: new THREE.MeshLambertMaterial({ vertexColors: true }),
  glass: new THREE.MeshLambertMaterial({ vertexColors: true, transparent: true, opacity: 0.7 }),
  glow: new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false }),
};

// createShipModel(typeId, { size, team }) -> THREE.Group (нос в -Z, низ в y=0, центр по x/z)
// team: 'A' -> двигатели голубые, 'B' -> красные (командная читаемость на поле)
export function createShipModel(typeId, opts = {}) {
  const spec = BUILDERS[typeId];
  if (!spec) return null;
  const dims = spec.dims || guessDims(typeId);
  const g = Grid(dims[0], dims[1], dims[2]);
  spec.build(g);

  const overrides = opts.team === 'B' ? { E: 0xff7a66, V: 0xff5a4a } : null;
  const geos = meshGrid(g, overrides || {});
  const group = new THREE.Group();
  for (const [key, geo] of Object.entries(geos)) {
    geo.translate(-dims[0] / 2, 0, -dims[2] / 2);
    group.add(new THREE.Mesh(geo, materials[key]));
  }
  const maxFootprint = Math.max(dims[0], dims[2], dims[1]);
  const size = opts.size != null ? opts.size : spec.target;
  group.scale.setScalar(size / maxFootprint);
  group.userData.voxel = { typeId, dims, faces: Object.values(geos).reduce((a, geo) => a + geo.attributes.position.count / 3, 0), voxels: g.cells.filter((ch) => ch !== '.').length };
  return group;
}

// размеры сетки вычисляются из самой постройки (прогон в пустую копию не нужен —
// все билдеры декларируют размеры явно через DIMS ниже)
const DIMS = {
  tie_fighter: [16, 16, 16],
  tie_advanced_x1: [16, 16, 16],
  xwing_t65: [16, 9, 18],
  eta2_actis: [14, 6, 14],
  millennium_falcon: [18, 7, 18],
  death_star_1: [17, 17, 17],
  slave_1: [15, 10, 13],
  star_destroyer: [23, 10, 17],
  ghost: [19, 11, 17],
  phantom: [11, 7, 11],
  vulture_droid: [13, 9, 12],
};
function guessDims(typeId) { return DIMS[typeId] || [12, 8, 12]; }

export const SHIP_MODEL_TYPES = Object.keys(BUILDERS);
export { BLOCKS };

// отладочный доступ из консоли
window.VoxelShips = { createShipModel, SHIP_MODEL_TYPES, BLOCKS };
