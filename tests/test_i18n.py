"""영어 화면 사전 점검: 화면 코드가 t("한국어") 로 부르는 문장과 정적 HTML 의 한국어 문구가 모두 영어 사전에 있는지.

사전은 hub/static/i18n/en-*.js 의 I18N.add({...}) 에 "한국어": "영어" 로 들어 있다. 빠진 문장은 영어 화면에서
한국어 그대로 보이므로 여기서 잡는다."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "hub" / "static"
HANGUL = re.compile(r"[가-힣]")
SAME_IN_BOTH = {"한국어"}   # 언어 고르기의 「한국어」는 어느 화면에서나 한국어로 둔다
# JS 문자열 리터럴: "..." 또는 '...' 또는 `...`(${} 없는 것). 키는 사전 파일에서 큰따옴표로 쓴다
KEY = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:')
CALL = re.compile(r"""\bt\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|`([^`$]*)`)""")


def unquote(s: str) -> str:
    return json.loads('"' + s.replace("\n", "\\n") + '"')


def dictionary() -> dict:
    keys = {}
    for p in sorted((STATIC / "i18n").glob("en-*.js")):
        for m in KEY.finditer(p.read_text(encoding="utf-8")):
            keys[unquote(m.group(1))] = p.name
    return keys


def calls(text: str) -> set:
    out = set()
    for m in CALL.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(2) if m.group(2) is not None else m.group(3)
        try:
            out.add(unquote(raw) if m.group(3) is None else raw)
        except ValueError:
            out.add(raw)
    return out


class _Texts(HTMLParser):
    """정적 HTML 의 글자 마디와 title·placeholder·aria-label·alt (script·style 안은 뺀다)."""

    def __init__(self):
        super().__init__()
        self.skip = 0
        self.found = set()

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in attrs:
            if k in ("title", "placeholder", "aria-label", "alt") and v and HANGUL.search(v):
                self.found.add(v.strip())

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and HANGUL.search(data):
            self.found.add(data.strip())


def test_every_t_call_has_an_english_entry():
    keys = dictionary()
    missing = {}
    for name in ("office3d.js", "admin.html", "shared.js"):
        for k in calls((STATIC / name).read_text(encoding="utf-8")):
            if HANGUL.search(k) and k not in keys:
                missing.setdefault(name, []).append(k)
    assert not missing, missing


def test_static_html_text_has_english_entries():
    keys = dictionary()
    missing = {}
    for name in ("index.html", "admin.html"):
        p = _Texts()
        p.feed((STATIC / name).read_text(encoding="utf-8"))
        miss = sorted(k for k in p.found if k not in keys and k not in SAME_IN_BOTH)
        if miss:
            missing[name] = miss
    assert not missing, missing


def test_dictionary_values_are_english():
    for p in sorted((STATIC / "i18n").glob("en-*.js")):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r'"(?:[^"\\]|\\.)*"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
            assert not HANGUL.search(m.group(1)), (p.name, m.group(0))
