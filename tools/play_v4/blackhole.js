// Чёрная дыра фона — как на известных визуализациях («Гаргантюа» из «Интерстеллара», снимки EHT):
// чёрная тень горизонта, горячий аккреционный диск, его дальняя часть, изогнутая гравитацией дугой
// над и под тенью, тонкое фотонное кольцо и доплеровская асимметрия (приближающаяся сторона ярче).
// Считается трассировкой лучей в шейдере: каждый пиксель — луч, который гнётся по формуле для
// метрики Шварцшильда (ускорение −1.5·h²·r/|r|⁵, единица длины — радиус Шварцшильда).
// Это квадрат-«билборд» в сцене: всегда повёрнут к камере, клики не перехватывает.
import * as THREE from 'three';

const vertexShader = `varying vec2 vUv; void main() { vUv = uv * 2.0 - 1.0; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const fragmentShader = `
precision highp float;
varying vec2 vUv;
uniform float uTime, uTilt;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
}
float fbm(vec2 p) { float s = 0.0, a = 0.5; for (int i = 0; i < 4; i++) { s += a * noise(p); p *= 2.07; a *= 0.5; } return s; }

const float R_IN = 2.6, R_OUT = 11.0;           // внутренний край ~ последняя устойчивая орбита (3 r_s), наружный
vec3 diskColor(vec3 p, vec3 dir) {
  float r = length(p.xz);
  float phi = atan(p.z, p.x);
  float t = clamp((r - R_IN) / (R_OUT - R_IN), 0.0, 1.0);
  // температура: у внутреннего края бело-жёлтый, дальше оранжевый и тёмно-красный
  vec3 hot = vec3(1.0, 0.93, 0.78), warm = vec3(1.0, 0.55, 0.18), cool = vec3(0.55, 0.12, 0.04);
  vec3 c = mix(hot, warm, smoothstep(0.0, 0.45, t));
  c = mix(c, cool, smoothstep(0.45, 1.0, t));
  // турбулентные кольца, вращаются: внутренние быстрее (кеплеровская скорость)
  float swirl = phi + uTime * 0.9 / pow(r, 1.5) * 6.0;
  float n = fbm(vec2(r * 2.3, swirl * 3.0)) * 0.75 + 0.45 * fbm(vec2(r * 7.0, swirl * 9.0));
  float bright = pow(1.0 - t, 1.6) * 2.4 + 0.15;
  // доплер: сторона, летящая к наблюдателю, ярче и белее
  vec3 v = normalize(vec3(-p.z, 0.0, p.x));
  float dop = 1.0 + 0.75 * dot(v, -normalize(dir));
  bright *= pow(dop, 3.0) * n;
  c = mix(c, vec3(1.0, 0.97, 0.9), clamp((dop - 1.0) * 0.6, 0.0, 0.5));
  float edge = smoothstep(0.0, 0.06, t) * (1.0 - smoothstep(0.8, 1.0, t));
  return c * bright * edge;
}

void main() {
  float d2 = dot(vUv, vUv);
  if (d2 > 1.0) discard;
  float D = 26.0;                                  // расстояние наблюдателя (в радиусах Шварцшильда)
  vec3 ro = vec3(0.0, D * sin(uTilt), -D * cos(uTilt));
  vec3 fw = normalize(-ro), rt = normalize(cross(vec3(0.0, 1.0, 0.0), fw)), up = cross(fw, rt);
  vec3 dir = normalize(fw + (vUv.x * rt + vUv.y * up) * 0.62);
  vec3 pos = ro, vel = dir;
  vec3 h = cross(pos, vel); float h2 = dot(h, h);
  vec3 col = vec3(0.0); float alpha = 0.0;
  for (int i = 0; i < 260; i++) {
    float r2 = dot(pos, pos);
    if (r2 < 1.0) { alpha = 1.0; break; }                        // горизонт событий: свет не возвращается
    float dt = clamp(0.07 * sqrt(r2), 0.015, 0.9);
    vec3 prev = pos;
    vel += -1.5 * h2 * pos / pow(r2, 2.5) * dt;
    pos += vel * dt;
    if (prev.y * pos.y < 0.0) {                                 // луч пересёк плоскость диска
      vec3 p = mix(prev, pos, prev.y / (prev.y - pos.y));
      float r = length(p.xz);
      if (r > R_IN && r < R_OUT) {
        vec3 c = diskColor(p, vel);
        float a = clamp(length(c) * 0.9, 0.0, 0.97);
        col += (1.0 - alpha) * c;
        alpha += (1.0 - alpha) * a;
        if (alpha > 0.99) break;
      }
    }
    if (r2 > D * D * 1.6 && dot(pos, vel) > 0.0) break;         // улетел прочь
  }
  // лёгкое свечение вокруг (как на снимках — ореол от яркого диска)
  float glow = exp(-6.0 * max(0.0, sqrt(d2) - 0.28)) * 0.06;
  col += vec3(1.0, 0.6, 0.3) * glow * (1.0 - alpha);
  alpha = max(alpha, glow);
  float fade = 1.0 - smoothstep(0.85, 1.0, sqrt(d2));          // края квадрата не видны
  col = col / (1.0 + col * 0.35);                                // мягкая тональная компрессия, без пересвета
  gl_FragColor = vec4(col * fade, alpha * fade);
}`;

export function createBlackHole(size = 40) {
  const mat = new THREE.ShaderMaterial({
    vertexShader, fragmentShader,
    uniforms: { uTime: { value: 0 }, uTilt: { value: 0.16 } },   // наклон диска к наблюдателю ~9°
    transparent: true, depthWrite: false,
    blending: THREE.CustomBlending, blendSrc: THREE.OneFactor, blendDst: THREE.OneMinusSrcAlphaFactor,  // цвет уже умножен на альфу
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), mat);
  mesh.name = 'background-black-hole';
  mesh.renderOrder = -1;
  mesh.raycast = () => {};
  return {
    mesh,
    update(t, camera, rotationZ = -0.12) {
      mat.uniforms.uTime.value = t;
      mesh.quaternion.copy(camera.quaternion);
      mesh.rotateZ(rotationZ);                                   // диск чуть наклонён на экране, как на кадрах фильма
    },
  };
}
