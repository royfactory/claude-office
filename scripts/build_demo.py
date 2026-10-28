#!/usr/bin/env python3
"""시연 화면(GitHub Pages)을 site/ 에 만든다 — 허브 없이 가짜 사무실이 돈다.

hub/static 을 그대로 복사하고, 페이지가 저장소 하위 주소(…github.io/claude-office/)에서도 열리도록 절대 경로(/static/·/assets/·/admin)를
상대 경로로 바꾼 뒤, 화면 코드보다 먼저 static/demo.js(허브 흉내)를 읽게 끼운다. 기본 캐릭터 그림은 site/assets/ 로.
기본 설정은 허브 코드의 default_config() 를 그대로 쓴다(허브 의존성 fastapi·pydantic 이 있어야 한다).

usage: python scripts/build_demo.py [출력 폴더, 기본 site]
"""
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HUB = REPO / "hub"


def default_config() -> dict:
    os.environ["OFFICE_DATA"] = tempfile.mkdtemp()   # 저장된 설정을 읽지 않게 빈 폴더
    os.environ.setdefault("OFFICE_TOKEN", "")
    sys.path.insert(0, str(HUB))
    import app   # noqa: E402
    return app.default_config()


ASSETS = re.compile(r"""(?<=["'`])/assets/""")


def relink(text: str) -> str:
    text = ASSETS.sub("assets/", text)
    text = text.replace('"/static/', '"static/').replace("'/static/", "'static/")
    text = text.replace('href="/admin"', 'href="admin.html"').replace('href="/"', 'href="index.html"')
    return text


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "site").resolve()
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(HUB / "static", out / "static")
    (out / "assets").mkdir()
    for p in (HUB / "defaults").glob("*.webp"):
        shutil.copy2(p, out / "assets" / p.name)
    cfg = default_config()
    (out / "static" / "demo-config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    # 화면 코드: 그림 주소와 three.js 모듈 주소
    for name in ("office3d.js", "shared.js"):
        p = out / "static" / name
        s = ASSETS.sub("assets/", p.read_text(encoding="utf-8"))
        s = s.replace('"/static/vendor/three.module.min.js"', '"./vendor/three.module.min.js"')
        p.write_text(s, encoding="utf-8")
    # 두 페이지: 사이트 뿌리에 두고 demo.js 를 i18n.js 보다 먼저
    for src, dst in (("index.html", "index.html"), ("admin.html", "admin.html")):
        s = relink((out / "static" / src).read_text(encoding="utf-8"))
        s = s.replace('<script src="static/i18n.js"></script>', '<script src="static/demo.js"></script>\n<script src="static/i18n.js"></script>', 1)
        assert "static/demo.js" in s, src
        s = re.sub(r"(<title>)", '<meta name="description" content="claude-office demo: a live 3D office for Claude Code sessions (sample data)">\n\\1', s, 1)
        (out / dst).write_text(s, encoding="utf-8")
    for name in ("index.html", "admin.html"):   # 뿌리로 옮긴 페이지의 원본은 지운다(헷갈리지 않게)
        (out / "static" / name).unlink()
    (out / ".nojekyll").write_text("")
    leftovers = [str(p.relative_to(out)) for p in out.rglob("*") if p.suffix in (".html", ".js") and re.search(r"""["'`]/(?:api|assets|static)/""", p.read_text(encoding="utf-8", errors="ignore")) and "vendor" not in p.parts]
    print(f"[demo] {out} — 파일 {sum(1 for _ in out.rglob('*') if _.is_file())}개")
    if leftovers:
        print("[demo] 절대 경로가 남은 파일(fetch 는 demo.js 가 가로채므로 /api/ 는 괜찮다):", ", ".join(leftovers))


if __name__ == "__main__":
    main()
