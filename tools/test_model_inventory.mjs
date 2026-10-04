import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');
const manifest = JSON.parse(read('demo/assets/models/meshes/index.json'));
const entries = Object.entries(manifest).filter(([id, cfg]) => !id.startsWith('_') && cfg?.file);
const meshDir = path.join(root, 'demo/assets/models/meshes');
const files = fs.readdirSync(meshDir).filter((f) => f.endsWith('.json') && f !== 'index.json').sort();
const indexedFiles = entries.map(([, cfg]) => cfg.file).sort();

assert.equal(entries.length, 26, 'Minecraft-каталог должен содержать 26 моделей');
assert.deepEqual(indexedFiles, files, 'каждый Minecraft mesh должен быть индексирован ровно один раз');
for (const [id, cfg] of entries) {
  const rec = JSON.parse(fs.readFileSync(path.join(meshDir, cfg.file), 'utf8'));
  assert.equal(rec.n.length, 3, `${id}: нужны три размера`);
  assert.ok(rec.faces.length > 0, `${id}: модель не должна быть пустой`);
}

const shipsContext = {};
vm.runInNewContext(read('demo/ships.js'), shipsContext, { filename: 'ships.js' });
const gameTypes = Object.keys(shipsContext.SWBShips.SHIP_DB);
assert.equal(gameTypes.length, 11, 'в игровом ростере должно быть 11 типов');

const mockContext = {};
vm.runInNewContext(read('demo/mock_core.js'), mockContext, { filename: 'mock_core.js' });
const state = JSON.parse(mockContext.swb.create_match(12345, 60));
assert.equal(state.ships.length, 6, 'демо-бой должен стартовать как 3×3');
assert.deepEqual([...new Set(state.ships.map((s) => s.seat))].sort(), ['A1', 'B1']);
assert.equal(new Set(state.ships.map((s) => `${s.q},${s.r}`)).size, 6, 'стартовые клетки не должны пересекаться');
for (const ship of state.ships) {
  const radius = Math.max(Math.abs(ship.q), Math.abs(ship.r), Math.abs(-ship.q - ship.r));
  assert.ok(radius <= 3, `${ship.id}: старт вне поля радиуса 3`);
  assert.ok(gameTypes.includes(ship.type_id), `${ship.id}: неизвестный игровой тип`);
  assert.ok(ship.facing >= 0 && ship.facing < 6, `${ship.id}: неверный курс`);
}

console.log(`OK: ${gameTypes.length} игровых типов, ${entries.length} Minecraft-моделей, старт 3×3 внутри radius=3`);
