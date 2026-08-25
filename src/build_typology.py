"""Build and validate an exploratory rural financial-access typology.

The model is deliberately narrower than the service-routing scope. It fits only
comparable 읍/면 rows with primary road distances, evaluates Ward hierarchical
clusterings for k=2..5, and publishes labels only when predeclared quality gates
pass. Urban rows and road-distance fallback rows stay visible but unassigned.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist, squareform

from config import DATA_OUT, ROOT

INPUT_NAME = "access_road.csv"
OUTPUT_NAME = "access_typology.csv"
METADATA_NAME = "typology_evaluation.json"
REPORT_NAME = "typology_evaluation.md"

FEATURES = ("road_km", "cnt_3km", "ratio_65plus")
K_CANDIDATES = range(2, 6)
SEED = 20_260_812
STABILITY_ROUNDS = 100
SUBSAMPLE_FRACTION = 0.8
RULE_DISTANCE_THRESHOLD_KM = 3.0

# These are project adoption gates, not universal statistical thresholds.
GATES = {
    "silhouette_min": 0.35,
    "stability_median_ari_min": 0.75,
    "stability_p10_ari_min": 0.50,
    "cluster_jaccard_min_median_min": 0.75,
    "min_cluster_share": 0.05,
    "preprocessing_ari_min": 0.75,
    "preprocessing_cluster_jaccard_min": 0.70,
}


def read_rows() -> list[dict[str, str]]:
    path = DATA_OUT / INPUT_NAME
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


def is_rural_peer(row: dict[str, str]) -> bool:
    return row["dong"].endswith(("읍", "면"))


def feature_matrices(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray, dict]:
    raw = np.array([[float(row[name]) for name in FEATURES] for row in rows], dtype=float)
    transformed = raw.copy()

    standardized, medians, scales = robust_scale(transformed)
    preprocessing = {
        "transformations": {
            "road_km": "identity",
            "cnt_3km": "identity",
            "ratio_65plus": "identity",
        },
        "primary_rationale": (
            "preserve linear policy meaning of kilometres, outlet counts, and percentage points"
        ),
        "scaling": "median/IQR robust scaling",
        "transformed_medians": dict(zip(FEATURES, medians.tolist())),
        "transformed_iqr": dict(zip(FEATURES, scales.tolist())),
    }
    return raw, standardized, preprocessing


def robust_scale(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    medians = np.median(matrix, axis=0)
    q1 = np.quantile(matrix, 0.25, axis=0)
    q3 = np.quantile(matrix, 0.75, axis=0)
    scales = np.where(q3 > q1, q3 - q1, 1.0)
    return (matrix - medians) / scales, medians, scales


def adjusted_rand_index(left: np.ndarray, right: np.ndarray) -> float:
    """Compute the permutation-invariant adjusted Rand index."""

    n = len(left)
    if n < 2:
        return 1.0

    def pairs(value: int) -> int:
        return value * (value - 1) // 2

    left_counts = Counter(left.tolist())
    right_counts = Counter(right.tolist())
    joint_counts = Counter(zip(left.tolist(), right.tolist()))
    total_pairs = pairs(n)
    left_pairs = sum(pairs(value) for value in left_counts.values())
    right_pairs = sum(pairs(value) for value in right_counts.values())
    joint_pairs = sum(pairs(value) for value in joint_counts.values())
    expected = left_pairs * right_pairs / total_pairs
    maximum = (left_pairs + right_pairs) / 2
    return (joint_pairs - expected) / (maximum - expected) if maximum != expected else 1.0


def silhouette_score(matrix: np.ndarray, labels: np.ndarray) -> float:
    distances = squareform(pdist(matrix))
    unique = sorted(set(labels.tolist()))
    scores: list[float] = []
    for index, label in enumerate(labels):
        same = np.where(labels == label)[0]
        same = same[same != index]
        if not len(same):
            scores.append(0.0)
            continue
        within = float(distances[index, same].mean())
        nearest_other = min(
            float(distances[index, np.where(labels == other)[0]].mean())
            for other in unique
            if other != label
        )
        denominator = max(within, nearest_other)
        scores.append((nearest_other - within) / denominator if denominator else 0.0)
    return float(np.mean(scores))


def stability_scores(
    matrix: np.ndarray,
    labels: np.ndarray,
    k: int,
) -> tuple[list[float], dict[int, list[float]]]:
    rng = np.random.default_rng(SEED + k)
    sample_size = max(k * 3, int(len(matrix) * SUBSAMPLE_FRACTION))
    ari_scores: list[float] = []
    jaccard_scores = {int(label): [] for label in sorted(set(labels.tolist()))}
    for _ in range(STABILITY_ROUNDS):
        indexes = np.sort(rng.choice(len(matrix), size=sample_size, replace=False))
        sampled_labels = fcluster(
            linkage(matrix[indexes], method="ward"),
            k,
            criterion="maxclust",
        )
        ari_scores.append(adjusted_rand_index(labels[indexes], sampled_labels))
        sampled_index_set = set(indexes.tolist())
        for full_label in jaccard_scores:
            full_cluster = set(np.where(labels == full_label)[0].tolist()) & sampled_index_set
            overlaps: list[float] = []
            for sampled_label in sorted(set(sampled_labels.tolist())):
                sampled_cluster = set(indexes[np.where(sampled_labels == sampled_label)[0]].tolist())
                union = full_cluster | sampled_cluster
                overlaps.append(len(full_cluster & sampled_cluster) / len(union) if union else 1.0)
            jaccard_scores[full_label].append(max(overlaps))
    return ari_scores, jaccard_scores


def preprocessing_sensitivity(
    raw: np.ndarray,
    reference_labels: np.ndarray | None,
    k: int | None,
) -> dict | None:
    """Compare labels with a plausible log1p alternative adoption gate."""

    if reference_labels is None or k is None:
        return None
    alternative = raw.copy()
    alternative[:, 0] = np.log1p(alternative[:, 0])
    alternative[:, 1] = np.log1p(alternative[:, 1])
    alternative, _, _ = robust_scale(alternative)
    alternative_labels = fcluster(
        linkage(alternative, method="ward"),
        k,
        criterion="maxclust",
    )
    cluster_matches = []
    for reference_id in sorted(set(reference_labels.tolist())):
        reference_cluster = set(np.where(reference_labels == reference_id)[0].tolist())
        matches = []
        for alternative_id in sorted(set(alternative_labels.tolist())):
            alternative_cluster = set(np.where(alternative_labels == alternative_id)[0].tolist())
            union = reference_cluster | alternative_cluster
            matches.append((
                len(reference_cluster & alternative_cluster) / len(union),
                int(alternative_id),
            ))
        best_jaccard, best_id = max(matches)
        cluster_matches.append({
            "reference_cluster_id": int(reference_id),
            "best_alternative_cluster_id": best_id,
            "jaccard": round(best_jaccard, 6),
        })
    return {
        "status": "adoption_gate",
        "alternative": "log1p(road_km, cnt_3km) then median/IQR scaling",
        "adjusted_rand_index": round(
            adjusted_rand_index(reference_labels, alternative_labels),
            6,
        ),
        "cluster_matches": cluster_matches,
    }


def select_candidate(candidates: list[dict]) -> dict | None:
    """Select the strongest valid model without imposing a preferred k."""

    passing = [candidate for candidate in candidates if candidate["passes_project_gates"]]
    if not passing:
        return None
    return max(
        passing,
        key=lambda candidate: (candidate["silhouette"], -candidate["k"]),
    )


def evaluate_candidates(
    raw: np.ndarray,
    matrix: np.ndarray,
) -> tuple[list[dict], dict | None, np.ndarray | None]:
    min_cluster_count = max(2, math.ceil(len(matrix) * GATES["min_cluster_share"]))
    candidates: list[dict] = []
    labels_by_k: dict[int, np.ndarray] = {}

    for k in K_CANDIDATES:
        labels = fcluster(linkage(matrix, method="ward"), k, criterion="maxclust")
        labels_by_k[k] = labels
        stability, cluster_jaccard = stability_scores(matrix, labels, k)
        sizes = sorted(Counter(labels.tolist()).values())
        cluster_jaccard_summary = [
            {
                "cluster_id": cluster_id,
                "median": round(float(np.median(values)), 6),
                "p10": round(float(np.quantile(values, 0.10)), 6),
            }
            for cluster_id, values in sorted(cluster_jaccard.items())
        ]
        result = {
            "k": k,
            "observed_cluster_count": len(sizes),
            "silhouette": round(silhouette_score(matrix, labels), 6),
            "stability_median_ari": round(float(np.median(stability)), 6),
            "stability_p10_ari": round(float(np.quantile(stability, 0.10)), 6),
            "cluster_sizes": sizes,
            "cluster_jaccard": cluster_jaccard_summary,
            "cluster_jaccard_min_median": min(
                value["median"] for value in cluster_jaccard_summary
            ),
            "min_cluster_required": min_cluster_count,
        }
        sensitivity = preprocessing_sensitivity(raw, labels, k)
        result["preprocessing_sensitivity"] = sensitivity
        result["passes_project_gates"] = (
            result["observed_cluster_count"] == k
            and result["silhouette"] >= GATES["silhouette_min"]
            and result["stability_median_ari"] >= GATES["stability_median_ari_min"]
            and result["stability_p10_ari"] >= GATES["stability_p10_ari_min"]
            and result["cluster_jaccard_min_median"]
            >= GATES["cluster_jaccard_min_median_min"]
            and min(sizes) >= min_cluster_count
            and sensitivity is not None
            and sensitivity["adjusted_rand_index"]
            >= GATES["preprocessing_ari_min"]
            and min(
                match["jaccard"] for match in sensitivity["cluster_matches"]
            ) >= GATES["preprocessing_cluster_jaccard_min"]
        )
        candidates.append(result)

    selected = select_candidate(candidates)
    if selected is None:
        return candidates, None, None
    return candidates, selected, labels_by_k[selected["k"]]


def cluster_profiles(
    raw: np.ndarray,
    matrix: np.ndarray,
    labels: np.ndarray,
    rows: list[dict[str, str]],
) -> dict[int, dict]:
    distances = squareform(pdist(matrix))
    profiles: dict[int, dict] = {}
    for cluster_id in sorted(set(labels.tolist())):
        indexes = np.where(labels == cluster_id)[0]
        within = distances[np.ix_(indexes, indexes)]
        medoid_index = int(indexes[int(np.argmin(within.sum(axis=1)))])
        profiles[cluster_id] = {
            "count": int(len(indexes)),
            "medians": dict(zip(
                FEATURES,
                [round(float(value), 6) for value in np.median(raw[indexes], axis=0)],
            )),
            "representative": {
                "code": rows[medoid_index]["code"],
                "sigungu": rows[medoid_index]["sigungu"],
                "dong": rows[medoid_index]["dong"],
            },
        }
    return profiles


def semantic_names(profiles: dict[int, dict]) -> dict[int, str]:
    if not profiles:
        return {}
    hub = max(profiles, key=lambda key: profiles[key]["medians"]["cnt_3km"])
    remaining = [key for key in profiles if key != hub]
    remote = max(remaining, key=lambda key: profiles[key]["medians"]["road_km"]) if remaining else None

    names = {hub: "농촌 접점중심형"}
    if remote is not None:
        names[remote] = "장거리·접점희소형"
    unnamed = [cluster_id for cluster_id in profiles if cluster_id not in names]
    if unnamed:
        aging = max(
            unnamed,
            key=lambda key: profiles[key]["medians"]["ratio_65plus"],
        )
        names[aging] = "고령·저접점형"
    for cluster_id in unnamed:
        if cluster_id not in names:
            names[cluster_id] = f"복합취약형-{cluster_id}"
    return names


def write_typology(
    all_rows: list[dict[str, str]],
    fit_rows: list[dict[str, str]],
    labels: np.ndarray | None,
    names: dict[int, str],
    rule_age_threshold: float,
) -> Counter:
    assignment: dict[str, tuple[int, str]] = {}
    if labels is not None:
        assignment = {
            row["code"]: (int(label), names[int(label)])
            for row, label in zip(fit_rows, labels)
        }

    output_rows: list[dict] = []
    for row in all_rows:
        if row["code"] in assignment:
            cluster_id, cluster_name = assignment[row["code"]]
            status = "assigned_exploratory"
        elif is_rural_peer(row) and row["road_distance_primary"] != "Y":
            cluster_id, cluster_name = "", ""
            status = "excluded_route_quality"
        elif not is_rural_peer(row):
            cluster_id, cluster_name = "", ""
            status = "outside_rural_peer_cohort"
        else:
            cluster_id, cluster_name = "", ""
            status = "model_not_adopted"

        if is_rural_peer(row):
            long_distance = float(row["road_km"]) > RULE_DISTANCE_THRESHOLD_KM
            high_aging = float(row["ratio_65plus"]) >= rule_age_threshold
            if long_distance and high_aging:
                rule_type = "장거리·고령집중형"
            elif long_distance:
                rule_type = "장거리형"
            elif high_aging:
                rule_type = "고령집중형"
            else:
                rule_type = "상대적 접근양호형"
            rule_quality = "primary" if row["road_distance_primary"] == "Y" else "route_quality_uncertain"
        else:
            rule_type = ""
            rule_quality = "outside_rural_peer_cohort"
        output_rows.append({
            "code": row["code"],
            "sigungu": row["sigungu"],
            "dong": row["dong"],
            "analysis_cohort": "rural_peer" if is_rural_peer(row) else "urban_comparator",
            "typology_status": status,
            "cluster_id": cluster_id,
            "cluster_label": cluster_name,
            "rule_type": rule_type,
            "rule_quality": rule_quality,
            "road_km": row["road_km"],
            "cnt_3km": row["cnt_3km"],
            "ratio_65plus": row["ratio_65plus"],
            "road_distance_primary": row["road_distance_primary"],
        })

    path = DATA_OUT / OUTPUT_NAME
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    return Counter(row["typology_status"] for row in output_rows)


def write_report(metadata: dict) -> None:
    selected = metadata["selected_model"]
    lines = [
        "# 농촌 금융 접근 취약유형 모델 평가",
        "",
        "## 결론",
        "",
    ]
    if selected:
        lines += [
            f"전북 243개 행정동 전체를 한 번에 군집화하지 않고, 비교 가능한 읍·면 중 "
            f"기본 도로거리 품질을 통과한 {metadata['fit_row_count']}개만 모델 적합에 사용했다.",
            f"사전 문서화한 품질·재표집·전처리 민감도 게이트를 통과한 후보 중 실루엣이 가장 높은 "
            f"모델은 `k={selected['k']}`다. 결과는 탐색적 유형이며 정책 "
            "우선순위나 개인 위험도 점수가 아니다.",
            "",
        ]
    else:
        lines += [
            "어떤 군집 수도 문서화한 품질 게이트를 통과하지 못했다. 모델 라벨을 공개하지 않고 "
            "원지표 기반 규칙형 유형을 사용한다.",
            "",
        ]

    lines += [
        "## 입력과 경계",
        "",
        f"- 전체 행정동: {metadata['input_row_count']}개",
        f"- 모델 적합 읍·면: {metadata['fit_row_count']}개",
        f"- 도시형 비교대상 제외: {metadata['excluded']['outside_rural_peer_cohort']}개",
        f"- 도로거리 폴백 제외: {metadata['excluded']['route_quality']}개",
        "- 입력변수: 대표점 도로거리, 대표점 기준 직선 3km 내 접점 수, 65세 이상 비율",
        "- 세 변수는 중앙값/IQR로 강건 표준화",
        "- 우회계수는 경로 품질 영향과 불안정성을 별도로 보여주며 군집 입력에서는 제외",
        "",
        "## 후보 군집 수 검증",
        "",
        "| k | 실루엣 | 재표집 ARI 중앙값 | ARI 하위 10% | Jaccard 중앙값 최솟값 | log1p ARI | 군집 크기 | 게이트 |",
        "|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for candidate in metadata["candidate_models"]:
        lines.append(
            f"| {candidate['k']} | {candidate['silhouette']:.3f} | "
            f"{candidate['stability_median_ari']:.3f} | {candidate['stability_p10_ari']:.3f} | "
            f"{candidate['cluster_jaccard_min_median']:.3f} | "
            f"{candidate['preprocessing_sensitivity']['adjusted_rand_index']:.3f} | "
            f"{candidate['cluster_sizes']} | {'PASS' if candidate['passes_project_gates'] else 'FAIL'} |"
        )

    if selected:
        lines += ["", "## 선택 모델의 유형 프로필", "", "| 유형 | 행정동 | 도로거리 중앙값 | 3km 내 접점 중앙값 | 65세+ 비율 중앙값 | 대표 읍·면 |", "|---|---:|---:|---:|---:|---|"]
        for profile in metadata["cluster_profiles"]:
            medians = profile["medians"]
            representative = profile["representative"]
            lines.append(
                f"| {profile['cluster_label']} | {profile['count']} | {medians['road_km']:.2f}km | "
                f"{medians['cnt_3km']:.1f}개 | {medians['ratio_65plus']:.1f}% | "
                f"{representative['sigungu']} {representative['dong']} |"
            )

    sensitivity = metadata["preprocessing_sensitivity"]
    if sensitivity:
        matches = ", ".join(
            f"군집 {item['reference_cluster_id']}={item['jaccard']:.3f}"
            for item in sensitivity["cluster_matches"]
        )
        lines += [
            "",
            "## 전처리 민감도 진단",
            "",
            "주 모델은 km·접점 수·비율의 선형 정책 의미를 보존하고 중앙값/IQR로 표준화했다. "
            "거리와 접점 수의 큰 값을 압축하는 `log1p` 대안을 추가 비교했고, 두 결과의 ARI "
            f"`{metadata['project_gates']['preprocessing_ari_min']:.2f}` 이상과 군집별 최적 대응 "
            f"Jaccard 최솟값 `{metadata['project_gates']['preprocessing_cluster_jaccard_min']:.2f}` "
            "이상을 프로젝트 채택 게이트로 고정했다.",
            f"- 주 모델과 로그 대안의 ARI: `{sensitivity['adjusted_rand_index']:.3f}`",
            f"- 주 모델 군집별 최적 대응 Jaccard: {matches}",
            "- 전처리에 따라 일부 소속이 달라지므로 원지표·규칙형 유형을 함께 확인한다.",
        ]

    lines += [
        "",
        "## 규칙형 안전장치",
        "",
        f"- 장거리 기준: 도로거리 `{metadata['rule_based_fallback']['distance_threshold_km']:.1f}km` 초과",
        f"- 고령집중 기준: 모델 적합 농촌 비교집단의 65세+ 비율 중앙값 "
        f"`{metadata['rule_based_fallback']['age_threshold_pct']:.2f}%` 이상",
        "- 3km와 농촌 중앙값은 이 프로젝트의 시나리오 분류선이며 법정·공식 금융소외 기준이 아니다.",
        "- 모델이 향후 데이터에서 게이트를 통과하지 못해도 이 두 원지표로 네 유형을 재현한다.",
        "- 규칙형 유형도 행정동 대표점 프록시이며 주민 수를 뜻하지 않는다.",
        "",
        "## 해석과 사용 제한",
        "",
        "- 군집명은 모델 출력 후 중앙값 프로필을 보고 붙인 설명명이다.",
        "- 행정동 대표점 결과이므로 주민별 이동시간·노출인구로 해석하지 않는다.",
        "- 도로거리 폴백 4개는 모델 적합과 라벨 부여에서 제외하고 지도에 불확실성으로 표시한다.",
        "- 도시 동은 농촌 비교집단 모델 밖에 두며, 전북 전체에 같은 유형을 강제로 부여하지 않는다.",
        "- 모델 선택 게이트는 이번 분석에서 문서화해 향후 갱신에 고정 적용할 프로젝트 기준이다. 독립된 사전등록 기준이나 보편적 통계 기준은 아니다.",
        "- 유형은 순회서비스 후보를 설명하는 보조 근거다. 최종 거점과 동선은 운영 제약 최적화에서 결정한다.",
    ]
    (ROOT / "reports" / REPORT_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    input_path = DATA_OUT / INPUT_NAME
    all_rows = read_rows()
    fit_rows = [
        row for row in all_rows
        if is_rural_peer(row) and row["road_distance_primary"] == "Y"
    ]
    raw, matrix, preprocessing = feature_matrices(fit_rows)
    candidates, selected, labels = evaluate_candidates(raw, matrix)
    profiles = cluster_profiles(raw, matrix, labels, fit_rows) if labels is not None else {}
    names = semantic_names(profiles)
    sensitivity = selected["preprocessing_sensitivity"] if selected else None
    rule_age_threshold = float(np.median([float(row["ratio_65plus"]) for row in fit_rows]))
    status_counts = write_typology(all_rows, fit_rows, labels, names, rule_age_threshold)

    profile_rows = [
        {
            "cluster_id": int(cluster_id),
            "cluster_label": names[cluster_id],
            **profile,
        }
        for cluster_id, profile in sorted(profiles.items())
    ]
    metadata = {
        "analysis_version": 2,
        "input_file": f"data/processed/{INPUT_NAME}",
        "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
        "input_row_count": len(all_rows),
        "fit_scope": "읍/면 and road_distance_primary=Y",
        "fit_row_count": len(fit_rows),
        "excluded": {
            "outside_rural_peer_cohort": sum(not is_rural_peer(row) for row in all_rows),
            "route_quality": sum(
                is_rural_peer(row) and row["road_distance_primary"] != "Y" for row in all_rows
            ),
        },
        "features": list(FEATURES),
        "feature_definitions": {
            "road_km": "행정동 대표점에서 최근접 분석가용 금융접점까지 OSM 방향성 도로거리",
            "cnt_3km": "행정동 대표점에서 직선거리 3km 이내 분석가용 금융접점 수",
            "ratio_65plus": "행정동 주민등록인구 중 65세 이상 비율",
        },
        "preprocessing": preprocessing,
        "method": "Ward hierarchical agglomerative clustering",
        "candidate_k": list(K_CANDIDATES),
        "selection_rule": (
            "highest silhouette among candidates passing every project gate; lower k breaks exact ties"
        ),
        "rule_based_fallback": {
            "scope": "읍/면",
            "distance_threshold_km": RULE_DISTANCE_THRESHOLD_KM,
            "age_threshold_pct": round(rule_age_threshold, 6),
            "types": [
                "장거리·고령집중형",
                "장거리형",
                "고령집중형",
                "상대적 접근양호형",
            ],
        },
        "project_gates": GATES,
        "stability": {
            "metric": "adjusted Rand index against full-fit labels on 80% subsamples",
            "cluster_metric": "best-match cluster-wise Jaccard on the same subsamples",
            "rounds": STABILITY_ROUNDS,
            "seed": SEED,
        },
        "candidate_models": candidates,
        "selected_model": selected,
        "preprocessing_sensitivity": sensitivity,
        "model_status": (
            "accepted_for_exploratory_typology_not_policy_ranking"
            if selected else "rejected_use_rule_based_typology"
        ),
        "cluster_profiles": profile_rows,
        "output_status_counts": dict(status_counts),
        "limitations": [
            "administrative representative-point proxy, not resident-level exposure",
            "rural peer cohort only; urban dongs are outside the model",
            "road-distance fallback rows are unassigned",
            "cluster names are post-hoc descriptive labels",
        ],
    }
    (DATA_OUT / METADATA_NAME).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_report(metadata)

    print(f"typology rows: {len(all_rows)} → data/processed/{OUTPUT_NAME}")
    print(f"fit cohort: {len(fit_rows)}; status: {metadata['model_status']}")
    if selected:
        print(
            f"selected k={selected['k']}; silhouette={selected['silhouette']:.3f}; "
            f"stability median/p10={selected['stability_median_ari']:.3f}/"
            f"{selected['stability_p10_ari']:.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
