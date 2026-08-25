"""Deterministic optional-visit routing with time windows.

The engine is deliberately UI- and provider-independent.  It consumes a small
JSON-compatible contract containing candidates, target priorities, a directed
travel matrix, service times, and operating hours.  For the competition slice
the candidate pool is intentionally small, so exact subset dynamic programming
is easier to audit than a black-box solver.
"""

from __future__ import annotations

from collections import Counter

MAX_EXACT_CANDIDATES = 12


def parse_hhmm(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM value: {value}")
    return hour * 60 + minute


def format_hhmm(value: float) -> str:
    rounded = int(round(value))
    return f"{rounded // 60:02d}:{rounded % 60:02d}"


def validate_input(payload: dict) -> None:
    candidates = payload["candidates"]
    candidate_ids = [row["candidate_id"] for row in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate_id must be unique")
    if len(candidates) > MAX_EXACT_CANDIDATES:
        raise ValueError(
            f"exact engine supports at most {MAX_EXACT_CANDIDATES} candidates"
        )
    if not (1 <= int(payload["vehicle_count"]) <= len(candidates) or not candidates):
        raise ValueError("vehicle_count must be positive and no larger than candidates")
    if not (1 <= int(payload["max_stops_per_vehicle"]) <= max(1, len(candidates))):
        raise ValueError("max_stops_per_vehicle is outside candidate range")
    if int(payload["service_cycle_days"]) <= 0:
        raise ValueError("service_cycle_days must be positive")

    operating_start = parse_hhmm(payload["operating_start"])
    operating_end = parse_hhmm(payload["operating_end"])
    if operating_end <= operating_start:
        raise ValueError("operating_end must be later than operating_start")

    node_ids = {payload["start_node_id"], payload["end_node_id"], *candidate_ids}
    travel = payload["travel_minutes"]
    distance = payload["distance_km"]
    for origin in node_ids:
        if origin not in travel or origin not in distance:
            raise ValueError(f"matrix origin missing: {origin}")
        for destination in node_ids:
            for matrix, name in ((travel, "travel_minutes"), (distance, "distance_km")):
                value = matrix[origin].get(destination)
                if value is None or float(value) < 0:
                    raise ValueError(f"{name} missing/negative: {origin} -> {destination}")

    target_ids = {row["target_id"] for row in payload["targets"]}
    tier_ids = {row["tier_id"] for row in payload["priority_tiers"]}
    if any(row["priority_tier"] not in tier_ids for row in payload["targets"]):
        raise ValueError("target references unknown priority tier")
    for candidate in candidates:
        if not set(candidate["serves_target_ids"]) <= target_ids:
            raise ValueError("candidate references unknown target")
        start = parse_hhmm(candidate["time_window_start"])
        end = parse_hhmm(candidate["time_window_end"])
        if end <= start or int(candidate["service_minutes"]) <= 0:
            raise ValueError("candidate time window/service time is invalid")


def _transition(payload: dict, state: dict, candidate: dict) -> dict | None:
    travel_minutes = float(
        payload["travel_minutes"][state["last_node_id"]][candidate["candidate_id"]]
    )
    distance_km = float(
        payload["distance_km"][state["last_node_id"]][candidate["candidate_id"]]
    )
    arrival = state["finish_minute"] + travel_minutes
    service_start = max(arrival, parse_hhmm(candidate["time_window_start"]))
    wait = service_start - arrival
    finish = service_start + int(candidate["service_minutes"])
    if finish > parse_hhmm(candidate["time_window_end"]):
        return None
    return_to_end = float(
        payload["travel_minutes"][candidate["candidate_id"]][payload["end_node_id"]]
    )
    if finish + return_to_end > parse_hhmm(payload["operating_end"]):
        return None
    stop = {
        "candidate_id": candidate["candidate_id"],
        "target_ids": list(candidate["serves_target_ids"]),
        "arrival": format_hhmm(arrival),
        "service_start": format_hhmm(service_start),
        "service_end": format_hhmm(finish),
        "travel_minutes_from_previous": round(travel_minutes, 3),
        "travel_km_from_previous": round(distance_km, 3),
        "wait_minutes": round(wait, 3),
        "service_minutes": int(candidate["service_minutes"]),
    }
    return {
        "mask": state["mask"] | (1 << candidate["index"]),
        "last_node_id": candidate["candidate_id"],
        "finish_minute": finish,
        "travel_minutes": state["travel_minutes"] + travel_minutes,
        "travel_km": state["travel_km"] + distance_km,
        "wait_minutes": state["wait_minutes"] + wait,
        "service_minutes": state["service_minutes"] + int(candidate["service_minutes"]),
        "stops": [*state["stops"], stop],
    }


def _state_key(state: dict) -> tuple:
    return (
        round(state["finish_minute"], 9),
        round(state["travel_minutes"], 9),
        round(state["wait_minutes"], 9),
        tuple(stop["candidate_id"] for stop in state["stops"]),
    )


def _finalize_route(payload: dict, state: dict) -> dict:
    end_travel = float(
        payload["travel_minutes"][state["last_node_id"]][payload["end_node_id"]]
    )
    end_distance = float(
        payload["distance_km"][state["last_node_id"]][payload["end_node_id"]]
    )
    end_minute = state["finish_minute"] + end_travel
    start_minute = parse_hhmm(payload["operating_start"])
    return {
        "candidate_mask": state["mask"],
        "start_node_id": payload["start_node_id"],
        "end_node_id": payload["end_node_id"],
        "start_time": payload["operating_start"],
        "end_time": format_hhmm(end_minute),
        "elapsed_minutes": round(end_minute - start_minute, 3),
        "travel_minutes": round(state["travel_minutes"] + end_travel, 3),
        "travel_km": round(state["travel_km"] + end_distance, 3),
        "wait_minutes": round(state["wait_minutes"], 3),
        "service_minutes": state["service_minutes"],
        "return_leg": {
            "travel_minutes": round(end_travel, 3),
            "travel_km": round(end_distance, 3),
        },
        "stops": state["stops"],
    }


def enumerate_feasible_routes(payload: dict) -> dict[int, dict]:
    candidates = [{**row, "index": index} for index, row in enumerate(payload["candidates"])]
    start_state = {
        "mask": 0,
        "last_node_id": payload["start_node_id"],
        "finish_minute": parse_hhmm(payload["operating_start"]),
        "travel_minutes": 0.0,
        "travel_km": 0.0,
        "wait_minutes": 0.0,
        "service_minutes": 0,
        "stops": [],
    }
    states: dict[tuple[int, int], dict] = {}
    routes = {0: _finalize_route(payload, start_state)}

    for candidate in candidates:
        state = _transition(payload, start_state, candidate)
        if state is not None:
            states[(state["mask"], candidate["index"])] = state

    max_stops = int(payload["max_stops_per_vehicle"])
    for size in range(1, max_stops + 1):
        current = [state for (mask, _), state in states.items() if mask.bit_count() == size]
        for state in current:
            finalized = _finalize_route(payload, state)
            current_best = routes.get(state["mask"])
            if current_best is None or (
                finalized["elapsed_minutes"],
                finalized["travel_minutes"],
                tuple(stop["candidate_id"] for stop in finalized["stops"]),
            ) < (
                current_best["elapsed_minutes"],
                current_best["travel_minutes"],
                tuple(stop["candidate_id"] for stop in current_best["stops"]),
            ):
                routes[state["mask"]] = finalized
            if size == max_stops:
                continue
            for candidate in candidates:
                if state["mask"] & (1 << candidate["index"]):
                    continue
                next_state = _transition(payload, state, candidate)
                if next_state is None:
                    continue
                key = (next_state["mask"], candidate["index"])
                if key not in states or _state_key(next_state) < _state_key(states[key]):
                    states[key] = next_state
    return routes


def _coverage(payload: dict, candidate_mask: int) -> tuple[tuple[int, ...], set[str]]:
    covered: set[str] = set()
    for index, candidate in enumerate(payload["candidates"]):
        if candidate_mask & (1 << index):
            covered.update(candidate["serves_target_ids"])
    target_tier = {row["target_id"]: row["priority_tier"] for row in payload["targets"]}
    counts = Counter(target_tier[target_id] for target_id in covered)
    tier_order = [row["tier_id"] for row in payload["priority_tiers"]]
    return tuple(counts[tier_id] for tier_id in tier_order), covered


def _solution_key(payload: dict, solution: dict) -> tuple:
    coverage_vector, covered = _coverage(payload, solution["candidate_mask"])
    routes = solution["routes"]
    return (
        tuple(-value for value in coverage_vector),
        -len(covered),
        round(sum(route["travel_minutes"] + route["wait_minutes"] for route in routes), 9),
        round(max((route["elapsed_minutes"] for route in routes), default=0), 9),
        tuple(
            tuple(stop["candidate_id"] for stop in route["stops"])
            for route in routes
        ),
    )


def exact_solution(payload: dict) -> dict:
    routes = enumerate_feasible_routes(payload)
    solutions = {0: {"candidate_mask": 0, "routes": []}}
    for _ in range(int(payload["vehicle_count"])):
        next_solutions = dict(solutions)
        for used_mask, solution in solutions.items():
            for route_mask, route in routes.items():
                if route_mask == 0 or used_mask & route_mask:
                    continue
                combined_mask = used_mask | route_mask
                candidate = {
                    "candidate_mask": combined_mask,
                    "routes": [*solution["routes"], route],
                }
                if (
                    combined_mask not in next_solutions
                    or _solution_key(payload, candidate)
                    < _solution_key(payload, next_solutions[combined_mask])
                ):
                    next_solutions[combined_mask] = candidate
        solutions = next_solutions
    return min(solutions.values(), key=lambda value: _solution_key(payload, value))


def greedy_solution(payload: dict) -> dict:
    candidates = [{**row, "index": index} for index, row in enumerate(payload["candidates"])]
    used_mask = 0
    routes = []
    for _ in range(int(payload["vehicle_count"])):
        state = {
            "mask": 0,
            "last_node_id": payload["start_node_id"],
            "finish_minute": parse_hhmm(payload["operating_start"]),
            "travel_minutes": 0.0,
            "travel_km": 0.0,
            "wait_minutes": 0.0,
            "service_minutes": 0,
            "stops": [],
        }
        for _ in range(int(payload["max_stops_per_vehicle"])):
            options = []
            for candidate in candidates:
                bit = 1 << candidate["index"]
                if used_mask & bit or state["mask"] & bit:
                    continue
                next_state = _transition(payload, state, candidate)
                if next_state is None:
                    continue
                options.append((
                    round(next_state["travel_minutes"] - state["travel_minutes"], 9),
                    candidate["candidate_id"],
                    next_state,
                ))
            if not options:
                break
            state = min(options, key=lambda value: value[:2])[2]
        if state["mask"]:
            used_mask |= state["mask"]
            routes.append(_finalize_route(payload, state))
    return {"candidate_mask": used_mask, "routes": routes}


def summarize_solution(payload: dict, solution: dict, method: str) -> dict:
    coverage_vector, covered = _coverage(payload, solution["candidate_mask"])
    target_ids = {row["target_id"] for row in payload["targets"]}
    candidates_by_target: dict[str, list[dict]] = {target_id: [] for target_id in target_ids}
    for candidate in payload["candidates"]:
        for target_id in candidate["serves_target_ids"]:
            candidates_by_target[target_id].append(candidate)

    unvisited = []
    for target in payload["targets"]:
        target_id = target["target_id"]
        if target_id in covered:
            continue
        target_candidates = candidates_by_target[target_id]
        if not target_candidates:
            reason = "no_eligible_candidate"
        else:
            reason = "not_selected_under_stop_time_objective"
        unvisited.append({
            "target_id": target_id,
            "priority_tier": target["priority_tier"],
            "reason": reason,
        })

    route_rows = []
    for vehicle_index, route in enumerate(solution["routes"], 1):
        route_rows.append({"vehicle_id": f"vehicle-{vehicle_index}", **route})
    return {
        "method": method,
        "objective_order": [
            *[f"maximize_covered_{row['tier_id']}" for row in payload["priority_tiers"]],
            "maximize_total_covered",
            "minimize_travel_plus_wait_minutes",
            "minimize_max_route_elapsed_minutes",
        ],
        "coverage_by_tier": {
            row["tier_id"]: coverage_vector[index]
            for index, row in enumerate(payload["priority_tiers"])
        },
        "covered_target_count": len(covered),
        "covered_target_ids": sorted(covered),
        "unvisited_targets": unvisited,
        "vehicles_used": len(route_rows),
        "temporal_access": {
            "service_cycle_days": int(payload["service_cycle_days"]),
            "covered_target_max_wait_days_upper_bound": int(payload["service_cycle_days"]),
            "unvisited_targets_have_scheduled_service": False if unvisited else True,
        },
        "routes": route_rows,
        "totals": {
            "travel_km": round(sum(row["travel_km"] for row in route_rows), 3),
            "travel_minutes": round(sum(row["travel_minutes"] for row in route_rows), 3),
            "wait_minutes": round(sum(row["wait_minutes"] for row in route_rows), 3),
            "service_minutes": sum(row["service_minutes"] for row in route_rows),
            "max_route_elapsed_minutes": round(
                max((row["elapsed_minutes"] for row in route_rows), default=0),
                3,
            ),
        },
    }


def solve(payload: dict) -> dict:
    validate_input(payload)
    greedy = summarize_solution(payload, greedy_solution(payload), "nearest_feasible_greedy")
    exact = summarize_solution(payload, exact_solution(payload), "exact_subset_dp")
    return {
        "baseline": greedy,
        "optimized": exact,
        "comparison": {
            "coverage_by_tier_delta": {
                row["tier_id"]: (
                    exact["coverage_by_tier"][row["tier_id"]]
                    - greedy["coverage_by_tier"][row["tier_id"]]
                )
                for row in payload["priority_tiers"]
            },
            "covered_target_delta": (
                exact["covered_target_count"] - greedy["covered_target_count"]
            ),
            "travel_minutes_delta": round(
                exact["totals"]["travel_minutes"] - greedy["totals"]["travel_minutes"],
                3,
            ),
            "wait_minutes_delta": round(
                exact["totals"]["wait_minutes"] - greedy["totals"]["wait_minutes"],
                3,
            ),
        },
    }


def _empty_summary(payload: dict, method: str) -> dict:
    return {
        "method": method,
        "objective_order": [],
        "coverage_by_tier": {
            row["tier_id"]: 0 for row in payload["priority_tiers"]
        },
        "covered_target_count": 0,
        "covered_target_ids": [],
        "unvisited_targets": [
            {
                "target_id": row["target_id"],
                "priority_tier": row["priority_tier"],
                "reason": "zone_not_allocated_route_day",
            }
            for row in payload["targets"]
        ],
        "vehicles_used": 0,
        "temporal_access": {
            "service_cycle_days": int(payload["service_cycle_days"]),
            "covered_target_max_wait_days_upper_bound": None,
            "unvisited_targets_have_scheduled_service": False,
        },
        "routes": [],
        "totals": {
            "travel_km": 0.0,
            "travel_minutes": 0.0,
            "wait_minutes": 0.0,
            "service_minutes": 0,
            "max_route_elapsed_minutes": 0.0,
        },
    }


def _aggregate_key(payload: dict, state: dict) -> tuple:
    return (
        *[-state["coverage_by_tier"][row["tier_id"]] for row in payload["priority_tiers"]],
        -state["covered_target_count"],
        round(state["travel_plus_wait_minutes"], 9),
        round(state["max_route_elapsed_minutes"], 9),
        state["allocated_route_days"],
        tuple((row["zone_id"], row["allocated_route_days"]) for row in state["plans"]),
    )


def _add_plan(payload: dict, state: dict, option: dict) -> dict:
    summary = option["optimized"]
    return {
        "coverage_by_tier": {
            row["tier_id"]: (
                state["coverage_by_tier"][row["tier_id"]]
                + summary["coverage_by_tier"][row["tier_id"]]
            )
            for row in payload["priority_tiers"]
        },
        "covered_target_count": (
            state["covered_target_count"] + summary["covered_target_count"]
        ),
        "travel_plus_wait_minutes": (
            state["travel_plus_wait_minutes"]
            + summary["totals"]["travel_minutes"]
            + summary["totals"]["wait_minutes"]
        ),
        "max_route_elapsed_minutes": max(
            state["max_route_elapsed_minutes"],
            summary["totals"]["max_route_elapsed_minutes"],
        ),
        "allocated_route_days": (
            state["allocated_route_days"] + option["allocated_route_days"]
        ),
        "plans": [*state["plans"], option],
    }


def _province_summary(payload: dict, plans: list[dict], result_key: str, method: str) -> dict:
    tier_ids = [row["tier_id"] for row in payload["priority_tiers"]]
    coverage = Counter()
    covered: set[str] = set()
    unvisited = []
    route_items = []
    totals = Counter()
    max_elapsed = 0.0

    for option in plans:
        summary = option[result_key]
        coverage.update(summary["coverage_by_tier"])
        covered.update(summary["covered_target_ids"])
        unvisited.extend(
            {**row, "service_zone": option["zone_id"]}
            for row in summary["unvisited_targets"]
        )
        for route in summary["routes"]:
            route_items.append({"service_zone": option["zone_id"], **route})
        totals["travel_km"] += summary["totals"]["travel_km"]
        totals["travel_minutes"] += summary["totals"]["travel_minutes"]
        totals["wait_minutes"] += summary["totals"]["wait_minutes"]
        totals["service_minutes"] += summary["totals"]["service_minutes"]
        max_elapsed = max(max_elapsed, summary["totals"]["max_route_elapsed_minutes"])

    route_items.sort(key=lambda row: (
        row["service_zone"],
        tuple(stop["candidate_id"] for stop in row["stops"]),
    ))
    scheduled_routes = []
    vehicle_count = int(payload["vehicle_count"])
    for index, route in enumerate(route_items):
        scheduled_routes.append({
            **route,
            "cycle_day": index // vehicle_count + 1,
            "vehicle_id": f"vehicle-{index % vehicle_count + 1}",
        })

    return {
        "method": method,
        "objective_order": [
            f"maximize_covered_{tier_id}" for tier_id in tier_ids
        ] + [
            "maximize_total_covered",
            "minimize_travel_plus_wait_minutes",
            "minimize_max_route_elapsed_minutes",
        ],
        "coverage_by_tier": {tier_id: coverage[tier_id] for tier_id in tier_ids},
        "covered_target_count": len(covered),
        "covered_target_ids": sorted(covered),
        "unvisited_targets": sorted(
            unvisited, key=lambda row: (row["service_zone"], row["target_id"])
        ),
        "route_days_used": len(scheduled_routes),
        "temporal_access": {
            "service_cycle_days": int(payload["service_cycle_days"]),
            "operating_days_per_cycle": int(payload["operating_days_per_cycle"]),
            "route_day_capacity": (
                int(payload["vehicle_count"])
                * int(payload["operating_days_per_cycle"])
            ),
            "covered_target_max_wait_days_upper_bound": int(payload["service_cycle_days"]),
            "unvisited_targets_have_scheduled_service": False if unvisited else True,
        },
        "routes": scheduled_routes,
        "totals": {
            "travel_km": round(totals["travel_km"], 3),
            "travel_minutes": round(totals["travel_minutes"], 3),
            "wait_minutes": round(totals["wait_minutes"], 3),
            "service_minutes": int(totals["service_minutes"]),
            "max_route_elapsed_minutes": round(max_elapsed, 3),
        },
    }


def configure_province(payload: dict, parameters: dict) -> dict:
    """Apply UI scenario knobs without changing targets, depots, or matrices."""

    vehicle_count = int(parameters["vehicle_count"])
    operating_days = int(parameters["operating_days_per_cycle"])
    service_minutes = int(parameters["service_minutes"])
    max_stops = int(parameters["max_stops_per_route"])
    operating_start = parameters["operating_start"]
    operating_end = parameters["operating_end"]
    if vehicle_count <= 0 or operating_days <= 0:
        raise ValueError("vehicle_count and operating_days_per_cycle must be positive")
    cycle_days = int(parameters.get("service_cycle_days", payload["service_cycle_days"]))
    if cycle_days <= 0:
        raise ValueError("service_cycle_days must be positive")
    if operating_days > cycle_days:
        raise ValueError("operating days cannot exceed service cycle days")
    if service_minutes <= 0 or max_stops <= 0:
        raise ValueError("service_minutes and max_stops_per_route must be positive")
    if parse_hhmm(operating_end) <= parse_hhmm(operating_start):
        raise ValueError("operating_end must be later than operating_start")

    zones = []
    for zone in payload["zones"]:
        engine = zone["engine_input"]
        candidates = [
            {**candidate, "service_minutes": service_minutes}
            for candidate in engine["candidates"]
        ]
        zones.append({
            "zone_id": zone["zone_id"],
            "engine_input": {
                **engine,
                "vehicle_count": 1,
                "max_stops_per_vehicle": min(max_stops, len(candidates)),
                "operating_start": operating_start,
                "operating_end": operating_end,
                "service_cycle_days": cycle_days,
                "candidates": candidates,
            },
        })

    route_day_capacity = vehicle_count * operating_days
    minimum_days = 1 if route_day_capacity >= len(zones) else 0
    return {
        **payload,
        "vehicle_count": vehicle_count,
        "operating_days_per_cycle": operating_days,
        "minimum_route_days_per_active_zone": minimum_days,
        "service_cycle_days": cycle_days,
        "zones": zones,
    }


def solve_province(payload: dict) -> dict:
    """Allocate route-days across service zones, then solve each zone exactly."""

    vehicle_count = int(payload["vehicle_count"])
    operating_days = int(payload["operating_days_per_cycle"])
    minimum_days = int(payload["minimum_route_days_per_active_zone"])
    if vehicle_count <= 0 or operating_days <= 0 or minimum_days < 0:
        raise ValueError("province fleet/day inputs must be positive")
    capacity = vehicle_count * operating_days
    zones = sorted(payload["zones"], key=lambda row: row["zone_id"])
    if len({row["zone_id"] for row in zones}) != len(zones):
        raise ValueError("zone_id must be unique")
    if capacity < minimum_days * len(zones):
        raise ValueError("route-day capacity cannot satisfy minimum zone coverage")

    options_by_zone = []
    for zone in zones:
        engine = zone["engine_input"]
        candidates = engine["candidates"]
        if not candidates:
            raise ValueError(f"zone has no candidates: {zone['zone_id']}")
        options = []
        if minimum_days == 0:
            empty = _empty_summary(engine, "no_route_day_allocated")
            options.append({
                "zone_id": zone["zone_id"],
                "allocated_route_days": 0,
                "baseline": empty,
                "optimized": empty,
            })
        for route_days in range(max(1, minimum_days), min(len(candidates), capacity) + 1):
            zone_input = {**engine, "vehicle_count": route_days}
            result = solve(zone_input)
            options.append({
                "zone_id": zone["zone_id"],
                "allocated_route_days": route_days,
                "baseline": result["baseline"],
                "optimized": result["optimized"],
            })
        if minimum_days == 1 and options and not options[0]["optimized"]["routes"]:
            # 운영시간 안에 서비스 가능한 경로가 하나도 없는 시·군은 경로일을 강제 배정하지 않는다.
            empty = _empty_summary(engine, "no_feasible_route_in_operating_window")
            options = [{
                "zone_id": zone["zone_id"],
                "allocated_route_days": 0,
                "baseline": empty,
                "optimized": empty,
            }]
        options_by_zone.append(options)

    initial = {
        "coverage_by_tier": {
            row["tier_id"]: 0 for row in payload["priority_tiers"]
        },
        "covered_target_count": 0,
        "travel_plus_wait_minutes": 0.0,
        "max_route_elapsed_minutes": 0.0,
        "allocated_route_days": 0,
        "plans": [],
    }
    states = {0: initial}
    for options in options_by_zone:
        next_states = {}
        for used_days, state in states.items():
            for option in options:
                next_used = used_days + option["allocated_route_days"]
                if next_used > capacity:
                    continue
                candidate = _add_plan(payload, state, option)
                if (
                    next_used not in next_states
                    or _aggregate_key(payload, candidate)
                    < _aggregate_key(payload, next_states[next_used])
                ):
                    next_states[next_used] = candidate
        states = next_states
    if not states:
        raise ValueError("no feasible province route-day allocation")
    selected = min(states.values(), key=lambda row: _aggregate_key(payload, row))

    optimized = _province_summary(
        payload,
        selected["plans"],
        "optimized",
        "zone_allocation_plus_exact_subset_dp",
    )
    baseline = _province_summary(
        payload,
        selected["plans"],
        "baseline",
        "same_zone_capacity_nearest_feasible_greedy",
    )
    return {
        "allocation_method": "minimum_zone_days_then_lexicographic_route_day_knapsack",
        "zone_allocations": [
            {
                "zone_id": option["zone_id"],
                "allocated_route_days": option["allocated_route_days"],
                "optimized_covered": option["optimized"]["covered_target_count"],
                "baseline_covered": option["baseline"]["covered_target_count"],
            }
            for option in selected["plans"]
        ],
        "baseline": baseline,
        "optimized": optimized,
        "comparison": {
            "coverage_by_tier_delta": {
                tier_id: (
                    optimized["coverage_by_tier"][tier_id]
                    - baseline["coverage_by_tier"][tier_id]
                )
                for tier_id in [row["tier_id"] for row in payload["priority_tiers"]]
            },
            "covered_target_delta": (
                optimized["covered_target_count"] - baseline["covered_target_count"]
            ),
            "travel_minutes_delta": round(
                optimized["totals"]["travel_minutes"]
                - baseline["totals"]["travel_minutes"],
                3,
            ),
            "wait_minutes_delta": round(
                optimized["totals"]["wait_minutes"]
                - baseline["totals"]["wait_minutes"],
                3,
            ),
        },
    }
