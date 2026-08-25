"""프로젝트 공용 설정 로더.

.env를 읽어 API 키를 제공한다. 외부 라이브러리 없이 표준 라이브러리만 사용한다.
키가 없으면 명시적으로 실패시켜, 키 없이 조용히 잘못된 결과가 나오는 것을 막는다.
"""

from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_OUT = ROOT / "data" / "processed"

_PLACEHOLDER = "PASTE_YOUR_KEY_HERE"


def load_env(path: Path | None = None) -> dict[str, str]:
    """.env를 파싱해 os.environ에 주입하고 dict로 반환."""
    path = path or ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if val:
            values[key.strip()] = val
            os.environ.setdefault(key.strip(), val)
    return values


def get_key(name: str, required: bool = True) -> str:
    """키를 가져온다. 미설정이거나 placeholder면 required일 때 예외."""
    load_env()
    val = os.environ.get(name, "").strip()
    if val in ("", _PLACEHOLDER):
        if required:
            raise RuntimeError(
                f"{name}가 설정되지 않았습니다. {ROOT/'.env'} 파일에 값을 넣어주세요."
            )
        return ""
    return val
