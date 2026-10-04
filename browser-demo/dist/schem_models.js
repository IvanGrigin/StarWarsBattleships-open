// demo/schem_models.js — источник моделей из Minecraft-схематиков.
// Конвейер мастер-плана: постройка -> tools/schem_to_mesh.py -> assets/models/meshes/*.json.
// Файл JSON: { n:[nx,ny,nz], faces: [[px,py,pz, ux,uy,uz,ul, vx,vy,vz,vl, r,g,b], ...] }.
// Модель строится центрированной (низ в -h/2), масштаб запекает models3d под FOOTPRINT.

import * as THREE from 'three';

const cache = new Map();          // type_id -> THREE.Group
const DIR_NORMALS = [
  [1, 0, 0], [-1, 0, 0],
  [0, 1, 0], [0, -1, 0],
  [0, 0, 1], [0, 0, -1],
];

let material = null;
function mat() {
  if (!material) {
    material = new THREE.MeshStandardMaterial({ vertexColors: true, metalness: 0.22, roughness: 0.72, envMapIntensity: 1.5 });
  }
  return material;
}

export function buildGeometry(rec) {
  const faces = rec.faces;
  const pos = new Float32Array(faces.length * 18);
  const nrm = new Float32Array(faces.length * 18);
  const col = new Float32Array(faces.length * 18);
  let o = 0;
  const p = [0, 0, 0], u = [0, 0, 0], v = [0, 0, 0];
  for (let f = 0; f < faces.length; f++) {
    const q = faces[f];
    p[0] = q[0]; p[1] = q[1]; p[2] = q[2];
    u[0] = q[3]; u[1] = q[4]; u[2] = q[5];
    v[0] = q[6]; v[1] = q[7]; v[2] = q[8];
    const r = q[9] / 255, g = q[10] / 255, b = q[11] / 255;
    const d = q[12];
    const n = DIR_NORMALS[d] || DIR_NORMALS[2];
    // winding по нормали направления
    const cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    const flip = (cross[0] * n[0] + cross[1] * n[1] + cross[2] * n[2]) < 0;
    const corners = flip
      ? [[0, 0], [0, 1], [1, 1], [1, 0]]
      : [[0, 0], [1, 0], [1, 1], [0, 1]];
    const tri = [0, 1, 2, 0, 2, 3];
    for (const ci of tri) {
      const [a, b2] = corners[ci];
      pos[o] = p[0] + u[0] * a + v[0] * b2;
      pos[o + 1] = p[1] + u[1] * a + v[1] * b2;
      pos[o + 2] = p[2] + u[2] * a + v[2] * b2;
      nrm[o] = n[0]; nrm[o + 1] = n[1]; nrm[o + 2] = n[2];
      col[o] = r; col[o + 1] = g; col[o + 2] = b;
      o += 3;
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(nrm, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  return geo;
}

function deg(v) { return (Number(v) || 0) * Math.PI / 180; }

/**
 * Приводит исходную Minecraft-геометрию к общему контракту сцены:
 * нос -Z, верх +Y, низ y=0, центр по XZ в нуле.
 *
 * rotY — грубая коррекция исходника (исторически знак инвертирован);
 * rotX/rotFine/rotZ — точная XYZ-калибровка; offsets применяются только
 * после калибровки и нормализации, fwd всегда означает локальный нос -Z.
 */
export function createSchemGroup(rec, typeId, cfg = {}, footprints = null) {
  const geo = buildGeometry(rec);

  if (cfg.rotY) geo.applyMatrix4(new THREE.Matrix4().makeRotationY(-deg(cfg.rotY)));
  if (cfg.rotFine || cfg.rotX || cfg.rotZ) {
    geo.applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(
      deg(cfg.rotX), deg(cfg.rotFine), deg(cfg.rotZ), 'XYZ'
    )));
  }

  // Нормализуем уже после всех калибровочных поворотов: так высокий или
  // повёрнутый исходник не сдвигается с клетки и не проваливается под поле.
  geo.computeBoundingBox();
  const rawBox = geo.boundingBox;
  const rawSize = rawBox.getSize(new THREE.Vector3());
  const fp = footprints && footprints[typeId];
  const want = cfg.size != null ? Number(cfg.size)
    : (fp ? Math.max(fp.x, fp.z) : 0.72);
  const planar = Math.max(rawSize.x, rawSize.z, 1e-6);
  const scale = (want / planar) * (cfg.scale != null ? Number(cfg.scale) : 1);
  geo.scale(scale, scale, scale);

  geo.computeBoundingBox();
  const box = geo.boundingBox;
  const center = box.getCenter(new THREE.Vector3());
  geo.translate(
    -center.x + (Number(cfg.offX) || 0),
    -box.min.y + (Number(cfg.offY) || 0),
    -center.z + (Number(cfg.offZ) || 0) - (Number(cfg.fwd) || 0)
  );
  geo.computeBoundingBox();
  geo.computeBoundingSphere();

  const group = new THREE.Group();
  group.add(new THREE.Mesh(geo, mat()));
  group.userData.schem = {
    typeId,
    dims: rec.n,
    tris: rec.faces.length * 2,
    source: cfg.file,
    canonical: { nose: '-Z', up: '+Y', floorY: 0 }
  };
  return group;
}

// footprints: { type_id: {x, z} } — целевые габариты; масштаб запекается один раз.
export async function loadSchemModels(footprints, skipTypeIds = null) {
  let manifest;
  try {
    const res = await fetch('assets/models/meshes/index.json');
    if (!res.ok) return 0;
    manifest = await res.json();
  } catch { return 0; }
  let loaded = 0;
  for (const [typeId, cfg0] of Object.entries(manifest || {})) {
    const cfg = typeof cfg0 === 'string' ? { file: cfg0 } : cfg0;
    const file = cfg.file;
    if (!file || typeId.startsWith('_') || cache.has(typeId)) continue;
    if (footprints && !Object.prototype.hasOwnProperty.call(footprints, typeId)) continue;
    if (skipTypeIds && skipTypeIds.has(typeId)) continue;
    try {
      const rec = await (await fetch('assets/models/meshes/' + file)).json();
      const group = createSchemGroup(rec, typeId, cfg, footprints);
      cache.set(typeId, group);
      loaded += 1;
    } catch (e) {
      console.error('schem-модель не собралась: ' + file, e);
    }
  }
  return loaded;
}

function faces2tris(rec) { return rec.faces.length * 2; }

// createShipModel(type_id) -> THREE.Group | null (без масштабирования — запекает models3d)
export function createShipModel(typeId) {
  const g = cache.get(typeId);
  if (!g) return null;
  const copy = new THREE.Group();
  g.children.forEach((m) => {
    const mesh = new THREE.Mesh(m.geometry.clone(), m.material);
    mesh.castShadow = true; mesh.receiveShadow = false;
    copy.add(mesh);
  });
  copy.userData.schem = g.userData.schem;
  return copy;
}

export function hasSchemModel(typeId) { return cache.has(typeId); }
