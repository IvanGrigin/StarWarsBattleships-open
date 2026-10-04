/* demo/space_fx.js — космическое окружение вокруг/под гекс-полем 3D-сцены.
 *
 * Собирается одним вызовом buildSpaceFX(scene, renderer) из board3d.init;
 * пофреймовые обновления — через возвращённый хендлер:
 *   const fx = buildSpaceFX(scene, renderer);
 *   fx.update(dt, timeSeconds);  // в rAF-цикле board3d
 *   fx.dispose();                // при разборке сцены
 *
 * Состав:
 *   1. Туманность — сфера-купол r=120 (BackSide) с canvas-текстурой 512×256:
 *      тёмно-синий градиент + 4 мягких цветных пятна (фиолет/бирюза/оранж/синий)
 *      + россыпь мелких звёзд. Детерминировано (seeded PRNG mulberry32).
 *   2. Планета — газовый гигант r=18 в (-55, -26, -40): canvas-текстура
 *      (горизонтальные полосы охры/крема с шумом) + голубой атмосферный ободок
 *      (BackSide, additive).
 *   3. Астероиды — 12..16 низкополигональных камней (искажённый додекаэдр),
 *      дрейфуют под плоскостью поля (y −6..−2) по круговым орбитам вокруг центра.
 *   4. Кометы — раз в 6..14 с короткий аддитивный штрих в небе, затухает ~0.8 с.
 *   5. Дальний слой звёзд (Points) с мерцанием — opacity материала по синусу.
 *
 * Перф: туманность/планета/звёзды — статичные меши; в кадре двигаются только
 * астероиды, кометы (0..2 шт.) и opacity мерцающего слоя.
 */
import * as THREE from 'three';

// ---------- seeded PRNG (mulberry32) ----------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Стабильный хеш координат → [0,1): дубли вершин в non-indexed полиэдрах
// получают одинаковое смещение и меш не рвётся.
function vhash(x, y, z) {
  const s = Math.sin(x * 127.1 + y * 311.7 + z * 74.7) * 43758.5453;
  return s - Math.floor(s);
}

const UP_Y = new THREE.Vector3(0, 1, 0);

export function buildSpaceFX(scene, renderer) { // renderer пока не нужен — зарезервирован
  const rand = mulberry32(20260916);
  const root = new THREE.Group();
  root.name = 'spaceFX';
  scene.add(root);

  // ---------- текстуры (canvas, детерминированные) ----------

  function makeNebulaTexture() {
    const W = 512, H = 256;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const g = cv.getContext('2d');
    // тёмно-синяя база
    const base = g.createLinearGradient(0, 0, 0, H);
    base.addColorStop(0, '#070b1a');
    base.addColorStop(0.45, '#0b1330');
    base.addColorStop(1, '#04060c');
    g.fillStyle = base;
    g.fillRect(0, 0, W, H);
    // мягкие цветные пятна (радиальные градиенты, низкая непрозрачность)
    const blobs = [
      { x: 0.20, y: 0.42, r: 0.34, rgb: [122, 66, 205], a: 0.26 }, // фиолетовый
      { x: 0.60, y: 0.30, r: 0.30, rgb: [46, 188, 196], a: 0.18 }, // бирюзовый
      { x: 0.84, y: 0.66, r: 0.26, rgb: [226, 138, 58], a: 0.15 }, // оранжевый
      { x: 0.44, y: 0.78, r: 0.30, rgb: [64, 92, 220],  a: 0.20 }  // глубокий синий
    ];
    for (const b of blobs) {
      const cx = (b.x + (rand() - 0.5) * 0.06) * W;
      const cy = b.y * H;
      const rr = b.r * W;
      const rgb = b.rgb.join(',');
      const grad = g.createRadialGradient(cx, cy, 0, cx, cy, rr);
      grad.addColorStop(0, 'rgba(' + rgb + ',' + b.a + ')');
      grad.addColorStop(0.55, 'rgba(' + rgb + ',' + (b.a * 0.45).toFixed(3) + ')');
      grad.addColorStop(1, 'rgba(' + rgb + ',0)');
      g.fillStyle = grad;
      g.fillRect(cx - rr, cy - rr, rr * 2, rr * 2);
    }
    // россыпь мелких звёзд (с ручной обёрткой по горизонтальному шву)
    for (let i = 0; i < 620; i++) {
      const x = rand() * W, y = rand() * H;
      const r = rand() < 0.88 ? 0.4 + rand() * 0.6 : 1.0 + rand() * 0.8;
      const a = 0.25 + rand() * 0.75;
      const tint = rand();
      g.fillStyle = tint < 0.75
        ? 'rgba(255,255,255,' + a.toFixed(2) + ')'
        : tint < 0.9
          ? 'rgba(190,214,255,' + a.toFixed(2) + ')'
          : 'rgba(255,224,180,' + a.toFixed(2) + ')';
      const dots = [x];
      if (x < 3) dots.push(x + W);
      else if (x > W - 3) dots.push(x - W);
      for (const dx of dots) {
        g.beginPath();
        g.arc(dx, y, r, 0, Math.PI * 2);
        g.fill();
      }
    }
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = THREE.RepeatWrapping;     // без шва на стыке сферы
    tex.wrapT = THREE.ClampToEdgeWrapping;
    return tex;
  }

  function makePlanetTexture() {
    const W = 512, H = 256;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const g = cv.getContext('2d');
    // палитра газового гиганта: тёмно-коричневый → охра → крем
    const palette = [
      [116, 78, 46], [154, 110, 62], [196, 150, 92], [226, 198, 148], [240, 226, 190]
    ];
    for (let y = 0; y < H; y++) {
      const t = y / H;
      // сумма синусов → плавные, но «случайные» полосы
      let v = Math.sin(t * 21.7 + 1.7) * 0.55 + Math.sin(t * 43.3 + 4.2) * 0.28 + Math.sin(t * 8.9 + 0.6) * 0.17;
      v = (v + 1) / 2;
      const f = v * (palette.length - 1);
      const i0 = Math.min(palette.length - 1, Math.floor(f));
      const i1 = Math.min(palette.length - 1, i0 + 1);
      const k = f - i0;
      const c = palette[i0].map((ch, i) => Math.round(ch + (palette[i1][i] - ch) * k));
      g.fillStyle = 'rgb(' + c.join(',') + ')';
      g.fillRect(0, y, W, 1);
    }
    // затемнение полюсов
    let pg = g.createLinearGradient(0, 0, 0, H * 0.16);
    pg.addColorStop(0, 'rgba(38,28,20,0.6)');
    pg.addColorStop(1, 'rgba(38,28,20,0)');
    g.fillStyle = pg;
    g.fillRect(0, 0, W, H * 0.16);
    pg = g.createLinearGradient(0, H, 0, H * 0.84);
    pg.addColorStop(0, 'rgba(38,28,20,0.6)');
    pg.addColorStop(1, 'rgba(38,28,20,0)');
    g.fillStyle = pg;
    g.fillRect(0, H * 0.84, W, H * 0.16);
    // шум: горизонтальные мазки, тайлятся по левому/правому шву
    for (let i = 0; i < 900; i++) {
      const x = rand() * W, y = rand() * H;
      const w = 4 + rand() * 46, h = 0.6 + rand() * 1.6;
      const a = (0.04 + rand() * 0.1).toFixed(3);
      g.fillStyle = rand() < 0.5
        ? 'rgba(255,244,214,' + a + ')'
        : 'rgba(58,38,22,' + a + ')';
      for (const xo of [x - W, x, x + W]) g.fillRect(xo, y, w, h);
    }
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = THREE.RepeatWrapping;
    return tex;
  }

  function makeCometTexture() {
    // вертикальный градиент: голова (v=1, +Y плоскости) яркая, хвост прозрачный
    const cv = document.createElement('canvas');
    cv.width = 32; cv.height = 128;
    const g = cv.getContext('2d');
    const grad = g.createLinearGradient(0, 128, 0, 0);
    grad.addColorStop(0, 'rgba(255,255,255,0)');
    grad.addColorStop(0.55, 'rgba(190,220,255,0.35)');
    grad.addColorStop(0.85, 'rgba(235,245,255,0.9)');
    grad.addColorStop(1, 'rgba(255,255,255,1)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 32, 128);
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    return tex;
  }

  // ---------- 1. туманность-купол ----------

  const dome = new THREE.Mesh(
    new THREE.SphereGeometry(120, 48, 32),
    new THREE.MeshBasicMaterial({ map: makeNebulaTexture(), side: THREE.BackSide, depthWrite: false })
  );
  dome.renderOrder = -10;
  root.add(dome);

  // ---------- 2. планета + атмосфера ----------

  const planet = new THREE.Mesh(
    new THREE.SphereGeometry(18, 48, 32),
    new THREE.MeshStandardMaterial({ map: makePlanetTexture(), roughness: 1, metalness: 0 })
  );
  planet.position.set(-55, -26, -40);   // нижний угол кадра, за полем
  planet.rotation.z = 0.35;             // лёгкий наклон оси
  root.add(planet);

  const atmo = new THREE.Mesh(
    new THREE.SphereGeometry(18 * 1.06, 48, 32),
    new THREE.MeshBasicMaterial({
      color: 0x7fb4ff, transparent: true, opacity: 0.22,
      side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false
    })
  );
  atmo.position.copy(planet.position);
  root.add(atmo);

  // ---------- 3. астероиды под плоскостью поля ----------

  const asteroids = [];
  const nAst = 12 + Math.floor(rand() * 5); // 12..16
  const rockColors = [0x8a7a68, 0x6f6156, 0x7c6a58, 0x94826e, 0x655a4e];
  for (let i = 0; i < nAst; i++) {
    const geo = new THREE.DodecahedronGeometry(1, 0);
    const p = geo.attributes.position;
    for (let v = 0; v < p.count; v++) {
      const x = p.getX(v), y = p.getY(v), z = p.getZ(v);
      const f = 0.72 + vhash(x, y, z) * 0.56; // 0.72..1.28, стабильно для дублей вершин
      p.setXYZ(v, x * f, y * f, z * f);
    }
    geo.computeVertexNormals();
    const mat = new THREE.MeshStandardMaterial({
      color: rockColors[Math.floor(rand() * rockColors.length)],
      roughness: 0.95, metalness: 0.05, flatShading: true
    });
    const mesh = new THREE.Mesh(geo, mat);
    const s = 0.28 + rand() * 0.5;
    mesh.scale.set(s * (0.8 + rand() * 0.4), s * (0.8 + rand() * 0.4), s * (0.8 + rand() * 0.4));
    mesh.position.y = -6 + rand() * 4;
    root.add(mesh);
    asteroids.push({
      mesh,
      orbitR: 8 + rand() * 9,                                  // 8..17 вокруг центра
      yBase: -6 + rand() * 4,                                  // -6..-2 (под полем)
      speed: (0.03 + rand() * 0.06) * (rand() < 0.5 ? 1 : -1), // рад/с, медленно
      phase: rand() * Math.PI * 2,
      bobAmp: 0.25 + rand() * 0.4,
      bobSpeed: 0.3 + rand() * 0.4,
      spinX: (rand() - 0.5) * 0.5,
      spinY: (rand() - 0.5) * 0.5,
      spinZ: (rand() - 0.5) * 0.3
    });
  }

  // ---------- 4. кометы ----------

  const cometTex = makeCometTexture();
  const cometGeo = new THREE.PlaneGeometry(1, 1);
  const cometBaseMat = new THREE.MeshBasicMaterial({
    map: cometTex, transparent: true, opacity: 1,
    blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide
  });
  const comets = [];
  let nextCometAt = 3 + rand() * 4; // первая — быстро, дальше раз в 6..14 с

  function spawnComet(time) {
    if (comets.length >= 2) return;
    const az = rand() * Math.PI * 2;
    const d = 48 + rand() * 34;    // горизонтальная дистанция (за полем)
    const start = new THREE.Vector3(Math.cos(az) * d, 22 + rand() * 36, Math.sin(az) * d);
    const sgn = rand() < 0.5 ? 1 : -1;
    const dir = new THREE.Vector3(
      -Math.sin(az) * sgn + Math.cos(az) * (rand() - 0.5) * 0.5,
      -(0.12 + rand() * 0.3),
      Math.cos(az) * sgn + Math.sin(az) * (rand() - 0.5) * 0.5
    ).normalize();
    const mat = cometBaseMat.clone();
    const mesh = new THREE.Mesh(cometGeo, mat);
    mesh.scale.set(0.1 + rand() * 0.1, 6 + rand() * 6, 1); // тонкий длинный штрих
    mesh.quaternion.setFromUnitVectors(UP_Y, dir);
    mesh.position.copy(start);
    mesh.renderOrder = 5;
    root.add(mesh);
    comets.push({
      t0: time, start, dir,
      speed: 24 + rand() * 20,      // единиц/с
      life: 0.8 + rand() * 0.4,     // затухает за ~0.8 с
      mesh, mat, baseOpacity: 0.95
    });
  }

  // ---------- 5. дальние мерцающие звёзды ----------

  const nTw = 420;
  const twPos = new Float32Array(nTw * 3);
  for (let i = 0; i < nTw; i++) {
    const a = rand() * Math.PI * 2;
    const y = rand() * 1.3 - 0.2;
    const rr = 92 + rand() * 20;
    const s = Math.sqrt(Math.max(0, 1 - y * y));
    twPos[i * 3] = Math.cos(a) * s * rr;
    twPos[i * 3 + 1] = y * rr;
    twPos[i * 3 + 2] = Math.sin(a) * s * rr;
  }
  const twGeo = new THREE.BufferGeometry();
  twGeo.setAttribute('position', new THREE.BufferAttribute(twPos, 3));
  const twinkleMat = new THREE.PointsMaterial({
    color: 0xdce8ff, size: 0.8, sizeAttenuation: true,
    transparent: true, opacity: 0.8, depthWrite: false
  });
  root.add(new THREE.Points(twGeo, twinkleMat));

  // ---------- обновление ----------

  function update(dt, time) {
    // астероиды: круговой дрейф + небольшая вертикальная качка + вращение
    for (const a of asteroids) {
      const ang = a.phase + time * a.speed;
      a.mesh.position.set(
        Math.cos(ang) * a.orbitR,
        a.yBase + Math.sin(time * a.bobSpeed + a.phase) * a.bobAmp,
        Math.sin(ang) * a.orbitR
      );
      a.mesh.rotation.x += a.spinX * dt;
      a.mesh.rotation.y += a.spinY * dt;
      a.mesh.rotation.z += a.spinZ * dt;
    }
    // кометы по расписанию
    if (time >= nextCometAt) {
      spawnComet(time);
      nextCometAt = time + 6 + rand() * 8;
    }
    for (let i = comets.length - 1; i >= 0; i--) {
      const c = comets[i];
      const age = time - c.t0;
      if (age >= c.life) {
        c.mesh.removeFromParent();
        c.mat.dispose();
        comets.splice(i, 1);
        continue;
      }
      c.mesh.position.copy(c.start).addScaledVector(c.dir, c.speed * age);
      const fadeIn = Math.min(1, age / 0.12);
      const fadeOut = Math.max(0, 1 - Math.max(0, age - c.life * 0.45) / (c.life * 0.55));
      c.mat.opacity = c.baseOpacity * fadeIn * fadeOut;
    }
    // мерцание дальнего слоя: opacity материала по синусу
    twinkleMat.opacity = 0.45 + 0.3 * (0.5 + 0.5 * Math.sin(time * 1.9)) + 0.08 * Math.sin(time * 4.7 + 1.3);
  }

  function dispose() {
    root.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      const mats = Array.isArray(o.material) ? o.material : (o.material ? [o.material] : []);
      for (const m of mats) {
        if (m.map) m.map.dispose();
        m.dispose();
      }
    });
    cometTex.dispose();
    scene.remove(root);
  }

  return { update, dispose };
}
