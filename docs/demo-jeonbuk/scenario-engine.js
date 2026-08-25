(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.JeonbukScenario = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const round = (value, digits = 9) => {
    const scale = 10 ** digits;
    return Math.round((value + Number.EPSILON) * scale) / scale;
  };

  function compareValue(left, right) {
    if (Array.isArray(left) && Array.isArray(right)) {
      const length = Math.min(left.length, right.length);
      for (let index = 0; index < length; index += 1) {
        const compared = compareValue(left[index], right[index]);
        if (compared !== 0) return compared;
      }
      return left.length - right.length;
    }
    if (typeof left === "number" && typeof right === "number") return left - right;
    if (left === right) return 0;
    return left < right ? -1 : 1;
  }

  function parseHHMM(value) {
    if (!/^\d{2}:\d{2}$/.test(value)) throw new Error(`잘못된 시각: ${value}`);
    const [hour, minute] = value.split(":").map(Number);
    if (hour > 23 || minute > 59) throw new Error(`잘못된 시각: ${value}`);
    return hour * 60 + minute;
  }

  function formatHHMM(value) {
    const rounded = Math.round(value);
    return `${String(Math.floor(rounded / 60)).padStart(2, "0")}:${String(rounded % 60).padStart(2, "0")}`;
  }

  function validateParameters(parameters, controls) {
    const normalized = { ...parameters };
    const integerFields = [
      ["vehicle_count", "차량 수"],
      ["operating_days_per_cycle", "운영일"],
      ["max_stops_per_route", "1일 최대 방문 수"],
    ];
    for (const [field, label] of integerFields) {
      const value = Number(normalized[field]);
      const rule = controls[field];
      if (!Number.isInteger(value) || value < rule.min || value > rule.max) {
        throw new Error(`${label}는 ${rule.min}~${rule.max} 범위의 정수여야 합니다.`);
      }
      normalized[field] = value;
    }

    const cycleRule = controls.service_cycle_days;
    if (cycleRule && normalized.service_cycle_days !== undefined) {
      const cycle = Number(normalized.service_cycle_days);
      if (!Number.isInteger(cycle) || cycle < cycleRule.min || cycle > cycleRule.max) {
        throw new Error(`서비스 주기는 ${cycleRule.min}~${cycleRule.max} 범위의 정수여야 합니다.`);
      }
      normalized.service_cycle_days = cycle;
      if (normalized.operating_days_per_cycle > cycle) {
        throw new Error("주간 운영일은 서비스 주기를 넘을 수 없습니다.");
      }
    }

    const service = Number(normalized.service_minutes);
    const serviceRule = controls.service_minutes;
    if (
      !Number.isInteger(service)
      || service < serviceRule.min
      || service > serviceRule.max
      || (service - serviceRule.min) % serviceRule.step !== 0
    ) {
      throw new Error(`장소당 서비스시간은 ${serviceRule.step}분 단위여야 합니다.`);
    }
    normalized.service_minutes = service;

    const timeRule = controls.operating_time;
    const minimum = parseHHMM(timeRule.min);
    const maximum = parseHHMM(timeRule.max);
    for (const [field, label] of [["operating_start", "시작 시각"], ["operating_end", "종료 시각"]]) {
      const value = parseHHMM(normalized[field]);
      if (value < minimum || value > maximum || (value - minimum) % timeRule.step_minutes !== 0) {
        throw new Error(`${label}은 ${timeRule.step_minutes}분 단위여야 합니다.`);
      }
    }
    if (parseHHMM(normalized.operating_end) <= parseHHMM(normalized.operating_start)) {
      throw new Error("종료 시각은 시작 시각보다 늦어야 합니다.");
    }
    return normalized;
  }

  function configureProvince(base, parameters) {
    const cycleDays = parameters.service_cycle_days ?? base.service_cycle_days;
    const zones = base.zones.map((zone) => {
      const engine = zone.engine_input;
      const candidates = engine.candidates.map((candidate) => ({
        ...candidate,
        service_minutes: parameters.service_minutes,
      }));
      return {
        zone_id: zone.zone_id,
        engine_input: {
          ...engine,
          vehicle_count: 1,
          max_stops_per_vehicle: Math.min(parameters.max_stops_per_route, candidates.length),
          operating_start: parameters.operating_start,
          operating_end: parameters.operating_end,
          service_cycle_days: cycleDays,
          candidates,
        },
      };
    });
    const capacity = parameters.vehicle_count * parameters.operating_days_per_cycle;
    return {
      ...base,
      vehicle_count: parameters.vehicle_count,
      operating_days_per_cycle: parameters.operating_days_per_cycle,
      minimum_route_days_per_active_zone: capacity >= zones.length ? 1 : 0,
      service_cycle_days: cycleDays,
      zones,
    };
  }

  function bitCount(value) {
    let count = 0;
    let remaining = value;
    while (remaining) {
      remaining &= remaining - 1;
      count += 1;
    }
    return count;
  }

  function transition(engine, state, candidate) {
    const travelMinutes = Number(engine.travel_minutes[state.last_node_id][candidate.candidate_id]);
    const distanceKm = Number(engine.distance_km[state.last_node_id][candidate.candidate_id]);
    const arrival = state.finish_minute + travelMinutes;
    const serviceStart = Math.max(arrival, parseHHMM(candidate.time_window_start));
    const wait = serviceStart - arrival;
    const finish = serviceStart + candidate.service_minutes;
    if (finish > parseHHMM(candidate.time_window_end)) return null;
    const returnMinutes = Number(engine.travel_minutes[candidate.candidate_id][engine.end_node_id]);
    if (finish + returnMinutes > parseHHMM(engine.operating_end)) return null;
    return {
      mask: state.mask | (1 << candidate.index),
      last_node_id: candidate.candidate_id,
      finish_minute: finish,
      travel_minutes: state.travel_minutes + travelMinutes,
      travel_km: state.travel_km + distanceKm,
      wait_minutes: state.wait_minutes + wait,
      service_minutes: state.service_minutes + candidate.service_minutes,
      stops: [...state.stops, candidate.candidate_id],
    };
  }

  function stateKey(state) {
    return [
      round(state.finish_minute),
      round(state.travel_minutes),
      round(state.wait_minutes),
      state.stops,
    ];
  }

  function finalizeRoute(engine, state) {
    const endTravel = Number(engine.travel_minutes[state.last_node_id][engine.end_node_id]);
    const endDistance = Number(engine.distance_km[state.last_node_id][engine.end_node_id]);
    const endMinute = state.finish_minute + endTravel;
    return {
      candidate_mask: state.mask,
      end_time: formatHHMM(endMinute),
      elapsed_minutes: round(endMinute - parseHHMM(engine.operating_start), 3),
      travel_minutes: round(state.travel_minutes + endTravel, 3),
      travel_km: round(state.travel_km + endDistance, 3),
      wait_minutes: round(state.wait_minutes, 3),
      service_minutes: state.service_minutes,
      stops: state.stops,
    };
  }

  function routeKey(route) {
    return [route.elapsed_minutes, route.travel_minutes, route.stops];
  }

  function enumerateFeasibleRoutes(engine) {
    const candidates = engine.candidates.map((candidate, index) => ({ ...candidate, index }));
    const start = {
      mask: 0,
      last_node_id: engine.start_node_id,
      finish_minute: parseHHMM(engine.operating_start),
      travel_minutes: 0,
      travel_km: 0,
      wait_minutes: 0,
      service_minutes: 0,
      stops: [],
    };
    const states = new Map();
    const routes = new Map([[0, finalizeRoute(engine, start)]]);
    for (const candidate of candidates) {
      const state = transition(engine, start, candidate);
      if (state) states.set(`${state.mask}:${candidate.index}`, state);
    }

    for (let size = 1; size <= engine.max_stops_per_vehicle; size += 1) {
      const current = [...states.values()].filter((state) => bitCount(state.mask) === size);
      for (const state of current) {
        const route = finalizeRoute(engine, state);
        const previous = routes.get(state.mask);
        if (!previous || compareValue(routeKey(route), routeKey(previous)) < 0) routes.set(state.mask, route);
        if (size === engine.max_stops_per_vehicle) continue;
        for (const candidate of candidates) {
          if (state.mask & (1 << candidate.index)) continue;
          const next = transition(engine, state, candidate);
          if (!next) continue;
          const key = `${next.mask}:${candidate.index}`;
          const existing = states.get(key);
          if (!existing || compareValue(stateKey(next), stateKey(existing)) < 0) states.set(key, next);
        }
      }
    }
    return routes;
  }

  function coverage(engine, mask) {
    const covered = new Set();
    engine.candidates.forEach((candidate, index) => {
      if (mask & (1 << index)) candidate.serves_target_ids.forEach((target) => covered.add(target));
    });
    const targetTier = new Map(engine.targets.map((target) => [target.target_id, target.priority_tier]));
    const counts = Object.fromEntries(engine.priority_tiers.map((tier) => [tier.tier_id, 0]));
    covered.forEach((target) => { counts[targetTier.get(target)] += 1; });
    return { counts, covered };
  }

  function solutionKey(engine, solution) {
    const covered = coverage(engine, solution.candidate_mask);
    return [
      ...engine.priority_tiers.map((tier) => -covered.counts[tier.tier_id]),
      -covered.covered.size,
      round(solution.routes.reduce((sum, route) => sum + route.travel_minutes + route.wait_minutes, 0)),
      round(Math.max(0, ...solution.routes.map((route) => route.elapsed_minutes))),
      solution.routes.map((route) => route.stops),
    ];
  }

  function summarizeZone(engine, solution) {
    const covered = coverage(engine, solution.candidate_mask);
    return {
      coverage_by_tier: covered.counts,
      covered_target_count: covered.covered.size,
      covered_target_ids: [...covered.covered].sort(),
      route_count: solution.routes.length,
      routes: solution.routes.map((route) => ({ ...route, stops: [...route.stops] })),
      totals: {
        travel_km: round(solution.routes.reduce((sum, route) => sum + route.travel_km, 0), 3),
        travel_minutes: round(solution.routes.reduce((sum, route) => sum + route.travel_minutes, 0), 3),
        wait_minutes: round(solution.routes.reduce((sum, route) => sum + route.wait_minutes, 0), 3),
        service_minutes: solution.routes.reduce((sum, route) => sum + route.service_minutes, 0),
        max_route_elapsed_minutes: round(Math.max(0, ...solution.routes.map((route) => route.elapsed_minutes)), 3),
      },
    };
  }

  function emptyZone(engine) {
    return {
      coverage_by_tier: Object.fromEntries(engine.priority_tiers.map((tier) => [tier.tier_id, 0])),
      covered_target_count: 0,
      covered_target_ids: [],
      route_count: 0,
      routes: [],
      totals: {
        travel_km: 0,
        travel_minutes: 0,
        wait_minutes: 0,
        service_minutes: 0,
        max_route_elapsed_minutes: 0,
      },
    };
  }

  function exactZoneOptions(engine, maximumRouteDays, allowZero) {
    const routes = enumerateFeasibleRoutes(engine);
    let solutions = new Map([[0, { candidate_mask: 0, routes: [] }]]);
    const options = allowZero ? [emptyZone(engine)] : [];
    for (let routeDay = 1; routeDay <= maximumRouteDays; routeDay += 1) {
      const next = new Map(solutions);
      for (const [usedMask, solution] of solutions) {
        for (const [routeMask, route] of routes) {
          if (routeMask === 0 || (usedMask & routeMask)) continue;
          const combinedMask = usedMask | routeMask;
          const candidate = { candidate_mask: combinedMask, routes: [...solution.routes, route] };
          const previous = next.get(combinedMask);
          if (!previous || compareValue(solutionKey(engine, candidate), solutionKey(engine, previous)) < 0) {
            next.set(combinedMask, candidate);
          }
        }
      }
      solutions = next;
      let best = null;
      for (const solution of solutions.values()) {
        if (!best || compareValue(solutionKey(engine, solution), solutionKey(engine, best)) < 0) best = solution;
      }
      options.push(summarizeZone(engine, best));
    }
    return options;
  }

  function aggregateKey(province, state) {
    return [
      ...province.priority_tiers.map((tier) => -state.coverage_by_tier[tier.tier_id]),
      -state.covered_target_count,
      round(state.travel_plus_wait_minutes),
      round(state.max_route_elapsed_minutes),
      state.allocated_route_days,
      state.plans.map((plan) => [plan.zone_id, plan.allocated_route_days]),
    ];
  }

  function addPlan(province, state, option) {
    const summary = option.summary;
    return {
      coverage_by_tier: Object.fromEntries(province.priority_tiers.map((tier) => [
        tier.tier_id,
        state.coverage_by_tier[tier.tier_id] + summary.coverage_by_tier[tier.tier_id],
      ])),
      covered_target_count: state.covered_target_count + summary.covered_target_count,
      travel_plus_wait_minutes: state.travel_plus_wait_minutes + summary.totals.travel_minutes + summary.totals.wait_minutes,
      max_route_elapsed_minutes: Math.max(state.max_route_elapsed_minutes, summary.totals.max_route_elapsed_minutes),
      allocated_route_days: state.allocated_route_days + option.allocated_route_days,
      plans: [...state.plans, option],
    };
  }

  function solveConfiguredProvince(province, parameters) {
    const capacity = province.vehicle_count * province.operating_days_per_cycle;
    const zones = [...province.zones].sort((left, right) => compareValue(left.zone_id, right.zone_id));
    const optionsByZone = zones.map((zone) => {
      const maximum = Math.min(zone.engine_input.candidates.length, capacity);
      const summaries = exactZoneOptions(zone.engine_input, maximum, province.minimum_route_days_per_active_zone === 0);
      const startDay = province.minimum_route_days_per_active_zone === 0 ? 0 : 1;
      const options = summaries.map((summary, index) => ({
        zone_id: zone.zone_id,
        allocated_route_days: startDay + index,
        summary,
      }));
      if (startDay === 1 && options.length && options[0].summary.route_count === 0) {
        return [{ zone_id: zone.zone_id, allocated_route_days: 0, summary: options[0].summary }];
      }
      return options;
    });

    const zeroCoverage = Object.fromEntries(province.priority_tiers.map((tier) => [tier.tier_id, 0]));
    let states = new Map([[0, {
      coverage_by_tier: zeroCoverage,
      covered_target_count: 0,
      travel_plus_wait_minutes: 0,
      max_route_elapsed_minutes: 0,
      allocated_route_days: 0,
      plans: [],
    }]]);
    for (const options of optionsByZone) {
      const next = new Map();
      for (const [usedDays, state] of states) {
        for (const option of options) {
          const nextUsed = usedDays + option.allocated_route_days;
          if (nextUsed > capacity) continue;
          const candidate = addPlan(province, state, option);
          const previous = next.get(nextUsed);
          if (!previous || compareValue(aggregateKey(province, candidate), aggregateKey(province, previous)) < 0) {
            next.set(nextUsed, candidate);
          }
        }
      }
      states = next;
    }
    if (!states.size) throw new Error("입력 조건에서 실행 가능한 전북 배정안이 없습니다.");
    let selected = null;
    for (const state of states.values()) {
      if (!selected || compareValue(aggregateKey(province, state), aggregateKey(province, selected)) < 0) selected = state;
    }

    const totals = {
      travel_km: 0,
      travel_minutes: 0,
      wait_minutes: 0,
      service_minutes: 0,
      max_route_elapsed_minutes: 0,
    };
    let routeDaysUsed = 0;
    for (const plan of selected.plans) {
      totals.travel_km += plan.summary.totals.travel_km;
      totals.travel_minutes += plan.summary.totals.travel_minutes;
      totals.wait_minutes += plan.summary.totals.wait_minutes;
      totals.service_minutes += plan.summary.totals.service_minutes;
      totals.max_route_elapsed_minutes = Math.max(
        totals.max_route_elapsed_minutes,
        plan.summary.totals.max_route_elapsed_minutes,
      );
      routeDaysUsed += plan.summary.route_count;
    }
    const targetCount = zones.reduce((sum, zone) => sum + zone.engine_input.targets.length, 0);
    const routeItems = selected.plans.flatMap((plan) => plan.summary.routes.map((route) => ({
      service_zone: plan.zone_id,
      ...route,
    })));
    routeItems.sort((left, right) => compareValue(
      [left.service_zone, left.stops],
      [right.service_zone, right.stops],
    ));
    const routes = routeItems.map((route, index) => ({
      ...route,
      cycle_day: Math.floor(index / province.vehicle_count) + 1,
      vehicle_id: `vehicle-${index % province.vehicle_count + 1}`,
    }));
    return {
      parameters,
      route_day_capacity: capacity,
      minimum_route_days_per_active_zone: province.minimum_route_days_per_active_zone,
      all_zones_allocated: selected.plans.every((plan) => plan.allocated_route_days > 0),
      coverage_by_tier: selected.coverage_by_tier,
      covered_target_count: selected.covered_target_count,
      target_count: targetCount,
      route_days_used: routeDaysUsed,
      unvisited_target_count: targetCount - selected.covered_target_count,
      routes,
      totals: {
        travel_km: round(totals.travel_km, 3),
        travel_minutes: round(totals.travel_minutes, 3),
        wait_minutes: round(totals.wait_minutes, 3),
        service_minutes: totals.service_minutes,
        max_route_elapsed_minutes: round(totals.max_route_elapsed_minutes, 3),
      },
      zone_allocations: selected.plans.map((plan) => ({
        zone_id: plan.zone_id,
        allocated_route_days: plan.allocated_route_days,
        covered_target_count: plan.summary.covered_target_count,
        target_count: zones.find((zone) => zone.zone_id === plan.zone_id).engine_input.targets.length,
        coverage_by_tier: plan.summary.coverage_by_tier,
      })),
    };
  }

  function sliceProvinceInput(base, zoneIds) {
    if (zoneIds == null || zoneIds === "" || zoneIds === "all") return base;
    const requested = Array.isArray(zoneIds) ? zoneIds : [zoneIds];
    if (!requested.length) return { ...base, zones: [] };
    const wanted = new Set(requested);
    const zones = base.zones.filter((zone) => wanted.has(zone.zone_id));
    if (zones.length !== wanted.size) {
      const known = new Set(base.zones.map((zone) => zone.zone_id));
      const missing = requested.find((zoneId) => !known.has(zoneId));
      throw new Error(`없는 시·군: ${missing}`);
    }
    if (zones.length === base.zones.length) return base;
    return { ...base, zones };
  }

  function calculate(base, parameters, controls) {
    const normalized = validateParameters(parameters, controls);
    return solveConfiguredProvince(configureProvince(base, normalized), normalized);
  }

  return { calculate, parseHHMM, validateParameters, sliceProvinceInput };
});
