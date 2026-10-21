// 3D 사무실(쿼터뷰). 프로젝트 하나 = 층 하나, 세션·서브에이전트 = 사람.
// 상태는 /api/stream(SSE)으로 받고, 방·가구는 코드로 만든 단순한 도형이다.
import * as THREE from "/static/vendor/three.module.min.js";

const { roomForTool, assignCharacters, lookFor, esc, ago } = window.Office;
const $ = id => document.getElementById(id);
// 내용이 바뀐 때만 DOM 을 고쳐 쓴다(SSE·타이머가 같은 내용을 다시 그려도 화면은 건드리지 않게)
function setHTML(el, html) { if (el._html === html) return false; el._html = html; el.innerHTML = html; return true; }
function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
function setStyle(el, prop, v) { if (el.style.getPropertyValue(prop) !== v) el.style.setProperty(prop, v); }
// 3D 화면을 잠깐(ms 동안) 매 프레임 그리게 깨운다. 그 밖에는 frame() 이 낮은 빈도로만 그린다
let wakeUntil = 0;
function kick(ms = 250) { const u = performance.now() + ms; if (u > wakeUntil) wakeUntil = u; }
// 'n초 전' 같은 시간 글자: HTML 에는 시각(data-ts)만 넣어 내용 비교에서 빼고, 글자는 tickTimes 가 그 칸만 채운다.
// ts 가 없으면 '지금'(0초)으로 본다
const agoSpan = (ts, sfx = "") => `<span data-ts="${ts == null ? "" : ts}"${sfx ? ` data-sfx="${sfx}"` : ""}></span>`;
function tickTimes(root, now) {
  let changed = false;
  for (const s of root.querySelectorAll("[data-ts]")) {
    const ts = s.dataset.ts === "" ? now : +s.dataset.ts;
    const txt = ago(now - ts) + (s.dataset.sfx || "");
    if (s.textContent !== txt) { s.textContent = txt; changed = true; }
  }
  return changed;
}

// ---------- 평면도 ----------
// 3열(A·B·C) × 3줄(뒤·가운데·앞). 줄 사이는 가로 복도(z=-3, z=6), 열 사이는 세로 복도(x=-6.75, x=3.875).
const COL = { A: [-17, -7.75], B: [-5.75, 2.75], C: [5, 17] };
const ROW = { back: [-12, -4], mid: [-2, 5], front: [7, 12] };
const CORR = { back: -3, mid: -3, front: 6 };
const VX = [-6.75, 3.875];
// 방 아이콘(Font Awesome Free solid). 3D 간판은 캔버스에 그려서 글리프 코드를 직접 쓴다
const ROOM_ICON = { library: "book", dev: "laptop-code", server: "server", search: "globe", meeting: "people-group", mydesk: "user", lounge: "mug-hot" };
const ROOM_GLYPH = { library: "\uf02d", dev: "\uf5fc", server: "\uf233", search: "\uf0ac", meeting: "\ue533", mydesk: "\uf007", lounge: "\uf7b6" };
const FA_FONT = `"Font Awesome 7 Free"`;
const toolIcon = tool => (cfg && ROOM_ICON[roomForTool(cfg, tool)]) || "wrench";
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
renderer.localClippingEnabled = true;
// 바닥(y=0) 아래는 그리지 않는 면. 엘리베이터가 내려갈 때 '나'와 바닥판이 구멍 속으로 잘려 들어가게 한다
const FLOOR_CLIP = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
// 층 하나(바닥·벽·가구·사람)는 officeRoot 에 담는다. 엘리베이터를 탈 때 카메라·탑승칸은 그대로 두고
// 이 묶음을 위아래로 흘려보내 '엘리베이터가 오르내리는' 것처럼 보이게 한다
const officeRoot = new THREE.Group();
scene.add(officeRoot);
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
  (o.parent || officeRoot).add(m);
  return m;
}
function cyl(r, h, c, x, y, z, o = {}) {
  const m = new THREE.Mesh(CYL, o.mat || mat(c));
  m.scale.set(r, h, r);
  m.position.set(x, y + h / 2, z);
  m.castShadow = true; m.receiveShadow = true;
  (o.parent || officeRoot).add(m);
  return m;
}
function ball(r, c, x, y, z) {
  const m = new THREE.Mesh(SPH, mat(c));
  m.scale.setScalar(r);
  m.position.set(x, y, z);
  m.castShadow = true;
  officeRoot.add(m);
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
  officeRoot.add(g);
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
function signTexture(glyph, name, en) {
  // 글자 길이에 맞춰 캔버스 폭을 정한다(간판 판의 가로세로 비율도 이걸 따른다)
  const c = document.createElement("canvas"), g = c.getContext("2d");
  g.font = `700 54px ${FONT}`; const wn = g.measureText(name).width;
  g.font = `600 34px ${FONT}`; const we = g.measureText("· " + en).width;
  c.width = Math.ceil(112 + wn + 16 + we + 28); c.height = 104;
  g.fillStyle = "rgba(255,255,255,0.55)"; roundRect(g, 2, 2, c.width - 4, 100, 22); g.fill();  // 바탕만 반투명, 글자는 진하게
  g.textBaseline = "middle";
  g.fillStyle = "#334155"; g.font = `900 50px ${FA_FONT}`; g.textAlign = "center"; g.fillText(glyph || "", 58, 56); g.textAlign = "left";
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
    officeRoot.add(sign); signs[r.id] = sign;
  }
  buildLibrary(R.library); buildMeeting(R.meeting); buildDev(R.dev); buildLounge(R.lounge);
  buildMyDesk(R.mydesk); buildServer(R.server); buildSearch(R.search); buildElevator(); buildCafe(); buildCabin();
  [[-18, -12.8], [18, -12.8], [-4.4, 6.2], [4, 13], [-11, 13], [18, 6]].forEach(([x, z]) => plant(x, z, 0.9));
  // 층 표시: 엘리베이터 앞 복도 바닥에 크게 칠한 층 번호와, 엘리베이터 위 전광판
  floorDecal = new THREE.Mesh(new THREE.PlaneGeometry(8, 2), new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }));
  floorDecal.rotation.x = -Math.PI / 2; floorDecal.position.set(-8.4, 0.07, 6.05);
  officeRoot.add(floorDecal);
  elevSign = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthTest: false }));
  elevSign.position.set(-15, 3.9, 7.2); elevSign.renderOrder = 11;
  officeRoot.add(elevSign);
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
  setSignOn(elevSign, text, hue);
  if (cabin) setSignOn(cabin.sign, text, hue);
}
function setSignOn(sprite, text, hue) {
  const c = document.createElement("canvas"); c.width = 256; c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#0b1220"; roundRect(g, 4, 4, 248, 120, 18); g.fill();
  g.strokeStyle = `hsl(${hue}, 70%, 55%)`; g.lineWidth = 6; roundRect(g, 4, 4, 248, 120, 18); g.stroke();
  g.fillStyle = "#fbbf24"; g.shadowColor = "#f59e0b"; g.shadowBlur = 18;
  g.font = `800 76px ${FONT}`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 128, 68);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  if (sprite.material.map) sprite.material.map.dispose();
  sprite.material.map = t; sprite.material.needsUpdate = true;
  sprite.scale.set(1.9, 0.95, 1);
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

// 엘리베이터 바닥판: 평소엔 숨기고, 엘리베이터가 움직일 때만 '나'를 태우고 오르내린다(층 묶음 밖, 제자리)
let cabin = null;
function buildCabin() {
  const [x, z] = ELEV.inside, g = new THREE.Group();
  const plate = new THREE.Mesh(new THREE.BoxGeometry(3.4, 0.14, 3.6), new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.4, roughness: 0.4, transparent: true }));
  plate.position.y = 0.07; plate.castShadow = true; g.add(plate);
  const rim = new THREE.LineSegments(new THREE.EdgesGeometry(plate.geometry), new THREE.LineBasicMaterial({ color: 0xfbbf24, transparent: true }));
  rim.position.y = 0.07; g.add(rim);
  const sign = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthTest: false })); sign.position.y = 3.4; sign.renderOrder = 12; g.add(sign);
  g.position.set(x, 0, z); g.visible = false;
  for (const mm of [plate.material, rim.material, sign.material]) mm.clippingPlanes = [FLOOR_CLIP];
  scene.add(g);
  // 내려갈 때 엘리베이터 바닥에 열리는 구멍(어두운 승강로 입구). 가운데서부터 벌어진다
  const hole = new THREE.Group();
  const pit = new THREE.Mesh(new THREE.PlaneGeometry(3.5, 3.7), new THREE.MeshBasicMaterial({ color: 0x05070c }));
  pit.rotation.x = -Math.PI / 2; hole.add(pit);
  const lip = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(3.5, 0.01, 3.7)), new THREE.LineBasicMaterial({ color: 0xfbbf24 }));
  hole.add(lip);
  hole.position.set(x, 0.065, z); hole.visible = false;
  scene.add(hole);
  cabin = { group: g, sign, hole, fadeMats: [plate.material, rim.material, sign.material] };
}
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
  kick();
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
  officeRoot.add(group);
  const lab = document.createElement("div");
  lab.className = "lab" + (sub ? " sub" : "");
  // 위에서부터: 말풍선(Claude가 한 말) · 상태 배지(지금 하는 일) · 명찰(누구인지)
  lab.innerHTML = `<div class="say"><span class="q"></span></div><div class="pill"></div><div class="tag"><span class="t"></span><span class="g"><i></i></span></div>`;
  labels.appendChild(lab);
  return { key, sub, group, look, ring, hit, lab, lookKey: "", head: null, path: [], pos: [0, 0], room: "", leaving: false, opacity: 1, scale: s };
}
function setLook(a, ch, st) {
  const l = lookFor(ch, st);
  const k = `${l.image}|${l.emoji}|${ch.color}|${ch.pixel}|${l.image && imageTexture(l.image, ch.pixel).userData.ready}`;
  if (a.lookKey === k) return;
  a.lookKey = k;
  a.look.traverse(disposeOwnMat);
  a.look.clear(); a.head = null;
  if (l.image) {
    const tex = imageTexture(l.image, ch.pixel);
    const sp = new THREE.Sprite(perActor(new THREE.SpriteMaterial({ map: tex, transparent: true, alphaTest: 0.08 })));
    const img = tex.image, asp = img && img.width ? img.width / img.height : 1;
    const h = 2.0;
    sp.scale.set(h * asp, h, 1); sp.center.set(0.5, 0); sp.position.y = 0.05;
    a.look.add(sp); a.head = sp;
  } else {
    const body = new THREE.Mesh(CAPSULE, mat(new THREE.Color(ch.color).getHex()));
    body.position.y = 0.6; body.castShadow = true;
    a.look.add(body);
    const sp = new THREE.Sprite(perActor(new THREE.SpriteMaterial({ map: emojiTexture(l.emoji || "🙂"), transparent: true })));
    sp.scale.set(0.95, 0.95, 1); sp.position.y = 1.5;
    a.look.add(sp); a.head = sp;
  }
  kick();
}
// 사람마다 따로 만든 재질(얼굴 스프라이트, 흐리게 하려고 복제한 재질)은 그 사람이 없어질 때 함께 버린다.
// 공용 재질(mat() 캐시, 그림자·고리)과 텍스처 캐시(emoji·이미지)는 버리지 않는다
const perActor = m => { m.userData.perActor = true; return m; };
function disposeOwnMat(m) { if (m.material && (m.userData.own || m.material.userData.perActor)) m.material.dispose(); }
function setOpacity(a, o) {
  a.opacity = o;
  a.group.traverse(m => {
    if (!m.material || m === a.hit) return;
    if (!m.userData.own) {
      const orig = m.material;
      m.userData.base = orig.opacity; m.material = orig.clone(); m.userData.own = true;
      if (orig.userData.perActor) orig.dispose();   // 복제로 바꿔 끼운 원본 스프라이트 재질
    }
    m.material.transparent = true;
    m.material.opacity = m.userData.base * o;
  });
}
function setClip(a, on) {
  setOpacity(a, a.opacity ?? 1);   // 재질을 그 사람 전용으로 복제해 둔다
  a.group.traverse(m => {
    if (!m.material || m === a.hit) return;
    m.material.clippingPlanes = on ? [FLOOR_CLIP] : null;
    m.material.needsUpdate = true;
  });
}
function disposeActor(a) {
  a.group.removeFromParent();   // 사람은 층 묶음(officeRoot) 안에 있다
  a.group.traverse(disposeOwnMat);
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
// 층에 들어오면 그 층에서 가장 최근에 일한 세션을 골라 둔다(일하는 중인 세션 먼저).
// pickPending = 이 층에서 아직 자동으로 고르지 않음, autoPicked = 지금 선택이 자동으로 고른 것
let pickPending = true, autoPicked = false;
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
  $("play").innerHTML = on ? '<i class="fa-solid fa-stop"></i> 정지' : '<i class="fa-solid fa-play"></i> 재생';
  $("play").classList.toggle("on", on);
  setHTML($("playHint"), on ? "근무 중인 층을 돌아가며 보는 중" : "근무 중인 층 순회");
  $("progress").style.width = "0%";
}
$("play").onclick = () => setPlaying(!playing);
$("rotate").value = String(rotateSec);
$("rotate").onchange = e => { rotateSec = +e.target.value; rotateAt = Date.now(); savePlay(); };
function rotateTick() {
  const nowMs = Date.now(), dt = nowMs - lastTick;
  lastTick = nowMs;
  if (document.hidden) { rotateAt += dt; return; }   // 탭이 숨겨진 동안은 순회도 멈춘다(남은 시간 그대로)
  if (!playing || !state) return;
  const busy = userBusy() && !transit;
  if (busy) {
    rotateAt += dt;   // 멈춘 동안 흐른 시간만큼 미뤄 남은 시간을 그대로 둔다
    const ta = $("composeText");
    const left = Math.ceil((IDLE_RESUME_MS - (nowMs - lastInput)) / 1000);
    setHTML($("playHint"), '<i class="fa-solid fa-circle-pause"></i>' + (document.activeElement === ta || (ta && ta.value.trim())
      ? "메시지를 쓰는 중이라 멈춤" : `사용 중이라 잠깐 멈춤 · ${Math.max(1, left)}초 뒤 이어서`));
  } else if (pausedNow) {
    setHTML($("playHint"), "근무 중인 층을 돌아가며 보는 중");
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
  mePill(`${f.n}F로 가는 중`);
}
function mePill(text) {
  const p = me.actor.lab.querySelector(".pill");
  if (setHTML(p, text ? `<i class="fa-solid fa-elevator"></i>${esc(text)}` : "")) { p.dataset.st = text ? "trip" : ""; me.actor.lab._dirty = true; kick(); }
}
function stepTransit(t) {
  const m = me.actor, tr = transit;
  if (tr.phase === "walk") {
    if (m.path.length <= 2) doorOpenUntil = t + 800;          // 문 앞에 오면 연다
    if (!m.path.length) { tr.phase = "close"; tr.t = t; doorOpenUntil = 0; }
  } else if (tr.phase === "close" && t - tr.t > 800) {
    // 층은 그대로 두고 '나'와 엘리베이터 바닥판만 위로(또는 아래로) 사라졌다가, 새 층에서 반대쪽에서 나타난다
    tr.phase = "ride"; tr.t = t;
    const from = tr.from || tr.n;
    tr.dir = tr.n >= from ? 1 : -1;
    tr.floors = Math.max(1, Math.abs(tr.n - from));
    tr.vanish = 1100; tr.travel = 500 + tr.floors * 550; tr.appear = 1100;
    tr.dur = tr.vanish + tr.travel + tr.appear;
    tr.shown = null; tr.swapped = false;
    scene.attach(m.group);                       // '나'는 층 묶음에서 빠져 바닥판과 함께 움직인다
    setClip(m, true);
    cabin.group.visible = true; cabin.group.position.y = 0;
    $("stage").classList.add("riding");
    $("ride").classList.add("on");
    placeCar(tr.target, tr.dur);
  } else if (tr.phase === "ride") {
    // 위로 갈 때는 높이 올라가며 흐려진다. 아래로 갈 때는 바닥에 구멍이 열리고 그 속으로 내려가며,
    // 바닥 아래는 잘라 그리지 않는다(FLOOR_CLIP). 새 층에서 아래로부터 올라올 때도 구멍을 열고 닫는다
    const el = t - tr.t, from = tr.from || tr.n, UP = 7, DEPTH = 3.8;
    let y = 0, alpha = 1, cur = from, hole = 0, labA = 1;
    if (el < tr.vanish) {                        // 떠나기
      const p = el / tr.vanish;
      if (tr.dir > 0) { y = UP * p * p; alpha = 1 - p; labA = 1 - p; }
      else { hole = Math.min(1, p * 5); const q = Math.max(0, (p - 0.18) / 0.82); y = -DEPTH * q * q; labA = 1 - q; }
    } else if (el < tr.vanish + tr.travel) {      // 이동: 아무도 안 보이고 층 숫자만 올라간다(그사이 층을 바꾼다)
      if (!tr.swapped) {
        tr.swapped = true;
        $("stage").classList.add("swap"); setTimeout(() => $("stage").classList.remove("swap"), 450);
        gotoFloor(tr.target);
      }
      const p = (el - tr.vanish) / tr.travel;
      cur = Math.round(from + (tr.n - from) * p);
      y = tr.dir > 0 ? UP : -DEPTH; alpha = tr.dir > 0 ? 0 : 1; labA = 0;
      hole = tr.dir > 0 ? 0 : Math.max(0, 1 - (el - tr.vanish) / 350);   // 내려간 뒤 구멍이 닫힌다
    } else {                                     // 도착
      const p = Math.min(1, (el - tr.vanish - tr.travel) / tr.appear);
      if (tr.dir > 0) {                          // 아래에서 구멍을 열고 올라온다
        hole = p < 0.82 ? Math.min(1, p * 5) : Math.max(0, (1 - p) / 0.18);
        const r = Math.min(1, Math.max(0, (p - 0.1) / 0.72)), e = 1 - (1 - r) * (1 - r);
        y = -DEPTH * (1 - e); labA = e;
      } else {                                   // 위에서 내려온다
        const q = 1 - (1 - p) * (1 - p);
        y = UP * (1 - q); alpha = q; labA = q;
      }
      cur = tr.n;
    }
    cabin.hole.visible = hole > 0.01;
    cabin.hole.scale.set(Math.max(0.01, hole), 1, Math.max(0.01, hole));
    cabin.group.position.y = y;
    m.rideY = y;
    setOpacity(m, alpha);
    m.lab.style.opacity = String(labA);
    cabin.fadeMats.forEach(mm => { mm.opacity = alpha; });
    if (cur !== tr.shown) {
      tr.shown = cur;
      const arrow = tr.n > from ? "▲" : tr.n < from ? "▼" : "■";
      const icon = tr.n > from ? "fa-arrow-up" : tr.n < from ? "fa-arrow-down" : "fa-elevator";
      $("ride").innerHTML = `<i class="fa-solid fa-elevator"></i> <i class="fa-solid ${icon}"></i> <b>${cur}F</b>` +
        (cur === tr.n ? ` <span>${esc(tr.target)}</span>` : ` <span><i class="fa-solid fa-arrow-right"></i> ${tr.n}F</span>`);
      setElevSign(`${arrow}${cur}`, floorHue(cur));
    }
    if (el >= tr.dur + 150) {
      if (!tr.swapped) { tr.swapped = true; gotoFloor(tr.target); }
      endRide();
      tr.phase = "arrive"; tr.t = t; doorOpenUntil = t + 2600;
      m.pos = ELEV.inside.slice();
      setTimeout(() => $("ride").classList.remove("on"), 900);
    }
  } else if (tr.phase === "arrive" && t - tr.t > 600) {
    tr.phase = "out"; m.path = route("elevator", "mydesk", me.pos);
  } else if (tr.phase === "out" && !m.path.length) {
    transit = null; mePill(""); rotateAt = Date.now();
  }
}
// 탑승 연출을 정리하고 '나'를 다시 층 묶음에 넣는다(도착했을 때, 또는 손으로 층을 바꿔 끊었을 때)
function endRide() {
  officeRoot.position.y = 0;
  if (cabin) { cabin.group.visible = false; cabin.group.position.y = 0; cabin.hole.visible = false; cabin.fadeMats.forEach(mm => { mm.opacity = 1; }); }
  if (me.actor) {
    me.actor.rideY = 0;
    setOpacity(me.actor, 1);
    setClip(me.actor, false);
    me.actor.lab.style.opacity = "";
    if (me.actor.group.parent !== officeRoot) officeRoot.attach(me.actor.group);
  }
  $("stage").classList.remove("riding");
}
function placeCar(project, ms) {
  const story = [...$("floors").querySelectorAll(".story")].find(x => x.dataset.p === project);
  const car = $("car");
  if (ms) setStyle(car, "transition-duration", `${ms}ms, .3s`);
  else if (!(transit && transit.phase === "ride")) setStyle(car, "transition-duration", "");
  if (story) { setStyle(car, "display", ""); setStyle(car, "transform", `translateY(${story.offsetTop}px)`); setStyle(car, "height", story.offsetHeight + "px"); }
  else setStyle(car, "display", "none");
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
  // 권한 창을 띄우고 사용자의 승인을 기다리는 중(선택 훅을 넣은 컴퓨터만 보낸다). 그 도구의 방에 서서 기다린다
  if (a.kind === "approval") return "approval";
  if (a.stalled) return "stalled";
  if (a.kind === "working" || a.kind === "shell") return "working";
  if (a.kind === "waiting") return "waiting";   // 턴은 끝났지만 백그라운드 작업을 기다리는 중(불은 켜 둔다)
  return a.kind === "thinking" ? "thinking" : "idle";
}
function roomFor(key, a, parentRoom) {
  let room;
  if (a.kind === "idle") room = "lounge";
  else if (a.kind === "waiting") room = (a.bg && a.bg[0]) ? roomForTool(cfg, a.bg[0].tool) : (lastRoom.get(key) || "server");
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
  floorKey = p; selected = null; pickPending = true; autoPicked = false;
  history.replaceState(null, "", "#p=" + encodeURIComponent(p));
  for (const a of actors.values()) disposeActor(a);
  actors.clear(); seatOf.clear();
  apply(true);
}

function log(project, who, text, ts, icon) {
  const l = logs.get(project) || [];
  l.unshift({ ts: ts || Date.now() / 1000 - skew, who, text, icon });
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
        if (!it.sub) (it.x.recent || []).slice().reverse().forEach(r => log(a.project, it.who, `${r.tool}${r.target ? " · " + r.target : ""}`, r.ts, toolIcon(r.tool)));
      } else if (was === undefined && it.sub) log(a.project, it.who, "출근", undefined, "elevator");
      else if (t && t !== was) log(a.project, it.who, t, undefined, toolIcon(it.x.tool));
      prevTool.set(it.key, t);
    }
  }
  for (const k of [...prevTool.keys()]) if (!seen.has(k)) {
    if (k.includes("/")) { const p = (state.agents.find(a => k.startsWith(a.id + "/")) || {}).project; if (p) log(p, "서브에이전트", "퇴근", undefined, "elevator"); }
    prevTool.delete(k);
  }
}

function apply(instant) {
  if (!state) return;
  cfg = state.config;
  const fl = floors();
  const before = floorKey;
  chooseFloor(fl);
  if (before !== floorKey) { for (const a of actors.values()) disposeActor(a); actors.clear(); seatOf.clear(); instant = true; selected = null; pickPending = true; autoPicked = false; }
  const floor = fl.find(f => f.project === floorKey);
  autoPick(floor);
  const agents = floor ? floor.agents : [];
  if (floor && !(transit && transit.phase === "ride" && !transit.swapped)) applyTheme(floor.n, fl.length, floor.project);
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
  renderRuleBox();
  setStyle($("empty"), "display", state.hosts.some(h => h.online) ? "none" : "grid");
  kick();
}

function updateSigns() {
  const sig = JSON.stringify(cfg.rooms);
  if (updateSigns.sig === sig) return;
  updateSigns.sig = sig;
  for (const r of cfg.rooms) if (signs[r.id]) {
    const old = signs[r.id].material.map;
    const t = signTexture(ROOM_GLYPH[r.id], r.name, EN[r.id] || "");
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
  setText(me.actor.lab.querySelector(".t"), nm === "나" ? "나" : `${nm} (나)`);
  setStyle(me.actor.lab, "--c", "#f97316");
  setStyle(me.actor.lab.querySelector(".say"), "display", "none");
}

// ---------- 화면 글자 ----------
function stateHTML(a, st, now) {
  if (st === "waiting") {
    const n = (a.bg || []).length, b = (a.bg || [])[0];
    return `<i class="fa-solid fa-hourglass-half"></i>백그라운드 기다리는 중${n ? ` <small>${n}개${b ? " · " + esc(b.target || b.tool) : ""}</small>` : ""}`;
  }
  if (st === "approval") return `<i class="fa-solid fa-hand"></i>승인 대기${a.tool ? ` · <code>${esc(a.tool)}</code>` : ""} · <small>${agoSpan(a.since || null, "째")}</small>`;
  if (st === "stalled") return `<i class="fa-solid fa-hourglass-end"></i>턱 괴고 고민 중 <small>${agoSpan(a.lastActivity)}</small>`;
  if (st === "working") {
    if (a.kind === "shell") return `<i class="fa-solid fa-terminal"></i>셸 명령`;
    const long = a.since && now - a.since > 120 ? ` <small><i class="fa-solid fa-clock"></i> ${agoSpan(a.since)}</small>` : "";
    return `<i class="fa-solid fa-${toolIcon(a.tool)}"></i><code>${esc(a.tool)}</code>${a.target ? `<span class="tg">${esc(a.target)}</span>` : ""}${long}`;
  }
  if (st === "thinking") return `<i class="fa-solid fa-brain"></i>고민 중 <small>${agoSpan(a.since || null, "째")}</small>`;
  return now - (a.since || now) > 600 ? `<i class="fa-solid fa-bed"></i>휴식 <small>${agoSpan(a.since)}</small>` : `<i class="fa-solid fa-mug-hot"></i>휴식 <small>${agoSpan(a.since || null)}</small>`;
}
// 토큰 수를 짧게(1234 → 1k, 1500000 → 1.5M)
const fmtTok = n => !n ? "0" : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n);
function ctxPct(a) { const c = a && a.ctx; return c && c.max ? Math.min(100, Math.round(c.used / c.max * 100)) : null; }
const ctxLevel = p => p >= 85 ? "hi" : p >= 65 ? "mid" : "lo";
const STATE_COLOR = { working: "#38bdf8", thinking: "#a78bfa", stalled: "#fbbf24", waiting: "#2dd4bf", approval: "#f97316", idle: "#94a3b8" };
const STATE_WORD = { working: "근무", thinking: "고민", stalled: "막힘", waiting: "대기", approval: "승인", idle: "휴식" };
function renderLabels() {
  const now = Date.now() / 1000 - skew;
  let changed = false;
  for (const ac of actors.values()) {
    const it = ac.item; if (!it) continue;
    const lab = ac.lab;
    const say = cfg.speech !== false && it.a.say && (it.st !== "idle" || selected === it.key) ? it.a.say : "";
    const pillHTML = stateHTML(it.a, it.st, now), pillOff = it.st === "idle" && selected !== it.key;
    const title = it.sub ? `${it.a.type}${it.a.description ? " · " + it.a.description : ""}` : (it.a.title || it.a.name);
    const color = it.ch ? it.ch.color : "#64748b";
    // 쉬는 사람은 라운지에 몰려 이름표가 겹친다 — 올리거나 고르거나 크게 확대했을 때만 보인다
    const sel = selected === it.key, quiet = it.st === "idle" && !sel && hovered !== it.key && zoom < 1.8;
    const pct = it.sub ? null : ctxPct(it.a);
    const sig = [say, pillHTML, it.st, pillOff, title, color, sel, quiet, pct].join("\u0001");
    if (lab._sig !== sig) {   // 내용이 같으면 손대지 않는다(크기를 다시 재는 일도 없다)
      lab._sig = sig;
      lab.querySelector(".q").textContent = say;
      lab.querySelector(".say").style.display = say ? "" : "none";
      const pill = lab.querySelector(".pill");
      pill.innerHTML = pillHTML;
      pill.dataset.st = it.st;
      pill.style.display = pillOff ? "none" : "";
      lab.querySelector(".t").textContent = title;
      // 명찰 아래 얇은 막대 = 컨텍스트 창을 얼마나 썼나(65%↑ 노랑, 85%↑ 빨강 — 곧 자동 압축)
      const g = lab.querySelector(".g");
      g.style.display = pct == null ? "none" : "";
      if (pct != null) { g.dataset.lv = ctxLevel(pct); g.firstChild.style.width = pct + "%"; g.title = `컨텍스트 ${pct}%`; }
      lab.style.setProperty("--c", color);   // 명찰 띠 = 캐릭터 색
      lab.classList.toggle("sel", sel);
      lab.classList.toggle("idle", it.st === "idle");
      lab.classList.toggle("quiet", quiet);
      ac.ring.visible = sel;
      lab._dirty = changed = true;
    }
    if (tickTimes(lab, now)) lab._dirty = changed = true;
  }
  if (changed) kick();
}
function autoPick(floor) {
  if (!floor || !floor.agents.length) return;
  const alive = selected && floor.agents.some(a => a.id === selected || selected.startsWith(a.id + "/"));
  if (alive) return;
  if (selected && autoPicked) pickPending = true;     // 자동으로 고른 세션이 끝나 사라졌으면 다음 후보
  if (!pickPending) return;                           // 사람이 선택을 풀었으면 이 층에서는 다시 고르지 않는다
  const best = floor.agents.slice().sort((a, b) =>
    (b.kind !== "idle") - (a.kind !== "idle") || (b.lastActivity || 0) - (a.lastActivity || 0))[0];
  selected = best.id; pickPending = false; autoPicked = true;
}
function select(key) {
  pickPending = false; autoPicked = false;   // 사람이 고르거나 풀면 자동 선택은 손을 뗀다
  selected = selected === key ? null : key;
  if (selected && doneAt.delete(selected.split("/")[0])) renderAttention();   // 끝난 세션을 열어 봤으면 '확인함'
  if (selected) showTab("session");   // 캐릭터를 고르면 그 세션 탭으로
  renderLabels();
  if (state) { const fl = floors(); renderPeople(fl.find(f => f.project === floorKey), assignCharacters(cfg, state.agents)); }
}

const MAX_WINDOWS = 8;
function renderFloors(fl) {
  const now = Date.now() / 1000 - skew;
  const chars = assignCharacters(cfg, state.agents);
  // 창문 하나 = 세션 하나. 근무 중이면 불이 켜지고 그 세션의 캐릭터가 창가에 선다
  setHTML($("floors"), fl.slice().reverse().map(f => {
    const ws = f.agents.slice().sort((a, b) => (b.kind !== "idle") - (a.kind !== "idle") || (b.lastActivity || 0) - (a.lastActivity || 0));
    const wins = ws.slice(0, MAX_WINDOWS).map(a => {
      const ch = chars.get(a.id), st = stateOf(a), l = ch ? lookFor(ch, st) : { emoji: "🙂" };
      const face = l.image ? `<img src="/assets/${encodeURIComponent(l.image)}" alt="">` : esc(l.emoji || "🙂");
      return `<span class="win ${a.kind !== "idle" ? "lit" : ""} w-${st}" title="${esc(a.title || a.name)} · ${STATE_WORD[st]}">${face}</span>`;
    }).join("") + (ws.length > MAX_WINDOWS ? `<span class="win more">+${ws.length - MAX_WINDOWS}</span>` : "");
    return `<div class="story${f.project === floorKey ? " cur" : ""}${f.busy ? " busy" : ""}" data-p="${esc(f.project)}">
      <span class="no" style="--h:${(f.n * 47) % 360}">${f.n}F</span>
      <span class="info"><b>${esc(f.project)}</b><small>${f.busy ? `<em>${f.busy}명 근무 중</em> · ` : ""}세션 ${f.agents.length}개${f.busy ? "" : " · " + agoSpan(f.last, " 전")}</small>
      <span class="wins">${wins}</span></span></div>`;
  }).join("") || `<div class="muted" style="padding:16px">보이는 세션이 없습니다.</div>`);
  tickTimes($("floors"), now);
  setHTML($("lobbyHosts"), state.hosts.map(h => `<span class="chip"><span class="dot ${h.online ? "on" : "off"}"></span>${esc(h.host)}</span>`).join(" "));
  // 엘리베이터 칸을 지금 보는 층으로 옮긴다(위치가 바뀌면 미끄러지듯 이동)
  if (!(transit && transit.phase === "ride")) placeCar(floorKey);
  const f = fl.find(x => x.project === floorKey);
  setHTML($("floorBadge"), f ? `<span class="badge" style="--h:${(f.n * 47) % 360}">${f.n}F</span><b>${esc(f.project)}</b><small>${esc(f.host || "")} · 세션 ${f.agents.length}개</small>` : "");
}
$("floors").addEventListener("click", e => {
  const f = e.target.closest("[data-p]");
  if (!f) return;
  if (playing) rotateAt = Date.now();  // 손으로 고른 층은 한 간격 동안 머문다
  if (transit) { endRide(); transit = null; me.actor.path = []; me.actor.pos = me.pos.slice(); mePill(""); $("ride").classList.remove("on"); }
  gotoFloor(f.dataset.p);
});
setPlaying(playing);

function renderPeople(floor, chars) {
  const now = Date.now() / 1000 - skew;
  if (!floor) { setHTML($("people"), ""); setHTML($("detail"), ""); updateCompose(null); updateSessionTab(null); return; }
  const rows = [];
  for (const a of floor.agents) {
    rows.push(personRow(a.id, a, chars.get(a.id), stateOf(a), a.title || a.name, a.name, now, false));
    for (const s of a.subagents || []) rows.push(personRow(a.id + "/" + s.id, { ...s, kind: s.tool ? "working" : "thinking", lastActivity: s.since }, chars.get(a.id + "/" + s.id), s.tool ? "working" : "thinking", `${s.type}${s.description ? " · " + s.description : ""}`, "서브에이전트", now, true));
  }
  const busy = floor.agents.filter(a => a.kind !== "idle").length;
  setText($("peopleHead"), `${floor.agents.length}명 · ${busy}명 근무 중`);
  setText($("tabPeopleN"), String(floor.agents.length || ""));
  setHTML($("people"), rows.join(""));
  tickTimes($("people"), now);
  const a = floor.agents.find(x => x.id === selected) || floor.agents.find(x => selected && selected.startsWith(x.id + "/"));
  setHTML($("detail"), a ? detailCard(a, chars.get(a.id), now) : "");
  tickTimes($("detail"), now);
  updateCompose(a, now);
  updateSessionTab(a);
}
function personRow(key, a, ch, st, title, sub, now, isSub) {
  const label = STATE_WORD[st];
  const line = st === "working" ? `${a.tool || "셸"}${a.target ? " · " + a.target : ""}`
    : st === "approval" ? `승인 대기${a.tool ? " · " + a.tool : ""}${a.target ? " · " + a.target : ""}` : (a.say || "");
  return `<li data-k="${esc(key)}" class="${isSub ? "sub" : ""}${selected === key ? " on" : ""}">
    <span class="av" style="--c:${ch ? ch.color : "#64748b"}">${ch ? avatarSmall(ch, st) : ""}</span>
    <span class="body"><span class="r1"><b>${esc(title)}</b><span class="st st-${st}">${label}</span></span>
    <span class="r2">${esc(line)}</span>
    <span class="r3">${esc(sub)} · 도구 ${a.tools || 0}회 · ${agoSpan(a.since || null)}${todoCount(a.todos)}${!isSub && ctxPct(a) != null ? ` · <span class="ctxp lv-${ctxLevel(ctxPct(a))}">ctx ${ctxPct(a)}%</span>` : ""}</span></span></li>`;
}
function avatarSmall(ch, st) {
  const l = lookFor(ch, st);
  return l.image ? `<img src="/assets/${encodeURIComponent(l.image)}" alt=""${ch.pixel ? ' style="image-rendering:pixelated"' : ""}>` : `<span class="emo">${esc(l.emoji || "🙂")}</span>`;
}
// 할 일 체크리스트: 세션의 Claude 가 TaskCreate/TaskUpdate(또는 TodoWrite)로 만든 목록을 보여 주기만 한다
// 각 컴퓨터의 Claude 전역 지침(~/.claude/CLAUDE.md)에 넣을 문장. 이게 있어야 Claude 가 할 일 목록을 늘 만든다
const CHECKLIST_RULE = "## 할 일 체크리스트\n\n- 단계가 2개 이상인 작업은 시작할 때 할 일 도구(`TaskCreate`, 없으면 `TodoWrite`)로 단계 목록을 만들고,\n  단계를 시작하고 끝낼 때마다 `TaskUpdate`로 상태(진행 중·완료)를 바꾼다. 한 번에 끝나는 질문·작은 수정에는 만들지 않는다.\n";
function ruleHint(host) {
  return `<div class="rule-hint"><p><i class="fa-solid fa-circle-info"></i> <b>${esc(host)}</b> 의 Claude 전역 지침에 할 일 체크리스트 규칙이 없어 목록이 잘 안 생깁니다.
    그 컴퓨터의 <code>~/.claude/CLAUDE.md</code>(Windows: <code>%USERPROFILE%\\.claude\\CLAUDE.md</code>)에 아래 문장을 넣고 세션을 다시 시작하세요.</p>
    <pre>${esc(CHECKLIST_RULE)}</pre><button class="copy" data-copy="rule"><i class="fa-solid fa-copy"></i> 문장 복사</button></div>`;
}
function hostInfo(host) { return (state && state.hosts.find(h => h.host === host)) || {}; }
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");   // http 주소(보안 컨텍스트 아님)에서는 예전 방식으로
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta);
  ta.select(); try { document.execCommand("copy"); } finally { ta.remove(); }
  return Promise.resolve();
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-copy=rule]"); if (!b) return;
  copyText(CHECKLIST_RULE).then(() => { b.innerHTML = '<i class="fa-solid fa-check"></i> 복사했습니다'; setTimeout(() => { b.innerHTML = '<i class="fa-solid fa-copy"></i> 문장 복사'; }, 1800); });
});
function renderRuleBox() {
  if (!state) return;
  const rows = state.hosts.map(h => {
    const st = h.checklistRule === true ? `<span class="ok"><i class="fa-solid fa-circle-check"></i> 들어 있음</span>`
      : h.checklistRule === false ? `<span class="no"><i class="fa-solid fa-circle-xmark"></i> 없음</span>` : `<span class="muted">확인 전</span>`;
    return `<li><b>${esc(h.host)}</b>${st}</li>`;
  }).join("");
  const sig = rows;
  if (renderRuleBox.sig === sig) return;
  renderRuleBox.sig = sig;
  $("ruleBox").innerHTML = `<div class="pane-head">할 일 체크리스트 설정</div>
    <p class="muted">Claude 가 여러 단계 작업마다 할 일 목록을 만들게 하려면, 세션을 띄우는 컴퓨터마다 Claude 전역 지침
    <code>~/.claude/CLAUDE.md</code>(Windows: <code>%USERPROFILE%\\.claude\\CLAUDE.md</code>)에 아래 문장을 넣습니다. 새로 시작한 세션부터 적용됩니다.</p>
    <ol class="rule-hosts">${rows}</ol><pre>${esc(CHECKLIST_RULE)}</pre><button class="copy" data-copy="rule"><i class="fa-solid fa-copy"></i> 문장 복사</button>`;
}
function todoCount(todos) {
  if (!todos || !todos.length) return "";
  return ` · 할 일 ${todos.filter(t => t.st === "completed").length}/${todos.length}`;
}
function todoList(todos) {
  if (!todos || !todos.length) return "";
  const done = todos.filter(t => t.st === "completed").length;
  const icon = { completed: "circle-check", in_progress: "circle-play", pending: "circle" };
  return `<h4>할 일 <span class="todo-n">${done}/${todos.length}</span></h4><ol class="todos">` + todos.map(t =>
    `<li class="${t.st}"><i class="fa-solid fa-${icon[t.st] || "circle"}"></i><span>${esc(t.s)}</span></li>`).join("") + `</ol>`;
}
function detailCard(a, ch, now) {
  const recent = (a.recent || []).map(r => `<li><span class="t">${esc(r.tool)}</span><span class="g">${esc(r.target)}</span><span class="a">${r.ts ? agoSpan(r.ts) : ""}</span></li>`).join("");
  return `<div class="detail"><div class="dh"><span class="av big" style="--c:${ch ? ch.color : "#64748b"}">${ch ? avatarSmall(ch, stateOf(a)) : ""}</span>
    <span><b>${esc(a.title || a.name)}</b><small>${esc(a.name)} · ${esc(ch ? ch.name : "")} · PID ${esc(a.pid)}</small></span></div>
    ${sessionMeta(a)}
    ${a.kind === "approval" ? `<p class="approval-note"><i class="fa-solid fa-hand"></i> 권한 승인을 기다리는 중${a.tool ? ` · <code>${esc(a.tool)}</code>` : ""}${a.target ? ` · ${esc(a.target)}` : ""} · ${agoSpan(a.since || null, "째")}<small>그 컴퓨터의 터미널에서 승인하거나 거절하면 풀립니다.</small></p>` : ""}
    ${a.say && cfg.speech !== false ? `<p class="quote">“${esc(a.say)}”</p>` : ""}
    ${todoList(a.todos) || (hostInfo(a.host).checklistRule === false ? ruleHint(a.host) : "")}
    <h4>최근 도구</h4>${recent ? `<ol class="recent">${recent}</ol>` : `<div class="muted">기록 없음</div>`}</div>`;
}
// 모델·브랜치·바꾼 줄·출력 토큰 + 컨텍스트 막대(수집기가 기록의 usage 로 계산해 보낸다)
function sessionMeta(a) {
  const bits = [];
  if (a.model) bits.push(`<span title="모델"><i class="fa-solid fa-microchip"></i>${esc(a.model)}</span>`);
  if (a.branch) bits.push(`<span title="git 브랜치"><i class="fa-solid fa-code-branch"></i>${esc(a.branch)}</span>`);
  const ln = a.lines || [0, 0];
  if (ln[0] || ln[1]) bits.push(`<span title="이 세션이 Edit·Write 로 더하고 뺀 줄"><i class="fa-solid fa-pen-to-square"></i><em class="add">+${ln[0]}</em> <em class="del">−${ln[1]}</em></span>`);
  if (a.outTokens) bits.push(`<span title="이 세션이 쓴 출력 토큰(기록이 아주 크면 끝부분만 센 값)"><i class="fa-solid fa-feather"></i>출력 ${fmtTok(a.outTokens)}</span>`);
  const p = ctxPct(a);
  const bar = p == null ? "" : `<div class="ctxbar" data-lv="${ctxLevel(p)}"><div class="row"><b>컨텍스트</b><span>${fmtTok(a.ctx.used)} / ${fmtTok(a.ctx.max)} · ${p}%</span></div>
    <div class="track"><i style="width:${p}%"></i></div>${a.compacts ? `<small>압축 ${a.compacts}회 · 마지막 ${agoSpan(a.compactAt, " 전")}</small>` : p >= 85 ? `<small>곧 자동 압축될 수 있습니다</small>` : ""}</div>`;
  return bits.length || bar ? `<div class="smeta">${bits.join("")}</div>${bar}` : "";
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
  if ($("sessionEmpty").hidden !== !!a) $("sessionEmpty").hidden = !!a;
  if ($("tabSessionDot").className !== (a ? "dot" : "")) $("tabSessionDot").className = a ? "dot" : "";   // 고른 세션이 있으면 탭에 점
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
  if (!a) { if (!box.hidden) box.hidden = true; composeFor = null; return; }
  if (box.hidden) box.hidden = false;
  if (composeFor !== a.id) { composeFor = a.id; $("composeText").value = ""; $("composeCount").textContent = "0 / 4000"; }
  setText($("composeTarget"), `${a.title || a.name} @${a.host}`);
  const m = state.messaging || {};
  let note = "", warn = false, can = false;
  if (!m.auth) note = "허브에 OFFICE_TOKEN 이 없어 꺼져 있습니다(.env 에 정하고 허브를 다시 띄우세요).";
  else if (!m.ready) note = "관리 화면 「화면 설정」에서 '대시보드에서 메시지 보내기'를 켜야 합니다.";
  else if (!a.canMessage) note = "이 세션의 컴퓨터 수집기가 메시지를 받지 않습니다(그 컴퓨터 .env 의 CLAUDE_OFFICE_MESSAGES=on, Windows 는 아직 미지원).";
  else if (a.mode === "bypassPermissions") { can = true; warn = true; note = "이 세션은 권한 확인을 건너뛰는 모드라, 메시지가 그 터미널에서 승인을 기다립니다(5분 안에 승인하지 않으면 버려짐)."; }
  else { can = true; note = "받는 Claude 는 '다른 세션이 보낸 메시지'로 받습니다. 권한 승인이나 설정 변경은 메시지로 할 수 없습니다."; }
  const help = $("composeHelp");
  if (help.dataset.tip !== note) help.dataset.tip = note;
  help.classList.toggle("warn", can && warn);
  help.classList.toggle("off", !can);
  const ta = $("composeText"), ph = can ? "Claude 에게 보낼 말 (⌘/Ctrl + Enter 로 보내기)" : "보낼 수 없음 · [?] 참고";
  if (ta.disabled !== !can) { ta.disabled = !can; $("composeSend").disabled = !can; }
  if (ta.placeholder !== ph) ta.placeholder = ph;
  const mine = (state.messages || []).filter(x => x.session === a.id).slice(-4).reverse();
  setHTML($("composeLog"), mine.map(x => `<li title="${esc(x.error || "")}"><span class="s ${x.status}">${MSG_LABEL[x.status] || x.status}</span><span class="p">${esc(x.error && x.status !== "sent" ? x.error : x.preview)}</span><span class="muted">${agoSpan(x.createdAt, " 전")}</span></li>`).join(""));
  tickTimes($("composeLog"), now || Date.now() / 1000 - skew);
}
$("composeHelp").addEventListener("pointerdown", e => {
  const h = e.currentTarget;
  if (document.activeElement === h) { e.preventDefault(); h.blur(); }   // 열려 있으면 닫기
});
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
    log(a.project, `나 → ${a.title || a.name}`, text.slice(0, 60), undefined, "comment");
    return;
  }
}

function renderLog(floor) {
  const now = Date.now() / 1000 - skew;
  const l = floor ? (logs.get(floor.project) || []) : [];
  setHTML($("log"), l.slice(0, 30).map(x => `<li><span class="a">${agoSpan(x.ts, " 전")}</span><span class="w">${esc(x.who)}</span><span class="x">${x.icon ? `<i class="fa-solid fa-${x.icon}"></i> ` : ""}${esc(x.text)}</span></li>`).join("") || `<li class="muted">아직 기록이 없습니다.</li>`);
  tickTimes($("log"), now);
}
function renderLegend() {
  const sig = JSON.stringify(cfg.rooms);
  if (renderLegend.sig === sig) return;
  renderLegend.sig = sig;
  $("legend").innerHTML = cfg.rooms.map(r => `<li><i class="fa-solid fa-${ROOM_ICON[r.id]}"></i><b>${esc(r.name)}</b><span>${esc(r.desc || "")}</span></li>`).join("") +
    `<li><i class="fa-solid fa-elevator"></i><b>엘리베이터</b><span>서브에이전트 출퇴근</span></li>` +
    `<li class="appr"><i class="fa-solid fa-hand"></i><b>승인 대기</b><span>권한 창 앞에서 기다리는 세션(주황 배지). 선택 기능이라 그 컴퓨터에 훅을 넣어야 보입니다 — README 「선택: 승인 대기 감지(훅)」</span></li>`;
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
    const tf = `translate(${p.x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, -100%)`;
    if (lab._tf !== tf) { lab._tf = tf; lab.style.transform = tf; }
    const z = p.ac.key === hovered || p.ac.key === selected ? "100000" : String(Math.round(p.y));
    if (lab._z !== z) { lab._z = z; lab.style.zIndex = z; }
  }
}

// ---------- 최근 소식(아래 서랍) ----------
// 모든 층의 세션이 일을 마친(근무 → 휴식) 때, 시작한(휴식 → 근무) 때, 새로 생기거나 끝난 때를 최신 순으로 모은다.
// 처음 열 때는 지금 상태로 채운다: 쉬는 세션 = 마지막으로 마친 시각, 일하는 세션 = 시작 시각(근사).
const FEED_MAX = 300;
const feed = [];                 // {ts, type: done|start|new|end|approval, id, project, title, say, tool}
const feedKind = new Map();      // 세션 id -> 지난번 근무 여부
const feedAppr = new Map();      // 세션 id -> 지난번 승인 대기 여부
let feedOpen = false, feedFilter = "all", feedSeenTs = 0, feedQuery = "", feedView = "news", tlScope = "floor", tlWin = 600;
try { feedView = localStorage.getItem("office.feedView") === "tl" ? "tl" : "news"; tlScope = localStorage.getItem("office.tlScope") === "busy" ? "busy" : "floor"; tlWin = +localStorage.getItem("office.tlWin") === 1800 ? 1800 : 600; } catch (_) {}
try { feedOpen = localStorage.getItem("office.feed") === "1"; feedSeenTs = +localStorage.getItem("office.feedSeen") || 0; } catch (_) {}
const feedCompacts = new Map();  // 세션 id -> 지난번 압축 횟수
const FEED_ICON = { done: "circle-check", start: "circle-play", new: "plus", end: "power-off", approval: "hand", compact: "compress" };
const FEED_WORD = { done: "작업 완료", start: "작업 시작", new: "새 세션", end: "세션 종료", approval: "승인 대기", compact: "컨텍스트 압축" };
function feedPush(e) { feed.push(e); if (feed.length > FEED_MAX) feed.splice(0, feed.length - FEED_MAX); }
function trackFeed(first) {
  const now = Date.now() / 1000 - skew, seen = new Set(), events = [];
  for (const a of state.agents) {
    seen.add(a.id);
    const busy = a.kind !== "idle", base = { id: a.id, project: a.project, title: a.title || a.name };
    if (first) {
      feedPush({ ...base, type: busy ? "start" : "done", ts: (busy ? a.since : a.since || a.lastActivity) || now, say: busy ? "" : a.say });
    } else if (!feedKind.has(a.id)) {
      feedPush({ ...base, type: "new", ts: a.startedAt || now });
      if (busy) feedPush({ ...base, type: "start", ts: now });
    } else if (feedKind.get(a.id) !== busy) {
      feedPush({ ...base, type: busy ? "start" : "done", ts: now, say: busy ? "" : a.say });
      if (busy) doneAt.delete(a.id);
      else { doneAt.set(a.id, now); events.push({ type: "done", a }); }
    }
    feedKind.set(a.id, busy);
    // 컨텍스트 압축: 횟수가 늘어난 순간 한 줄
    const nc = a.compacts || 0;
    if (!first && feedCompacts.has(a.id) && nc > feedCompacts.get(a.id)) feedPush({ ...base, type: "compact", ts: a.compactAt || now, n: nc });
    feedCompacts.set(a.id, nc);
    // 승인 대기에 들어간 순간 한 줄(풀릴 때는 따로 남기지 않는다)
    const appr = a.kind === "approval";
    // 같은 순간의 '작업 시작'보다 위에 오게 아주 조금 뒤 시각으로 둔다
    if (appr && !feedAppr.get(a.id)) {
      feedPush({ ...base, type: "approval", ts: ((first ? a.since : now) || now) + 0.001, tool: a.tool || "" });
      if (!first) events.push({ type: "approval", a });
    }
    feedAppr.set(a.id, appr);
  }
  for (const id of [...feedKind.keys()]) if (!seen.has(id)) {
    const last = [...feed].reverse().find(e => e.id === id);
    if (last) feedPush({ id, project: last.project, title: last.title, type: "end", ts: now });
    feedKind.delete(id); feedAppr.delete(id); feedCompacts.delete(id); doneAt.delete(id);
  }
  renderFeed();
  alertFor(events.splice(0));
  renderAttention();
}
function renderFeed() {
  const now = Date.now() / 1000 - skew;
  const fl = state ? floors() : [];
  const floorN = new Map(fl.map(f => [f.project, f.n]));
  const sorted = [...feed].sort((a, b) => b.ts - a.ts);
  const recent = sorted.filter(e => now - e.ts < 3600);
  const done = recent.filter(e => e.type === "done").length, start = recent.filter(e => e.type === "start").length;
  setHTML($("feedCounts"), (done ? `<span class="done" title="최근 1시간 완료">완료 ${done}</span>` : "") +
    (start ? `<span class="start" title="최근 1시간 시작">시작 ${start}</span>` : ""));
  const top = sorted[0];
  setHTML($("feedLatest"), top ? `<i class="fa-solid fa-${FEED_ICON[top.type]}"></i> ${esc(top.title)} · ${FEED_WORD[top.type]} · ${agoSpan(top.ts, " 전")}` : "");
  tickTimes($("feedLatest"), now);
  if (!feedOpen) return;
  renderTimeline();
  if (feedView !== "news") return;
  const q = feedQuery.trim().toLowerCase();
  const list = sorted.filter(e => (feedFilter === "all" || (feedFilter === "life" ? e.type === "new" || e.type === "end" : e.type === feedFilter)) &&
    (!q || [e.title, e.project, e.say, e.tool, FEED_WORD[e.type]].some(v => v && String(v).toLowerCase().includes(q))));
  setHTML($("feedList"), list.slice(0, 120).map(e => {
    const n = floorN.get(e.project);
    const what = e.type === "compact" ? `${FEED_WORD[e.type]} · ${e.n}회째 · ${esc(e.project)}` : e.type === "done" && e.say ? `${FEED_WORD[e.type]} · <q>${esc(e.say)}</q>`
      : e.type === "approval" && e.tool ? `${FEED_WORD[e.type]} · <code>${esc(e.tool)}</code> · ${esc(e.project)}` : `${FEED_WORD[e.type]} · ${esc(e.project)}`;
    return `<li data-id="${esc(e.id)}" data-p="${esc(e.project)}" class="${e.ts > feedSeenTs ? "unseen" : ""}">
      <i class="fa-solid fa-${FEED_ICON[e.type]} ic ${e.type}"></i><span class="t">${agoSpan(e.ts, " 전")}</span>
      <span class="who">${n ? `<span class="badge" style="--h:${floorHue(n)}">${n}F</span>` : ""}<b>${esc(e.title)}</b></span>
      <span class="what">${what}</span></li>`;
  }).join("") || `<li class="empty">${q || feedFilter !== "all" ? "조건에 맞는 소식이 없습니다." : "아직 소식이 없습니다."}</li>`);
  tickTimes($("feedList"), now);
}
// 끌어서 정한 높이(px). 0 이면 기본(무대의 42%)
let feedH = 0;
try { feedH = +localStorage.getItem("office.feedH") || 0; } catch (_) {}
const FEED_MIN = 40, FEED_CLOSE_BELOW = 84;
function applyFeedH() {
  const st = $("stage");
  if (feedOpen && feedH) st.style.setProperty("--feedH", Math.min(feedH, st.clientHeight - 90) + "px");
  else st.style.removeProperty("--feedH");
}
function setFeedOpen(on) {
  feedOpen = on;
  $("stage").classList.toggle("feed-open", on);
  applyFeedH();
  $("feedToggle").setAttribute("aria-expanded", on ? "true" : "false");
  renderFeed();
  if (on) { feedSeenTs = Date.now() / 1000 - skew; try { localStorage.setItem("office.feedSeen", String(feedSeenTs)); } catch (_) {} }
  try { localStorage.setItem("office.feed", on ? "1" : "0"); } catch (_) {}
  setTimeout(resize, 260);   // 서랍 높이가 바뀌어도 3D 화면 크기는 그대로(무대 위에 겹친다). 라벨 위치만 다시
}
$("feedToggle").onclick = () => setFeedOpen(!feedOpen);
// 위쪽 가장자리를 끌어 높이 조절. 아주 낮추면 접히고, 접힌 상태에서 끌어올리면 펼쳐진다
$("feedGrip").addEventListener("pointerdown", e => {
  e.preventDefault();
  const st = $("stage"), grip = e.currentTarget, startY = e.clientY, startH = $("feed").offsetHeight;
  grip.setPointerCapture(e.pointerId);
  st.classList.add("feed-dragging");
  let h = startH;
  const move = ev => {
    h = Math.max(FEED_MIN, Math.min(st.clientHeight - 90, startH + (startY - ev.clientY)));
    if (!feedOpen && h > FEED_CLOSE_BELOW) { feedOpen = true; st.classList.add("feed-open"); renderFeed(); }
    st.style.setProperty("--feedH", h + "px");
    kick();
  };
  const up = () => {
    grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); grip.removeEventListener("pointercancel", up);
    st.classList.remove("feed-dragging");
    if (h <= FEED_CLOSE_BELOW) { setFeedOpen(false); return; }
    feedH = Math.round(h);
    try { localStorage.setItem("office.feedH", String(feedH)); } catch (_) {}
    setFeedOpen(true);
  };
  grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", up); grip.addEventListener("pointercancel", up);
});
addEventListener("resize", applyFeedH);

// ---------- 왼쪽·오른쪽 패널 접기 ----------
function setPanel(side, closed) {
  const app = document.querySelector(".app"), btn = $(side === "left" ? "toggleLeft" : "toggleRight");
  app.classList.toggle(side + "-closed", closed);
  const toLeft = side === "left" ? !closed : closed;   // 화살표는 누르면 패널이 움직일 방향
  btn.innerHTML = `<i class="fa-solid fa-chevron-${toLeft ? "left" : "right"}"></i>`;
  btn.title = (side === "left" ? "빌딩 패널 " : "오른쪽 패널 ") + (closed ? "펼치기" : "접기");
  try { localStorage.setItem("office.panel." + side, closed ? "1" : "0"); } catch (_) {}
  if (side === "left" && !closed && floorKey) placeCar(floorKey);   // 다시 보이면 엘리베이터 칸 위치를 맞춘다
}
for (const side of ["left", "right"]) {
  let closed = false;
  try { closed = localStorage.getItem("office.panel." + side) === "1"; } catch (_) {}
  setPanel(side, closed);
  $(side === "left" ? "toggleLeft" : "toggleRight").onclick = () =>
    setPanel(side, !document.querySelector(".app").classList.contains(side + "-closed"));
}
$("feedFilter").addEventListener("click", e => {
  const b = e.target.closest("[data-f]"); if (!b) return;
  feedFilter = b.dataset.f;
  $("feedFilter").querySelectorAll("[data-f]").forEach(x => x.classList.toggle("on", x === b));
  renderFeed();
});
$("feedSearch").addEventListener("input", e => { feedQuery = e.target.value; renderFeed(); });
$("feedSearch").addEventListener("keydown", e => { if (e.key === "Escape") { e.target.value = ""; feedQuery = ""; renderFeed(); e.target.blur(); } });

// ---------- 타임라인 ----------
// 세션마다 한 줄. 수집기가 보낸 최근 30분의 도구 구간([도구, 시작, 끝, 대상, 실패])을 그 도구의 방 색으로 놓고,
// 사람이 말을 건 시각은 흰 세로선으로. 끝이 없는 구간(지금 쓰는 중)은 빗금
const TL_ROOMS = ["library", "dev", "server", "search", "meeting", "mydesk"];
function durText(sec) {
  if (sec < 10) return sec.toFixed(1) + "초";
  if (sec < 60) return Math.round(sec) + "초";
  const m = Math.floor(sec / 60), r = Math.round(sec % 60);
  return m + "분" + (r ? ` ${r}초` : "");
}
function setFeedView(v) {
  feedView = v;
  $("stage").classList.toggle("tl-view", v === "tl");
  $("feedView").querySelectorAll("[data-v]").forEach(x => x.classList.toggle("on", x.dataset.v === v));
  try { localStorage.setItem("office.feedView", v); } catch (_) {}
  renderFeed();
}
function renderTimeline() {
  if (!feedOpen || feedView !== "tl" || !state || !cfg) return;
  const now = Date.now() / 1000 - skew, from = now - tlWin;
  const fl = floors(), floorN = new Map(fl.map(f => [f.project, f.n]));
  const touched = a => a.timeline && (a.timeline.spans.some(s => (s[2] == null ? now : s[2]) >= from) || a.timeline.prompts.some(p => p >= from));
  const agents = (tlScope === "floor" ? ((fl.find(f => f.project === floorKey) || {}).agents || [])
    : state.agents.filter(a => a.kind !== "idle" || touched(a))).slice()
    .sort((x, y) => (floorN.get(x.project) || 0) - (floorN.get(y.project) || 0) || (x.startedAt || 0) - (y.startedAt || 0));
  const pct = t => ((Math.max(t, from) - from) / tlWin * 100).toFixed(2);
  const lanes = agents.map(a => {
    const tl = a.timeline || { spans: [], prompts: [] };
    const spans = tl.spans.filter(s => (s[2] == null ? now : s[2]) >= from).map(([tool, st, en, tg, err]) => {
      const end = en == null ? now : Math.min(en, now), w = Math.max(0, (end - Math.max(st, from)) / tlWin * 100);
      const room = roomForTool(cfg, tool);
      const tip = `${tool}${tg ? " · " + tg : ""} · ${en == null ? "쓰는 중 " : ""}${durText(Math.max(0, end - st))}${err ? " · 실패" : ""}`;
      return `<i class="sp${en == null ? " open" : ""}${err ? " err" : ""}" style="left:${pct(st)}%;width:${w.toFixed(2)}%;background-color:var(--rc-${room}, var(--rc-dev));color:var(--rc-${room}, var(--rc-dev))" title="${esc(tip)}"></i>`;
    }).join("");
    const pms = tl.prompts.filter(p => p >= from).map(p => `<i class="pm" style="left:${pct(p)}%" title="내가 말을 건 때"></i>`).join("");
    const n = floorN.get(a.project), st = stateOf(a);
    return `<div class="lane${selected === a.id ? " sel" : ""}" data-id="${esc(a.id)}" data-p="${esc(a.project)}">
      <span class="ln"><span class="sd" style="--sc:${STATE_COLOR[st]}" title="${STATE_WORD[st]}"></span>${tlScope === "busy" && n ? `<span class="badge" style="--h:${floorHue(n)}">${n}F</span>` : ""}<b title="${esc(a.title || a.name)}">${esc(a.title || a.name)}</b></span>
      <span class="tr">${spans}${pms}</span></div>`;
  }).join("");
  const ticks = [0, 1, 2, 3, 4, 5].map(i => {
    const left = (i / 5 * 100).toFixed(0), back = Math.round(tlWin * (1 - i / 5) / 60);
    return `<span style="left:${left}%">${back ? `-${back}분` : "지금"}</span>`;
  }).join("");
  setHTML($("timeline"), lanes ? lanes + `<div class="axis"><span></span><span class="tk">${ticks}</span></div>`
    : `<div class="empty">${tlScope === "floor" ? "이 층에 세션이 없습니다." : `최근 ${tlWin / 60}분 동안 일한 세션이 없습니다.`} 도구 기록은 수집기를 새로 깐 뒤부터 쌓입니다.</div>`);
  const leg = TL_ROOMS.map(id => { const r = (cfg.rooms || []).find(x => x.id === id); return r ? `<span><i style="background:var(--rc-${id})"></i>${esc(r.name)}</span>` : ""; }).join("") +
    `<span><i class="pmk"></i>내가 말함</span><span><i style="outline:2px solid #ef4444;outline-offset:-1px;background:transparent"></i>실패</span>`;
  setHTML($("tlLegend"), leg);
}
$("feedView").addEventListener("click", e => { const b = e.target.closest("[data-v]"); if (b) setFeedView(b.dataset.v); });
$("tlScope").addEventListener("click", e => {
  const b = e.target.closest("[data-s]"); if (!b) return;
  tlScope = b.dataset.s;
  $("tlScope").querySelectorAll("[data-s]").forEach(x => x.classList.toggle("on", x === b));
  try { localStorage.setItem("office.tlScope", tlScope); } catch (_) {}
  renderFeed();
});
$("tlScope").querySelectorAll("[data-s]").forEach(x => x.classList.toggle("on", x.dataset.s === tlScope));
$("tlWin").value = String(tlWin);
$("tlWin").onchange = e => { tlWin = +e.target.value; try { localStorage.setItem("office.tlWin", String(tlWin)); } catch (_) {} renderFeed(); };
$("timeline").addEventListener("click", e => { const l = e.target.closest(".lane"); if (l) jumpTo(l.dataset.id, l.dataset.p); });
$("feedList").addEventListener("click", e => {
  const li = e.target.closest("li[data-id]"); if (!li) return;
  if (!state.agents.some(a => a.id === li.dataset.id)) return;   // 끝난 세션은 갈 곳이 없다
  if (li.dataset.p !== floorKey) gotoFloor(li.dataset.p);
  if (selected !== li.dataset.id) select(li.dataset.id);
});
setFeedOpen(feedOpen);
setFeedView(feedView);

// ---------- 나를 기다리는 세션(모든 층) ----------
// 층을 돌아다니는 동안 다른 층에서 승인을 기다리거나 일을 끝낸 세션을 놓치지 않게, 화면 위 가운데에 칩으로 모은다.
// 승인 대기·막힘은 지금 상태 그대로, '완료'는 이 화면이 지켜보는 동안 일을 마쳤고 아직 열어 보지 않은 세션.
const doneAt = new Map();   // 세션 id -> 일을 마친 시각(열어 보거나 다시 일을 시작하면 지운다)
const ATTN = {
  approval: { icon: "hand", word: "승인 대기", short: "승인" },
  stalled: { icon: "hourglass-end", word: "막힘", short: "막힘" },
  done: { icon: "circle-check", word: "작업 완료", short: "완료" },
};
const ATTN_ORDER = ["approval", "stalled", "done"];
let attnOpen = "";
function attention() {
  if (!state) return [];
  const out = [];
  for (const a of state.agents) {
    if (a.kind === "approval") out.push({ a, type: "approval", ts: a.since });
    else if (a.stalled) out.push({ a, type: "stalled", ts: a.lastActivity });
    else if (a.kind === "idle" && doneAt.has(a.id)) out.push({ a, type: "done", ts: doneAt.get(a.id) });
  }
  return out.sort((x, y) => ATTN_ORDER.indexOf(x.type) - ATTN_ORDER.indexOf(y.type) || (y.ts || 0) - (x.ts || 0));
}
function renderAttention() {
  if (!state) return;
  const now = Date.now() / 1000 - skew, list = attention();
  const by = t => list.filter(x => x.type === t);
  setHTML($("attn"), ATTN_ORDER.filter(t => by(t).length).map(t =>
    `<button class="ac ac-${t}${attnOpen === t ? " on" : ""}" data-t="${t}" title="${ATTN[t].word} — 눌러서 목록"><i class="fa-solid fa-${ATTN[t].icon}"></i>${ATTN[t].short} <b>${by(t).length}</b></button>`).join(""));
  if (attnOpen && !by(attnOpen).length) attnOpen = "";
  const floorN = new Map(floors().map(f => [f.project, f.n]));
  const items = attnOpen ? by(attnOpen) : [];
  setHTML($("attnList"), items.length ? items.map(x => {
    const n = floorN.get(x.a.project);
    const what = x.type === "approval" ? `${x.a.tool ? esc(x.a.tool) + " · " : ""}${agoSpan(x.ts || null, "째")}`
      : x.type === "stalled" ? `조용한 지 ${agoSpan(x.a.lastActivity)}` : `${agoSpan(x.ts, " 전")}${x.a.say ? ` · ${esc(x.a.say)}` : ""}`;
    return `<li data-id="${esc(x.a.id)}" data-p="${esc(x.a.project)}">${n ? `<span class="badge" style="--h:${floorHue(n)}">${n}F</span>` : ""}
      <span class="w"><b>${esc(x.a.title || x.a.name)}</b><small>${what}</small></span></li>`;
  }).join("") + (attnOpen === "done" ? `<li class="all" data-all="1"><i class="fa-solid fa-check-double"></i> 모두 확인</li>` : "") : "");
  $("attnList").hidden = !items.length;
  tickTimes($("attn"), now); tickTimes($("attnList"), now);
  // 브라우저 탭 제목에도 '나를 기다리는 수'(승인 + 확인 안 한 완료)
  const n = by("approval").length + by("done").length;
  const t = (n ? `(${n}) ` : "") + "Claude 사무실";
  if (document.title !== t) document.title = t;
}
function jumpTo(id, project) {
  if (!state.agents.some(a => a.id === id)) return;
  if (transit) { endRide(); transit = null; me.actor.path = []; me.actor.pos = me.pos.slice(); mePill(""); $("ride").classList.remove("on"); }
  if (playing) rotateAt = Date.now();
  if (project !== floorKey) gotoFloor(project);
  if (selected !== id) select(id); else if (doneAt.delete(id)) renderAttention();
}
$("attn").addEventListener("click", e => {
  const b = e.target.closest("[data-t]"); if (!b) return;
  attnOpen = attnOpen === b.dataset.t ? "" : b.dataset.t;
  renderAttention();
});
$("attnList").addEventListener("click", e => {
  const li = e.target.closest("li"); if (!li) return;
  if (li.dataset.all) { doneAt.clear(); attnOpen = ""; renderAttention(); return; }
  attnOpen = ""; jumpTo(li.dataset.id, li.dataset.p); renderAttention();
});
document.addEventListener("pointerdown", e => {
  if (attnOpen && !e.target.closest("#attn, #attnList")) { attnOpen = ""; renderAttention(); }
});

// ---------- 소리·데스크톱 알림 ----------
// 끔 → 승인만 → 승인·완료 순서로 바꾼다. 소리는 이 브라우저에서 한 번이라도 누른 뒤에야 난다(자동 재생 규칙).
// 데스크톱 알림 창은 https 나 localhost 로 열었을 때만 쓸 수 있다(그 밖에는 소리와 탭 제목만).
const ALERT_MODES = ["off", "approval", "all"];
const ALERT_LABEL = { off: "알림 끔", approval: "승인만", all: "승인·완료" };
const ALERT_ICON = { off: "bell-slash", approval: "bell", all: "bell" };
let alertMode = "off", audio = null, lastBeep = 0;
try { alertMode = ALERT_MODES.includes(localStorage.getItem("office.alert")) ? localStorage.getItem("office.alert") : "off"; } catch (_) {}
const canNotify = () => "Notification" in window && window.isSecureContext;
function renderAlertBtn() {
  const b = $("alertBtn");
  b.innerHTML = `<i class="fa-solid fa-${ALERT_ICON[alertMode]}"></i> ${ALERT_LABEL[alertMode]}`;
  b.classList.toggle("on", alertMode !== "off");
  b.title = `소리·알림: ${ALERT_LABEL[alertMode]} (누르면 바뀜, 단축키 M)` +
    (canNotify() ? (Notification.permission === "denied" ? "\n데스크톱 알림이 브라우저에서 막혀 있어 소리만 냅니다." : "")
      : "\n데스크톱 알림 창은 https·localhost 에서만 됩니다. 여기서는 소리와 탭 제목 숫자로 알립니다.");
}
function unlockAudio() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === "suspended") audio.resume();
  } catch (_) {}
}
function beep(kind) {
  if (!audio || audio.state !== "running" || performance.now() - lastBeep < 1500) return;
  lastBeep = performance.now();
  const notes = kind === "approval" ? [880, 660, 880] : [523, 784];   // 승인 = 세 번 두드림, 완료 = 올라가는 두 음
  let t = audio.currentTime;
  for (const f of notes) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = "sine"; o.frequency.value = f;
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(0.16, t + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
    o.connect(g); g.connect(audio.destination);
    o.start(t); o.stop(t + 0.22); t += 0.17;
  }
}
function notify(ev) {
  if (!canNotify() || Notification.permission !== "granted" || (!document.hidden && document.hasFocus())) return;
  const a = ev.a, n = (floors().find(f => f.project === a.project) || {}).n;
  try {
    const note = new Notification(ev.type === "approval" ? `승인 대기 · ${a.title || a.name}` : `작업 완료 · ${a.title || a.name}`, {
      body: `${n ? n + "F " : ""}${a.project}${ev.type === "approval" && a.tool ? " · " + a.tool : a.say ? " · " + a.say : ""}`,
      tag: "office-" + a.id, silent: true,
    });
    note.onclick = () => { window.focus(); jumpTo(a.id, a.project); note.close(); };
  } catch (_) {}
}
function alertFor(events) {
  if (alertMode === "off" || !events.length) return;
  const mine = events.filter(e => e.type === "approval" || alertMode === "all");
  if (!mine.length) return;
  beep(mine.some(e => e.type === "approval") ? "approval" : "done");
  mine.slice(0, 3).forEach(notify);
}
function setAlertMode(m) {
  alertMode = m;
  try { localStorage.setItem("office.alert", m); } catch (_) {}
  renderAlertBtn();
  if (m !== "off") {
    unlockAudio(); beep(m === "approval" ? "approval" : "done");   // 고른 소리를 한 번 들려준다
    if (canNotify() && Notification.permission === "default") Notification.requestPermission().then(renderAlertBtn).catch(() => {});
  }
}
$("alertBtn").onclick = () => setAlertMode(ALERT_MODES[(ALERT_MODES.indexOf(alertMode) + 1) % ALERT_MODES.length]);
document.addEventListener("pointerdown", () => { if (alertMode !== "off") unlockAudio(); }, { capture: true, passive: true });
renderAlertBtn();

// ---------- 단축키 ----------
// 글을 쓰는 칸에서는 동작하지 않는다. ? 로 목록
const KEYS = [
  ["↑ ↓", "위층·아래층"], ["1 – 9", "그 층으로"], ["Space", "층 순회 재생·정지"], ["A", "나를 기다리는 다음 세션으로"],
  ["F", "최근 소식 펼치기·접기"], ["T", "타임라인 보기"], ["/", "소식 검색"], ["[  ]", "왼쪽·오른쪽 패널 접기"], ["M", "소리·알림 바꾸기"], ["Esc", "선택 풀기·창 닫기"], ["?", "이 목록"],
];
function renderKeys() {
  setHTML($("keysList"), KEYS.map(([k, d]) => `<li><kbd>${k}</kbd><span>${d}</span></li>`).join(""));
}
function toggleKeys(on) { $("keys").hidden = !(on ?? $("keys").hidden); }
function stepFloor(d) {
  const fl = floors(), cur = (fl.find(f => f.project === floorKey) || {}).n || 0;
  const next = fl.find(f => f.n === cur + d);
  if (next) jumpFloor(next.project);
}
function jumpFloor(project) {
  if (transit) { endRide(); transit = null; me.actor.path = []; me.actor.pos = me.pos.slice(); mePill(""); $("ride").classList.remove("on"); }
  if (playing) rotateAt = Date.now();
  gotoFloor(project);
}
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey || e.isComposing) return;
  const t = e.target;
  if (t instanceof Element && t.closest("input, textarea, select, [contenteditable]")) return;
  if (!state) return;
  const k = e.key;
  if (k === "?") { toggleKeys(); }
  else if (k === "Escape") { if (!$("keys").hidden) toggleKeys(false); else if (attnOpen) { attnOpen = ""; renderAttention(); } else if (selected) select(selected); }
  else if (k === "ArrowUp") stepFloor(1);
  else if (k === "ArrowDown") stepFloor(-1);
  else if (/^[1-9]$/.test(k)) { const f = floors().find(x => x.n === +k); if (f) jumpFloor(f.project); }
  else if (k === " ") { if (t instanceof Element && t.closest("button")) return; setPlaying(!playing); }
  else if (k === "a" || k === "A") {
    const list = attention(); if (!list.length) return;
    const i = list.findIndex(x => x.a.id === selected);
    const x = list[(i + 1) % list.length]; jumpTo(x.a.id, x.a.project);
  }
  else if (k === "f" || k === "F") setFeedOpen(!feedOpen);
  else if (k === "t" || k === "T") { if (!feedOpen) setFeedOpen(true); setFeedView(feedView === "tl" ? "news" : "tl"); }
  else if (k === "/") { if (!feedOpen) setFeedOpen(true); setFeedView("news"); $("feedSearch").focus(); }
  else if (k === "[") setPanel("left", !document.querySelector(".app").classList.contains("left-closed"));
  else if (k === "]") setPanel("right", !document.querySelector(".app").classList.contains("right-closed"));
  else if (k === "m" || k === "M") $("alertBtn").click();
  else return;
  e.preventDefault();
});
$("keys").addEventListener("click", e => { if (e.target === $("keys") || e.target.closest(".x")) toggleKeys(false); });
$("keysBtn").onclick = () => toggleKeys();
renderKeys();

// ---------- 매 프레임 ----------
// 움직이는 것(걷는 사람, 엘리베이터 연출·문, 카메라 이동·확대, 서랍 끌기, 화면 내용 변경)이 있으면 매 프레임,
// 없으면 초당 8번만 그린다(LED 깜빡임·지구본·고민 중 고개 정도). 탭이 숨겨지면 브라우저가 프레임을 멈춘다
const tmp = new THREE.Vector3();
const IDLE_FRAME_MS = 125;
let lastT = performance.now();
function busyScene(t) {
  if (transit || t < wakeUntil) return true;
  for (const ac of actors.values()) if (ac.path.length || ac.fade !== undefined) return true;
  if (me.actor && me.actor.path.length) return true;
  const open = t < doorOpenUntil;
  return doors.some(d => Math.abs(d.base + (open ? d.dir * 1.6 : 0) - d.m.position.x) > 0.003);
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) { lastT = performance.now(); kick(); } });
function frame(t) {
  if (!busyScene(t) && t - lastT < IDLE_FRAME_MS) { requestAnimationFrame(frame); return; }
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
    ac.group.position.set(ac.pos[0], (moving ? Math.abs(Math.sin(t / 90)) * 0.14 : 0) + (ac.rideY || 0), ac.pos[1]);
    if (ac.head) ac.head.material.rotation = ac.item && ac.item.st === "stalled" ? Math.sin(t / 500) * 0.28 : 0;
    const lift = (ac.group.parent === officeRoot ? officeRoot.position.y : 0) + (ac.rideY || 0);
    tmp.set(ac.pos[0], (ac.head && ac.head.center.y === 0 ? 2.2 : 2.05) * ac.scale + lift, ac.pos[1]).project(camera);
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
// 웹폰트가 늦게 오면 간판을 다시 그린다(캔버스는 폰트가 준비된 뒤에만 아이콘 글리프를 그린다)
document.fonts.load(`900 50px ${FA_FONT}`).then(() => { updateSigns.sig = null; if (cfg) updateSigns(); }).catch(() => {});
buildOffice();
new ResizeObserver(resize).observe(stage);
resize();
requestAnimationFrame(frame);
// 5초마다 시간에 따라 바뀌는 글자('n초 전', 오래 걸림 표시, 최근 1시간 수)를 맞춘다. 내용이 같으면 DOM 은 그대로
setInterval(() => {
  if (!state || document.hidden) return;
  renderLabels(); const fl = floors(); renderFloors(fl); const f = fl.find(x => x.project === floorKey);
  renderPeople(f, assignCharacters(cfg, state.agents)); renderLog(f); renderFeed(); renderAttention();
}, 5000);

// ---------- 허브 연결 ----------
// 짧은 끊김은 EventSource 의 기본 재연결에 맡긴다. 그동안 화면 위에 '연결 끊김 · n초 전 데이터'를 띄우고,
// 다시 받은 상태를 반영하면 지운다. 오래 못 붙거나(브라우저가 포기했거나 계속 실패) 허브가 오래 조용한데
// /health 도 답이 없으면 EventSource 를 닫고 지수 백오프(1→2→4…30초)로 직접 다시 연다.
// 활동 로그·최근 소식은 처음 한 번만 채우고(seeded), 다시 붙은 뒤에는 바뀐 것만 더한다. 허브가 막 다시 떠서
// 수집기 보고가 아직 없는 빈 상태는 잠깐 미뤄, 세션이 다 끝났다가 다시 생긴 것처럼 소식이 쌓이지 않게 한다.
const PROBE_AFTER_MS = 25000, GIVEUP_MS = 12000, RESYNC_MS = 8000, BACKOFF_MAX = 30000;
let seeded = false, es = null, aliveAt = Date.now(), lostAt = 0, retryMs = 1000, retryTimer = 0;
let connectingSince = 0, resyncUntil = 0, knownHosts = [], held = null, probing = false, hiddenDirty = false;
function setLive(on) {
  const el = $("live"), cls = on ? "live on" : "live off";
  if (el.className !== cls) el.className = cls;
  setText($("liveText"), on ? "LIVE" : "다시 연결 중");
}
function showStale() {
  const el = $("stale");
  if (!lostAt) { el.classList.remove("on"); return; }
  setText($("staleText"), `연결 끊김 · ${ago(Math.max(0, (Date.now() - aliveAt) / 1000))} 전 데이터`);
  el.classList.add("on");
}
function markLost() {
  if (!lostAt) lostAt = Date.now();
  setLive(false); showStale();
}
function scheduleReconnect() {
  if (es) { es.close(); es = null; }
  clearTimeout(retryTimer);
  const wait = retryMs * (0.8 + Math.random() * 0.4);
  retryMs = Math.min(BACKOFF_MAX, retryMs * 2);
  markLost();
  retryTimer = setTimeout(connect, wait);
}
const agentKey = a => a.host + "/" + a.id;
function applyPatch(base, p) {
  const s = { ...base, version: p.version, now: p.now, hosts: p.hosts };
  for (const k of ["config", "messaging", "messages"]) if (k in p) s[k] = p[k];
  const by = new Map(base.agents.map(a => [agentKey(a), a]));
  for (const k of p.del || []) by.delete(k);
  const fresh = [];
  for (const a of p.set || []) { const k = agentKey(a); if (!by.has(k)) fresh.push(k); by.set(k, a); }
  const order = p.order || base.agents.map(agentKey).filter(k => by.has(k)).concat(fresh);
  s.agents = order.map(k => by.get(k)).filter(Boolean);
  return s;
}
function connect() {
  clearTimeout(retryTimer);
  if (es) es.close();
  const src = es = new EventSource("/api/stream");
  let first = true;   // 이 연결의 첫 상태: 새로 보이는 사람은 걸어 들어오지 않고 제자리에 둔다
  connectingSince = Date.now();
  src.onopen = () => {
    if (es !== src) return;
    connectingSince = 0; retryMs = 1000; setLive(true);
    if (seeded && lostAt) resyncUntil = Date.now() + RESYNC_MS;
  };
  src.onmessage = e => {
    if (es !== src) return;
    if (onState(JSON.parse(e.data), first)) first = false;
  };
  // 첫 소식 뒤로는 바뀐 것만 온다(event: patch). 지금 상태(붙잡아 둔 상태가 있으면 그것)에 덧대어 같은 길로 넘긴다
  src.addEventListener("patch", e => {
    if (es !== src) return;
    const base = held ? held.s : state;
    if (!base) { scheduleReconnect(); return; }   // 덧댈 상태가 없으면 새로 붙어 전체를 받는다
    if (onState(applyPatch(base, JSON.parse(e.data)), first)) first = false;
  });
  src.onerror = () => {
    if (es !== src) return;
    if (!lostAt && !connectingSince) aliveAt = Date.now();   // 열려 있다 방금 끊김: 그때까지 받은 상태는 최신이었다
    markLost();
    if (!connectingSince) connectingSince = Date.now();
    // 브라우저가 포기했거나(허브가 오류 응답) 한동안 계속 실패하면 직접 백오프로
    if (src.readyState === EventSource.CLOSED || Date.now() - lostAt > GIVEUP_MS) scheduleReconnect();
  };
}
function onState(s, first, force) {
  // 다시 붙은 직후, 전에 보던 컴퓨터가 아직 다 보고하지 않았으면(허브 재시작 직후) 잠깐 기다린다
  if (!force && seeded && Date.now() < resyncUntil &&
      !knownHosts.every(h => s.hosts.some(x => x.host === h && x.online))) { held = { s, first }; return false; }
  held = null; resyncUntil = 0;
  state = s;
  skew = Date.now() / 1000 - state.now;
  cfg = state.config;
  knownHosts = state.hosts.filter(h => h.online).map(h => h.host);
  trackLogs(!seeded); trackFeed(!seeded); seeded = true;
  if (document.hidden) hiddenDirty = true;   // 숨겨진 동안은 상태만 받아 두고, 다시 보일 때 한 번에 그린다
  else apply(first);
  aliveAt = Date.now(); lostAt = 0; retryMs = 1000; setLive(true); showStale();
  return true;
}
// 1초마다: 끊김 표시의 초를 올리고, 막힌 연결을 정리하고, 오래 조용하면 허브가 살아 있는지 묻는다
setInterval(() => {
  const now = Date.now();
  if (held && now >= resyncUntil) onState(held.s, held.first, true);
  if (lostAt && !document.hidden) showStale();
  if (es && connectingSince && lostAt && now - connectingSince > GIVEUP_MS) { scheduleReconnect(); return; }
  if (es && es.readyState === EventSource.OPEN && !lostAt && now - aliveAt > PROBE_AFTER_MS && !probing && !document.hidden) {
    probing = true;
    const ac = new AbortController(), to = setTimeout(() => ac.abort(), 5000);
    fetch("/health", { cache: "no-store", signal: ac.signal })
      .then(r => { if (!r.ok) throw new Error(r.status); aliveAt = Date.now(); })
      .catch(() => scheduleReconnect())
      .finally(() => { clearTimeout(to); probing = false; });
  }
}, 1000);
document.addEventListener("visibilitychange", () => {
  if (document.hidden || !state) return;
  if (hiddenDirty) { hiddenDirty = false; apply(true); }
  renderFeed();
});
addEventListener("online", () => { if (lostAt) { retryMs = 1000; connect(); } });
connect();
