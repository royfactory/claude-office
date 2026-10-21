// 3D 사무실(쿼터뷰). 프로젝트 하나 = 층 하나, 세션·서브에이전트 = 사람.
// 상태는 /api/stream(SSE)으로 받고, 방·가구는 코드로 만든 단순한 도형이다.
import * as THREE from "/static/vendor/three.module.min.js";

const { roomForTool, assignCharacters, lookFor, esc, ago } = window.Office;
const $ = id => document.getElementById(id);

// ---------- 평면도 ----------
// 3열(A·B·C) × 3줄(뒤·가운데·앞). 줄 사이는 가로 복도(z=-3, z=6), 열 사이는 세로 복도(x=-6.75, x=3.875).
const COL = { A: [-17, -7.75], B: [-5.75, 2.75], C: [5, 17] };
const ROW = { back: [-12, -4], mid: [-2, 5], front: [7, 12] };
const CORR = { back: -3, mid: -3, front: 6 };
const VX = [-6.75, 3.875];
const EN = { library: "LIBRARY", dev: "DEV", server: "SERVER", search: "SEARCH", meeting: "MEETING", mydesk: "MY DESK", lounge: "LOUNGE" };
const LAYOUT = {
  library: { col: "A", row: "back", floor: 0xeadfca },
  meeting: { col: "B", row: "back", floor: 0xe2e7ee },
  dev:     { col: "C", row: "back", floor: 0xe9ecf1 },
  lounge:  { col: "A", row: "mid",  floor: 0xf0e2d0 },
  mydesk:  { col: "B", row: "mid",  floor: 0xd3e3f6 },
  server:  { col: "C", row: "mid",  floor: 0xdfe3ea },
  search:  { col: "B", row: "front", floor: 0xd5eee3 },
};
const ELEV = { x0: -17, x1: -13, z0: 7, z1: 12, door: [-15, 7], corr: 6, inside: [-15, 9.6] };
const R = {};
for (const [id, l] of Object.entries(LAYOUT)) {
  const [x0, x1] = COL[l.col], [z0, z1] = ROW[l.row];
  const doorZ = l.row === "front" ? z0 : (l.row === "mid" ? z0 : z1);
  R[id] = { id, x0, x1, z0, z1, cx: (x0 + x1) / 2, cz: (z0 + z1) / 2, door: [(x0 + x1) / 2, doorZ], corr: CORR[l.row], seats: [], color: l.floor };
}

// ---------- 장면 ----------
const stage = $("stage"), canvas = $("scene"), labels = $("labels");
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
} catch (e) {
  $("nogl").style.display = "grid";
  throw e;
}
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);
const CAM_OFFSET = new THREE.Vector3(34, 30, 34);
const ELEV_SIN = Math.sin(Math.atan2(30, Math.hypot(34, 34)));
const target = new THREE.Vector3(0, 0, 0.5);
let viewH = 30;

const hemi = new THREE.HemisphereLight(0xffffff, 0xaab4c4, 1.25);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 1.7);
sun.position.set(16, 34, 12);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -26, right: 26, top: 26, bottom: -26, near: 1, far: 90 });
sun.shadow.bias = -0.0004;
scene.add(sun);

const BOX = new THREE.BoxGeometry(1, 1, 1);
const CYL = new THREE.CylinderGeometry(1, 1, 1, 20);
const SPH = new THREE.SphereGeometry(1, 20, 14);
const mats = new Map();
const mat = (c, extra) => {
  const k = c + (extra ? JSON.stringify(extra) : "");
  if (!mats.has(k)) mats.set(k, new THREE.MeshStandardMaterial({ color: c, roughness: 0.85, ...(extra || {}) }));
  return mats.get(k);
};
function box(w, h, d, c, x, y, z, o = {}) {
  const m = new THREE.Mesh(BOX, o.mat || mat(c));
  m.scale.set(w, h, d);
  m.position.set(x, y + h / 2, z);
  m.castShadow = o.cast !== false;
  m.receiveShadow = true;
  if (o.ry) m.rotation.y = o.ry;
  (o.parent || scene).add(m);
  return m;
}
function cyl(r, h, c, x, y, z, o = {}) {
  const m = new THREE.Mesh(CYL, o.mat || mat(c));
  m.scale.set(r, h, r);
  m.position.set(x, y + h / 2, z);
  m.castShadow = true; m.receiveShadow = true;
  (o.parent || scene).add(m);
  return m;
}
function ball(r, c, x, y, z) {
  const m = new THREE.Mesh(SPH, mat(c));
  m.scale.setScalar(r);
  m.position.set(x, y, z);
  m.castShadow = true;
  scene.add(m);
  return m;
}
function plant(x, z, s = 1) {
  cyl(0.32 * s, 0.5 * s, 0xc9a27a, x, 0, z);
  ball(0.55 * s, 0x5fae6e, x, 0.95 * s, z);
  ball(0.38 * s, 0x6cc07a, x + 0.25 * s, 1.35 * s, z - 0.1 * s);
}
function chair(x, z, c = 0x3b5bdb, face = 0) { // face: 의자 등받이가 놓일 방향(라디안)
  const g = new THREE.Group();
  box(0.55, 0.08, 0.55, c, 0, 0.42, 0, { parent: g });
  box(0.55, 0.55, 0.08, c, 0, 0.5, -0.26, { parent: g });
  box(0.06, 0.42, 0.06, 0x64748b, 0, 0, 0, { parent: g });
  g.position.set(x, 0, z); g.rotation.y = face;
  scene.add(g);
}
function desk(x, z) {
  box(1.7, 0.07, 0.85, 0xf8fafc, x, 0.72, z);
  box(0.07, 0.72, 0.8, 0xcbd5e1, x - 0.8, 0, z);
  box(0.07, 0.72, 0.8, 0xcbd5e1, x + 0.8, 0, z);
  box(0.75, 0.45, 0.05, 0x1e293b, x, 0.95, z - 0.25);
  box(0.7, 0.38, 0.02, 0x60a5fa, x, 0.985, z - 0.22, { mat: mat(0x60a5fa, { emissive: 0x1d4ed8, emissiveIntensity: 0.35 }) });
  box(0.1, 0.18, 0.1, 0x334155, x, 0.79, z - 0.25);
}

// ---------- 글자 텍스처 ----------
const FONT = `-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`;
const EMOJI_FONT = `"Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif`;
function signTexture(emoji, name, en) {
  // 글자 길이에 맞춰 캔버스 폭을 정한다(간판 판의 가로세로 비율도 이걸 따른다)
  const c = document.createElement("canvas"), g = c.getContext("2d");
  g.font = `700 54px ${FONT}`; const wn = g.measureText(name).width;
  g.font = `600 34px ${FONT}`; const we = g.measureText("· " + en).width;
  c.width = Math.ceil(112 + wn + 16 + we + 28); c.height = 104;
  g.fillStyle = "rgba(255,255,255,0.55)"; roundRect(g, 2, 2, c.width - 4, 100, 22); g.fill();  // 바탕만 반투명, 글자는 진하게
  g.textBaseline = "middle";
  g.font = `60px ${EMOJI_FONT}`; g.fillText(emoji || "", 24, 56);
  g.fillStyle = "#1f2937"; g.font = `700 54px ${FONT}`; g.fillText(name, 104, 55);
  g.fillStyle = "#475569"; g.font = `600 34px ${FONT}`; g.fillText("· " + en, 104 + wn + 16, 57);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  t.userData.aspect = c.width / c.height;
  return t;
}
function roundRect(g, x, y, w, h, r) {
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
}
const emojiTex = new Map();
function emojiTexture(e) {
  if (!emojiTex.has(e)) {
    const c = document.createElement("canvas"); c.width = c.height = 128;
    const g = c.getContext("2d");
    g.font = `104px ${EMOJI_FONT}`; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(e, 64, 72);
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
    emojiTex.set(e, t);
  }
  return emojiTex.get(e);
}
const imgTex = new Map();
const loader = new THREE.TextureLoader();
function imageTexture(name, pixel) {
  const k = name + (pixel ? ":px" : "");
  if (!imgTex.has(k)) {
    const t = loader.load(`/assets/${encodeURIComponent(name)}`, () => { t.userData.ready = true; dirtyLooks = true; });
    t.colorSpace = THREE.SRGBColorSpace;
    if (pixel) { t.magFilter = THREE.NearestFilter; t.minFilter = THREE.NearestFilter; t.generateMipmaps = false; }
    imgTex.set(k, t);
  }
  return imgTex.get(k);
}

// ---------- 건물 ----------
const signs = {};
const themed = [];   // [mesh, 기본색, 층 색조를 섞는 비율]
function buildOffice() {
  themed.push([box(37, 0.3, 27, 0xf6f3ec, 0, -0.3, 0.25, { cast: false }), 0xf6f3ec, 0.16]);   // 바닥판
  box(37.6, 0.25, 27.6, 0xd6d0c4, 0, -0.55, 0.25, { cast: false });     // 바닥 테두리
  for (const r of Object.values(R)) {
    themed.push([box(r.x1 - r.x0, 0.05, r.z1 - r.z0, r.color, r.cx, 0, r.cz, { cast: false }), r.color, 0.22]);
    themed.push([box(r.x1 - r.x0, 1.5, 0.16, 0xf1f5f9, r.cx, 0, r.z0), 0xf1f5f9, 0.42]);   // 뒷벽(층마다 벽 색이 다르다)
    themed.push([box(0.16, 1.5, r.z1 - r.z0, 0xe2e8f0, r.x0, 0, r.cz), 0xe2e8f0, 0.42]);   // 왼벽
    // 간판은 늘 카메라를 보는 반투명 판(스프라이트)으로, 방 안쪽 뒤편 가운데에 띄운다
    const sign = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthTest: false, opacity: 0.92 }));
    sign.scale.set(4.8, 0.8, 1); sign.center.set(0.5, 0.5);
    sign.position.set(r.cx, 1.75, r.z0 + Math.min(2.2, (r.z1 - r.z0) * 0.32)); sign.renderOrder = 10;
    scene.add(sign); signs[r.id] = sign;
  }
  buildLibrary(R.library); buildMeeting(R.meeting); buildDev(R.dev); buildLounge(R.lounge);
  buildMyDesk(R.mydesk); buildServer(R.server); buildSearch(R.search); buildElevator(); buildCafe();
  [[-18, -12.8], [18, -12.8], [-4.4, 6.2], [4, 13], [-11, 13], [18, 6]].forEach(([x, z]) => plant(x, z, 0.9));
  // 층 표시: 엘리베이터 앞 복도 바닥에 크게 칠한 층 번호와, 엘리베이터 위 전광판
  floorDecal = new THREE.Mesh(new THREE.PlaneGeometry(8, 2), new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }));
  floorDecal.rotation.x = -Math.PI / 2; floorDecal.position.set(-8.4, 0.07, 6.05);
  scene.add(floorDecal);
  elevSign = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthTest: false }));
  elevSign.position.set(-15, 3.9, 7.2); elevSign.renderOrder = 11;
  scene.add(elevSign);
}
let floorDecal, elevSign;

// ---------- 층마다 다른 분위기 ----------
// 색조는 층 배지와 같은 색(층 번호 × 47°). 채광은 높이를 따른다: 아래층은 서늘하고 어둑하게,
// 위층으로 갈수록 해가 높고 따뜻하고 밝게. 해의 방향도 층마다 돌아서 그림자 방향이 달라진다.
const floorHue = n => (n * 47) % 360;
let themeKey = "";
function applyTheme(n, total, project) {
  const key = `${n}/${total}/${project}`;
  if (key === themeKey) return;
  themeKey = key;
  const hue = floorHue(n), f = total > 1 ? (n - 1) / (total - 1) : 0.5;
  const tintC = new THREE.Color().setHSL(hue / 360, 0.6, 0.66);
  for (const [m, base, amt] of themed) m.material = mat(new THREE.Color(base).lerp(tintC, amt).getHex());
  // 아래층 = 이른 아침(낮고 푸른 빛, 긴 그림자) … 위층 = 한낮·노을(높고 따뜻한 빛). 전체 밝기는 처음 값 근처를 지킨다
  sun.intensity = 1.5 + 0.7 * f;
  sun.color.set(0xbfd6ff).lerp(new THREE.Color(0xffd9a0), f);
  const ang = (25 + n * 52) * Math.PI / 180, h = 14 + 24 * f;
  sun.position.set(Math.cos(ang) * 24, h, Math.sin(ang) * 24);
  hemi.intensity = 1.15 + 0.3 * f;
  hemi.color.setHSL(hue / 360, 0.45, 0.96);
  hemi.groundColor.setHSL(hue / 360, 0.25, 0.7);
  stage.style.setProperty("--fh", hue);
  stage.style.setProperty("--fl", (14 + 10 * f).toFixed(0) + "%");
  // 바닥 층 번호
  const c = document.createElement("canvas"); c.width = 1024; c.height = 256;
  const g = c.getContext("2d");
  g.fillStyle = `hsla(${hue}, 70%, 40%, 0.95)`; g.font = `900 210px ${FONT}`; g.textBaseline = "middle";
  g.fillText(`${n}F`, 10, 136);
  const w = g.measureText(`${n}F`).width;
  g.fillStyle = `hsla(${hue}, 50%, 32%, 0.85)`; g.font = `800 92px ${FONT}`; g.fillText(project.slice(0, 16), w + 40, 140);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  if (floorDecal.material.map) floorDecal.material.map.dispose();
  floorDecal.material.map = t; floorDecal.material.needsUpdate = true;
  setElevSign(`${n}F`, hue);
}
function setElevSign(text, hue) {
  const c = document.createElement("canvas"); c.width = 256; c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#0b1220"; roundRect(g, 4, 4, 248, 120, 18); g.fill();
  g.strokeStyle = `hsl(${hue}, 70%, 55%)`; g.lineWidth = 6; roundRect(g, 4, 4, 248, 120, 18); g.stroke();
  g.fillStyle = "#fbbf24"; g.shadowColor = "#f59e0b"; g.shadowBlur = 18;
  g.font = `800 76px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 128, 68);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  if (elevSign.material.map) elevSign.material.map.dispose();
  elevSign.material.map = t; elevSign.material.needsUpdate = true;
  elevSign.scale.set(1.9, 0.95, 1);
}
function buildLibrary(r) {
  const books = [0xef4444, 0x3b82f6, 0x10b981, 0xf59e0b, 0x8b5cf6, 0x0ea5e9];
  for (let i = 0; i < 4; i++) {
    const x = r.x0 + 1.6 + i * 2.25, z = r.z0 + 0.45;
    box(2.0, 2.3, 0.55, 0x9a6b43, x, 0, z);
    for (let s = 0; s < 3; s++) for (let b = 0; b < 7; b++)
      box(0.2, 0.42, 0.42, books[(i + s + b) % books.length], x - 0.75 + b * 0.25, 0.25 + s * 0.72, z + 0.08, { cast: false });
    r.seats.push([x, z + 1.35]);
  }
  box(3.2, 0.08, 1.3, 0xc8a27a, r.cx + 0.5, 0.74, r.cz + 1.4);
  box(0.12, 0.74, 0.12, 0x8b6b4a, r.cx + 0.5, 0, r.cz + 1.4);
  for (const dx of [-1, 0, 1]) { chair(r.cx + 0.5 + dx * 1.0, r.cz + 2.4, 0xb7791f, Math.PI); r.seats.push([r.cx + 0.5 + dx * 1.0, r.cz + 2.35]); }
  plant(r.x1 - 0.8, r.z1 - 0.8, 0.8);
}
function buildMeeting(r) {
  box(5.2, 0.08, 1.9, 0xffffff, r.cx, 0.74, r.cz + 0.6);
  box(4.8, 0.74, 0.12, 0xcbd5e1, r.cx, 0, r.cz + 0.6, { cast: false });
  for (let i = 0; i < 4; i++) {
    const x = r.cx - 1.9 + i * 1.27;
    chair(x, r.cz - 0.75, 0x334155, 0); r.seats.push([x, r.cz - 0.75]);
    chair(x, r.cz + 1.95, 0x334155, Math.PI); r.seats.push([x, r.cz + 1.95]);
  }
  box(3.0, 1.3, 0.06, 0xffffff, r.cx + 2.2, 0.5, r.z0 + 0.12);
  [0xef4444, 0x22c55e, 0x3b82f6].forEach((c, i) => box(0.5, 0.35, 0.02, c, r.cx + 1.3 + i * 0.7, 1.1, r.z0 + 0.17, { cast: false }));
}
function buildDev(r) {
  for (let row = 0; row < 3; row++) for (let col = 0; col < 3; col++) {
    const x = r.x0 + 2.2 + col * 3.9, z = r.z0 + 1.6 + row * 2.4;
    desk(x, z); chair(x, z + 0.75, 0x3b5bdb, Math.PI);
    r.seats.push([x, z + 0.8]);
  }
  plant(r.x1 - 0.7, r.z1 - 0.7, 0.8);
}
function buildLounge(r) {
  themed.push([box(6.5, 0.02, 4.5, 0xe9d5b9, r.cx, 0.05, r.cz + 0.5, { cast: false }), 0xe9d5b9, 0.45]);
  box(4.4, 0.45, 1.0, 0x7c4a2d, r.cx, 0, r.z0 + 1.2);
  box(4.4, 0.75, 0.3, 0x6b3f26, r.cx, 0.2, r.z0 + 0.75);
  box(1.0, 0.45, 2.6, 0x7c4a2d, r.x0 + 1.4, 0, r.cz + 0.3);
  box(1.6, 0.4, 0.9, 0xd6b894, r.cx + 0.3, 0, r.cz + 0.6);
  box(1.4, 0.9, 0.08, 0x111827, r.x1 - 1.2, 0.7, r.z0 + 0.12);
  plant(r.x1 - 0.8, r.z1 - 0.8, 0.9);
  for (let row = 0; row < 3; row++) for (let i = 0; i < 4; i++)
    r.seats.push([r.x0 + 2.6 + i * 1.75 + (row % 2) * 0.85, r.z0 + 2.3 + row * 1.6]);
}
function buildMyDesk(r) {
  themed.push([box(9.0, 0.02, 6.0, 0xbcd4f2, r.cx, 0.05, r.cz, { cast: false }), 0xbcd4f2, 0.6]);
  box(4.4, 1.0, 0.9, 0xffffff, r.cx, 0, r.cz - 0.3);
  box(4.4, 0.06, 1.1, 0xe2e8f0, r.cx, 1.0, r.cz - 0.3);
  box(2.0, 0.3, 0.02, 0xd97757, r.cx, 0.55, r.cz + 0.16, { cast: false });
  box(0.7, 0.45, 0.05, 0x1e293b, r.cx - 1.2, 1.06, r.cz - 0.55);
  me.pos = [r.cx, r.cz - 1.5];
  for (let i = 0; i < 4; i++) r.seats.push([r.cx - 2.0 + i * 1.33, r.cz + 1.4]);
  for (let i = 0; i < 3; i++) r.seats.push([r.cx - 1.4 + i * 1.4, r.cz + 2.6]);
}
const leds = [];
function buildServer(r) {
  for (let row = 0; row < 2; row++) for (let i = 0; i < 5; i++) {
    const x = r.x0 + 2.0 + i * 2.1, z = r.z0 + 0.9 + row * 3.2;
    box(1.0, 2.4, 0.9, 0x1f2937, x, 0, z);
    for (let k = 0; k < 6; k++) {
      const led = box(0.08, 0.05, 0.02, 0x22c55e, x - 0.3 + (k % 3) * 0.12, 0.5 + Math.floor(k / 3) * 0.9, z + 0.46,
        { cast: false, mat: new THREE.MeshStandardMaterial({ color: 0x22c55e, emissive: k % 4 ? 0x22c55e : 0xf59e0b, emissiveIntensity: 1 }) });
      leds.push(led);
    }
    if (i % 2 === 0) r.seats.push([x, z + 1.1]);
  }
}
let globe;
function buildSearch(r) {
  for (let i = 0; i < 3; i++) {
    const x = r.x0 + 1.6 + i * 1.6;
    box(0.5, 1.7, 0.4, 0x7c3aed, x, 0, r.z0 + 1.2);
    box(0.42, 0.55, 0.03, 0xc4b5fd, x, 1.0, r.z0 + 1.42, { cast: false, mat: mat(0xc4b5fd, { emissive: 0x7c3aed, emissiveIntensity: 0.4 }) });
    r.seats.push([x, r.z0 + 2.2]);
  }
  cyl(0.08, 1.0, 0x64748b, r.x1 - 1.6, 0, r.cz);
  globe = ball(0.55, 0x38bdf8, r.x1 - 1.6, 1.5, r.cz);
  box(1.6, 0.06, 0.9, 0xffffff, r.cx + 1.6, 0.72, r.z1 - 1.2);
  r.seats.push([r.cx + 1.6, r.z1 - 0.5], [r.x1 - 1.6, r.cz + 1.1]);
}
const doors = [];
function buildElevator() {
  const { x0, x1, z0, z1 } = ELEV, cx = (x0 + x1) / 2;
  box(x1 - x0, 0.05, z1 - z0, 0xcbd5e1, cx, 0, (z0 + z1) / 2, { cast: false });
  box(x1 - x0, 3.2, 0.2, 0x94a3b8, cx, 0, z1 - 0.1);
  box(0.2, 3.2, z1 - z0, 0xa3b0c2, x0 + 0.1, 0, (z0 + z1) / 2);
  box(x1 - x0, 0.25, 0.3, 0x64748b, cx, 2.9, z0 + 0.15);
  box(0.25, 2.9, 0.3, 0x64748b, x0 + 0.12, 0, z0 + 0.15);
  box(0.25, 2.9, 0.3, 0x64748b, x1 - 0.12, 0, z0 + 0.15);
  for (const s of [-1, 1]) doors.push({ m: box(1.75, 2.8, 0.08, 0xd1d5db, cx + s * 0.9, 0, z0 + 0.2), base: cx + s * 0.9, dir: s });
  box(0.3, 0.3, 0.05, 0xfbbf24, x1 + 0.4, 1.5, z0 + 0.05, { mat: mat(0xfbbf24, { emissive: 0xf59e0b, emissiveIntensity: 0.6 }) });
}
let doorOpenUntil = 0;
function buildCafe() {
  themed.push([box(11.5, 0.05, 4.8, 0xf3dfc6, 11, 0, 9.6, { cast: false }), 0xf3dfc6, 0.35]);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) {
    const x = 7 + i * 3.6, z = 8.4 + j * 2.4;
    cyl(0.55, 0.05, 0xffffff, x, 0.72, z); cyl(0.06, 0.72, 0x9ca3af, x, 0, z);
    chair(x - 0.85, z, 0xf97316, Math.PI / 2); chair(x + 0.85, z, 0xf97316, -Math.PI / 2);
  }
}

// ---------- '나' ----------
const me = { pos: [0, 0], group: null, key: "" };

// ---------- 카메라 ----------
let zoom = 1;
function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  renderer.setSize(w, h, false);
  const aspect = w / h;
  viewH = Math.max(27, 45 / aspect);     // 바닥 전체가 들어오게
  camera.left = -viewH * aspect / 2; camera.right = viewH * aspect / 2;
  camera.top = viewH / 2; camera.bottom = -viewH / 2;
  camera.zoom = zoom;
  camera.updateProjectionMatrix();
  placeCamera();
}
function placeCamera() {
  camera.position.copy(target).add(CAM_OFFSET);
  camera.lookAt(target);
  camera.zoom = zoom; camera.updateProjectionMatrix();
}
function resetCamera() { target.set(0, 0, 0.5); zoom = 1; placeCamera(); }
const RIGHT = new THREE.Vector3(1, 0, -1).normalize(), UPG = new THREE.Vector3(-1, 0, -1).normalize();
let drag = null;
canvas.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, sx: e.clientX, sy: e.clientY, moved: false }; canvas.setPointerCapture(e.pointerId); });
let hovered = null;
canvas.addEventListener("pointermove", e => {
  if (!drag) { const k = hitKey(e); if (k !== hovered) { hovered = k; renderLabels(); } return; }
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  drag.x = e.clientX; drag.y = e.clientY;
  if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) > 4) drag.moved = true;
  const u = viewH / zoom / stage.clientHeight;
  target.addScaledVector(RIGHT, -dx * u).addScaledVector(UPG, dy * u / ELEV_SIN);
  target.x = clamp(target.x, -20, 20); target.z = clamp(target.z, -15, 15);
  placeCamera();
});
canvas.addEventListener("pointerup", e => {
  if (drag && !drag.moved) pick(e);
  drag = null;
});
canvas.addEventListener("wheel", e => { e.preventDefault(); setZoom(zoom * Math.exp(-e.deltaY * 0.0015)); }, { passive: false });
canvas.addEventListener("dblclick", resetCamera);
$("zin").onclick = () => setZoom(zoom * 1.25);
$("zout").onclick = () => setZoom(zoom / 1.25);
$("zreset").onclick = resetCamera;
function setZoom(z) { const was = zoom >= 1.8; zoom = clamp(z, 0.6, 4); placeCamera(); if ((zoom >= 1.8) !== was) renderLabels(); }
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
function hitKey(e) {
  const r = canvas.getBoundingClientRect();
  ndc.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hits = ray.intersectObjects([...actors.values()].filter(a => !a.leaving).map(a => a.hit));
  return hits.length ? hits[0].object.userData.key : null;
}
function pick(e) { const k = hitKey(e); if (k) select(k); }

// ---------- 사람 ----------
const actors = new Map();   // key -> actor
const lastRoom = new Map();
const seatOf = new Map();   // key -> {room, i}
const HIT = new THREE.BoxGeometry(1, 2.2, 1);
const HITMAT = new THREE.MeshBasicMaterial({ visible: false });
const BLOB = new THREE.CircleGeometry(0.5, 24);
const BLOBMAT = new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.16, depthWrite: false });
const RING = new THREE.RingGeometry(0.55, 0.72, 32);
const RINGMAT = new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.95, depthWrite: false });
const CAPSULE = new THREE.CapsuleGeometry(0.3, 0.5, 6, 16);

function newActor(key, sub) {
  const group = new THREE.Group();
  const s = sub ? 0.95 : 1.3;
  group.scale.setScalar(s);
  const blob = new THREE.Mesh(BLOB, BLOBMAT); blob.rotation.x = -Math.PI / 2; blob.position.y = 0.06; group.add(blob);
  const ring = new THREE.Mesh(RING, RINGMAT); ring.rotation.x = -Math.PI / 2; ring.position.y = 0.07; ring.visible = false; group.add(ring);
  const hit = new THREE.Mesh(HIT, HITMAT); hit.position.y = 1.1; hit.userData.key = key; group.add(hit);
  const look = new THREE.Group(); group.add(look);
  scene.add(group);
  const lab = document.createElement("div");
  lab.className = "lab" + (sub ? " sub" : "");
  // 위에서부터: 말풍선(Claude가 한 말) · 상태 배지(지금 하는 일) · 명찰(누구인지)
  lab.innerHTML = `<div class="say"><span class="q"></span></div><div class="pill"></div><div class="tag"><span class="t"></span></div>`;
  labels.appendChild(lab);
  return { key, sub, group, look, ring, hit, lab, lookKey: "", head: null, path: [], pos: [0, 0], room: "", leaving: false, opacity: 1, scale: s };
}
function setLook(a, ch, st) {
  const l = lookFor(ch, st);
  const k = `${l.image}|${l.emoji}|${ch.color}|${ch.pixel}|${l.image && imageTexture(l.image, ch.pixel).userData.ready}`;
  if (a.lookKey === k) return;
  a.lookKey = k;
  a.look.traverse(m => { if (m.isSprite) m.material.dispose(); });
  a.look.clear(); a.head = null;
  if (l.image) {
    const tex = imageTexture(l.image, ch.pixel);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, alphaTest: 0.08 }));
    const img = tex.image, asp = img && img.width ? img.width / img.height : 1;
    const h = 2.0;
    sp.scale.set(h * asp, h, 1); sp.center.set(0.5, 0); sp.position.y = 0.05;
    a.look.add(sp); a.head = sp;
  } else {
    const body = new THREE.Mesh(CAPSULE, mat(new THREE.Color(ch.color).getHex()));
    body.position.y = 0.6; body.castShadow = true;
    a.look.add(body);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: emojiTexture(l.emoji || "🙂"), transparent: true }));
    sp.scale.set(0.95, 0.95, 1); sp.position.y = 1.5;
    a.look.add(sp); a.head = sp;
  }
}
function setOpacity(a, o) {
  a.opacity = o;
  a.group.traverse(m => {
    if (!m.material || m === a.hit) return;
    if (!m.userData.own) { m.userData.base = m.material.opacity; m.material = m.material.clone(); m.userData.own = true; }
    m.material.transparent = true;
    m.material.opacity = m.userData.base * o;
  });
}
function disposeActor(a) {
  scene.remove(a.group);
  a.group.traverse(m => { if (m.userData.own) m.material.dispose(); });
  a.lab.remove();
}

function seatPos(roomId, i) {
  const r = R[roomId];
  if (i < r.seats.length) return r.seats[i];
  // 자리가 모자라면 방 앞쪽 빈 곳에 줄을 세운다
  const j = i - r.seats.length, cols = Math.max(1, Math.floor((r.x1 - r.x0 - 2) / 1.3));
  return [r.x0 + 1.2 + (j % cols) * 1.3, r.z1 - 0.9 - Math.floor(j / cols) * 1.3];
}
function takeSeat(key, roomId) {
  const used = new Set();
  for (const [k, s] of seatOf) if (k !== key && s.room === roomId) used.add(s.i);
  const prev = seatOf.get(key);
  let i = prev && prev.room === roomId && !used.has(prev.i) ? prev.i : 0;
  while (used.has(i)) i++;
  seatOf.set(key, { room: roomId, i });
  return seatPos(roomId, i);
}
function doorOf(roomId) { return roomId === "elevator" ? { door: ELEV.door, corr: ELEV.corr } : R[roomId]; }
function route(from, to, dest) {
  if (from === to) return [dest];
  const a = doorOf(from), b = doorOf(to);
  const pts = [a.door, [a.door[0], a.corr]];
  if (a.corr !== b.corr) {
    const vx = VX.reduce((p, v) => Math.abs(v - a.door[0]) < Math.abs(p - a.door[0]) ? v : p);
    pts.push([vx, a.corr], [vx, b.corr]);
  }
  pts.push([b.door[0], b.corr], b.door, dest);
  if (from === "elevator") pts.unshift(ELEV.inside);
  return pts;
}

// ---------- 상태 ----------
let state = null, cfg = null, floorKey = null, selected = null, skew = 0, dirtyLooks = false;
const logs = new Map();       // project -> [{ts, who, text}]
const prevTool = new Map();   // key -> "tool target"
// 순회 재생: ▶ 이면 근무 중인 층을 아래층부터 정해진 간격으로 돌아가며 보여 준다.
// 사람이 화면을 쓰는 동안(클릭·드래그·휠·키 입력, 메시지 칸에 커서나 쓰던 글이 있을 때)은 잠깐 멈추고,
// IDLE_RESUME_MS 동안 입력이 없으면 멈춘 자리에서 남은 시간만큼 이어서 돈다.
const IDLE_RESUME_MS = 20000;
let playing = false, rotateSec = 20, rotateAt = 0, lastInput = 0, lastTick = Date.now(), pausedNow = false;
const PLAYER_CONTROLS = "#play, #rotate";   // 재생 버튼·간격 고르기는 '사용 중'으로 치지 않는다
for (const ev of ["pointerdown", "keydown", "wheel", "input"]) {
  document.addEventListener(ev, e => {
    if (e.target instanceof Element && e.target.closest(PLAYER_CONTROLS)) return;
    lastInput = Date.now();
  }, { capture: true, passive: true });
}
function userBusy() {
  const ta = $("composeText");
  return Date.now() - lastInput < IDLE_RESUME_MS || document.activeElement === ta || (ta && ta.value.trim() !== "");
}
try { playing = localStorage.getItem("office.play") === "1"; rotateSec = +localStorage.getItem("office.rotate") || 20; } catch (_) {}
function savePlay() { try { localStorage.setItem("office.play", playing ? "1" : "0"); localStorage.setItem("office.rotate", String(rotateSec)); } catch (_) {} }
function setPlaying(on) {
  playing = on; rotateAt = Date.now(); lastInput = 0; pausedNow = false; savePlay();
  $("progress").parentElement.classList.remove("paused");
  $("play").textContent = on ? "■ 정지" : "▶ 재생";
  $("play").classList.toggle("on", on);
  $("playHint").textContent = on ? "근무 중인 층을 돌아가며 보는 중" : "근무 중인 층 순회";
  $("progress").style.width = "0%";
}
$("play").onclick = () => setPlaying(!playing);
$("rotate").value = String(rotateSec);
$("rotate").onchange = e => { rotateSec = +e.target.value; rotateAt = Date.now(); savePlay(); };
function rotateTick() {
  const nowMs = Date.now(), dt = nowMs - lastTick;
  lastTick = nowMs;
  if (!playing || !state) return;
  const busy = userBusy() && !transit;
  if (busy) {
    rotateAt += dt;   // 멈춘 동안 흐른 시간만큼 미뤄 남은 시간을 그대로 둔다
    const ta = $("composeText");
    const left = Math.ceil((IDLE_RESUME_MS - (nowMs - lastInput)) / 1000);
    $("playHint").textContent = document.activeElement === ta || (ta && ta.value.trim())
      ? "⏸ 메시지를 쓰는 중이라 멈춤" : `⏸ 사용 중이라 잠깐 멈춤 · ${Math.max(1, left)}초 뒤 이어서`;
  } else if (pausedNow) {
    $("playHint").textContent = "근무 중인 층을 돌아가며 보는 중";
  }
  if (busy !== pausedNow) { pausedNow = busy; $("progress").parentElement.classList.toggle("paused", busy); }
  if (busy) return;
  const p = Math.min(1, (nowMs - rotateAt) / (rotateSec * 1000));
  $("progress").style.width = (p * 100).toFixed(1) + "%";
  if (p < 1) return;
  if (transit) return;
  rotateAt = Date.now();
  const active = floors().filter(f => f.busy).sort((a, b) => a.n - b.n);  // 아래층부터 올라간다
  if (!active.length) return;
  const cur = active.find(f => f.project === floorKey);
  // 지금 층보다 위의 첫 근무 층, 없으면 맨 아래 근무 층으로 돌아간다
  const curN = (floors().find(f => f.project === floorKey) || {}).n || 0;
  const next = active.find(f => f.n > curN) || active[0];
  if (next.project !== floorKey || !cur) travelTo(next.project);
}

// ---------- '나'의 엘리베이터 이동 ----------
// 걸어서 엘리베이터에 타고(walk) → 문 닫힘(close) → 빌딩 엘리베이터 칸이 그 층으로(ride)
// → 새 층에서 문 열림(arrive) → 내 자리로 걸어감(out)
let transit = null;
function travelTo(project) {
  const f = floors().find(x => x.project === project);
  if (!f) return;
  if (transit || !me.actor) { gotoFloor(project); return; }
  const from = (floors().find(x => x.project === floorKey) || {}).n;
  transit = { target: project, n: f.n, from, phase: "walk", t: performance.now() };
  me.actor.path = route("mydesk", "elevator", ELEV.inside);
  mePill(`🛗 ${f.n}F로 가는 중`);
}
function mePill(text) { const p = me.actor.lab.querySelector(".pill"); p.textContent = text; p.dataset.st = text ? "trip" : ""; me.actor.lab._dirty = true; }
function stepTransit(t) {
  const m = me.actor, tr = transit;
  if (tr.phase === "walk") {
    if (m.path.length <= 2) doorOpenUntil = t + 800;          // 문 앞에 오면 연다
    if (!m.path.length) { tr.phase = "close"; tr.t = t; doorOpenUntil = 0; }
  } else if (tr.phase === "close" && t - tr.t > 800) {
    tr.phase = "ride"; tr.t = t;
    tr.floors = Math.max(1, Math.abs(tr.n - (tr.from || tr.n)));
    tr.dur = 1200 + tr.floors * 900;            // 한 층에 0.9초 + 출발·정지
    tr.shown = null;
    $("stage").classList.add("riding");
    $("ride").classList.add("on");
    placeCar(tr.target, tr.dur);
  } else if (tr.phase === "ride") {
    // 가속·감속을 넣어 지금 지나는 층 숫자를 하나씩 바꾼다
    const p = Math.min(1, (t - tr.t) / tr.dur), e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    const from = tr.from || tr.n, cur = Math.round(from + (tr.n - from) * e);
    if (cur !== tr.shown) {
      tr.shown = cur;
      const arrow = tr.n > from ? "▲" : tr.n < from ? "▼" : "■";
      $("ride").innerHTML = `🛗 <i>${arrow}</i> <b>${cur}F</b>` + (cur === tr.n ? ` <span>${esc(tr.target)}</span>` : ` <span>→ ${tr.n}F</span>`);
      setElevSign(`${arrow}${cur}`, floorHue(cur));
    }
    if (p >= 1 && t - tr.t > tr.dur + 350) {
      tr.phase = "arrive"; tr.t = t; doorOpenUntil = t + 2600;   // 먼저 단계를 바꿔야 새 층 분위기가 바로 입혀진다
      gotoFloor(tr.target);
      m.pos = ELEV.inside.slice();
      $("stage").classList.remove("riding");
      setTimeout(() => $("ride").classList.remove("on"), 900);
    }
  } else if (tr.phase === "arrive" && t - tr.t > 600) {
    tr.phase = "out"; m.path = route("elevator", "mydesk", me.pos);
  } else if (tr.phase === "out" && !m.path.length) {
    transit = null; mePill(""); rotateAt = Date.now();
  }
}
function placeCar(project, ms) {
  const story = [...$("floors").querySelectorAll(".story")].find(x => x.dataset.p === project);
  const car = $("car");
  if (ms) car.style.transitionDuration = `${ms}ms, .3s`;
  else if (!(transit && transit.phase === "ride")) car.style.transitionDuration = "";
  if (story) { car.style.display = ""; car.style.transform = `translateY(${story.offsetTop}px)`; car.style.height = story.offsetHeight + "px"; }
  else car.style.display = "none";
  // 층이 바뀌었을 때만 그 층이 보이게 빌딩을 스크롤한다(매초 갱신마다 붙잡으면 손으로 스크롤할 수 없다).
  // 엘리베이터가 움직이는 동안은 frame() 의 followCar 가 칸을 따라간다
  if (story && project !== placeCar.last && !ms) {
    placeCar.last = project;
    const tower = story.closest(".tower"), top = story.offsetTop, h = story.offsetHeight;
    if (top < tower.scrollTop || top + h > tower.scrollTop + tower.clientHeight)
      tower.scrollTo({ top: Math.max(0, top - (tower.clientHeight - h) / 2), behavior: "smooth" });
  }
  if (ms) placeCar.last = project;
}
// 탑승 중: 움직이는 칸의 지금 위치를 읽어 빌딩 가운데에 두도록 스크롤을 맞춘다
function followCar() {
  const car = $("car"), tower = car.closest(".tower");
  if (car.style.display === "none") return;
  const y = new DOMMatrixReadOnly(getComputedStyle(car).transform).m42;
  tower.scrollTop = Math.max(0, y - (tower.clientHeight - car.offsetHeight) / 2);
}
setInterval(rotateTick, 200);

function stateOf(a) {
  if (a.stalled) return "stalled";
  if (a.kind === "working" || a.kind === "shell") return "working";
  return a.kind === "thinking" ? "thinking" : "idle";
}
function roomFor(key, a, parentRoom) {
  let room;
  if (a.kind === "idle") room = "lounge";
  else if (a.kind === "shell") room = "server";
  else if (a.tool) room = roomForTool(cfg, a.tool);
  else room = lastRoom.get(key) || parentRoom || (a.recent && a.recent[0] ? roomForTool(cfg, a.recent[0].tool) : cfg.defaultRoom);
  if (!R[room] || (room === "lounge" && a.kind !== "idle")) room = cfg.defaultRoom || "dev";
  lastRoom.set(key, room);
  return room;
}
function floors() {
  const m = new Map();
  for (const a of state.agents) {
    const f = m.get(a.project) || { project: a.project, agents: [], busy: 0, last: 0, first: Infinity, host: a.host };
    f.agents.push(a); f.busy += a.kind !== "idle" ? 1 : 0;
    f.last = Math.max(f.last, a.lastActivity || 0); f.first = Math.min(f.first, a.startedAt || 0);
    m.set(a.project, f);
  }
  return [...m.values()].sort((x, y) => x.first - y.first).map((f, i) => ({ ...f, n: i + 1 }));
}
function chooseFloor(fl) {
  const hashP = decodeURIComponent((location.hash.match(/p=([^&]+)/) || [])[1] || "");
  if (!floorKey && hashP && fl.some(f => f.project === hashP)) floorKey = hashP;
  const cur = fl.find(f => f.project === floorKey);
  if (!cur) floorKey = (fl.slice().sort((a, b) => b.busy - a.busy || b.last - a.last)[0] || {}).project || null;
  return floorKey;
}
function gotoFloor(p) {
  if (p === floorKey) return;
  floorKey = p; selected = null;
  history.replaceState(null, "", "#p=" + encodeURIComponent(p));
  for (const a of actors.values()) disposeActor(a);
  actors.clear(); seatOf.clear();
  apply(true);
}

function log(project, who, text, ts) {
  const l = logs.get(project) || [];
  l.unshift({ ts: ts || Date.now() / 1000 - skew, who, text });
  if (l.length > 60) l.length = 60;
  logs.set(project, l);
}
function trackLogs(first) {
  const seen = new Set();
  for (const a of state.agents) {
    const items = [{ key: a.id, who: a.name, x: a }].concat((a.subagents || []).map(s => ({ key: a.id + "/" + s.id, who: `${s.type}${s.description ? " · " + s.description : ""}`, x: s, sub: true })));
    for (const it of items) {
      seen.add(it.key);
      const t = it.x.tool ? `${it.x.tool}${it.x.target ? " · " + it.x.target : ""}` : "";
      const was = prevTool.get(it.key);
      if (first) {
        if (!it.sub) (it.x.recent || []).slice().reverse().forEach(r => log(a.project, it.who, `${r.tool}${r.target ? " · " + r.target : ""}`, r.ts));
      } else if (was === undefined && it.sub) log(a.project, it.who, "🛗 출근");
      else if (t && t !== was) log(a.project, it.who, t);
      prevTool.set(it.key, t);
    }
  }
  for (const k of [...prevTool.keys()]) if (!seen.has(k)) {
    if (k.includes("/")) { const p = (state.agents.find(a => k.startsWith(a.id + "/")) || {}).project; if (p) log(p, "서브에이전트", "🛗 퇴근"); }
    prevTool.delete(k);
  }
}

function apply(instant) {
  if (!state) return;
  cfg = state.config;
  const fl = floors();
  const before = floorKey;
  chooseFloor(fl);
  if (before !== floorKey) { for (const a of actors.values()) disposeActor(a); actors.clear(); seatOf.clear(); instant = true; }
  const floor = fl.find(f => f.project === floorKey);
  const agents = floor ? floor.agents : [];
  if (floor && !(transit && transit.phase === "ride")) applyTheme(floor.n, fl.length, floor.project);
  const chars = assignCharacters(cfg, state.agents);
  updateSigns();
  updateMe();

  const items = [];
  for (const a of agents) {
    const room = roomFor(a.id, a);
    items.push({ key: a.id, a, st: stateOf(a), room, sub: false, ch: chars.get(a.id) });
    for (const s of a.subagents || []) {
      const key = a.id + "/" + s.id;
      const sa = { ...s, kind: s.tool ? "working" : "thinking", lastActivity: s.since, name: s.type };
      items.push({ key, a: sa, st: s.tool ? "working" : "thinking", room: s.tool ? roomFor(key, sa) : (lastRoom.get(key) || room), sub: true, ch: chars.get(key), parent: a });
      lastRoom.set(key, items[items.length - 1].room);
    }
  }
  const seen = new Set();
  let arrivals = false;
  for (const it of items) {
    seen.add(it.key);
    let ac = actors.get(it.key);
    if (!ac) {
      ac = newActor(it.key, it.sub);
      actors.set(it.key, ac);
      const seat = takeSeat(it.key, it.room);
      if (instant) { ac.pos = seat.slice(); ac.path = []; }
      else { ac.pos = ELEV.inside.slice(); ac.path = route("elevator", it.room, seat); arrivals = true; setOpacity(ac, 1); }
      ac.room = it.room;
    } else if (ac.room !== it.room) {
      const seat = takeSeat(it.key, it.room);
      ac.path = route(ac.room, it.room, seat);
      ac.room = it.room;
    }
    ac.item = it;
    if (it.ch) setLook(ac, it.ch, it.st);
  }
  for (const [key, ac] of actors) {
    if (seen.has(key) || ac.leaving) continue;
    ac.leaving = true; seatOf.delete(key);
    ac.path = route(ac.room, "elevator", ELEV.inside);
    ac.lab.classList.add("gone");
  }
  if (arrivals) doorOpenUntil = performance.now() + 3000;
  renderLabels();
  renderFloors(fl);
  renderPeople(floor, chars);
  renderLog(floor);
  renderLegend();
  $("empty").style.display = state.hosts.some(h => h.online) ? "none" : "grid";
}

function updateSigns() {
  const sig = JSON.stringify(cfg.rooms);
  if (updateSigns.sig === sig) return;
  updateSigns.sig = sig;
  for (const r of cfg.rooms) if (signs[r.id]) {
    const old = signs[r.id].material.map;
    const t = signTexture(r.emoji, r.name, EN[r.id] || "");
    signs[r.id].material.map = t;
    signs[r.id].material.needsUpdate = true;
    signs[r.id].scale.set(1.2 * t.userData.aspect, 1.2, 1);
    if (old) old.dispose();
  }
}
function updateMe() {
  const ch = (cfg.characters || []).find(c => c.id === cfg.meCharacter) || { id: "_me", name: cfg.meName, emoji: "🧑‍💻", color: "#d97757", states: {} };
  if (!me.actor) {
    me.actor = newActor("_me", false);
    me.actor.pos = me.pos.slice();
    me.actor.hit.userData.key = "_me";
    me.actor.lab.classList.add("me");
  }
  setLook(me.actor, ch, "idle");
  const nm = cfg.meName || "나";
  me.actor.lab.querySelector(".t").textContent = nm === "나" ? "나" : `${nm} (나)`;
  me.actor.lab.style.setProperty("--c", "#f97316");
  me.actor.lab.querySelector(".say").style.display = "none";
}

// ---------- 화면 글자 ----------
function stateHTML(a, st, now) {
  if (st === "stalled") return `<i>🤔</i>턱 괴고 고민 중 <small>${ago(now - a.lastActivity)}</small>`;
  if (st === "working") {
    if (a.kind === "shell") return `<i>⌨️</i>셸 명령`;
    const long = a.since && now - a.since > 120 ? ` <small>⏳${ago(now - a.since)}</small>` : "";
    return `<i>🔧</i><code>${esc(a.tool)}</code>${a.target ? `<span class="tg">${esc(a.target)}</span>` : ""}${long}`;
  }
  if (st === "thinking") return `<i>💭</i>고민 중 <small>${ago(now - (a.since || now))}째</small>`;
  return now - (a.since || now) > 600 ? `<i>💤</i>휴식 <small>${ago(now - a.since)}</small>` : `<i>☕</i>휴식 <small>${ago(now - (a.since || now))}</small>`;
}
const STATE_COLOR = { working: "#38bdf8", thinking: "#a78bfa", stalled: "#fbbf24", idle: "#94a3b8" };
function renderLabels() {
  const now = Date.now() / 1000 - skew;
  for (const ac of actors.values()) {
    const it = ac.item; if (!it) continue;
    const lab = ac.lab;
    const say = cfg.speech !== false && it.a.say && (it.st !== "idle" || selected === it.key) ? it.a.say : "";
    lab.querySelector(".q").textContent = say;
    lab.querySelector(".say").style.display = say ? "" : "none";
    const pill = lab.querySelector(".pill");
    pill.innerHTML = stateHTML(it.a, it.st, now);
    pill.dataset.st = it.st;
    pill.style.display = it.st === "idle" && selected !== it.key ? "none" : "";
    lab.querySelector(".t").textContent = it.sub ? `${it.a.type}${it.a.description ? " · " + it.a.description : ""}` : (it.a.title || it.a.name);
    lab.style.setProperty("--c", it.ch ? it.ch.color : "#64748b");   // 명찰 띠 = 캐릭터 색
    lab.classList.toggle("sel", selected === it.key);
    lab.classList.toggle("idle", it.st === "idle");
    // 쉬는 사람은 라운지에 몰려 이름표가 겹친다 — 올리거나 고르거나 크게 확대했을 때만 보인다
    lab.classList.toggle("quiet", it.st === "idle" && selected !== it.key && hovered !== it.key && zoom < 1.8);
    if (hovered === it.key) lab.style.zIndex = "100000";
    ac.ring.visible = selected === it.key;
    lab._dirty = true;
  }
}
function select(key) {
  selected = selected === key ? null : key;
  if (selected) showTab("session");   // 캐릭터를 고르면 그 세션 탭으로
  renderLabels();
  if (state) { const fl = floors(); renderPeople(fl.find(f => f.project === floorKey), assignCharacters(cfg, state.agents)); }
}

const MAX_WINDOWS = 8;
function renderFloors(fl) {
  const now = Date.now() / 1000 - skew;
  const chars = assignCharacters(cfg, state.agents);
  // 창문 하나 = 세션 하나. 근무 중이면 불이 켜지고 그 세션의 캐릭터가 창가에 선다
  $("floors").innerHTML = fl.slice().reverse().map(f => {
    const ws = f.agents.slice().sort((a, b) => (b.kind !== "idle") - (a.kind !== "idle") || (b.lastActivity || 0) - (a.lastActivity || 0));
    const wins = ws.slice(0, MAX_WINDOWS).map(a => {
      const ch = chars.get(a.id), st = stateOf(a), l = ch ? lookFor(ch, st) : { emoji: "🙂" };
      const face = l.image ? `<img src="/assets/${encodeURIComponent(l.image)}" alt="">` : esc(l.emoji || "🙂");
      return `<span class="win ${a.kind !== "idle" ? "lit" : ""} w-${st}" title="${esc(a.title || a.name)} · ${{ working: "근무", thinking: "고민", stalled: "막힘", idle: "휴식" }[st]}">${face}</span>`;
    }).join("") + (ws.length > MAX_WINDOWS ? `<span class="win more">+${ws.length - MAX_WINDOWS}</span>` : "");
    return `<div class="story${f.project === floorKey ? " cur" : ""}${f.busy ? " busy" : ""}" data-p="${esc(f.project)}">
      <span class="no" style="--h:${(f.n * 47) % 360}">${f.n}F</span>
      <span class="info"><b>${esc(f.project)}</b><small>${f.busy ? `<em>${f.busy}명 근무 중</em> · ` : ""}세션 ${f.agents.length}개${f.busy ? "" : " · " + ago(now - f.last) + " 전"}</small>
      <span class="wins">${wins}</span></span></div>`;
  }).join("") || `<div class="muted" style="padding:16px">보이는 세션이 없습니다.</div>`;
  $("lobbyHosts").innerHTML = state.hosts.map(h => `<span class="chip"><span class="dot ${h.online ? "on" : "off"}"></span>${esc(h.host)}</span>`).join(" ");
  // 엘리베이터 칸을 지금 보는 층으로 옮긴다(위치가 바뀌면 미끄러지듯 이동)
  if (!(transit && transit.phase === "ride")) placeCar(floorKey);
  const f = fl.find(x => x.project === floorKey);
  $("floorBadge").innerHTML = f ? `<span class="badge" style="--h:${(f.n * 47) % 360}">${f.n}F</span><b>${esc(f.project)}</b><small>${esc(f.host || "")} · 세션 ${f.agents.length}개</small>` : "";
}
$("floors").addEventListener("click", e => {
  const f = e.target.closest("[data-p]");
  if (!f) return;
  if (playing) rotateAt = Date.now();  // 손으로 고른 층은 한 간격 동안 머문다
  if (transit) { transit = null; me.actor.path = []; me.actor.pos = me.pos.slice(); mePill(""); $("ride").classList.remove("on"); }
  gotoFloor(f.dataset.p);
});
setPlaying(playing);

function renderPeople(floor, chars) {
  const now = Date.now() / 1000 - skew;
  if (!floor) { $("people").innerHTML = ""; $("detail").innerHTML = ""; updateCompose(null); updateSessionTab(null); return; }
  const rows = [];
  for (const a of floor.agents) {
    rows.push(personRow(a.id, a, chars.get(a.id), stateOf(a), a.title || a.name, a.name, now, false));
    for (const s of a.subagents || []) rows.push(personRow(a.id + "/" + s.id, { ...s, kind: s.tool ? "working" : "thinking", lastActivity: s.since }, chars.get(a.id + "/" + s.id), s.tool ? "working" : "thinking", `${s.type}${s.description ? " · " + s.description : ""}`, "서브에이전트", now, true));
  }
  const busy = floor.agents.filter(a => a.kind !== "idle").length;
  $("peopleHead").textContent = `${floor.agents.length}명 · ${busy}명 근무 중`;
  $("tabPeopleN").textContent = floor.agents.length || "";
  $("people").innerHTML = rows.join("");
  const a = floor.agents.find(x => x.id === selected) || floor.agents.find(x => selected && selected.startsWith(x.id + "/"));
  $("detail").innerHTML = a ? detailCard(a, chars.get(a.id), now) : "";
  updateCompose(a, now);
  updateSessionTab(a);
}
function personRow(key, a, ch, st, title, sub, now, isSub) {
  const label = { working: "근무", thinking: "고민", stalled: "막힘", idle: "휴식" }[st];
  const line = st === "working" ? `${a.tool || "셸"}${a.target ? " · " + a.target : ""}` : (a.say || "");
  return `<li data-k="${esc(key)}" class="${isSub ? "sub" : ""}${selected === key ? " on" : ""}">
    <span class="av" style="--c:${ch ? ch.color : "#64748b"}">${ch ? avatarSmall(ch, st) : ""}</span>
    <span class="body"><span class="r1"><b>${esc(title)}</b><span class="st st-${st}">${label}</span></span>
    <span class="r2">${esc(line)}</span>
    <span class="r3">${esc(sub)} · 도구 ${a.tools || 0}회 · ${ago(now - (a.since || now))}</span></span></li>`;
}
function avatarSmall(ch, st) {
  const l = lookFor(ch, st);
  return l.image ? `<img src="/assets/${encodeURIComponent(l.image)}" alt=""${ch.pixel ? ' style="image-rendering:pixelated"' : ""}>` : `<span class="emo">${esc(l.emoji || "🙂")}</span>`;
}
function detailCard(a, ch, now) {
  const recent = (a.recent || []).map(r => `<li><span class="t">${esc(r.tool)}</span><span class="g">${esc(r.target)}</span><span class="a">${r.ts ? ago(now - r.ts) : ""}</span></li>`).join("");
  return `<div class="detail"><div class="dh"><span class="av big" style="--c:${ch ? ch.color : "#64748b"}">${ch ? avatarSmall(ch, stateOf(a)) : ""}</span>
    <span><b>${esc(a.title || a.name)}</b><small>${esc(a.name)} · ${esc(ch ? ch.name : "")} · PID ${esc(a.pid)}</small></span></div>
    ${a.say && cfg.speech !== false ? `<p class="quote">“${esc(a.say)}”</p>` : ""}
    <h4>최근 도구</h4>${recent ? `<ol class="recent">${recent}</ol>` : `<div class="muted">기록 없음</div>`}</div>`;
}
$("people").addEventListener("click", e => { const s = e.target.closest("[data-k]"); if (s) select(s.dataset.k); });

// ---------- 오른쪽 패널 탭 ----------
// 사람들 · 세션(고른 세션의 상세 + 메시지) · 활동 로그 · 안내. 마지막에 본 탭은 이 브라우저에 기억한다
const TABS = ["people", "session", "log", "legend"];
function showTab(name) {
  if (!TABS.includes(name)) name = "people";
  document.querySelectorAll(".tabs [data-tab]").forEach(b => {
    const on = b.dataset.tab === name;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".pane[data-pane]").forEach(p => p.classList.toggle("on", p.dataset.pane === name));
  try { localStorage.setItem("office.tab", name); } catch (_) {}
}
document.querySelector(".tabs").addEventListener("click", e => { const b = e.target.closest("[data-tab]"); if (b) showTab(b.dataset.tab); });
function updateSessionTab(a) {
  $("sessionEmpty").hidden = !!a;
  $("tabSessionDot").className = a ? "dot" : "";   // 고른 세션이 있으면 탭에 점
}
let savedTab = "people";
try { savedTab = localStorage.getItem("office.tab") || "people"; } catch (_) {}
showTab(savedTab);
updateSessionTab(null);

// ---------- 고른 세션에 메시지 보내기 ----------
// 허브 → 그 컴퓨터의 수집기 → 세션 수신함 소켓으로 간다. 받는 Claude 는 '다른 세션이 보낸 메시지'로 받고,
// 권한 확인을 건너뛰는 세션(bypass)은 터미널에서 사용자가 승인해야 전달된다(Claude Code 규칙).
let token = "";
try { token = localStorage.getItem("office.token") || ""; } catch (_) {}
let composeFor = null;
const MSG_LABEL = { queued: "대기", sending: "전달 중", sent: "전달함", failed: "실패", expired: "만료" };
function updateCompose(a, now) {
  const box = $("compose");
  if (!a) { box.hidden = true; composeFor = null; return; }
  box.hidden = false;
  if (composeFor !== a.id) { composeFor = a.id; $("composeText").value = ""; $("composeCount").textContent = "0 / 4000"; }
  $("composeTarget").textContent = `${a.title || a.name} @${a.host}`;
  const m = state.messaging || {};
  let note = "", warn = false, can = false;
  if (!m.auth) note = "허브에 OFFICE_TOKEN 이 없어 꺼져 있습니다(.env 에 정하고 허브를 다시 띄우세요).";
  else if (!m.ready) note = "관리 화면 「화면 설정」에서 '대시보드에서 메시지 보내기'를 켜야 합니다.";
  else if (!a.canMessage) note = "이 세션의 컴퓨터 수집기가 메시지를 받지 않습니다(그 컴퓨터 .env 의 CLAUDE_OFFICE_MESSAGES=on, Windows 는 아직 미지원).";
  else if (a.mode === "bypassPermissions") { can = true; warn = true; note = "이 세션은 권한 확인을 건너뛰는 모드라, 메시지가 그 터미널에서 승인을 기다립니다(5분 안에 승인하지 않으면 버려짐)."; }
  else { can = true; note = "받는 Claude 는 '다른 세션이 보낸 메시지'로 받습니다. 권한 승인이나 설정 변경은 메시지로 할 수 없습니다."; }
  const np = $("composeNote"); np.textContent = note; np.classList.toggle("warn", warn);
  $("composeText").disabled = !can; $("composeSend").disabled = !can;
  const mine = (state.messages || []).filter(x => x.session === a.id).slice(-4).reverse();
  $("composeLog").innerHTML = mine.map(x => `<li title="${esc(x.error || "")}"><span class="s ${x.status}">${MSG_LABEL[x.status] || x.status}</span><span class="p">${esc(x.error && x.status !== "sent" ? x.error : x.preview)}</span><span class="muted">${ago((now || Date.now() / 1000 - skew) - x.createdAt)} 전</span></li>`).join("");
}
$("composeText").addEventListener("input", e => { $("composeCount").textContent = `${e.target.value.length} / 4000`; });
$("composeText").addEventListener("keydown", e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendCompose(); } });
$("composeSend").onclick = () => sendCompose();
async function sendCompose() {
  const a = state && state.agents.find(x => x.id === composeFor);
  const text = $("composeText").value.trim();
  if (!a || !text) return;
  if (!confirm(`'${a.title || a.name}' (${a.host}) 세션에 보낼까요?\n\n${text.slice(0, 300)}${text.length > 300 ? "…" : ""}`)) return;
  for (let tries = 0; tries < 2; tries++) {
    const r = await fetch("/api/sessions/message", { method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { "X-Office-Token": token } : {}) },
      body: JSON.stringify({ host: a.host, session: a.id, text }) });
    if (r.status === 401) {
      const t = prompt("메시지 보내기에는 허브의 OFFICE_TOKEN 이 필요합니다. 값을 넣어 주세요.");
      if (!t) return;
      token = t.trim(); try { localStorage.setItem("office.token", token); } catch (_) {}
      continue;
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert("보내지 못했습니다: " + (j.detail || r.statusText)); return; }
    $("composeText").value = ""; $("composeCount").textContent = "0 / 4000";
    log(a.project, `나 → ${a.title || a.name}`, `💬 ${text.slice(0, 60)}`);
    return;
  }
}

function renderLog(floor) {
  const now = Date.now() / 1000 - skew;
  const l = floor ? (logs.get(floor.project) || []) : [];
  $("log").innerHTML = l.slice(0, 30).map(x => `<li><span class="a">${ago(now - x.ts)} 전</span><span class="w">${esc(x.who)}</span><span class="x">${esc(x.text)}</span></li>`).join("") || `<li class="muted">아직 기록이 없습니다.</li>`;
}
function renderLegend() {
  const sig = JSON.stringify(cfg.rooms);
  if (renderLegend.sig === sig) return;
  renderLegend.sig = sig;
  $("legend").innerHTML = cfg.rooms.map(r => `<li><span class="emo">${esc(r.emoji)}</span><b>${esc(r.name)}</b><span>${esc(r.desc || "")}</span></li>`).join("") +
    `<li><span class="emo">🛗</span><b>엘리베이터</b><span>서브에이전트 출퇴근</span></li>`;
}

// 이름표·말풍선이 겹치면 뒤에 선 사람(화면 위쪽) 것을 위로 비켜 올린다. 크기는 글이 바뀔 때만 잰다.
function layoutLabels(list) {
  list.sort((a, b) => b.y - a.y);   // 앞(화면 아래)에 선 사람부터 자리를 잡는다
  const boxes = [];
  for (const p of list) {
    const lab = p.ac.lab;
    if (lab._w === undefined || lab._dirty) { lab._w = lab.offsetWidth; lab._h = lab.offsetHeight; lab._dirty = false; }
    let y = p.y;
    // '나'는 자리에 고정된 사람이라 비키지 않는다
    const visible = p.ac !== me.actor && !lab.classList.contains("quiet") && !lab.classList.contains("gone") && lab._h > 0;
    if (visible) {
      for (let guard = 0; guard < 12; guard++) {
        const hit = boxes.find(b => p.x - lab._w / 2 < b.x1 && p.x + lab._w / 2 > b.x0 && y - lab._h < b.y1 && y > b.y0);
        if (!hit) break;
        y = hit.y0 - 2;
      }
      boxes.push({ x0: p.x - lab._w / 2, x1: p.x + lab._w / 2, y0: y - lab._h, y1: y });
    }
    lab.style.transform = `translate(${p.x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
    lab.style.zIndex = p.ac.key === hovered || p.ac.key === selected ? "100000" : String(Math.round(p.y));
  }
}

// ---------- 매 프레임 ----------
const tmp = new THREE.Vector3();
let lastT = performance.now();
function frame(t) {
  const dt = Math.min(0.12, (t - lastT) / 1000); lastT = t;  // 느린 기기에서도 걸음이 늦어지지 않게
  const w = stage.clientWidth, h = stage.clientHeight;
  const all = me.actor ? [...actors.values(), me.actor] : [...actors.values()];
  const placed = [];
  for (const ac of all) {
    let moving = false;
    if (ac.path.length) {
      const [tx, tz] = ac.path[0];
      const dx = tx - ac.pos[0], dz = tz - ac.pos[1], d = Math.hypot(dx, dz), step = (ac === me.actor && transit ? 9 : 5.5) * dt;
      if (d <= step) { ac.pos = [tx, tz]; ac.path.shift(); } else { ac.pos[0] += dx / d * step; ac.pos[1] += dz / d * step; moving = true; }
      if (ac.leaving && !ac.path.length) { ac.fade = 1; doorOpenUntil = t + 1500; }
    }
    if (ac.fade !== undefined) {
      ac.fade -= dt * 1.6; setOpacity(ac, Math.max(0, ac.fade));
      if (ac.fade <= 0) { disposeActor(ac); actors.delete(ac.key); continue; }
    }
    ac.group.position.set(ac.pos[0], moving ? Math.abs(Math.sin(t / 90)) * 0.14 : 0, ac.pos[1]);
    if (ac.head) ac.head.material.rotation = ac.item && ac.item.st === "stalled" ? Math.sin(t / 500) * 0.28 : 0;
    tmp.set(ac.pos[0], (ac.head && ac.head.center.y === 0 ? 2.2 : 2.05) * ac.scale, ac.pos[1]).project(camera);
    placed.push({ ac, x: (tmp.x + 1) / 2 * w, y: (1 - tmp.y) / 2 * h });
  }
  layoutLabels(placed);
  placed.length = 0;
  const open = t < doorOpenUntil;
  for (const d of doors) {
    const goal = d.base + (open ? d.dir * 1.6 : 0);
    d.m.position.x += (goal - d.m.position.x) * Math.min(1, dt * 5);
  }
  leds.forEach((l, i) => { l.material.emissiveIntensity = 0.4 + 0.6 * (Math.sin(t / 180 + i * 1.7) > 0.2 ? 1 : 0); });
  if (globe) globe.rotation.y += dt * 0.6;
  if (transit && me.actor) stepTransit(t);
  if (transit && transit.phase === "ride") followCar();
  if (dirtyLooks && state) { dirtyLooks = false; for (const ac of actors.values()) ac.lookKey = ""; apply(false); }
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

// ---------- 시작 ----------
buildOffice();
new ResizeObserver(resize).observe(stage);
resize();
requestAnimationFrame(frame);
setInterval(() => { if (state) { renderLabels(); const fl = floors(); renderFloors(fl); const f = fl.find(x => x.project === floorKey); renderPeople(f, assignCharacters(cfg, state.agents)); renderLog(f); } }, 5000);

let seeded = false;
function connect() {
  const es = new EventSource("/api/stream");
  let first = true;
  es.onopen = () => { $("live").className = "live on"; $("liveText").textContent = "LIVE"; };
  es.onmessage = e => {
    state = JSON.parse(e.data);
    skew = Date.now() / 1000 - state.now;
    cfg = state.config;
    trackLogs(!seeded); seeded = true;
    apply(first);
    first = false;
  };
  es.onerror = () => { $("live").className = "live off"; $("liveText").textContent = "다시 연결 중"; };
}
connect();
