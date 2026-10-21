// 사무실 화면과 관리 화면이 함께 쓰는 규칙: 도구 → 방, 세션 → 캐릭터, 캐릭터 → 모습.
(function (g) {
  "use strict";

  function globMatch(pattern, s) {
    pattern = String(pattern).trim(); s = String(s || "");
    if (pattern.endsWith("*")) return s.toLowerCase().startsWith(pattern.slice(0, -1).toLowerCase());
    return s.toLowerCase() === pattern.toLowerCase();
  }

  function roomForTool(cfg, tool) {
    if (!tool) return cfg.defaultRoom || "dev";
    for (const r of cfg.toolRooms || []) if (globMatch(r.pattern, tool)) return r.room;
    return cfg.defaultRoom || "dev";
  }

  function hash(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  // 화면에 있는 세션·서브에이전트 전부에 캐릭터를 정한다. 규칙이 먼저, 그다음 자동 배정.
  // 자동 배정은 같은 층(프로젝트) 안에서 겹치지 않게 고른다 — 한 층에 같은 캐릭터가 둘 서 있지 않도록.
  // 반환: Map(key → character). key 는 세션 id 또는 "<세션 id>/<서브에이전트 id>".
  function assignCharacters(cfg, agents) {
    const byId = new Map((cfg.characters || []).map(c => [c.id, c]));
    const pool = (cfg.characters || []).filter(c => c.inPool);
    const out = new Map();
    const takenBy = new Map();  // project -> Set(character id)
    const taken = p => { if (!takenBy.has(p)) takenBy.set(p, new Set()); return takenBy.get(p); };
    const rule = (kind, value) => {
      for (const a of cfg.assignments || []) {
        if (a.match === kind && globMatch(a.value, value) && byId.has(a.character)) return byId.get(a.character);
      }
      return null;
    };
    const auto = [];
    const sorted = [...agents].sort((a, b) => (a.startedAt || 0) - (b.startedAt || 0));
    for (const a of sorted) {
      const c = rule("session", a.name) || rule("project", a.project) || rule("host", a.host);
      if (c) { out.set(a.id, c); taken(a.project).add(c.id); } else auto.push(a);
    }
    for (const a of auto) {
      if (!pool.length) { out.set(a.id, cfg.characters[0]); continue; }
      const t = taken(a.project);
      let i = hash(a.id) % pool.length, tries = 0;
      while (t.has(pool[i].id) && tries < pool.length) { i = (i + 1) % pool.length; tries++; }
      out.set(a.id, pool[i]); t.add(pool[i].id);
    }
    for (const a of sorted) {
      for (const s of a.subagents || []) {
        const c = rule("agentType", s.type) || byId.get(cfg.subagentCharacter) ||
          (pool.length ? pool[hash(s.id) % pool.length] : cfg.characters[0]);
        out.set(a.id + "/" + s.id, c);
      }
    }
    return out;
  }

  // 상태(working·thinking·stalled·idle)에 맞는 모습. 상태별 모습이 비어 있으면 기본 모습.
  function lookFor(ch, state) {
    const s = (ch.states || {})[state];
    if (s && (s.image || s.emoji)) return { image: s.image || "", emoji: s.emoji || "" };
    return { image: ch.image || "", emoji: ch.emoji || "" };
  }

  function avatarHTML(ch, state) {
    const l = lookFor(ch, state);
    if (l.image) return `<img class="av-img" src="/assets/${encodeURIComponent(l.image)}" alt="" draggable="false">`;
    return `<span class="av-emo">${esc(l.emoji || "🙂")}</span>`;
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function ago(sec) {
    if (sec == null || !isFinite(sec) || sec < 0) return "";
    if (sec < 60) return `${Math.floor(sec)}초`;
    if (sec < 3600) return `${Math.floor(sec / 60)}분`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}시간`;
    return `${Math.floor(sec / 86400)}일`;
  }

  g.Office = { globMatch, roomForTool, assignCharacters, lookFor, avatarHTML, esc, ago };
})(window);
