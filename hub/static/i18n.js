// 화면 언어. 한국어 문장을 그대로 키로 쓰고(gettext 방식), 영어일 때만 사전(I18N.add 로 모은 EN)에서 바꾼다.
// 사전에 없는 문장은 한국어 그대로 나온다. 정적 HTML 은 apply() 가 글자 마디·title·placeholder 를 바꾼다.
// 언어 설정(cfg.language): auto(기본, 브라우저 언어가 한국어면 한국어·아니면 영어) · ko · en.
// 허브 설정은 화면을 그린 뒤에 오므로, 마지막으로 정한 언어를 이 브라우저에 기억해 두고 처음부터 그 언어로 그린다.
// 설정이 그 기억과 다르면 기억을 바꾸고 한 번 새로 고친다.
(function (g) {
  "use strict";
  const KEY = "office.lang";
  const EN = {};
  const browserLang = () => {
    const l = ((navigator.languages && navigator.languages[0]) || navigator.language || "en").toLowerCase();
    return l.startsWith("ko") ? "ko" : "en";
  };
  const resolve = setting => (setting === "ko" || setting === "en") ? setting : browserLang();
  let remembered = null;
  try { remembered = localStorage.getItem(KEY); } catch (e) { /* 저장소를 못 쓰면 브라우저 언어 */ }
  let lang = (remembered === "ko" || remembered === "en") ? remembered : browserLang();
  document.documentElement.lang = lang;

  // {n} 은 값, {n|session|sessions} 는 n 이 1 이면 앞, 아니면 뒤(영어 단수·복수)
  function fill(s, vars) {
    if (!vars) return s;
    return s.replace(/\{(\w+)\|([^|}]*)\|([^}]*)\}/g, (m, k, one, many) => (k in vars ? (Number(vars[k]) === 1 ? one : many) : m))
      .replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
  }
  // t("세션 {n}개", { n: 3 }) → 한국어 "세션 3개" / 영어 "3 sessions"
  function t(ko, vars) {
    const s = lang === "en" && Object.prototype.hasOwnProperty.call(EN, ko) ? EN[ko] : ko;
    return fill(s, vars);
  }
  function add(dict) { Object.assign(EN, dict); }

  const ATTRS = ["title", "placeholder", "aria-label", "alt"];
  function apply(root) {
    if (lang !== "en") return;
    root = root || document;
    const walker = document.createTreeWalker(root.body || root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) nodes.push(n);
    for (const n of nodes) {
      const v = n.nodeValue, k = v.trim();
      if (k && Object.prototype.hasOwnProperty.call(EN, k)) n.nodeValue = v.replace(k, EN[k]);
    }
    for (const el of (root.body || root).querySelectorAll("[title],[placeholder],[aria-label],[alt]"))
      for (const a of ATTRS) {
        const v = el.getAttribute(a);
        if (v && Object.prototype.hasOwnProperty.call(EN, v.trim())) el.setAttribute(a, EN[v.trim()]);
      }
    const doc = root.ownerDocument || root;
    if (doc.title && Object.prototype.hasOwnProperty.call(EN, doc.title)) doc.title = EN[doc.title];
  }

  // 허브 설정의 언어를 받았을 때. 지금 그린 언어와 다르면 기억하고 새로 고친다(기억을 못 하면 고리가 생기니 그냥 둔다)
  function sync(setting) {
    const want = resolve(setting);
    let stored = false;
    try { localStorage.setItem(KEY, want); stored = localStorage.getItem(KEY) === want; } catch (e) { /* 그대로 */ }
    if (want !== lang && stored) { location.reload(); return true; }
    return false;
  }

  g.I18N = { get lang() { return lang; }, t, add, apply, sync, resolve, browserLang };
  g.t = t;
})(window);
