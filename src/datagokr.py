"""공공데이터포털(data.go.kr) 공용 클라이언트.

주의 — 흔한 함정
  포털이 주는 '일반 인증키'는 이미 URL 인코딩된 문자열(%2B, %2F 등)이다.
  이를 urlencode()로 한 번 더 감싸면 %252B가 되어 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 난다.
  따라서 serviceKey는 **인코딩하지 않고 원문 그대로** 쿼리에 붙인다.

서비스별로 활용신청이 따로 필요하다. 신청하지 않은 서비스는
NO_OPENAPI_SERVICE_ERROR 또는 SERVICE_KEY_IS_NOT_REGISTERED_ERROR를 반환한다.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from config import get_key

VILLAGE_HALL_API = "https://api.data.go.kr/openapi/tn_pubr_public_vill_hall_sen_cent_api"


class DataGoKrError(RuntimeError):
    pass


def request(url: str, params: dict, *, timeout: int = 30) -> dict:
    """serviceKey는 원문 유지, 나머지 파라미터만 인코딩해 호출한다."""
    key = get_key("DATA_GO_KR_KEY")
    rest = urllib.parse.urlencode({k: v for k, v in params.items() if k != "serviceKey"})
    full = f"{url}?serviceKey={key}&{rest}"
    try:
        with urllib.request.urlopen(full, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        err = re.search(r"errMsg[\"\s:>]+([A-Z_]+)", body)
        raise DataGoKrError(f"HTTP {e.code} {err.group(1) if err else body[:120]}") from None

    err = re.search(r"errMsg[\"\s:>]+([A-Z_]+)", body)
    if err:
        raise DataGoKrError(err.group(1))
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise DataGoKrError(f"JSON 파싱 실패: {body[:150]}") from None


def _body(payload: dict) -> dict:
    """응답 래퍼가 서비스마다 달라(body 직속 / response.body) 양쪽을 흡수한다."""
    if "body" in payload:
        return payload["body"]
    return payload.get("response", {}).get("body", {})


def _items(body: dict) -> list[dict]:
    """items가 리스트일 수도, {"item": [...]} 중첩일 수도 있다."""
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items


def fetch_all(url: str, *, rows: int = 1000, extra: dict | None = None,
              max_pages: int = 200) -> list[dict]:
    """페이지를 끝까지 돌며 items를 모은다."""
    out: list[dict] = []
    total = None
    for page in range(1, max_pages + 1):
        params = {"pageNo": page, "numOfRows": rows, "type": "json"}
        if extra:
            params.update(extra)
        body = _body(request(url, params))
        if total is None:
            total = int(body.get("totalCount") or 0)
        items = _items(body)
        out.extend(items)
        if not items or (total and len(out) >= total):
            break
    return out


def total_count(url: str, extra: dict | None = None) -> int:
    params = {"pageNo": 1, "numOfRows": 1, "type": "json"}
    if extra:
        params.update(extra)
    return int(_body(request(url, params)).get("totalCount") or 0)


if __name__ == "__main__":
    n = total_count(VILLAGE_HALL_API)
    print(f"경로당·마을회관 API 총건수: {n:,}")
