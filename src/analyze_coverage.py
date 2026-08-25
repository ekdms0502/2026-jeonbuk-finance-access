"""시군별 금융 접점 커버리지 × 고령화율 분석.

핵심 질문: 금융기관은 고령 인구가 많은 곳에 있는가?
기관별(특히 특정 은행) 미진출 시군을 고령화율과 대조해 사각지대를 드러낸다.

출력  reports/coverage_by_sigungu.md
      data/processed/coverage_by_sigungu.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

from config import ROOT, DATA_OUT

SIGUNGU = ["전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
           "완주군", "진안군", "무주군", "장수군", "임실군", "순창군", "고창군", "부안군"]
# 1금융권 분류 (은행법상 은행)
TIER1_GROUPS = {
    "시중은행": ["KB국민", "신한", "하나", "우리", "SC제일"],
    "지방은행": ["전북"],
    "특수은행": ["NH농협", "IBK기업", "한국산업", "Sh수협", "수출입"],
}


def norm_sgg(s: str) -> str:
    return "전주시" if "전주시" in s else s


def main() -> int:
    acc = list(csv.DictReader((DATA_OUT / "access_jeonbuk.csv").read_text(encoding="utf-8-sig").splitlines()))
    pts = [
        row for row in csv.DictReader(
            (DATA_OUT / "outlets_validated.csv").read_text(encoding="utf-8-sig").splitlines()
        )
        if row["finance_open"] == "Y"
    ]

    pop = defaultdict(lambda: [0, 0])
    for r in acc:
        s = norm_sgg(r["sigungu"])
        pop[s][0] += int(r["pop_total"])
        pop[s][1] += int(r["pop_65plus"])

    by_sgg = defaultdict(lambda: defaultdict(int))
    for p in pts:
        s = norm_sgg(p["sigungu"])
        by_sgg[s][p["type"]] += 1
        if p["type"] == "은행":
            for group, banks in TIER1_GROUPS.items():
                for b in banks:
                    if b in p["name"]:
                        by_sgg[s][b] += 1
                        by_sgg[s][group] += 1

    rows = []
    for s in SIGUNGU:
        total, p65 = pop[s]
        d = by_sgg[s]
        rows.append({
            "sigungu": s, "pop_total": total, "pop_65plus": p65,
            "ratio_65plus": round(p65 / total * 100, 1) if total else 0.0,
            "points_total": d["우체국"] + d["은행"] + d["신협"] + d["새마을금고"],
            "우체국": d["우체국"], "은행": d["은행"], "신협": d["신협"], "새마을금고": d["새마을금고"],
            "시중은행": d["시중은행"], "지방은행": d["지방은행"], "특수은행": d["특수은행"],
            "우리은행": d["우리"], "전북은행": d["전북"], "NH농협은행": d["NH농협"],
            "per_10k_65plus": round(((d["우체국"] + d["은행"] + d["신협"] + d["새마을금고"]) / p65 * 10000), 1) if p65 else 0.0,
        })
    rows.sort(key=lambda r: -r["ratio_65plus"])

    out = DATA_OUT / "coverage_by_sigungu.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    def gap(col: str):
        absent = [r for r in rows if r[col] == 0]
        present = [r for r in rows if r[col] > 0]
        f = lambda g: sum(x["ratio_65plus"] for x in g) / len(g) if g else 0.0
        return absent, present, f(absent), f(present)

    lines = ["# 시군별 금융 접점 커버리지 × 고령화율", "",
             "공개 목록에 등재된 분석 가용 접점과 시군별 고령화율을 기술통계로 대조한다.", "",
             "| 시군 | 65세+ 비율 | 65세+ 인구 | 접점 계 | 우체국 | 은행 | 신협 | 새마을금고 | 65세+ 1만명당 접점 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['sigungu']} | {r['ratio_65plus']}% | {r['pop_65plus']:,} | {r['points_total']} | "
                     f"{r['우체국']} | {r['은행']} | {r['신협']} | {r['새마을금고']} | {r['per_10k_65plus']} |")

    lines += ["", "## 기관별 미진출 시군", ""]
    for col in ("우리은행", "전북은행", "NH농협은행", "시중은행"):
        absent, _present, ra, rp = gap(col)
        lines += [f"### {col}", "",
                  f"- 미진출 **{len(absent)}개 시군**: {', '.join(x['sigungu'] for x in absent) or '없음'}",
                  f"- 미진출 시군 평균 고령화율 **{ra:.1f}%** vs 진출 시군 **{rp:.1f}%**",
                  f"- 미진출 시군 65세 이상 인구 **{sum(x['pop_65plus'] for x in absent):,}명**", ""]

    lines += ["## 해석 주의", "",
              "- 접점은 은행·신협·새마을금고·우체국을 포함하며, 지역농협·축협 단위조합은 미포함이다.",
              "- 은행·신협·새마을금고의 `finance_open=Y`는 실시간 영업 확인이 아니라 공개 목록 등재 프록시다.",
              "- 우체국은 API 승인 전이므로 2026-08-10 CSV 스냅샷 기준이다.",
              "- 65세 이상은 주민 수이며 금융 이용자 수가 아니다.",
              "- 은행 점포는 전국은행연합회 공시(2025.12말) 기준으로 현재와 시차가 있다.",
              "- 미진출은 '해당 시군에 영업점이 없음'을 뜻하며, 인근 시군 이용 가능성은 별도 고려가 필요하다."]

    rep = ROOT / "reports" / "coverage_by_sigungu.md"
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"시군 커버리지 → {out.relative_to(ROOT)} · {rep.relative_to(ROOT)}\n")
    print(f"{'시군':<8}{'65+비율':>8}{'접점':>6}{'1만명당':>8}   우리은행")
    for r in rows:
        mark = f"{r['우리은행']}곳" if r["우리은행"] else "✗ 없음"
        print(f"  {r['sigungu']:<6}{r['ratio_65plus']:>7.1f}%{r['points_total']:>6}{r['per_10k_65plus']:>8.1f}   {mark}")
    for col in ("우리은행", "전북은행", "NH농협은행"):
        absent, _, ra, rp = gap(col)
        print(f"\n{col}: 미진출 {len(absent)}개 시군 · 미진출 평균 고령화율 {ra:.1f}% vs 진출 {rp:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
