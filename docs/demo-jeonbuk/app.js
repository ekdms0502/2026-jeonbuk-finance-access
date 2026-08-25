(function () {
  "use strict";

  const data = window.JEONBUK_DASHBOARD;
  const mapData = window.JEONBUK_MAP;
  const scenario = window.JeonbukScenario;
  if (!data || !mapData || !scenario) throw new Error("전북 대시보드 번들을 불러오지 못했습니다.");

  const byId = (id) => document.getElementById(id);
  const format = new Intl.NumberFormat("ko-KR");
  const presets = new Map(data.sensitivity_presets.map((row) => [row.preset_id, row]));
  const tierTotals = data.route.engine_input.zones.reduce((totals, zone) => {
    zone.engine_input.targets.forEach((target) => { totals[target.priority_tier] += 1; });
    return totals;
  }, { P1: 0, P2: 0 });
  const priorityLabels = { P1: "P1 최우선", P2: "P2 우선", accessible: "3km 이하", quality_deferred: "품질유보" };
  const priorityColors = { P1: "#b83a3a", P2: "#e18a26", accessible: "#2f7d58", quality_deferred: "#7666a9" };
  const typePalette = ["#1769aa", "#7b61a8", "#2f7d58", "#d07a24", "#64748b"];
  const vehiclePalette = ["#1769aa", "#d97706", "#7b61a8", "#0f766e", "#c2410c", "#334155", "#be185d", "#4d7c0f", "#0369a1", "#6d28d9"];
  const vehicleDashes = ["", "8 4", "2 3", "10 3 2 3", "5 3"];
  const sizeDefinitions = {
    elderly_population: { label: "65세 이상 인구", value: (row) => row.pop_65plus, unit: "명" },
    elderly_ratio: { label: "고령인구 비율", value: (row) => row.ratio_65plus, unit: "%" },
    road_distance: { label: "도로거리", value: (row) => row.road_km, unit: "km" },
    fixed: { label: "동일 크기", value: () => 1, unit: "" },
  };
  const globalTypeLabels = [...new Set(data.admins.map((row) => row.cluster_label || row.rule_type || "비교집단·미분류"))].sort();
  const zoneEngines = new Map(data.route.engine_input.zones.map((zone) => [zone.zone_id, zone.engine_input]));
  const routeLegs = new Map(mapData.route_legs.map((leg) => [`${leg.zone_id}|${leg.origin_id}|${leg.destination_id}`, leg]));
  const adminByCode = new Map(data.admins.map((row) => [row.code, row]));
  const outletColors = { "우체국": "#2563EB", "은행": "#0891B2", "새마을금고": "#DB2777", "신협": "#B45309" };
  const outletTypes = ["우체국", "은행", "새마을금고", "신협"];
  const outletRadius = 2.8;
  const scenarioCache = new Map();
  const customResults = new Map();
  const routePathCache = new Map();
  const sizeStatsCache = new Map();
  const zoneViewBoxCache = new Map();
  const allZoneIds = [...new Set(data.admins.map((row) => row.service_zone))].sort();
  const selectedZones = new Set(allZoneIds);

  let selectedCode = null;
  let activeScenarioId = "default";
  let viewBox = { x: 0, y: 0, width: 720, height: 520 };
  let dragState = null;
  let viewBoxAnimation = null;
  let syncingZone = false;
  let tablePage = 1;
  let distanceMode = "road";
  const tablePageSize = 10;

  const mapWidth = 720;
  const mapHeight = 520;
  const mapPadding = 18;
  const middleLon = (mapData.bounds.min_lon + mapData.bounds.max_lon) / 2;
  const middleLat = (mapData.bounds.min_lat + mapData.bounds.max_lat) / 2;
  const lonCorrection = Math.cos(middleLat * Math.PI / 180);
  const worldWidth = (mapData.bounds.max_lon - mapData.bounds.min_lon) * lonCorrection;
  const worldHeight = mapData.bounds.max_lat - mapData.bounds.min_lat;
  const mapScale = Math.min((mapWidth - mapPadding * 2) / worldWidth, (mapHeight - mapPadding * 2) / worldHeight);

  function pct(part, whole) {
    return `${(part / whole * 100).toFixed(1)}%`;
  }

  function formatMonth(iso) {
    if (!iso) return "";
    const [year, month] = iso.split("-");
    return `${year}. ${month}`;
  }

  function formatDate(iso) {
    if (!iso) return "";
    const [year, month, day] = iso.split("-");
    return day ? `${year}. ${month}. ${day}` : formatMonth(iso);
  }

  function formatDuration(minutes) {
    const total = Math.max(0, Math.round(Number(minutes) || 0));
    return `${Math.floor(total / 60)}시간 ${total % 60}분`;
  }

  function isOverview() {
    return !byId("view-overview").hidden;
  }

  function distanceFill(km) {
    if (km > 5) return "#F11D22";
    if (km > 3) return "#FC750D";
    if (km > 1) return "#FDB90D";
    return "#03AF69";
  }

  function sourceMetrics() {
    const adminCount = data.admins.length;
    const over3 = data.admins.filter((row) => row.road_km > 3).length;
    const over5 = data.admins.filter((row) => row.road_km > 5).length;
    const watch = over3 - over5;
    const ok = adminCount - over3;
    const asOf = data.source_as_of || {};
    byId("m-admin").textContent = format.format(data.scope.analysis_admin_count);
    byId("m-zone").textContent = format.format(data.scope.analysis_service_zone_count);
    byId("m-threshold").textContent = format.format(data.scope.threshold_target_count);
    byId("m-target").textContent = format.format(data.scope.route_eligible_target_count);
    byId("m-senior").textContent = format.format(data.admins.reduce((sum, row) => sum + row.pop_65plus, 0));
    byId("m-outlet").textContent = format.format(data.source_summary.finance_outlet_count);
    byId("m-target-label").textContent = format.format(data.source_summary.finance_outlet_count);
    const listedCount = data.source_summary.finance_outlet_listed_count;
    if (listedCount != null) {
      byId("m-outlet-listed").textContent = format.format(listedCount);
      byId("src-outlet-listed").textContent = format.format(listedCount);
      byId("m-outlet-listed-analysis").textContent = format.format(listedCount);
    }
    byId("m-over3").textContent = format.format(over3);
    byId("m-over3-pct").textContent = pct(over3, adminCount);
    byId("m-over5").textContent = format.format(over5);
    byId("m-over5-pct").textContent = pct(over5, adminCount);
    byId("m-weak").textContent = format.format(over5);
    byId("m-weak-pct").textContent = pct(over5, adminCount);
    byId("m-watch").textContent = format.format(watch);
    byId("m-watch-pct").textContent = pct(watch, adminCount);
    byId("m-ok").textContent = format.format(ok);
    byId("m-ok-pct").textContent = pct(ok, adminCount);
    { const el = byId("as-of-date"); if (el) el.textContent = formatDate(data.analysis_date); }
    byId("src-admin-date").textContent = formatMonth(asOf.admin);
    byId("src-outlet-date").textContent = formatMonth(asOf.outlets);
    byId("src-outlet-retrieved").textContent = formatMonth(asOf.outlets_retrieved || asOf.outlets);
    byId("src-senior-date").textContent = formatMonth(asOf.population_65plus);
    byId("src-admin-count").textContent = format.format(data.scope.analysis_admin_count);
    byId("src-outlet-count").textContent = format.format(data.source_summary.finance_outlet_count);
    const roadPrimary = data.source_summary.road_primary_count;
    const roadTotal = data.source_summary.admin_count;
    byId("m-road-primary").textContent = format.format(roadPrimary);
    byId("m-road-total").textContent = format.format(roadTotal);
    byId("m-road-primary-copy").textContent = format.format(roadPrimary);
    byId("m-road-nonprimary").textContent = format.format(roadTotal - roadPrimary);
    byId("m-route-deferred").textContent = format.format(data.scope.route_quality_deferred_count);
    byId("analysis-date").textContent = data.analysis_date;
    byId("ops-speed").textContent = String(data.route.travel_model.uniform_speed_kmh);
  }

  function renderOverview(plan) {
    const active = plan || activePlan();
    if (!active || !byId("ops-targets")) return;
    const p1 = active.coverage_by_tier.P1;
    const p2 = active.coverage_by_tier.P2;
    byId("ops-targets").textContent = format.format(active.target_count);
    byId("ops-covered").textContent = format.format(active.covered_target_count);
    byId("ops-covered-pct").textContent = String(Math.round(active.covered_target_count / active.target_count * 100));
    byId("ops-p1").textContent = `${p1} / ${tierTotals.P1}`;
    byId("ops-p1-pct").textContent = String(Math.round(p1 / tierTotals.P1 * 100));
    byId("ops-p2").textContent = `${p2} / ${tierTotals.P2}`;
    byId("ops-p2-pct").textContent = String(Math.round(p2 / tierTotals.P2 * 100));
    byId("ops-days").textContent = format.format(active.route_days_used);
    byId("ops-km").textContent = format.format(Math.round(active.totals.travel_km));
    byId("ops-time").textContent = formatDuration(active.totals.travel_minutes);
  }

  function showView(name) {
    ["overview", "analysis", "scenario"].forEach((view) => {
      byId(`view-${view}`).hidden = view !== name;
    });
    document.querySelectorAll(".top-nav button").forEach((button) => {
      button.setAttribute("aria-current", button.dataset.view === name ? "page" : "false");
    });
    const mapbox = document.querySelector(".mapbox");
    if (name === "analysis") {
      byId("analysis-map-slot").prepend(mapbox);
      fitSelectedZonesViewBox();
    } else {
      byId("overview-map-host").appendChild(mapbox);
      if (name === "overview") setViewBox({ x: 0, y: 0, width: mapWidth, height: mapHeight });
    }
    if (name !== "scenario") drawMap();
  }

  function setupViewTabs() {
    document.querySelectorAll(".top-nav button").forEach((button) => {
      button.addEventListener("click", () => showView(button.dataset.view));
    });
    const brand = document.querySelector(".brand");
    if (brand) brand.addEventListener("click", (event) => { event.preventDefault(); showView("overview"); });
    byId("to-analysis").addEventListener("click", () => showView("analysis"));
    byId("refresh-data")?.addEventListener("click", () => {
      scenarioCache.clear();
      customResults.clear();
      sourceMetrics();
      renderScenarios("default");
    });
  }

  function projectCoordinate(coordinate) {
    const [lon, lat] = coordinate;
    return [
      mapWidth / 2 + (lon - middleLon) * lonCorrection * mapScale,
      mapHeight / 2 - (lat - middleLat) * mapScale,
    ];
  }

  function project(row) { return projectCoordinate([row.lon, row.lat]); }

  function pathFromLine(line) {
    if (!line || line.length < 2) return "";
    return line.map((coordinate, index) => {
      const [x, y] = projectCoordinate(coordinate);
      return `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
    }).join("");
  }

  function pathFromPolygons(polygons) {
    return polygons.flatMap((polygon) => polygon.map((ring) => `${pathFromLine(ring)}Z`)).join("");
  }

  const boundaryPathCache = new Map(mapData.boundaries.map((feature) => [feature.code, pathFromPolygons(feature.polygons)]));
  const roadPathCache = Object.fromEntries(Object.entries(mapData.major_roads).map(([roadClass, lines]) => [
    roadClass,
    lines.map(pathFromLine).join(""),
  ]));

  function svgElement(name, attributes = {}, titleText = "") {
    const element = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
    if (titleText) {
      const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
      title.textContent = titleText;
      element.appendChild(title);
    }
    return element;
  }

  function selectedZoneList() {
    return allZoneIds.filter((zoneId) => selectedZones.has(zoneId));
  }

  function isAllZonesSelected() {
    return selectedZones.size === allZoneIds.length;
  }

  function filteredAdmins() {
    if (isAllZonesSelected()) return data.admins;
    return data.admins.filter((row) => selectedZones.has(row.service_zone));
  }

  function servedTargetIds(plan) {
    const byZone = new Map();
    for (const route of plan?.routes || []) {
      const ids = byZone.get(route.service_zone) || new Set();
      const engine = zoneEngines.get(route.service_zone);
      for (const stop of route.stops || []) {
        const code = typeof stop === "object" ? (stop.target_id || stop.code || stop.candidate_id) : stop;
        if (adminByCode.has(code)) {
          ids.add(code);
          continue;
        }
        const candidate = engine?.candidates.find((row) => row.candidate_id === code);
        (candidate?.serves_target_ids || []).forEach((targetId) => ids.add(targetId));
      }
      byZone.set(route.service_zone, ids);
    }
    return byZone;
  }

  function visitedCodes(plan = activePlan()) {
    const codes = new Set();
    for (const ids of servedTargetIds(plan).values()) ids.forEach((code) => codes.add(code));
    return codes;
  }

  function excludedCodes() {
    return new Set((data.route.excluded_targets || []).map((row) => row.target_id));
  }

  function visitStatus(row, plan = activePlan()) {
    if (excludedCodes().has(row.code)) return { label: "품질유보", cls: "quality_deferred", note: "경로 품질유보로 운영 대상에서 제외했습니다." };
    if (row.priority !== "P1" && row.priority !== "P2") return { label: "해당 없음", cls: "visit-na", note: "경로대상(P1·P2)이 아닙니다." };
    if (visitedCodes(plan).has(row.code)) return { label: "방문", cls: "visit-yes", note: `${scopedPlanLabel()} 운영주기 내 방문 대상입니다.` };
    return { label: "미방문", cls: "visit-no", note: `${scopedPlanLabel()} 운영주기 방문 대상이 아닙니다.` };
  }

  function rankedAdmins() {
    return [...filteredAdmins()].sort((left, right) => right.road_km - left.road_km || left.code.localeCompare(right.code));
  }

  function csvCell(value) {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replaceAll("\"", "\"\"")}"` : text;
  }

  function downloadAccessCsv() {
    const rows = rankedAdmins();
    const header = ["순위", "시군", "행정동", "도로거리km", "3km내접점", "65세이상인구", "65세이상비율", "취약유형", "우선순위", "운영주기방문", "비고"];
    const body = rows.map((row, index) => {
      const visit = visitStatus(row);
      return [index + 1, row.service_zone, row.dong, row.road_km.toFixed(2), row.cnt_3km, row.pop_65plus, row.ratio_65plus.toFixed(1), row.cluster_label || row.rule_type || "도시 비교집단", priorityLabels[row.priority], visit.label, visit.note];
    });
    const blob = new Blob(["\uFEFF" + [header, ...body].map((line) => line.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "jeonbuk-access-admins.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function resetAnalysisFilters() {
    selectedZones.clear();
    allZoneIds.forEach((zoneId) => selectedZones.add(zoneId));
    byId("metric-filter").value = "distance";
    byId("size-filter").value = "elderly_population";
    byId("route-day-filter").value = "all";
    byId("layer-roads").checked = true;
    byId("layer-routes").checked = true;
    byId("layer-nodes").checked = false;
    byId("layer-labels").checked = true;
    tablePage = 1;
    applyZoneSelection();
  }

  function typologyColor(row) {
    const label = row.cluster_label || row.rule_type || "비교집단·미분류";
    return typePalette[globalTypeLabels.indexOf(label) % typePalette.length];
  }

  function distanceOf(row) {
    return distanceMode === "road" ? row.road_km : row.line_km;
  }

  function distanceModeLabel() {
    return distanceMode === "road" ? "도로거리" : "직선거리";
  }

  function pointColor(row, metric) {
    if (metric === "priority") return priorityColors[row.priority];
    if (metric === "distance") return distanceFill(distanceOf(row));
    return typologyColor(row);
  }

  function sizeStats(key) {
    if (sizeStatsCache.has(key)) return sizeStatsCache.get(key);
    const definition = sizeDefinitions[key];
    const values = data.admins.map(definition.value).sort((left, right) => left - right);
    const stats = { min: values[0], median: values[Math.floor(values.length / 2)], max: values[values.length - 1] };
    sizeStatsCache.set(key, stats);
    return stats;
  }

  function analysisPointScale() {
    const focused = !isAllZonesSelected() && selectedZones.size > 0;
    return focused
      ? { min: 3.0, max: 8.4, fixed: 4.0, opacity: "0.78" }
      : { min: 2.3, max: 5.8, fixed: 2.8, opacity: "0.68" };
  }

  function radiusForValue(key, value) {
    const scale = analysisPointScale();
    if (key === "fixed") return scale.fixed;
    const stats = sizeStats(key);
    const ratio = stats.max === stats.min ? 0.5 : (value - stats.min) / (stats.max - stats.min);
    const normalized = Math.max(0, Math.min(1, ratio));
    return Math.sqrt(scale.min ** 2 + normalized * (scale.max ** 2 - scale.min ** 2));
  }

  function pointRadius(row, key = byId("size-filter").value) {
    return radiusForValue(key, sizeDefinitions[key].value(row));
  }

  function formatSizeValue(key, value) {
    if (key === "elderly_population") return `${format.format(Math.round(value))}명`;
    if (key === "elderly_ratio") return `${Number(value).toFixed(1)}%`;
    if (key === "road_distance") return `${Number(value).toFixed(1)}km`;
    return "동일";
  }

  function colorLegendItems(metric) {
    if (metric === "typology") {
      const visibleLabels = new Set(filteredAdmins().map((row) => row.cluster_label || row.rule_type || "비교집단·미분류"));
      return globalTypeLabels.filter((label) => visibleLabels.has(label)).map((label) => ({ label, color: typePalette[globalTypeLabels.indexOf(label) % typePalette.length] }));
    }
    if (metric === "distance") {
      return [
        { label: "5km 초과", color: "#F11D22" },
        { label: "3~5km", color: "#FC750D" },
        { label: "1~3km", color: "#FDB90D" },
        { label: "1km 이하", color: "#03AF69" },
      ];
    }
    return Object.entries(priorityLabels).map(([key, label]) => ({ label, color: priorityColors[key] }));
  }

  function vehicleNumber(vehicleId) { return Math.max(1, Number(String(vehicleId).split("-").pop()) || 1); }
  function vehicleColor(vehicleId) { return vehiclePalette[(vehicleNumber(vehicleId) - 1) % vehiclePalette.length]; }
  function vehicleDash(vehicleId) { return vehicleDashes[(vehicleNumber(vehicleId) - 1) % vehicleDashes.length]; }

  function drawLegend(metric, sizeKey, routes) {
    const colorItems = colorLegendItems(metric).map((item) => `<span><i class="dot" style="background:${item.color}"></i>${item.label}</span>`).join("");
    let sizeItems = "";
    if (sizeKey === "fixed") {
      sizeItems = `<span><i class="size-dot" style="width:10px;height:10px"></i>동일</span>`;
    } else {
      const stats = sizeStats(sizeKey);
      const samples = [stats.min, stats.median, stats.max];
      sizeItems = samples.map((value) => {
        const radius = radiusForValue(sizeKey, value);
        return `<span><i class="size-dot" style="width:${radius * 2}px;height:${radius * 2}px"></i>${formatSizeValue(sizeKey, value)}</span>`;
      }).join("");
    }
    const vehicles = [...new Set(routes.map((route) => route.vehicle_id))].sort();
    const routeItems = vehicles.map((vehicle) => `<span><i class="line-key" style="border-color:${vehicleColor(vehicle)};border-top-style:${vehicleDash(vehicle) ? "dashed" : "solid"}"></i>${vehicle.replace("vehicle-", "차량 ")}</span>`).join("");
    byId("legend").innerHTML = `<div class="legend-group"><b class="legend-title">색</b>${colorItems}</div><div class="legend-group"><b class="legend-title">크기 · ${sizeDefinitions[sizeKey].label}</b>${sizeItems}</div>${routeItems ? `<div class="legend-group"><b class="legend-title">경로</b>${routeItems}</div>` : ""}`;
    byId("encoding-note").textContent = `색: ${metric === "distance" ? `${distanceModeLabel()} 구간` : byId("metric-filter").selectedOptions[0].textContent} · 크기: ${sizeDefinitions[sizeKey].label}`;
  }

  function scenarioScope() {
    if (isAllZonesSelected()) return "all";
    return selectedZoneList();
  }

  function scopeCacheKey(scope = scenarioScope()) {
    if (scope == null || scope === "all") return "all";
    const ids = (Array.isArray(scope) ? [...scope] : [scope]).filter(Boolean).sort();
    if (!ids.length) return "";
    if (ids.length === allZoneIds.length && ids.every((id, index) => id === allZoneIds[index])) return "all";
    return ids.join(",");
  }

  function isFullProvinceScope(scope = scenarioScope()) {
    return scopeCacheKey(scope) === "all";
  }

  function engineInputForScope(scope = scenarioScope()) {
    return scenario.sliceProvinceInput(data.route.engine_input, scope);
  }

  function planCacheKey(scenarioId, scope = scenarioScope()) {
    return `${scenarioId}|${scopeCacheKey(scope)}`;
  }

  function planFor(scenarioId, scope = scenarioScope()) {
    if (scenarioId === "custom") return customResults.get(scopeCacheKey(scope)) || null;
    const key = planCacheKey(scenarioId, scope);
    if (!scenarioCache.has(key)) {
      const preset = presets.get(scenarioId);
      if (!preset) return null;
      scenarioCache.set(key, scenario.calculate(engineInputForScope(scope), preset.parameters, data.input_controls));
    }
    return scenarioCache.get(key);
  }

  function activePlan() {
    if (activeScenarioId === "custom") {
      return customResults.get(scopeCacheKey()) || planFor("default", scenarioScope());
    }
    return planFor(activeScenarioId, scenarioScope());
  }

  function scopeTierTotals(scope = scenarioScope()) {
    return engineInputForScope(scope).zones.reduce((totals, zone) => {
      zone.engine_input.targets.forEach((target) => { totals[target.priority_tier] += 1; });
      return totals;
    }, { P1: 0, P2: 0 });
  }

  function activeScenarioLabel() {
    if (activeScenarioId === "custom") return "사용자 입력안";
    return presets.get(activeScenarioId)?.label || "운영안";
  }

  function scopedPlanLabel() {
    if (isFullProvinceScope(scenarioScope())) return activeScenarioLabel();
    return `${activeScenarioLabel()}·선택 시·군 재배정`;
  }

  function activeCycleDays() {
    return activePlan()?.parameters?.service_cycle_days ?? data.route.engine_input.service_cycle_days;
  }

  function visibleRoutes(plan) {
    if (!plan?.routes) return [];
    const day = byId("route-day-filter").value;
    return plan.routes.filter((route) => (isAllZonesSelected() || selectedZones.has(route.service_zone)) && (day === "all" || String(route.cycle_day) === day));
  }

  function routeGeometry(route) {
    const signature = `${route.service_zone}|${route.stops.join(",")}`;
    if (routePathCache.has(signature)) return routePathCache.get(signature);
    const engine = zoneEngines.get(route.service_zone);
    const sequence = [engine.start_node_id, ...route.stops, engine.end_node_id];
    const legs = [];
    const coordinates = [];
    for (let index = 0; index < sequence.length - 1; index += 1) {
      const leg = routeLegs.get(`${route.service_zone}|${sequence[index]}|${sequence[index + 1]}`);
      if (!leg) continue;
      legs.push(leg);
      coordinates.push(...(coordinates.length ? leg.path.slice(1) : leg.path));
    }
    const geometry = { d: pathFromLine(coordinates), legs };
    routePathCache.set(signature, geometry);
    return geometry;
  }

  function addArrowMarkers(svg, routes) {
    const defs = svgElement("defs");
    [...new Set(routes.map((route) => route.vehicle_id))].forEach((vehicle) => {
      const marker = svgElement("marker", { id: `arrow-${vehicle}`, viewBox: "0 0 8 8", refX: 7, refY: 4, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse", markerUnits: "userSpaceOnUse" });
      marker.appendChild(svgElement("path", { d: "M0,0 L8,4 L0,8 Z", fill: vehicleColor(vehicle) }));
      defs.appendChild(marker);
    });
    svg.appendChild(defs);
  }

  function renderBoundaries(svg) {
    const overview = isOverview();
    for (const feature of mapData.boundaries) {
      const admin = adminByCode.get(feature.code);
      const state = overview || isAllZonesSelected() ? "" : selectedZones.has(feature.service_zone) ? " zone-active" : " zone-muted";
      const path = svgElement("path", {
        d: boundaryPathCache.get(feature.code),
        class: `admin-boundary${state}`,
        "fill-rule": "evenodd",
      }, `${feature.service_zone} ${feature.name} 행정경계`);
      if (overview && admin) {
        const color = distanceFill(admin.road_km);
        path.style.fill = color;
        path.style.fillOpacity = "0.45";
        path.style.stroke = color;
        path.style.strokeOpacity = "0.7";
      }
      svg.appendChild(path);
    }
  }

  function selectedOutletTypes() {
    return new Set(
      [...document.querySelectorAll("input[name='outlet-type']:checked")].map((input) => input.value),
    );
  }

  function syncOutletLegendState() {
    const on = Boolean(byId("outlet-layer")?.checked);
    document.querySelectorAll("input[name='outlet-type']").forEach((input) => {
      input.disabled = !on;
    });
    document.querySelector(".outlet-type-list")?.classList.toggle("is-inert", !on);
  }

  function setupOutletLegend() {
    const master = byId("outlet-layer");
    if (!master) return;
    master.addEventListener("change", () => {
      syncOutletLegendState();
      if (isOverview()) drawMap();
    });
    document.querySelectorAll("input[name='outlet-type']").forEach((input) => {
      input.addEventListener("change", () => { if (isOverview()) drawMap(); });
    });
    syncOutletLegendState();
  }

  function renderOutlets(svg) {
    if (!byId("outlet-layer")?.checked) return;
    const visible = selectedOutletTypes();
    const ordered = [...(data.outlets || [])].sort(
      (left, right) => outletTypes.indexOf(left.type) - outletTypes.indexOf(right.type),
    );
    for (const outlet of ordered) {
      if (!visible.has(outlet.type)) continue;
      const [x, y] = project(outlet);
      svg.appendChild(svgElement("circle", {
        cx: x.toFixed(2),
        cy: y.toFixed(2),
        r: outletRadius,
        class: "outlet-dot",
        fill: outletColors[outlet.type] || "#64748b",
      }, `${outlet.type} ${outlet.name || ""}`.trim()));
    }
  }

  function renderRoads(svg) {
    if (!byId("layer-roads").checked) return;
    for (const roadClass of ["secondary", "primary", "trunk", "motorway"]) {
      if (!roadPathCache[roadClass]) continue;
      svg.appendChild(svgElement("path", { d: roadPathCache[roadClass], class: `road ${roadClass}` }, `OSM ${roadClass} 도로`));
    }
  }

  function siteFor(zoneId, nodeId) {
    const engine = zoneEngines.get(zoneId);
    const candidate = engine.candidates.find((row) => row.candidate_id === nodeId);
    if (candidate) return candidate;
    const depots = data.route.depots_by_zone[zoneId];
    if (depots.start.node_id === nodeId) return depots.start;
    if (depots.end.node_id === nodeId) return depots.end;
    return null;
  }

  function renderRouteLayers(svg, routes) {
    const showRoutes = byId("layer-routes").checked;
    const showNodes = byId("layer-nodes").checked;
    const nodeCoordinates = new Map();
    const shownDepots = new Set();
    const depotMarks = [];
    const stopCircles = [];
    const stopLabels = [];
    if (showRoutes) addArrowMarkers(svg, routes);

    for (const route of routes) {
      const geometry = routeGeometry(route);
      const color = vehicleColor(route.vehicle_id);
      if (showRoutes && geometry.d) {
        svg.appendChild(svgElement("path", { d: geometry.d, class: "route-casing" }));
        const line = svgElement("path", {
          d: geometry.d,
          class: "route-line",
          stroke: color,
          "stroke-dasharray": vehicleDash(route.vehicle_id),
          "marker-end": `url(#arrow-${route.vehicle_id})`,
          tabindex: 0,
        }, `${route.cycle_day}일차 ${route.vehicle_id.replace("vehicle-", "차량 ")} · ${route.service_zone} · ${route.stops.length}곳 · ${route.travel_km.toFixed(1)}km`);
        svg.appendChild(line);
      }
      if (showNodes) {
        geometry.legs.forEach((leg) => leg.node_sample.forEach((coordinate) => nodeCoordinates.set(coordinate.join(","), coordinate)));
      }
      if (!showRoutes) continue;
      route.stops.forEach((candidateId, index) => {
        const site = siteFor(route.service_zone, candidateId);
        if (!site) return;
        const [x, y] = project(site);
        stopCircles.push(svgElement("circle", { cx: x.toFixed(2), cy: y.toFixed(2), r: 4.1, class: "route-stop", stroke: color }, `${route.service_zone} ${site.name} · ${index + 1}번째 방문`));
        const label = svgElement("text", { x: x.toFixed(2), y: y.toFixed(2), class: "route-stop-label", fill: color });
        label.textContent = String(index + 1);
        stopLabels.push(label);
      });
      const depot = data.route.depots_by_zone[route.service_zone].start;
      const depotKey = `${route.service_zone}|${depot.node_id}`;
      if (!shownDepots.has(depotKey)) {
        shownDepots.add(depotKey);
        const [x, y] = project(depot);
        depotMarks.push(svgElement("rect", { x: (x - 3.7).toFixed(2), y: (y - 3.7).toFixed(2), width: 7.4, height: 7.4, rx: 1, class: "depot" }, `${route.service_zone} 출발·복귀 후보 · ${depot.name}`));
      }
    }

    const allNodes = [...nodeCoordinates.values()];
    const maximum = 2500;
    const displayedNodes = allNodes.length <= maximum ? allNodes : Array.from({ length: maximum }, (_, index) => allNodes[Math.round(index * (allNodes.length - 1) / (maximum - 1))]);
    displayedNodes.forEach((coordinate) => {
      const [x, y] = projectCoordinate(coordinate);
      svg.appendChild(svgElement("circle", { cx: x.toFixed(2), cy: y.toFixed(2), r: .72, class: "route-node" }));
    });
    depotMarks.forEach((node) => svg.appendChild(node));
    stopCircles.forEach((node) => svg.appendChild(node));
    stopLabels.forEach((node) => svg.appendChild(node));
    return { uniqueNodeCount: allNodes.length, displayedNodeCount: displayedNodes.length };
  }

  function renderZoneLabels(svg) {
    if (!byId("layer-labels").checked) return;
    mapData.zone_labels.filter((row) => isAllZonesSelected() || selectedZones.has(row.zone_id)).forEach((row) => {
      const [x, y] = project(row);
      const label = svgElement("text", { x: x.toFixed(2), y: y.toFixed(2), class: "zone-label" });
      label.textContent = row.zone_id;
      svg.appendChild(label);
    });
  }

  function pointTitle(row, sizeKey) {
    const definition = sizeDefinitions[sizeKey];
    return `${row.service_zone} ${row.dong} · ${distanceModeLabel()} ${distanceOf(row).toFixed(2)}km · ${definition.label} ${formatSizeValue(sizeKey, definition.value(row))}`;
  }

  function renderAdminPoints(svg, metric, sizeKey) {
    const visible = filteredAdmins().map((row) => ({ row, radius: pointRadius(row, sizeKey) })).sort((left, right) => right.radius - left.radius);
    for (const { row, radius } of visible) {
      const [x, y] = project(row);
      const point = svgElement("circle", {
        cx: x.toFixed(2), cy: y.toFixed(2), r: radius.toFixed(2), fill: pointColor(row, metric),
        "fill-opacity": analysisPointScale().opacity,
        class: `point${row.code === selectedCode ? " sel" : ""}`,
        tabindex: 0, role: "button", "aria-label": pointTitle(row, sizeKey),
      }, pointTitle(row, sizeKey));
      point.addEventListener("click", () => selectAdmin(row.code));
      point.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") selectAdmin(row.code); });
      svg.appendChild(point);
    }
  }

  function renderOrnaments(svg) {
    const north = svgElement("g", { "aria-hidden": "true" });
    north.appendChild(svgElement("path", { d: "M683,18 L677,34 L683,31 L689,34 Z", fill: "#102a43" }));
    const northLabel = svgElement("text", { x: 683, y: 15, class: "map-ornament", "text-anchor": "middle" });
    northLabel.textContent = "N";
    north.appendChild(northLabel);
    svg.appendChild(north);

    const length25km = 25 / 111.32 * mapScale;
    svg.appendChild(svgElement("line", { x1: 28, y1: 492, x2: (28 + length25km).toFixed(2), y2: 492, stroke: "#102a43", "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
    const scaleLabel = svgElement("text", { x: (28 + length25km / 2).toFixed(2), y: 486, class: "map-ornament", "text-anchor": "middle" });
    scaleLabel.textContent = "약 25 km";
    svg.appendChild(scaleLabel);
  }

  function applyViewBox() {
    byId("map").setAttribute("viewBox", `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`);
  }

  function updateMapAria() {
    const svg = byId("map");
    svg.setAttribute("role", isOverview() ? "img" : "group");
    if (isOverview()) {
      svg.setAttribute("aria-label", byId("outlet-layer")?.checked
        ? "전북 243개 행정동 대표점 도로거리 색상과 선택한 금융 접점 지도"
        : "전북 243개 행정동 대표점 도로거리 색상 지도");
      return;
    }
    const layers = ["행정경계"];
    if (byId("layer-roads").checked) layers.push("도로망");
    if (byId("layer-routes").checked) layers.push("순회경로");
    layers.push("243개 행정동 분석점");
    svg.setAttribute("aria-label", `전북 ${layers.join("·")} 지도`);
  }

  function drawMap() {
    const svg = byId("map");
    const metric = byId("metric-filter").value;
    const sizeKey = byId("size-filter").value;
    const routes = isOverview() ? [] : visibleRoutes(activePlan());
    byId("dist-toggle").hidden = isOverview() || metric !== "distance";
    svg.replaceChildren();
    renderBoundaries(svg);
    if (isOverview()) {
      renderOutlets(svg);
      applyViewBox();
      updateMapAria();
      return;
    }
    renderRoads(svg);
    renderAdminPoints(svg, metric, sizeKey);
    renderZoneLabels(svg);
    const nodeStats = renderRouteLayers(svg, routes) || { uniqueNodeCount: 0, displayedNodeCount: 0 };
    renderOrnaments(svg);
    applyViewBox();
    drawLegend(metric, sizeKey, routes);
    updateMapAria();
    const dayLabel = byId("route-day-filter").value === "all" ? "운영주기 전체" : `${byId("route-day-filter").value}일차`;
    const nodeText = byId("layer-nodes").checked ? ` · 도로노드 ${format.format(nodeStats.displayedNodeCount)}개 표시${nodeStats.uniqueNodeCount > nodeStats.displayedNodeCount ? `/${format.format(nodeStats.uniqueNodeCount)}개 표본` : ""}` : "";
    byId("route-summary").textContent = `${scopedPlanLabel()} · ${dayLabel} · 경로 ${routes.length}개${nodeText}`;
  }

  function renderAdminDetail(row) {
    const visit = visitStatus(row);
    byId("detail").innerHTML = `<h3>${row.service_zone} ${row.dong} <span class="badge ${row.priority.toLowerCase()}">${priorityLabels[row.priority]}</span></h3><div class="stat"><span>도로거리</span><b>${row.road_km.toFixed(2)} km</b></div><div class="stat"><span>직선거리</span><b>${row.line_km.toFixed(2)} km</b></div><div class="stat"><span>최근접 금융접점</span><b>${row.nearest_name} · ${row.nearest_type}</b></div><div class="stat"><span>65세 이상</span><b>${format.format(row.pop_65plus)}명 · ${row.ratio_65plus.toFixed(1)}%</b></div><div class="stat"><span>3km 내 접점</span><b>${format.format(row.cnt_3km)}곳</b></div><div class="stat"><span>취약유형</span><b>${row.cluster_label || row.rule_type || "도시 비교집단"}</b></div><div class="stat"><span>도로 품질</span><b>${row.road_distance_primary === "Y" ? "주 지표" : `품질유보 · ${row.route_quality}`}</b></div><div class="detail-note"><b>운영주기 방문</b> (주기 ${format.format(activeCycleDays())}일) · ${visit.label}<br>${visit.note}</div>`;
  }

  function selectAdmin(code, options = {}) {
    selectedCode = code;
    const row = data.admins.find((item) => item.code === code);
    if (!row) return;
    renderAdminDetail(row);
    document.querySelectorAll("#access-rows tr").forEach((element) => element.classList.toggle("sel", element.dataset.code === code));
    drawMap();
    if (options.pan && !isOverview()) panToAdmin(row);
  }

  function renderRank() {
    const rows = rankedAdmins();
    const pages = Math.max(1, Math.ceil(rows.length / tablePageSize));
    tablePage = Math.min(Math.max(1, tablePage), pages);
    const start = (tablePage - 1) * tablePageSize;
    const pageRows = rows.slice(start, start + tablePageSize);
    byId("access-count").textContent = format.format(rows.length);
    byId("access-rows").innerHTML = pageRows.map((row, index) => {
      const visit = visitStatus(row);
      const kmClass = row.road_km > 5 ? "km-hot" : row.road_km > 3 ? "km-warm" : "";
      return `<tr data-code="${row.code}" class="${row.code === selectedCode ? "sel" : ""}" tabindex="0"><td>${start + index + 1}</td><td>${row.service_zone}</td><td>${row.dong}</td><td class="${kmClass}">${row.road_km.toFixed(2)} km</td><td>${format.format(row.cnt_3km)}곳</td><td>${format.format(row.pop_65plus)}명</td><td>${row.ratio_65plus.toFixed(1)}%</td><td>${row.cluster_label || row.rule_type || "도시 비교집단"}</td><td><span class="badge ${row.priority.toLowerCase()}">${priorityLabels[row.priority]}</span></td><td><span class="badge ${visit.cls}">${visit.label}</span></td><td>${row.road_distance_primary === "Y" ? "-" : "품질유보"}</td></tr>`;
    }).join("");
    document.querySelectorAll("#access-rows tr").forEach((element) => {
      element.addEventListener("click", () => selectAdmin(element.dataset.code, { pan: true }));
      element.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectAdmin(element.dataset.code, { pan: true });
        }
      });
    });
    const pager = byId("access-pager");
    const buttons = [];
    for (let page = 1; page <= pages; page += 1) {
      if (pages > 9 && page > 2 && page < pages - 1 && Math.abs(page - tablePage) > 1) {
        if (buttons[buttons.length - 1] !== "…") buttons.push("…");
        continue;
      }
      buttons.push(page);
    }
    pager.innerHTML = buttons.map((page) => (page === "…"
      ? "<span>…</span>"
      : `<button type="button" data-page="${page}" ${page === tablePage ? "aria-current='page'" : ""}>${page}</button>`)).join("");
    pager.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        tablePage = Number(button.dataset.page);
        renderRank();
      });
    });
    if (!rows.some((row) => row.code === selectedCode)) selectedCode = rows[0]?.code || null;
    if (selectedCode) { selectAdmin(selectedCode); } else {
      byId("detail").innerHTML = "<p class=\"detail-empty\">시·군을 선택하면 행정동 상세가 표시됩니다.</p>";
      drawMap();
    }
  }

  function clampViewBox() {
    viewBox.width = Math.max(150, Math.min(mapWidth, viewBox.width));
    viewBox.height = viewBox.width * mapHeight / mapWidth;
    if (viewBox.height > mapHeight) { viewBox.height = mapHeight; viewBox.width = viewBox.height * mapWidth / mapHeight; }
    viewBox.x = Math.max(0, Math.min(mapWidth - viewBox.width, viewBox.x));
    viewBox.y = Math.max(0, Math.min(mapHeight - viewBox.height, viewBox.y));
  }

  function cancelViewBoxAnimation() {
    if (viewBoxAnimation) {
      cancelAnimationFrame(viewBoxAnimation);
      viewBoxAnimation = null;
    }
  }

  function setViewBox(next) {
    cancelViewBoxAnimation();
    viewBox = { ...next };
    clampViewBox();
    applyViewBox();
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function animateViewBox(next, duration = 320) {
    clampBox(next);
    if (prefersReducedMotion() || duration <= 0) {
      setViewBox(next);
      return;
    }
    const from = { ...viewBox };
    cancelViewBoxAnimation();
    const start = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      viewBox = {
        x: from.x + (next.x - from.x) * eased,
        y: from.y + (next.y - from.y) * eased,
        width: from.width + (next.width - from.width) * eased,
        height: from.height + (next.height - from.height) * eased,
      };
      applyViewBox();
      if (t < 1) {
        viewBoxAnimation = requestAnimationFrame(tick);
        return;
      }
      viewBox = { ...next };
      clampViewBox();
      applyViewBox();
      viewBoxAnimation = null;
    };
    viewBoxAnimation = requestAnimationFrame(tick);
  }

  function clampBox(box) {
    const saved = viewBox;
    viewBox = box;
    clampViewBox();
    Object.assign(box, viewBox);
    viewBox = saved;
    return box;
  }

  function computeZonesViewBox(zoneIds) {
    const ids = Array.isArray(zoneIds) ? zoneIds.filter(Boolean) : zoneIds ? [zoneIds] : [];
    if (!ids.length || ids.length === allZoneIds.length) return { x: 0, y: 0, width: mapWidth, height: mapHeight };
    const cacheKey = [...ids].sort().join("|");
    if (zoneViewBoxCache.has(cacheKey)) return { ...zoneViewBoxCache.get(cacheKey) };
    const wanted = new Set(ids);
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const feature of mapData.boundaries) {
      if (!wanted.has(feature.service_zone)) continue;
      for (const polygon of feature.polygons) {
        for (const ring of polygon) {
          for (const coordinate of ring) {
            const [x, y] = projectCoordinate(coordinate);
            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, x);
            maxY = Math.max(maxY, y);
          }
        }
      }
    }
    if (!Number.isFinite(minX)) return { x: 0, y: 0, width: mapWidth, height: mapHeight };
    const width = Math.max(24, maxX - minX);
    const height = Math.max(24, maxY - minY);
    let boxW = width * 1.24;
    let boxH = height * 1.24;
    const aspect = mapWidth / mapHeight;
    if (boxW / boxH > aspect) boxH = boxW / aspect;
    else boxW = boxH * aspect;
    const box = clampBox({
      x: (minX + maxX) / 2 - boxW / 2,
      y: (minY + maxY) / 2 - boxH / 2,
      width: boxW,
      height: boxH,
    });
    zoneViewBoxCache.set(cacheKey, { ...box });
    return { ...box };
  }

  function fitSelectedZonesViewBox() {
    if (isAllZonesSelected() || selectedZones.size === 0) {
      setViewBox({ x: 0, y: 0, width: mapWidth, height: mapHeight });
      return;
    }
    setViewBox(computeZonesViewBox(selectedZoneList()));
  }

  function viewBoxCenteredOn(x, y, width, height) {
    return clampBox({
      x: x - width / 2,
      y: y - height / 2,
      width,
      height,
    });
  }

  function panToAdmin(row) {
    const [x, y] = project(row);
    if (isAllZonesSelected()) {
      const width = Math.min(mapWidth, Math.max(220, viewBox.width * 0.55));
      animateViewBox(viewBoxCenteredOn(x, y, width, width * mapHeight / mapWidth));
      return;
    }
    animateViewBox(viewBoxCenteredOn(x, y, viewBox.width, viewBox.height));
  }

  function zoomMap(factor, anchorX = viewBox.x + viewBox.width / 2, anchorY = viewBox.y + viewBox.height / 2) {
    cancelViewBoxAnimation();
    const ratioX = (anchorX - viewBox.x) / viewBox.width;
    const ratioY = (anchorY - viewBox.y) / viewBox.height;
    viewBox.width *= factor;
    viewBox.height *= factor;
    viewBox.x = anchorX - ratioX * viewBox.width;
    viewBox.y = anchorY - ratioY * viewBox.height;
    clampViewBox();
    applyViewBox();
  }

  function zoneComboMarkup() {
    return `<label class="zone-option zone-option-all"><input type="checkbox" data-zone-all checked> 전북 전체</label>${allZoneIds.map((zoneId) => `<label class="zone-option"><input type="checkbox" data-zone-id="${zoneId}" checked> ${zoneId}</label>`).join("")}`;
  }

  function closeZoneCombos() {
    document.querySelectorAll(".zone-combo-panel").forEach((panel) => { panel.hidden = true; });
    document.querySelectorAll(".zone-combo-button").forEach((button) => button.setAttribute("aria-expanded", "false"));
  }

  function zoneSummaryLabel() {
    if (selectedZones.size === 0) return "시·군 선택";
    if (isAllZonesSelected()) return "전북 전체";
    const selected = selectedZoneList();
    if (selected.length === 1) return selected[0];
    return `${selected[0]} 외 ${selected.length - 1}곳`;
  }

  function paintZoneCombos() {
    const allOn = isAllZonesSelected();
    const summary = zoneSummaryLabel();
    document.querySelectorAll(".zone-combo-button").forEach((button) => { button.textContent = summary; });
    document.querySelectorAll("[data-zone-all]").forEach((input) => { input.checked = allOn; });
    document.querySelectorAll("[data-zone-id]").forEach((input) => {
      input.checked = selectedZones.has(input.getAttribute("data-zone-id"));
    });
  }

  function applyZoneSelection() {
    tablePage = 1;
    paintZoneCombos();
    if (!isOverview()) fitSelectedZonesViewBox();
    renderScenarios(activeScenarioId);
  }

  function onZoneComboChange(event) {
    const input = event.target;
    if (!(input instanceof HTMLInputElement) || input.type !== "checkbox") return;
    if (syncingZone) return;
    if (input.hasAttribute("data-zone-all")) {
      selectedZones.clear();
      if (input.checked) allZoneIds.forEach((zoneId) => selectedZones.add(zoneId));
    } else {
      const zoneId = input.getAttribute("data-zone-id");
      if (input.checked) selectedZones.add(zoneId);
      else selectedZones.delete(zoneId);
    }
    syncingZone = true;
    applyZoneSelection();
    syncingZone = false;
  }

  function setupZoneCombos() {
    byId("zone-filter-panel").innerHTML = zoneComboMarkup();
    byId("scenario-zone-filter-panel").innerHTML = zoneComboMarkup();
    paintZoneCombos();
    byId("zone-filter-panel").addEventListener("change", onZoneComboChange);
    byId("scenario-zone-filter-panel").addEventListener("change", onZoneComboChange);
    [["zone-filter-button", "zone-filter-panel"], ["scenario-zone-filter-button", "scenario-zone-filter-panel"]].forEach(([buttonId, panelId]) => {
      byId(buttonId).addEventListener("click", () => {
        const panel = byId(panelId);
        const willOpen = panel.hidden;
        closeZoneCombos();
        if (!willOpen) return;
        panel.hidden = false;
        byId(buttonId).setAttribute("aria-expanded", "true");
      });
    });
    document.addEventListener("pointerdown", (event) => {
      if (!event.target.closest(".zone-combo")) closeZoneCombos();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const open = document.querySelector(".zone-combo-panel:not([hidden])");
      if (!open) return;
      const button = open.parentElement.querySelector(".zone-combo-button");
      closeZoneCombos();
      button?.focus();
    });
  }

  function eventCoordinate(event) {
    const rect = byId("map").getBoundingClientRect();
    return [
      viewBox.x + (event.clientX - rect.left) / rect.width * viewBox.width,
      viewBox.y + (event.clientY - rect.top) / rect.height * viewBox.height,
    ];
  }

  function setupMapControls() {
    setupZoneCombos();
    byId("metric-filter").addEventListener("change", drawMap);
    byId("size-filter").addEventListener("change", () => {
      const row = data.admins.find((item) => item.code === selectedCode);
      if (row) renderAdminDetail(row);
      drawMap();
    });
    ["layer-roads", "layer-routes", "layer-nodes", "layer-labels"].forEach((id) => byId(id).addEventListener("change", drawMap));
    byId("route-day-filter").addEventListener("change", drawMap);
    byId("reset-filters").addEventListener("click", resetAnalysisFilters);
    byId("download-access").addEventListener("click", downloadAccessCsv);
    byId("download-table").addEventListener("click", downloadAccessCsv);
    byId("zoom-in").addEventListener("click", () => zoomMap(.78));
    byId("zoom-out").addEventListener("click", () => zoomMap(1.28));
    byId("dist-toggle").querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        if (distanceMode === button.dataset.mode) return;
        distanceMode = button.dataset.mode;
        byId("dist-toggle").querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", item.dataset.mode === distanceMode ? "true" : "false");
        });
        if (selectedCode) selectAdmin(selectedCode); else drawMap();
      });
    });
    const svg = byId("map");
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const [x, y] = eventCoordinate(event);
      zoomMap(event.deltaY < 0 ? .82 : 1.22, x, y);
    }, { passive: false });
    svg.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      cancelViewBoxAnimation();
      dragState = { clientX: event.clientX, clientY: event.clientY, viewX: viewBox.x, viewY: viewBox.y };
      svg.setPointerCapture(event.pointerId);
      svg.classList.add("dragging");
    });
    svg.addEventListener("pointermove", (event) => {
      if (!dragState) return;
      const rect = svg.getBoundingClientRect();
      viewBox.x = dragState.viewX - (event.clientX - dragState.clientX) / rect.width * viewBox.width;
      viewBox.y = dragState.viewY - (event.clientY - dragState.clientY) / rect.height * viewBox.height;
      clampViewBox();
      applyViewBox();
    });
    const stopDrag = () => { dragState = null; svg.classList.remove("dragging"); };
    svg.addEventListener("pointerup", stopDrag);
    svg.addEventListener("pointercancel", stopDrag);
    selectedCode = [...data.admins].sort((left, right) => right.road_km - left.road_km)[0].code;
    renderRank();
  }

  function applyRules() {
    const controls = data.input_controls;
    const rules = {
      "vehicle-count": controls.vehicle_count,
      "operating-days": controls.operating_days_per_cycle,
      "service-minutes": controls.service_minutes,
      "max-stops": controls.max_stops_per_route,
      "service-cycle": controls.service_cycle_days,
    };
    Object.entries(rules).forEach(([id, rule]) => {
      const input = byId(id); input.min = rule.min; input.max = rule.max; input.step = rule.step;
    });
    for (const id of ["operating-start", "operating-end"]) {
      const input = byId(id); input.min = controls.operating_time.min; input.max = controls.operating_time.max; input.step = controls.operating_time.step_minutes * 60;
    }
  }

  function fillForm(parameters) {
    byId("vehicle-count").value = parameters.vehicle_count;
    byId("operating-days").value = parameters.operating_days_per_cycle;
    byId("operating-start").value = parameters.operating_start;
    byId("operating-end").value = parameters.operating_end;
    byId("service-minutes").value = parameters.service_minutes;
    byId("max-stops").value = parameters.max_stops_per_route;
    byId("service-cycle").value = parameters.service_cycle_days ?? data.route.engine_input.service_cycle_days;
  }

  function readForm() {
    return {
      vehicle_count: Number(byId("vehicle-count").value),
      operating_days_per_cycle: Number(byId("operating-days").value),
      operating_start: byId("operating-start").value,
      operating_end: byId("operating-end").value,
      service_minutes: Number(byId("service-minutes").value),
      max_stops_per_route: Number(byId("max-stops").value),
      service_cycle_days: Number(byId("service-cycle").value),
    };
  }

  function referenceScenario(preset) {
    return { id: preset.preset_id, label: preset.label, parameters: preset.parameters, ...preset.result, all_zones_allocated: preset.all_zones_allocated };
  }

  function visibleScenarios() {
    const scope = scenarioScope();
    const cacheKey = scopeCacheKey(scope);
    const rows = data.sensitivity_presets.map((preset) => {
      if (isFullProvinceScope(scope)) return referenceScenario(preset);
      const result = planFor(preset.preset_id, scope);
      return { id: preset.preset_id, label: preset.label, parameters: preset.parameters, ...result };
    });
    const custom = customResults.get(cacheKey);
    if (custom) rows.push({ id: "custom", label: "사용자 입력안", ...custom });
    return rows;
  }

  function coverageRate(row) {
    if (!row.target_count) return 0;
    return Math.round(row.covered_target_count / row.target_count * 100);
  }

  function rate(part, whole) {
    if (!whole) return 0;
    return Math.round(part / whole * 100);
  }

  function planCaption(row) {
    const vehicles = row.parameters?.vehicle_count;
    const days = row.parameters?.operating_days_per_cycle;
    if (!vehicles || !days) return row.label;
    return `${row.label} (${vehicles}대 × ${days}일)`;
  }

  function zoneDisplayName(zoneId) {
    return zoneId === "전주시" ? "전주시 (완산·덕진)" : zoneId;
  }

  function fractionCell(part, whole) {
    const cls = whole && part === whole ? " class=\"best\"" : "";
    return `<td${cls}>${format.format(part)}/${format.format(whole)} (${rate(part, whole)}%)</td>`;
  }

  function updateRouteDayOptions(plan) {
    const select = byId("route-day-filter");
    const previous = select.value;
    const days = [...new Set((plan?.routes || []).map((route) => route.cycle_day))].sort((left, right) => left - right);
    select.innerHTML = `<option value="all">운영주기 전체</option>${days.map((day) => `<option value="${day}">${day}일차</option>`).join("")}`;
    select.value = days.includes(Number(previous)) ? previous : "all";
  }

  function fairnessCopy(active, scope) {
    const capacity = active.parameters.vehicle_count * active.parameters.operating_days_per_cycle;
    if (isFullProvinceScope(scope)) {
      return active.all_zones_allocated
        ? `${active.label}: 차량×운영일 ${capacity}경로일로 14개 시·군에 최소 1회씩 배정할 수 있습니다.`
        : `${active.label}: 가용 경로일이 ${capacity}일이라 14개 시·군 모두에 최소 1회 배정할 수 없습니다. 이 결과는 우선순위가 높은 일부 시·군 집중안입니다.`;
    }
    const scopeList = (Array.isArray(scope) ? scope : [scope]).filter(Boolean);
    if (!scopeList.length) return `${active.label}: 선택된 시·군이 없어 비교할 경로대상이 없습니다. 시·군 필터에서 하나 이상을 선택해야 합니다.`;
    const labels = scopeList.join(", ");
    return `${active.label}: ${labels} 경로대상만 다시 배정합니다. 차량×운영일 ${capacity}경로일을 이 범위의 용량으로 쓰며, 전북 전체 14개 시·군 최소 배정은 적용하지 않습니다. 이 결과는 전북 전체 기본안을 대체하지 않습니다.`;
  }

  function zoneVisitCounts(plan) {
    const counts = new Map();
    for (const row of plan?.zone_allocations || []) {
      if (!row.coverage_by_tier) continue;
      counts.set(row.zone_id, {
        P1: row.coverage_by_tier.P1 || 0,
        P2: row.coverage_by_tier.P2 || 0,
      });
    }
    if (counts.size) return counts;
    for (const [zoneId, ids] of servedTargetIds(plan)) {
      const rec = { P1: 0, P2: 0 };
      for (const id of ids) {
        const admin = adminByCode.get(id);
        if (admin?.priority === "P1") rec.P1 += 1;
        if (admin?.priority === "P2") rec.P2 += 1;
      }
      counts.set(zoneId, rec);
    }
    return counts;
  }

  function zoneTableMarkup(rows, visits, totals) {
    return `<table class="zone-table"><thead><tr><th>시·군</th><th>경로일</th><th>P1 방문 (${format.format(totals.P1)})</th><th>P2 방문 (${format.format(totals.P2)})</th></tr></thead><tbody>${rows.map((row) => {
      const visit = visits.get(row.zone_id) || { P1: 0, P2: 0 };
      return `<tr><td>${zoneDisplayName(row.zone_id)}</td><td>${row.allocated_route_days}일</td><td>${visit.P1}</td><td>${visit.P2}</td></tr>`;
    }).join("")}</tbody></table>`;
  }

  function syncPlanChips() {
    const customBtn = byId("plan-chips").querySelector("[data-preset='custom']");
    if (customBtn) customBtn.hidden = activeScenarioId !== "custom" && !customResults.get(scopeCacheKey());
    byId("plan-chips").querySelectorAll("[data-preset]").forEach((button) => {
      button.setAttribute("aria-current", button.dataset.preset === activeScenarioId ? "true" : "false");
    });
  }

  function renderScenarios(activeId) {
    const scope = scenarioScope();
    const scopeTotals = scopeTierTotals(scope);
    activeScenarioId = activeId === "custom" ? (customResults.has(scopeCacheKey(scope)) ? "custom" : "default") : activeId;
    if (activeId === "custom" && activeScenarioId !== "custom") {
      byId("preset-select").value = activeScenarioId;
      fillForm(presets.get(activeScenarioId).parameters);
    }
    const rows = visibleScenarios();
    const zoneCount = isFullProvinceScope(scope) ? data.scope.analysis_service_zone_count : (Array.isArray(scope) ? scope.length : 1);
    const allocationLabel = `${format.format(zoneCount)}개 시·군 최소 1회 배정`;
    const speed = data.route.travel_model.uniform_speed_kmh;
    byId("coverage-bars").innerHTML = rows.map((row) => {
      const pct = coverageRate(row);
      const best = row.covered_target_count === row.target_count;
      return `<button type="button" class="compare-card${best ? " best-card" : ""}" data-scenario="${row.id}" aria-current="${row.id === activeScenarioId ? "true" : "false"}"><div class="lbl">${planCaption(row)}</div><div class="val">${format.format(row.covered_target_count)} / ${format.format(row.target_count)}곳</div><div class="pct">${pct}%</div><div class="track"><div class="fill" style="width:${pct}%"></div></div></button>`;
    }).join("");
    const allocCell = (row) => (zoneCount === 0
      ? "<td>—</td>"
      : `<td class="${row.all_zones_allocated ? "alloc-yes" : "alloc-no"}">${row.all_zones_allocated ? "가능" : "불가"}</td>`);
    byId("scenario-table").innerHTML = `<thead><tr><th>지표</th>${rows.map((row) => `<th>${planCaption(row)}</th>`).join("")}</tr></thead><tbody><tr><td>차량 × 운영일</td>${rows.map((row) => `<td>${row.parameters ? `${row.parameters.vehicle_count}대 × ${row.parameters.operating_days_per_cycle}일` : "—"}</td>`).join("")}</tr><tr><td>서비스시간 (분)</td>${rows.map((row) => `<td>${row.parameters ? row.parameters.service_minutes : "—"}</td>`).join("")}</tr><tr><td>전체 방문 대상 (${format.format(scopeTotals.P1 + scopeTotals.P2)}개 기준)</td>${rows.map((row) => fractionCell(row.covered_target_count, row.target_count)).join("")}</tr><tr><td>P1 방문 (${format.format(scopeTotals.P1)}개) · 접근성 취약</td>${rows.map((row) => fractionCell(row.coverage_by_tier.P1, scopeTotals.P1)).join("")}</tr><tr><td>P2 방문 (${format.format(scopeTotals.P2)}개) · 기타</td>${rows.map((row) => fractionCell(row.coverage_by_tier.P2, scopeTotals.P2)).join("")}</tr><tr><td>경로일 (총)</td>${rows.map((row) => `<td>${format.format(row.route_days_used)}일</td>`).join("")}</tr><tr><td>이동거리 (추정, km)</td>${rows.map((row) => `<td>${format.format(Math.round(row.totals.travel_km))} km</td>`).join("")}</tr><tr><td>추정 이동시간*</td>${rows.map((row) => `<td>${formatDuration(row.totals.travel_minutes)}</td>`).join("")}</tr><tr><td>${allocationLabel}</td>${rows.map(allocCell).join("")}</tr></tbody>`;
    byId("scenario-note").textContent = `*추정 이동시간 = OSM 최단거리 ÷ ${speed}km/h 가정값입니다. 실제 교통시간을 반영하지 않습니다.`;
    const active = rows.find((row) => row.id === activeScenarioId) || rows[1];
    byId("fairness-warning").textContent = `${fairnessCopy(active, scope)} 차고지·장소 승인·시간창·서비스 시간·차량 재배치는 운영 가정값이며 미확정 상태입니다. 운영 확정 전에는 시연용 결과로만 활용해야 합니다.`;
    const livePlan = active.id === "custom" ? active : (planFor(active.id, scope) || active);
    const zoneRows = livePlan.zone_allocations || active.zone_allocations || [];
    const visits = zoneVisitCounts(livePlan);
    const mid = Math.ceil(zoneRows.length / 2);
    const totalDays = zoneRows.reduce((sum, row) => sum + (row.allocated_route_days || 0), 0);
    const totalP1 = zoneRows.reduce((sum, row) => sum + (visits.get(row.zone_id)?.P1 || 0), 0);
    const totalP2 = zoneRows.reduce((sum, row) => sum + (visits.get(row.zone_id)?.P2 || 0), 0);
    byId("zone-title").textContent = `${format.format(zoneCount)}개 시·군 경로일 배정 결과`;
    byId("zone-plan-label").textContent = active ? `${active.label} 기준 · 총 ${format.format(active.route_days_used)}경로일` : "";
    byId("zone-legend").innerHTML = `<span><i class="p1-dot"></i>P1: 접근성 취약 (${format.format(scopeTotals.P1)}개)</span><span><i class="p2-dot"></i>P2: 기타 (${format.format(scopeTotals.P2)}개)</span>`;
    byId("zone-list").innerHTML = `${zoneTableMarkup(zoneRows.slice(0, mid), visits, scopeTotals)}${zoneTableMarkup(zoneRows.slice(mid), visits, scopeTotals)}`;
    byId("zone-total").innerHTML = `<span>합계</span><span class="days">${format.format(totalDays)}일</span><span class="p1">P1 ${format.format(totalP1)}</span><span class="p2">P2 ${format.format(totalP2)}</span>`;
    byId("deferred-chip").textContent = `${format.format(data.scope.route_quality_deferred_count)}개`;
    byId("status-chip").textContent = data.status;
    byId("ready-chip").textContent = String(data.operational_ready);
    syncPlanChips();
    updateRouteDayOptions(activePlan());
    if (isFullProvinceScope(scope)) renderOverview(planFor("default", scope));
    if (!isOverview()) renderRank();
    else drawMap();
  }

  function setupScenarioControls() {
    applyRules();
    byId("plan-chips").innerHTML = `${data.sensitivity_presets.map((row) => `<button type="button" data-preset="${row.preset_id}">${row.label}</button>`).join("")}<button type="button" data-preset="custom" hidden>사용자 입력안</button>`;
    byId("preset-select").insertAdjacentHTML("beforeend", data.sensitivity_presets.map((row) => `<option value="${row.preset_id}">${row.label} · ${row.parameters.vehicle_count}대</option>`).join(""));
    const defaultPreset = presets.get("default"); fillForm(defaultPreset.parameters); byId("preset-select").value = "default";
    const activatePreset = (id) => {
      byId("preset-select").value = id;
      byId("form-error").classList.remove("show");
      if (id !== "custom") fillForm(presets.get(id).parameters);
      renderScenarios(id);
    };
    byId("plan-chips").addEventListener("click", (event) => {
      const button = event.target.closest("[data-preset]");
      if (button) activatePreset(button.dataset.preset);
    });
    byId("coverage-bars").addEventListener("click", (event) => {
      const card = event.target.closest("[data-scenario]");
      if (card) activatePreset(card.dataset.scenario);
    });
    byId("preset-select").addEventListener("change", (event) => activatePreset(event.target.value === "custom" ? "custom" : event.target.value));
    byId("reset-inputs").addEventListener("click", () => activatePreset("default"));
    document.querySelectorAll("#scenario-form input").forEach((input) => input.addEventListener("input", () => { byId("preset-select").value = "custom"; }));
    document.querySelectorAll("[data-step-for]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = byId(button.getAttribute("data-step-for"));
        const delta = Number(input.step || 1) * Number(button.dataset.step);
        const next = Number(input.value) + delta;
        input.value = String(Math.min(Number(input.max), Math.max(Number(input.min), next)));
        byId("preset-select").value = "custom";
      });
    });
    byId("scenario-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const button = byId("run-button"), error = byId("form-error");
      error.classList.remove("show"); button.disabled = true; button.textContent = "계산 중…";
      window.setTimeout(() => {
        try {
          customResults.set(scopeCacheKey(), scenario.calculate(engineInputForScope(), readForm(), data.input_controls));
          byId("preset-select").value = "custom"; renderScenarios("custom");
        } catch (caught) {
          error.textContent = caught.message; error.classList.add("show");
        } finally { button.disabled = false; button.textContent = "새 시나리오 계산"; }
      }, 20);
    });
    renderScenarios("default");
  }

  sourceMetrics();
  setupViewTabs();
  setupOutletLegend();
  setupMapControls();
  setupScenarioControls();
})();
