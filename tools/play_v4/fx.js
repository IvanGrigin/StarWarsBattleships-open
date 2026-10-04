// Боевые эффекты поля: лазерные выстрелы, попадание в щит и корпус, взрыв корабля с обломками.
// Только визуальные объекты сцены — на правила и клики не влияют (не участвуют в raycast по клеткам).
import * as THREE from 'three';

const add = { transparent: true, blending: THREE.AdditiveBlending, depthWrite: false };
const boltGeo = new THREE.CylinderGeometry(0.05, 0.05, 1.0, 6, 1, true); boltGeo.rotateX(Math.PI / 2);
const glowGeo = new THREE.CylinderGeometry(0.15, 0.15, 1.1, 8, 1, true); glowGeo.rotateX(Math.PI / 2);
const sphereGeo = new THREE.SphereGeometry(1, 20, 14);
const ringGeo = new THREE.RingGeometry(0.85, 1, 48); ringGeo.rotateX(-Math.PI / 2);
const shardGeos = [new THREE.TetrahedronGeometry(0.09), new THREE.BoxGeometry(0.14, 0.03, 0.08), new THREE.TetrahedronGeometry(0.06)];
const shardMat = new THREE.MeshStandardMaterial({ color: 0x8b95a6, metalness: 0.6, roughness: 0.45, emissive: 0x2a1204 });

function sparkTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.25, 'rgba(255,220,150,.9)');
  grd.addColorStop(0.6, 'rgba(255,120,40,.35)'); grd.addColorStop(1, 'rgba(255,80,20,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const SPARK = sparkTexture();

export function createFx(scene) {
  const live = [];                       // {obj, t, dur, step(k, dt)} — k: 0…1 доля жизни
  const spawn = (obj, dur, step) => { scene.add(obj); live.push({ obj, t: 0, dur, step }); step(0, 0); };

  function burst(pos, { n = 40, color = 0xffb060, speed = 2.2, size = 0.28, dur = 0.9, up = 0.6 } = {}) {
    const g = new THREE.BufferGeometry();
    const p = new Float32Array(n * 3), v = [];
    for (let i = 0; i < n; i++) {
      p.set([pos.x, pos.y, pos.z], i * 3);
      const d = new THREE.Vector3(Math.random() - 0.5, Math.random() * up, Math.random() - 0.5).normalize()
        .multiplyScalar(speed * (0.35 + Math.random()));
      v.push(d);
    }
    g.setAttribute('position', new THREE.BufferAttribute(p, 3));
    const mat = new THREE.PointsMaterial({ map: SPARK, color, size, ...add, opacity: 1 });
    const pts = new THREE.Points(g, mat);
    spawn(pts, dur, (k, dt) => {
      const a = g.attributes.position.array;
      for (let i = 0; i < n; i++) {
        v[i].multiplyScalar(1 - 1.8 * dt); v[i].y -= 0.6 * dt;
        a[i * 3] += v[i].x * dt; a[i * 3 + 1] += v[i].y * dt; a[i * 3 + 2] += v[i].z * dt;
      }
      g.attributes.position.needsUpdate = true;
      mat.opacity = 1 - k;
    });
  }

  function flashBall(pos, color, r0, r1, dur, opacity = 0.9) {
    const m = new THREE.Mesh(sphereGeo, new THREE.MeshBasicMaterial({ color, ...add, opacity }));
    m.position.copy(pos);
    spawn(m, dur, k => { m.scale.setScalar(r0 + (r1 - r0) * Math.sqrt(k)); m.material.opacity = opacity * (1 - k) ** 1.5; });
  }

  // Лазер: несколько коротких болтов летят от носа к цели; промах — уходят мимо.
  function laser(from, to, { color = 0xff4a4a, hit = true, shots = 2 } = {}) {
    return new Promise(res => {
      const a = from.clone().setY(0.45), b = to.clone().setY(0.45);
      if (!hit) b.add(new THREE.Vector3(Math.random() - 0.5, 0.25, Math.random() - 0.5).multiplyScalar(1.6)).lerp(a, -0.6);
      const len = a.distanceTo(b), speed = 9;
      const dur = Math.max(0.32, len / speed);                // даже в упор выстрел заметен
      for (let i = 0; i < shots; i++) {
        const side = new THREE.Vector3().subVectors(b, a).cross(new THREE.Vector3(0, 1, 0)).normalize().multiplyScalar((i - (shots - 1) / 2) * 0.16);
        const g = new THREE.Group();
        g.add(new THREE.Mesh(boltGeo, new THREE.MeshBasicMaterial({ color: 0xffffff, ...add, opacity: 1 })));
        g.add(new THREE.Mesh(glowGeo, new THREE.MeshBasicMaterial({ color, ...add, opacity: 0.8 })));
        g.lookAt(b.clone().sub(a));
        const A = a.clone().add(side), B = b.clone().add(side);
        g.visible = false;
        const delay = i * 0.09;
        spawn(g, dur + delay, (k, dt, t) => {
          const u = Math.max(0, (t - delay) / dur);
          g.visible = u > 0 && u < 1;
          g.position.lerpVectors(A, B, Math.min(1, u));
          g.lookAt(B.clone().add(B.clone().sub(A)));
        });
      }
      flashBall(a, color, 0.08, 0.35, 0.18, 0.8);         // вспышка у ствола
      setTimeout(res, (dur + 0.09 * (shots - 1)) * 1000);
    });
  }

  function impact(pos, { shield = false } = {}) {
    const p = pos.clone().setY(0.45);
    if (shield) {                                          // щит принял удар: голубая сфера мигает
      const m = new THREE.Mesh(sphereGeo, new THREE.MeshBasicMaterial({ color: 0x6fc8ff, ...add, opacity: 0.55, side: THREE.DoubleSide }));
      m.position.copy(p);
      spawn(m, 0.55, k => { m.scale.setScalar(0.75 + 0.2 * k); m.material.opacity = 0.55 * (1 - k); });
      burst(p, { n: 18, color: 0x9fdcff, speed: 1.6, size: 0.18, dur: 0.5 });
    } else {
      flashBall(p, 0xffc070, 0.1, 0.5, 0.3);
      burst(p, { n: 28, color: 0xffa050, speed: 2.4, size: 0.2, dur: 0.7 });
    }
  }

  // Взрыв: вспышка, ударная волна, огонь, дым-искры и обломки самой модели (её меши разлетаются).
  function explode(pos, model) {
    const p = pos.clone().setY(0.4);
    const light = new THREE.PointLight(0xffa040, 30, 7, 2); light.position.copy(p).setY(1.2);
    spawn(light, 0.9, k => { light.intensity = 30 * (1 - k) ** 2; });
    flashBall(p, 0xfff2c0, 0.25, 1.5, 0.35, 1);
    flashBall(p, 0xff7a2a, 0.4, 2.2, 1.0, 0.75);
    for (let i = 1; i <= 3; i++) {                          // цепочка вторичных взрывов по корпусу
      const q = p.clone().add(new THREE.Vector3((Math.random() - 0.5) * 0.9, 0.1, (Math.random() - 0.5) * 0.9));
      setTimeout(() => { flashBall(q, 0xffb050, 0.15, 0.9, 0.45, 0.9); burst(q, { n: 30, color: 0xffb060, speed: 2.4, size: 0.3, dur: 0.8 }); }, 120 * i + Math.random() * 80);
    }
    const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0xffc27a, ...add, opacity: 0.8, side: THREE.DoubleSide }));
    ring.position.copy(p).setY(0.12);
    spawn(ring, 0.9, k => { ring.scale.setScalar(0.3 + 3.2 * k); ring.material.opacity = 0.8 * (1 - k); });
    burst(p, { n: 140, color: 0xff9a40, speed: 3.8, size: 0.45, dur: 1.4, up: 1 });
    burst(p, { n: 40, color: 0xfff0c0, speed: 4.5, size: 0.16, dur: 0.7, up: 1 });
    const pieces = [];
    if (model) {
      model.updateMatrixWorld(true);
      model.traverse(o => {
        if (!o.isMesh || pieces.length > 40) return;
        const m = new THREE.Mesh(o.geometry, o.material);
        o.matrixWorld.decompose(m.position, m.quaternion, m.scale);
        pieces.push(m);
      });
    }
    for (let i = 0; i < 14; i++) {                          // рваные куски обшивки — всегда, даже у цельной модели
      const m = new THREE.Mesh(shardGeos[i % 3], shardMat);
      m.position.copy(p).add(new THREE.Vector3((Math.random() - 0.5) * 0.3, 0, (Math.random() - 0.5) * 0.3));
      pieces.push(m);
    }
    for (const m of pieces) {
      const v = new THREE.Vector3(m.position.x - p.x + (Math.random() - 0.5) * 0.6, 0.4 + Math.random() * 1.1,
        m.position.z - p.z + (Math.random() - 0.5) * 0.6).normalize().multiplyScalar(1.2 + Math.random() * 2.2);
      const spin = new THREE.Vector3(Math.random(), Math.random(), Math.random()).multiplyScalar(8);
      const s0 = m.scale.clone();
      spawn(m, 1.6 + Math.random() * 0.5, (k, dt) => {
        v.multiplyScalar(1 - 1.2 * dt); v.y -= 1.4 * dt;
        m.position.addScaledVector(v, dt);
        m.rotation.x += spin.x * dt; m.rotation.y += spin.y * dt; m.rotation.z += spin.z * dt;
        m.scale.copy(s0).multiplyScalar(Math.max(0.001, 1 - k * k));
      });
    }
  }

  function update(dt) {
    for (let i = live.length - 1; i >= 0; i--) {
      const f = live[i];
      f.t += dt;
      const k = Math.min(1, f.t / f.dur);
      f.step(k, dt, f.t);
      if (k >= 1) { scene.remove(f.obj); live.splice(i, 1); }
    }
  }
  return { laser, impact, explode, update, get busy() { return live.length > 0; } };
}
