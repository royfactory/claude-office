// 시연 모드(GitHub Pages 용): 허브 없이 가짜 사무실을 돌린다. scripts/build_demo.py 가 만든 site/ 에서만 읽힌다.
// 화면 코드는 그대로 두고 허브와 닿는 곳(EventSource /api/stream, fetch /api/...)만 가로챈다. 실제 세션은 쓰지 않는다.
(function (g) {
  "use strict";
  g.OFFICE_DEMO = true;
  const CONFIG_KEY = "office.demo.config";
  const now = () => Date.now() / 1000;
  const T0 = now();

  // 허브 기본 설정(build_demo.py 가 app.default_config() 로 뽑아 둔 것). 관리 화면에서 바꾸면 이 브라우저에만 남는다
  let config = null;
  try { config = JSON.parse(localStorage.getItem(CONFIG_KEY) || "null"); } catch (e) { /* 저장소를 못 쓰면 기본값 */ }
  if (!config) {
    const x = new XMLHttpRequest();
    x.open("GET", "static/demo-config.json", false);   // 화면 코드보다 먼저 있어야 해서 동기로 읽는다(작은 파일 하나)
    x.send();
    config = JSON.parse(x.responseText);
  }
  const saveConfig = c => { config = c; try { localStorage.setItem(CONFIG_KEY, JSON.stringify(c)); } catch (e) { /* 그대로 */ } };

  // ---------- 가짜 사무실 ----------
  const base = (id, project, title, extra) => Object.assign({
    id, name: project, project, title, kind: "idle", tool: "", target: "", since: now() - 30, lastActivity: now(),
    startedAt: T0 - 3600 - id.length * 400, tools: 40 + id.length * 7, say: "", model: "claude-opus-5-5",
    ctx: { used: 60000 + id.length * 15000, max: 200000 }, todos: [], recent: [], subagents: [], lines: [120, 30], outTokens: 52000,
  }, extra || {});
  const quiet = (id, project, title, min) => base(id, project, title, { lastActivity: now() - min * 60, since: now() - min * 60 });
  const web = {
    a: base("w1", "web-app", "Checkout page redesign", { kind: "working", tool: "Edit", target: "src/Checkout.tsx",
      say: "Splitting the cart summary into its own component.",
      todos: [{ s: "Extract CartSummary", st: "completed" }, { s: "Wire up promo codes", st: "in_progress" }, { s: "Update tests", st: "pending" }],
      git: { dirty: 3, ahead: 1, behind: 0 }, branch: "feat/checkout", limits: { five_hour: { pct: 38, resets: T0 + 3 * 3600 }, seven_day: { pct: 21, resets: T0 + 4 * 86400 }, ts: T0 } }),
    b: base("w2", "web-app", "Fix flaky e2e tests", { kind: "working", tool: "Read", target: "tests/e2e/cart.spec.ts", say: "Reading the failing spec first.", git: { dirty: 3, ahead: 1, behind: 0 } }),
    c: base("w3", "web-app", "Dependency upgrades", { kind: "working", tool: "Bash", target: "npm run build", say: "Running the build after the upgrade.", git: { dirty: 3, ahead: 1, behind: 0 } }),
    d: base("w4", "web-app", "Docs for new API", { kind: "idle", say: "Done — the API reference is updated.", lastActivity: now() - 40, git: { dirty: 3, ahead: 1, behind: 0 } }),
  };
  const others = [
    base("a1", "api-server", "Rate limiter", { kind: "working", tool: "Edit", target: "limiter.go", git: { dirty: 1, ahead: 0, behind: 0 } }),
    base("a2", "api-server", "DB migration", { kind: "thinking", git: { dirty: 1, ahead: 0, behind: 0 } }),
    base("m1", "mobile-app", "Push notifications", { kind: "working", tool: "WebSearch", target: "APNs token refresh" }),
    quiet("m2", "mobile-app", "Dark mode polish", 20),
    base("d1", "docs-site", "Landing copy", { kind: "working", tool: "Write", target: "index.md", git: { dirty: 0, ahead: 2, behind: 0 } }),
    quiet("l1", "ml-pipeline", "Feature store", 30),
    quiet("o1", "old-prototype", "Spike: websockets", 300),
    quiet("o2", "design-system", "Button tokens", 180),
  ];
  const sub = (id, type, description, tool, target) => ({ id, type, description, tool, target, since: now(), tools: 3, say: "" });
  // 이 시간표를 되풀이한다(초): 방을 옮기고, 서브에이전트가 엘리베이터로 오고, 승인을 기다리고, 일을 마치고 쉰다
  const START = JSON.parse(JSON.stringify(web));
  const SCRIPT = [
    [4, () => { web.b = { ...web.b, tool: "Grep", target: "waitFor(", say: "Found three timing-based waits." }; }],
    [7, () => { web.a = { ...web.a, subagents: [sub("s1", "Explore", "Find promo code usages", "Grep", "promo")] }; }],
    [11, () => { web.c = { ...web.c, tool: "WebFetch", target: "changelog", say: "Checking the breaking changes list." }; }],
    [15, () => { web.b = { ...web.b, tool: "Edit", target: "tests/e2e/cart.spec.ts", say: "Replacing sleeps with explicit waits." }; }],
    [19, () => { web.c = { ...web.c, kind: "approval", tool: "Bash", target: "rm -rf node_modules", since: now(), say: "" }; }],
    [24, () => { web.a = { ...web.a, tool: "Bash", target: "npm test", say: "All 128 tests pass.", subagents: [] }; }],
    [29, () => { web.b = { ...web.b, kind: "idle", tool: "", target: "", say: "Fixed — the spec is stable across 20 runs.", lastActivity: now(), since: now() }; }],
    [34, () => { web.c = { ...web.c, kind: "working", tool: "Bash", target: "npm install", since: now(), say: "Reinstalling dependencies." }; }],
    [40, () => { web.d = { ...web.d, kind: "working", tool: "Read", target: "docs/api.md", since: now(), say: "Adding the new endpoints." }; }],
    [46, () => { web.a = { ...web.a, tool: "Edit", target: "src/Promo.tsx", say: "Promo codes now validate on blur." }; }],
    [52, () => { Object.assign(web, JSON.parse(JSON.stringify(START))); }],
  ];
  const LOOP = 56;
  let step = 0, loopAt = now(), version = 1;
  function tick() {
    const el = now() - loopAt;
    while (step < SCRIPT.length && SCRIPT[step][0] <= el) { SCRIPT[step][1](); step++; }
    if (el >= LOOP) { step = 0; loopAt = now(); }
    version++;
  }
  function snapshot() {
    const t = now(), wave = x => Math.round(50 + 30 * Math.sin(t / x));
    const agents = [...Object.values(web), ...others].map(a => ({
      ...a, host: "macbook", lastActivity: a.kind === "idle" ? a.lastActivity : t, tools: a.tools + Math.floor((t - T0) / 9),
    }));
    return {
      version, now: t, config,
      hosts: [{ host: "macbook", age: 0.4, online: true, count: agents.length, checklistRule: true,
        setup: { roots: 1, hooks: 1, approveHook: 0, statusline: 1, todoTools: 1, os: "mac", messagesEnv: false, approveEnv: false, gitDenied: 0 },
        sys: { cpu: wave(7), gpu: wave(11) - 20, mem: 62 + Math.round(4 * Math.sin(t / 30)), disk: 58, memTotal: 34359738368, diskTotal: 994662584320, ts: Math.round(t) } }],
      agents, messaging: { ready: false, auth: false }, messages: [], approvals: [], approvalsReady: false,
    };
  }

  // 요약(/api/stats): 지난 7일 하루씩, 그럴듯한 고정 값
  function stats() {
    const days = [], projs = ["web-app", "api-server", "mobile-app", "docs-site", "ml-pipeline"];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86400000), key = d.toISOString().slice(0, 10), weekend = d.getDay() === 0 || d.getDay() === 6;
      const projects = {};
      projs.forEach((p, k) => {
        const seed = (i * 7 + k * 13) % 11, scale = weekend ? 0.3 : 1;
        if (seed < 2 && k > 2) return;
        projects[p] = { active: Math.round((4200 - k * 700 + seed * 260) * scale), tools: Math.round((310 - k * 45 + seed * 20) * scale),
          add: Math.round((900 - k * 150 + seed * 60) * scale), del: Math.round((260 - k * 40 + seed * 15) * scale),
          out: Math.round((180000 - k * 30000 + seed * 9000) * scale), sessions: Math.max(1, 4 - k + (seed % 3)) };
      });
      days.push({ date: key, projects });
    }
    return { today: days[days.length - 1].date, days };
  }

  // ---------- 허브 대신 ----------
  const RealES = g.EventSource, realFetch = g.fetch.bind(g);
  class DemoEventSource {
    constructor(url) {
      this.url = url; this.readyState = 0; this.listeners = {};
      if (!String(url).includes("api/stream")) return new RealES(url);
      setTimeout(() => { this.readyState = 1; this.onopen && this.onopen({}); this.push(); }, 50);
      this.timer = setInterval(() => { tick(); this.push(); }, 1000);
    }
    push() { this.onmessage && this.onmessage({ data: JSON.stringify(snapshot()) }); }
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
    removeEventListener() {}
    close() { clearInterval(this.timer); this.readyState = 2; }
  }
  DemoEventSource.CONNECTING = 0; DemoEventSource.OPEN = 1; DemoEventSource.CLOSED = 2;
  g.EventSource = DemoEventSource;

  const json = (body, status) => Promise.resolve(new Response(JSON.stringify(body), { status: status || 200, headers: { "Content-Type": "application/json" } }));
  g.fetch = function (input, init) {
    const url = String(input && input.url || input), method = ((init && init.method) || "GET").toUpperCase();
    const m = url.match(/api\/([a-z/]+)/);
    if (!m) return realFetch(input, init);
    const path = m[1];
    if (path === "config" && method === "PUT") { saveConfig(JSON.parse(init.body)); return json(config); }
    if (path === "config/reset") { try { localStorage.removeItem(CONFIG_KEY); } catch (e) { /* 그대로 */ } return realFetch("static/demo-config.json").then(r => r.json()).then(c => { config = c; return json(c); }); }
    if (path === "config") return json(config);
    if (path === "state") return json(snapshot());
    if (path === "stats") return json(stats());
    if (path === "assets" && method === "GET") return json([]);
    if (path === "assets") return json({ detail: "시연에서는 이미지를 올릴 수 없습니다" }, 400);
    return json({ detail: "시연에서는 되지 않습니다" }, 400);
  };

  // 화면 위 띠: 가짜 데이터라는 것과 받는 곳
  g.addEventListener("DOMContentLoaded", () => {
    const ko = g.I18N ? g.I18N.lang === "ko" : (navigator.language || "").startsWith("ko");
    const a = document.createElement("a");
    a.href = "https://github.com/royfactory/claude-office";
    a.target = "_blank"; a.rel = "noopener";
    a.textContent = ko ? "시연 · 가짜 데이터입니다 — GitHub 에서 받기 →" : "Demo with sample data — get it on GitHub →";
    a.style.cssText = "position:fixed;left:50%;bottom:10px;transform:translateX(-50%);z-index:99;padding:6px 14px;border-radius:999px;" +
      "background:#d97757;color:#fff;font:600 12px/1.4 system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.35)";
    document.body.appendChild(a);
  });
})(window);
