"""시연 화면 빌드(scripts/build_demo.py): 페이지가 하위 주소에서도 열리게 경로가 바뀌고, 허브 흉내가 먼저 읽히는지."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
pytest.importorskip("fastapi")   # 기본 설정을 허브 코드에서 뽑는다


def test_build_demo(tmp_path):
    out = tmp_path / "site"
    subprocess.run([sys.executable, str(REPO / "scripts" / "build_demo.py"), str(out)], check=True, capture_output=True)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert index.index("static/demo.js") < index.index("static/i18n.js")      # 허브 흉내가 화면 코드보다 먼저
    assert 'href="admin.html"' in index and '"/static/' not in index
    for name in ("static/office3d.js", "static/shared.js", "admin.html"):
        text = (out / name).read_text(encoding="utf-8")
        assert not re.search(r"""["'`]/assets/""", text), name                  # 그림은 상대 경로
    cfg = json.loads((out / "static" / "demo-config.json").read_text(encoding="utf-8"))
    imgs = [c["image"] for c in cfg["characters"]]
    assert all(imgs) and all((out / "assets" / n).is_file() for n in imgs)
    assert not (out / "static" / "index.html").exists()
