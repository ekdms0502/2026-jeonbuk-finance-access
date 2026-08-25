from __future__ import annotations

import copy
import itertools
import unittest

from route_scenario import configure_province, solve, solve_province


def payload(candidates: list[dict], vehicle_count: int = 1, max_stops: int = 1) -> dict:
    node_ids = ["start", "end", *[row["candidate_id"] for row in candidates]]
    distance = {
        origin: {destination: (0.0 if origin == destination else 1.0)
                 for destination in node_ids}
        for origin in node_ids
    }
    travel = {
        origin: {destination: (0.0 if origin == destination else 10.0)
                 for destination in node_ids}
        for origin in node_ids
    }
    return {
        "vehicle_count": vehicle_count,
        "max_stops_per_vehicle": max_stops,
        "service_cycle_days": 7,
        "operating_start": "09:00",
        "operating_end": "17:00",
        "start_node_id": "start",
        "end_node_id": "end",
        "priority_tiers": [
            {"tier_id": "P1", "description": "high"},
            {"tier_id": "P2", "description": "normal"},
        ],
        "targets": [
            {
                "target_id": row["serves_target_ids"][0],
                "priority_tier": row["priority_tier"],
            }
            for row in candidates
        ],
        "candidates": [
            {
                "candidate_id": row["candidate_id"],
                "serves_target_ids": row["serves_target_ids"],
                "service_minutes": row.get("service_minutes", 20),
                "time_window_start": row.get("time_window_start", "09:00"),
                "time_window_end": row.get("time_window_end", "16:30"),
            }
            for row in candidates
        ],
        "distance_km": distance,
        "travel_minutes": travel,
    }


class RouteScenarioTests(unittest.TestCase):
    def test_higher_priority_target_wins_stop_limit(self):
        data = payload([
            {"candidate_id": "near", "serves_target_ids": ["t2"], "priority_tier": "P2"},
            {"candidate_id": "far", "serves_target_ids": ["t1"], "priority_tier": "P1"},
        ])
        data["travel_minutes"]["start"]["near"] = 1.0
        data["distance_km"]["start"]["near"] = 0.1
        result = solve(data)
        self.assertEqual(result["baseline"]["covered_target_ids"], ["t2"])
        self.assertEqual(result["optimized"]["covered_target_ids"], ["t1"])

    def test_wait_time_is_explicit(self):
        data = payload([
            {
                "candidate_id": "later",
                "serves_target_ids": ["t1"],
                "priority_tier": "P1",
                "time_window_start": "10:00",
            },
        ])
        result = solve(data)["optimized"]
        self.assertEqual(result["totals"]["wait_minutes"], 50.0)
        self.assertEqual(result["routes"][0]["stops"][0]["service_start"], "10:00")

    def test_vehicle_count_is_an_input(self):
        data = payload([
            {"candidate_id": "a", "serves_target_ids": ["t1"], "priority_tier": "P1"},
            {"candidate_id": "b", "serves_target_ids": ["t2"], "priority_tier": "P2"},
        ], vehicle_count=2, max_stops=1)
        result = solve(data)["optimized"]
        self.assertEqual(result["covered_target_count"], 2)
        self.assertEqual(result["vehicles_used"], 2)

    def test_same_input_is_deterministic(self):
        data = payload([
            {"candidate_id": "b", "serves_target_ids": ["t2"], "priority_tier": "P2"},
            {"candidate_id": "a", "serves_target_ids": ["t1"], "priority_tier": "P1"},
        ], max_stops=2)
        self.assertEqual(solve(copy.deepcopy(data)), solve(copy.deepcopy(data)))

    def test_exact_solver_matches_independent_exhaustive_oracle(self):
        candidates = [
            {"candidate_id": "d", "serves_target_ids": ["t4"], "priority_tier": "P2"},
            {
                "candidate_id": "b",
                "serves_target_ids": ["t2"],
                "priority_tier": "P1",
                "time_window_start": "09:45",
            },
            {"candidate_id": "a", "serves_target_ids": ["t1"], "priority_tier": "P1"},
            {"candidate_id": "c", "serves_target_ids": ["t3"], "priority_tier": "P2"},
        ]
        data = payload(candidates, max_stops=3)
        data["operating_end"] = "12:00"

        travel = {
            "start": {"start": 0, "end": 0, "a": 18, "b": 8, "c": 15, "d": 5},
            "end": {"start": 0, "end": 0, "a": 0, "b": 0, "c": 0, "d": 0},
            "a": {"start": 0, "end": 14, "a": 0, "b": 6, "c": 8, "d": 12},
            "b": {"start": 0, "end": 9, "a": 11, "b": 0, "c": 7, "d": 6},
            "c": {"start": 0, "end": 10, "a": 9, "b": 5, "c": 0, "d": 4},
            "d": {"start": 0, "end": 16, "a": 7, "b": 13, "c": 3, "d": 0},
        }
        data["travel_minutes"] = travel
        data["distance_km"] = copy.deepcopy(travel)

        candidate_by_id = {row["candidate_id"]: row for row in data["candidates"]}
        target_tier = {row["target_id"]: row["priority_tier"] for row in data["targets"]}
        tier_order = [row["tier_id"] for row in data["priority_tiers"]]
        operating_start = 9 * 60
        operating_end = 12 * 60

        def minutes(value: str) -> int:
            hour, minute = (int(part) for part in value.split(":"))
            return hour * 60 + minute

        def oracle_key(sequence: tuple[str, ...]) -> tuple | None:
            current = operating_start
            last = "start"
            travel_total = 0.0
            wait_total = 0.0
            covered: set[str] = set()
            for candidate_id in sequence:
                candidate = candidate_by_id[candidate_id]
                leg = float(travel[last][candidate_id])
                arrival = current + leg
                service_start = max(arrival, minutes(candidate["time_window_start"]))
                wait = service_start - arrival
                finish = service_start + int(candidate["service_minutes"])
                if finish > minutes(candidate["time_window_end"]):
                    return None
                if finish + float(travel[candidate_id]["end"]) > operating_end:
                    return None
                current = finish
                last = candidate_id
                travel_total += leg
                wait_total += wait
                covered.update(candidate["serves_target_ids"])

            travel_total += float(travel[last]["end"])
            end_minute = current + float(travel[last]["end"])
            coverage = tuple(
                sum(target_tier[target_id] == tier_id for target_id in covered)
                for tier_id in tier_order
            )
            return (
                tuple(-value for value in coverage),
                -len(covered),
                round(travel_total + wait_total, 9),
                round(end_minute - operating_start, 9),
                sequence,
            )

        candidate_ids = tuple(candidate_by_id)
        feasible = []
        for size in range(1, data["max_stops_per_vehicle"] + 1):
            for sequence in itertools.permutations(candidate_ids, size):
                key = oracle_key(sequence)
                if key is not None:
                    feasible.append((key, sequence))
        expected = min(feasible)[1]

        optimized = solve(data)["optimized"]
        actual = tuple(
            stop["candidate_id"]
            for stop in optimized["routes"][0]["stops"]
        )
        self.assertEqual(actual, expected)
        self.assertEqual(optimized["covered_target_count"], len(expected))

    def test_province_allocates_minimum_day_to_each_zone(self):
        zone_a = payload([
            {"candidate_id": "a", "serves_target_ids": ["ta"], "priority_tier": "P1"},
        ])
        zone_b = payload([
            {"candidate_id": "b", "serves_target_ids": ["tb"], "priority_tier": "P2"},
        ])
        data = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 2,
            "minimum_route_days_per_active_zone": 1,
            "service_cycle_days": 7,
            "priority_tiers": zone_a["priority_tiers"],
            "zones": [
                {"zone_id": "A", "engine_input": zone_a},
                {"zone_id": "B", "engine_input": zone_b},
            ],
        }
        result = solve_province(data)["optimized"]
        self.assertEqual(result["covered_target_count"], 2)
        self.assertEqual(result["route_days_used"], 2)
        self.assertEqual([row["cycle_day"] for row in result["routes"]], [1, 2])

    def test_province_rejects_insufficient_zone_capacity(self):
        zone = payload([
            {"candidate_id": "a", "serves_target_ids": ["ta"], "priority_tier": "P1"},
        ])
        data = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 1,
            "minimum_route_days_per_active_zone": 1,
            "service_cycle_days": 7,
            "priority_tiers": zone["priority_tiers"],
            "zones": [
                {"zone_id": "A", "engine_input": zone},
                {"zone_id": "B", "engine_input": copy.deepcopy(zone)},
            ],
        }
        with self.assertRaisesRegex(ValueError, "minimum zone coverage"):
            solve_province(data)

    def test_configure_province_allows_partial_zone_comparison(self):
        zone_a = payload([
            {"candidate_id": "a", "serves_target_ids": ["ta"], "priority_tier": "P1"},
        ])
        zone_b = payload([
            {"candidate_id": "b", "serves_target_ids": ["tb"], "priority_tier": "P2"},
        ])
        data = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 2,
            "minimum_route_days_per_active_zone": 1,
            "service_cycle_days": 7,
            "priority_tiers": zone_a["priority_tiers"],
            "zones": [
                {"zone_id": "A", "engine_input": zone_a},
                {"zone_id": "B", "engine_input": zone_b},
            ],
        }
        configured = configure_province(data, {
            "vehicle_count": 1,
            "operating_days_per_cycle": 1,
            "operating_start": "09:00",
            "operating_end": "17:00",
            "service_minutes": 45,
            "max_stops_per_route": 4,
        })
        self.assertEqual(configured["minimum_route_days_per_active_zone"], 0)
        result = solve_province(configured)["optimized"]
        self.assertEqual(result["covered_target_ids"], ["ta"])

    def test_configure_province_applies_service_and_time_inputs(self):
        zone = payload([
            {"candidate_id": "a", "serves_target_ids": ["ta"], "priority_tier": "P1"},
        ])
        data = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 1,
            "minimum_route_days_per_active_zone": 1,
            "service_cycle_days": 7,
            "priority_tiers": zone["priority_tiers"],
            "zones": [{"zone_id": "A", "engine_input": zone}],
        }
        configured = configure_province(data, {
            "vehicle_count": 2,
            "operating_days_per_cycle": 3,
            "operating_start": "08:30",
            "operating_end": "18:30",
            "service_minutes": 60,
            "max_stops_per_route": 2,
        })
        engine = configured["zones"][0]["engine_input"]
        self.assertEqual(configured["vehicle_count"], 2)
        self.assertEqual(configured["operating_days_per_cycle"], 3)
        self.assertEqual(engine["operating_start"], "08:30")
        self.assertEqual(engine["operating_end"], "18:30")
        self.assertEqual(engine["candidates"][0]["service_minutes"], 60)

    def test_configure_province_service_cycle_override_and_guard(self):
        zone = payload([
            {"candidate_id": "a", "serves_target_ids": ["ta"], "priority_tier": "P1"},
        ])
        data = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 1,
            "minimum_route_days_per_active_zone": 1,
            "service_cycle_days": 7,
            "priority_tiers": zone["priority_tiers"],
            "zones": [{"zone_id": "A", "engine_input": zone}],
        }
        base_parameters = {
            "vehicle_count": 1,
            "operating_days_per_cycle": 5,
            "operating_start": "09:00",
            "operating_end": "17:00",
            "service_minutes": 45,
            "max_stops_per_route": 2,
        }
        configured = configure_province(data, {**base_parameters, "service_cycle_days": 14})
        self.assertEqual(configured["service_cycle_days"], 14)
        self.assertEqual(configured["zones"][0]["engine_input"]["service_cycle_days"], 14)
        with self.assertRaises(ValueError):
            configure_province(data, {**base_parameters, "service_cycle_days": 3})


if __name__ == "__main__":
    unittest.main()
