// Декорации существуют в мировой 3D-сцене, а не в CSS под canvas:
// орбита камеры даёт параллакс, время — медленный собственный ход объектов.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createBlackHole } from './blackhole.js';
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js';

function seeded(seed) {
  let state = seed >>> 0;
  return () => ((state = (Math.imul(state, 1664525) + 1013904223) >>> 0) / 0x100000000);
}

function planetTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = 512; canvas.height = 256;
  const context = canvas.getContext('2d');
  const pixels = context.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
    const u = x / canvas.width * Math.PI * 2;
    const v = y / canvas.height * Math.PI;
    const n = Math.sin(6 * u + 3 * Math.sin(2 * v)) * 0.42
      + Math.sin(14 * u - 9 * v) * 0.23 + Math.sin(31 * u + 17 * v) * 0.12;
    const ice = Math.abs(Math.cos(v)) > 0.89;
    const land = n > 0.29;
    const cloud = Math.sin(20 * u + 7 * Math.sin(v * 3)) + Math.sin(42 * u - v * 19) > 1.55;
    const rgb = ice ? [135, 166, 182] : cloud ? [132, 165, 182]
      : land ? [54, 82, 88] : [17, 61, 99];
    const shade = 0.82 + 0.16 * Math.sin(v);
    const i = 4 * (y * canvas.width + x);
    pixels.data[i] = rgb[0] * shade;
    pixels.data[i + 1] = rgb[1] * shade;
    pixels.data[i + 2] = rgb[2] * shade;
    pixels.data[i + 3] = 255;
  }
  context.putImageData(pixels, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeStars(scene, count, range, height, size, color, opacity, seed) {
  const random = seeded(seed);
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    positions[i * 3] = (random() - 0.5) * range;
    positions[i * 3 + 1] = height + (random() - 0.5) * 8;
    positions[i * 3 + 2] = (random() - 0.5) * range;
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  const stars = new THREE.Points(geometry, new THREE.PointsMaterial({ color, size,
    sizeAttenuation: false, transparent: true, opacity, blending: THREE.AdditiveBlending,
    depthWrite: false }));
  scene.add(stars);
  return stars;
}

export function createSpaceEnvironment(scene) {
  scene.background = new THREE.Color(0x050c14);
  const farStars = makeStars(scene, 820, 130, -30, 1.15, 0xa8c9e6, 0.72, 0x5a17c0de);
  const brightStars = makeStars(scene, 90, 95, -19, 2.1, 0xe7f1f2, 0.63, 0x5a17c0df);
  const dustStars = makeStars(scene, 170, 48, -8, 1.3, 0x74bbdf, 0.38, 0x5a17c0e0);

  const planet = new THREE.Group();
  planet.position.set(-11, -13, 8.5);
  const globe = new THREE.Mesh(new THREE.SphereGeometry(7.3, 48, 32),
    new THREE.MeshStandardMaterial({ map: planetTexture(), roughness: 1, metalness: 0 }));
  planet.add(globe);
  const atmosphere = new THREE.Mesh(new THREE.SphereGeometry(7.5, 48, 32), new THREE.ShaderMaterial({
    uniforms: { glowColor: { value: new THREE.Color(0x5ab8f3) } },
    vertexShader: `varying vec3 vNormal; varying vec3 vEye;
      void main() {
        vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vEye = normalize(-viewPosition.xyz);
        gl_Position = projectionMatrix * viewPosition;
      }`,
    fragmentShader: `uniform vec3 glowColor; varying vec3 vNormal; varying vec3 vEye;
      void main() {
        float rim = pow(1.0 - max(dot(vNormal, vEye), 0.0), 3.0);
        gl_FragColor = vec4(glowColor, rim * 0.72);
      }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  }));
  planet.add(atmosphere);
  scene.add(planet);

  const station = new THREE.Group();
  station.position.set(12.5, -13, -11);
  const stationGeo = new THREE.SphereGeometry(3.4, 32, 20);
  station.add(new THREE.Mesh(stationGeo, new THREE.MeshStandardMaterial({ color: 0x2d3b45,
    roughness: 0.78, metalness: 0.52 })));
  station.add(new THREE.LineSegments(new THREE.WireframeGeometry(stationGeo),
    new THREE.LineBasicMaterial({ color: 0x8ca2ad, transparent: true, opacity: 0.18 })));
  const trench = new THREE.Mesh(new THREE.TorusGeometry(3.39, 0.04, 6, 64),
    new THREE.MeshBasicMaterial({ color: 0x8f564b, transparent: true, opacity: 0.72 }));
  trench.rotation.x = Math.PI / 2; station.add(trench);
  const dishPosition = new THREE.Vector3(0.75, 1.04, 3.14);
  const dish = new THREE.Mesh(new THREE.CircleGeometry(0.69, 32),
    new THREE.MeshBasicMaterial({ color: 0x172630, side: THREE.DoubleSide }));
  dish.position.copy(dishPosition); dish.lookAt(dishPosition.clone().multiplyScalar(2)); station.add(dish);
  const dishRim = new THREE.Mesh(new THREE.TorusGeometry(0.7, 0.04, 5, 32),
    new THREE.MeshBasicMaterial({ color: 0x7c919a }));
  dishRim.position.copy(dishPosition).multiplyScalar(1.007);
  dishRim.quaternion.copy(dish.quaternion); station.add(dishRim);
  scene.add(station);
  // Настоящая модель вместо процедурной станции: недостроенная Звезда Смерти II
  // (N8 / nathanmlange, Sketchfab, CC BY 4.0 — см. tools/play_v4/assets/decor/README.md).
  // Процедурная сфера остаётся, пока модель грузится, и если загрузка не удалась.
  new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).load('/assets/decor/death_star_ii.glb', gltf => {
    const model = gltf.scene;
    model.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(model, true);
    const span = Math.max(...bounds.getSize(new THREE.Vector3()).toArray());
    if (!Number.isFinite(span) || span <= 0) return;
    model.position.sub(bounds.getCenter(new THREE.Vector3()));
    const scaled = new THREE.Group();
    scaled.scale.setScalar(7.6 / span);
    scaled.rotation.set(0.35, 0.6, 0.12);                // недостроенная сторона — к камере
    scaled.add(model);
    model.traverse(o => {                                  // на тёмном фоне серый корпус тонет — лёгкое свечение текстуры
      if (!o.isMesh) return;
      for (const m of Array.isArray(o.material) ? o.material : [o.material]) {
        if (m.map && !m.emissiveMap) { m.emissive = new THREE.Color(0xffffff); m.emissiveMap = m.map; m.emissiveIntensity = 0.28; }
      }
    });
    for (const child of [...station.children]) station.remove(child);
    station.position.set(9.5, -12, -12.5);                 // ближе к центру кадра, не под правой панелью
    station.add(scaled);
  }, undefined, () => { /* фон необязателен: остаётся процедурная станция */ });

  // Та же размеченная модель, что доступна игре: никаких новых ассетов или
  // сторонних загрузок. Корабль расположен ниже поля и никогда не перехватывает клики.
  const capitalShip = new THREE.Group();
  capitalShip.name = 'background-home-one';
  capitalShip.position.set(8, -5, 0);
  scene.add(capitalShip);
  new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).load('/models/mc80_home_one.glb', gltf => {
    const model = gltf.scene;
    model.updateMatrixWorld(true);
    let bounds = new THREE.Box3().setFromObject(model, true);
    let size = bounds.getSize(new THREE.Vector3());
    if (size.y > 1.4 * Math.max(size.x, size.z)) {
      model.rotation.x = -Math.PI / 2;
      model.updateMatrixWorld(true);
      bounds = new THREE.Box3().setFromObject(model, true);
      size = bounds.getSize(new THREE.Vector3());
    }
    const span = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(span) || span <= 0) return;
    const tonedMaterials = new Set();
    model.traverse(object => {
      if (!object.isMesh) return;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) if (material?.color && !tonedMaterials.has(material)) {
        material.color.multiplyScalar(0.55);
        tonedMaterials.add(material);
      }
    });
    model.position.sub(bounds.getCenter(new THREE.Vector3()));
    const scaled = new THREE.Group();
    scaled.scale.setScalar(7.5 / span);
    scaled.add(model);
    capitalShip.add(scaled);
  }, undefined, () => {
    // Фоновый корабль необязателен: игровое поле работает и при ошибке загрузки.
  });

  const random = seeded(0x0a57e101);
  const rockGeometry = new THREE.IcosahedronGeometry(1, 0);
  const shardGeometry = new THREE.BoxGeometry(1, 0.12, 0.38);
  const rockMaterials = [0x252e36, 0x30383d, 0x3b3634].map(color =>
    new THREE.MeshStandardMaterial({ color, flatShading: true, roughness: 0.97, metalness: 0.08 }));
  const metalMaterial = new THREE.MeshStandardMaterial({ color: 0x364852,
    flatShading: true, roughness: 0.66, metalness: 0.55 });
  const debris = Array.from({ length: 30 }, (_, i) => {
    const shard = i % 5 === 0;
    const mesh = new THREE.Mesh(shard ? shardGeometry : rockGeometry,
      shard ? metalMaterial : rockMaterials[i % rockMaterials.length]);
    const size = shard ? 0.17 + random() * 0.33 : 0.1 + random() * 0.35;
    mesh.scale.setScalar(size);
    scene.add(mesh);
    return { mesh, radius: 8.8 + random() * 9.7, angle: random() * Math.PI * 2,
      height: -3.5 - random() * 5.3, speed: (0.006 + random() * 0.009) * (i % 2 ? 1 : -1),
      spin: 0.035 + random() * 0.12, phase: random() * Math.PI * 2 };
  });

  // Звезда системы вдали: текстура Солнца (Solar System Scope, CC BY 4.0) светится сама,
  // вокруг — мягкая корона. Вне поля, клики не перехватывает.
  const sun = new THREE.Group();
  sun.position.set(-18, -28, -30);                      // левый верхний угол кадра, ниже поля
  const sunGlobe = new THREE.Mesh(new THREE.SphereGeometry(3.2, 40, 24), new THREE.MeshBasicMaterial({ color: 0xffe2b0 }));
  new THREE.TextureLoader().load('/assets/planets/sun.webp', tex => {
    tex.colorSpace = THREE.SRGBColorSpace; sunGlobe.material.map = tex; sunGlobe.material.color.setRGB(2.2, 1.7, 1.2); sunGlobe.material.toneMapped = false; sunGlobe.material.needsUpdate = true;
  });
  sun.add(sunGlobe);
  const coronaTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 128;
    const g = c.getContext('2d'), grd = g.createRadialGradient(64, 64, 10, 64, 64, 64);
    grd.addColorStop(0, 'rgba(255,236,190,.95)'); grd.addColorStop(0.35, 'rgba(255,180,90,.35)'); grd.addColorStop(1, 'rgba(255,140,60,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
    const x = new THREE.CanvasTexture(c); x.colorSpace = THREE.SRGBColorSpace; return x;
  })();
  const corona = new THREE.Sprite(new THREE.SpriteMaterial({ map: coronaTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
  corona.scale.setScalar(22);
  sun.add(corona);
  const halo = new THREE.Sprite(corona.material.clone()); halo.scale.setScalar(11); halo.material.opacity = 0.9; sun.add(halo);   // яркое ядро короны
  scene.add(sun);

  // Настоящая текстура планеты, если она положена в tools/play_v4/assets/planets/<имя>.webp;
  // иначе остаётся процедурная. Имя выбирает игра по эпохе партии.
  let planetName = null;
  function setPlanet(name) {
    if (!name || name === planetName) return;
    planetName = name;
    new THREE.TextureLoader().load(`/assets/planets/${name}.webp`, tex => {
      if (planetName !== name) return;
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.anisotropy = 4;
      globe.material.map = tex;
      globe.material.needsUpdate = true;
    }, undefined, () => { /* текстуры нет — процедурная планета */ });
  }

  // Место боя «у чёрной дыры»: вместо планеты и Солнца — чёрная дыра с аккреционным диском (blackhole.js).
  const blackHole = createBlackHole(30);
  blackHole.mesh.position.set(-13, -16, 7);             // внизу сбоку, на месте планеты — поле не перекрывает            // под полем и за ним: диск виден сквозь клетки
  blackHole.mesh.visible = false;
  scene.add(blackHole.mesh);
  let cameraRef = null;
  function setPlace(place, camera) {
    cameraRef = camera;
    const bh = place === 'blackhole';
    blackHole.mesh.visible = bh;
    planet.visible = !bh;
    sun.visible = !bh;
    station.visible = !bh;                               // рядом с чёрной дырой — ничего лишнего
  }

  function update(elapsedSeconds, reduceMotion = false) {
    const t = reduceMotion ? 0 : elapsedSeconds;
    farStars.rotation.y = t * 0.0009;
    brightStars.rotation.y = -t * 0.0015;
    dustStars.rotation.y = t * 0.003;
    brightStars.material.opacity = reduceMotion ? 0.63 : 0.57 + 0.08 * Math.sin(t * 0.7);
    globe.rotation.y = t * 0.0013;
    if (blackHole.mesh.visible && cameraRef) blackHole.update(reduceMotion ? 0 : elapsedSeconds, cameraRef);
    sunGlobe.rotation.y = t * 0.004;
    corona.material.rotation = t * 0.01;
    station.rotation.y = t * 0.0019;
    capitalShip.position.set(8 - 2.5 * Math.sin(t * 0.009), -5 + 0.25 * Math.sin(t * 0.015),
      0.8 * Math.sin(t * 0.007));
    capitalShip.rotation.y = 0.25 + 0.12 * Math.sin(t * 0.011);
    for (const item of debris) {
      const a = item.angle + t * item.speed;
      item.mesh.position.set(Math.cos(a) * item.radius,
        item.height + (reduceMotion ? 0 : 0.12 * Math.sin(t * 0.45 + item.phase)),
        Math.sin(a) * item.radius);
      item.mesh.rotation.set(item.phase + t * item.spin, a + t * item.spin * 0.7,
        item.phase * 0.5 + t * item.spin * 0.4);
    }
  }
  update(0);
  return { update, setPlanet, setPlace, blackHole, planet, station, capitalShip, debris, farStars, brightStars, dustStars };
}
