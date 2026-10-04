import assert from 'node:assert/strict';
import {
  DIR_DELTAS, axialToWorld, directionOffset, facingDegrees,
  facingRotY, noseVectorForFacing, normalizeFacing
} from '../demo/orientation.js';

const eps = 1e-12;
for (let facing = 0; facing < 6; facing++) {
  const [dq, dr] = DIR_DELTAS[facing];
  const expected = axialToWorld(dq, dr);
  const length = Math.hypot(expected.x, expected.z);
  const nose = noseVectorForFacing(facing);
  assert.ok(Math.abs(nose.x - expected.x / length) < eps, `facing ${facing}: x`);
  assert.ok(Math.abs(nose.z - expected.z / length) < eps, `facing ${facing}: z`);
  assert.deepEqual(directionOffset(facing, 2, 0.5), axialToWorld(dq, dr));
  assert.equal(facingRotY(facing), facingDegrees(facing) * Math.PI / 180);
}

assert.equal(normalizeFacing(-1), 5);
assert.equal(normalizeFacing(6), 0);
assert.deepEqual([0, 1, 2, 3, 4, 5].map(facingDegrees), [30, -30, -90, -150, -210, -270]);
console.log('orientation OK: nose -Z matches all six axial directions');
