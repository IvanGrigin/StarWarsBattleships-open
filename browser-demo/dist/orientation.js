// Единый контракт ориентации поля и всех 3D-моделей.
// Модель до установки на поле: нос -Z, верх +Y, центр по XZ в (0, 0).

export const DIR_DELTAS = Object.freeze([
  Object.freeze([0, -1]),
  Object.freeze([1, -1]),
  Object.freeze([1, 0]),
  Object.freeze([0, 1]),
  Object.freeze([-1, 1]),
  Object.freeze([-1, 0]),
]);

export const SQRT3 = Math.sqrt(3);

export function normalizeFacing(facing) {
  return ((Number(facing) % 6) + 6) % 6;
}

export function axialToWorld(q, r, cell = 1) {
  return {
    x: SQRT3 * cell * (q + r / 2),
    z: 1.5 * cell * r,
  };
}

export function directionOffset(facing, cell = 1, distance = 1) {
  const [dq, dr] = DIR_DELTAS[normalizeFacing(facing)];
  const p = axialToWorld(dq, dr, cell);
  return { x: p.x * distance, z: p.z * distance };
}

// Three.js: положительный rotation.y вращает локальный нос -Z в сторону -X.
export function facingDegrees(facing) {
  return 30 - 60 * normalizeFacing(facing);
}

export function facingRotY(facing) {
  return facingDegrees(facing) * Math.PI / 180;
}

export function noseVectorForFacing(facing) {
  const a = facingRotY(facing);
  return { x: -Math.sin(a), z: -Math.cos(a) };
}
