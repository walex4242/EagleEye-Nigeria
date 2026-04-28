/* ══════════════════════════════════════════════════════════════
   predictionView.js — Movement Prediction Intelligence v1.0
   
   Three integrated systems:
   1. TRAJECTORY PROJECTION  — Where are they going next?
   2. RECURRENCE HEATMAP     — Where are their base areas?
   3. STRIKE PREDICTION      — When will they strike next?

   Keyboard shortcut: P
   Integrates with: MapView, State, API, showToast
   ══════════════════════════════════════════════════════════════ */

const PredictionView = (() => {
  /* ══════════════════════════════════════════════════
     STATE
     ══════════════════════════════════════════════════ */
  let _trajectoryLayer = null; // L.layerGroup — projection cones & arrows
  let _heatmapLayer = null; // L.layerGroup — recurrence heatmap cells
  let _strikeLayer = null; // L.layerGroup — strike zone markers
  let _predictionData = null; // last computed prediction result
  let _heatmapData = null; // last computed heatmap result
  let _strikeData = null; // last computed strike result
  let _activeTab = 'trajectory';
  let _isComputing = false;

  /* ══════════════════════════════════════════════════
     INIT
     ══════════════════════════════════════════════════ */
  function init() {
    _buildPanel();
    _bindToolbarButton();
    _bindEvents();
    console.log('[PredictionView] Initialized ✓');
  }

  /* ══════════════════════════════════════════════════
     PANEL HTML
     ══════════════════════════════════════════════════ */
  function _buildPanel() {
    document.getElementById('prediction-panel')?.remove();
    document.getElementById('prediction-styles')?.remove();

    const panel = document.createElement('div');
    panel.id = 'prediction-panel';
    panel.innerHTML = `
      <div class="pred-header">
        <div class="pred-header-left">
          <span class="pred-icon">◈</span>
          <div>
            <div class="pred-title">MOVEMENT PREDICTION</div>
            <div class="pred-subtitle">Trajectory · Presence · Strike Forecast</div>
          </div>
        </div>
        <div class="pred-header-right">
          <span class="pred-live-dot"></span>
          <span class="pred-live-label" id="pred-status-label">READY</span>
          <button class="pred-close" id="pred-close-btn" title="Close (Escape)">✕</button>
        </div>
      </div>

      <!-- ── Controls strip ── -->
      <div class="pred-controls">
        <div class="pred-ctrl-group">
          <label class="pred-ctrl-label">DATA RANGE</label>
          <select id="pred-days" class="pred-select">
            <option value="3">3 days</option>
            <option value="7" selected>7 days</option>
            <option value="14">14 days</option>
            <option value="30">30 days</option>
          </select>
        </div>
        <div class="pred-ctrl-group">
          <label class="pred-ctrl-label">PROJECTION</label>
          <select id="pred-horizon" class="pred-select">
            <option value="12">12 hrs</option>
            <option value="24" selected>24 hrs</option>
            <option value="48">48 hrs</option>
            <option value="72">72 hrs</option>
          </select>
        </div>
        <div class="pred-ctrl-group">
          <label class="pred-ctrl-label">MIN CONFIDENCE</label>
          <select id="pred-min-conf" class="pred-select">
            <option value="0.5">50%</option>
            <option value="0.65" selected>65%</option>
            <option value="0.8">80%</option>
          </select>
        </div>
        <button class="pred-run-btn" id="pred-run-btn">
          <span class="pred-run-icon">▶</span>
          <span id="pred-run-label">RUN ANALYSIS</span>
        </button>
      </div>

      <!-- ── Tab bar ── -->
      <div class="pred-tabs">
        <button class="pred-tab active" data-tab="trajectory">
          <span class="pred-tab-icon">⟶</span> TRAJECTORY
        </button>
        <button class="pred-tab" data-tab="heatmap">
          <span class="pred-tab-icon">◉</span> BASE AREAS
        </button>
        <button class="pred-tab" data-tab="strike">
          <span class="pred-tab-icon">◇</span> STRIKE FORECAST
        </button>
        <button class="pred-tab" data-tab="summary">
          <span class="pred-tab-icon">≡</span> INTEL BRIEF
        </button>
      </div>

      <!-- ══ TAB: TRAJECTORY ══ -->
      <div class="pred-tab-content active" id="pred-tab-trajectory">
        <div class="pred-section-desc">
          Extrapolates movement vectors forward in time using bearing trends 
          and speed estimates. Projected paths shown as probability cones on map.
        </div>

        <div class="pred-empty" id="traj-empty">
          <div class="pred-empty-icon">⟶</div>
          <div class="pred-empty-title">No trajectory data</div>
          <div class="pred-empty-desc">Run analysis to project movement vectors</div>
        </div>

        <div id="traj-results" class="hidden">
          <div class="pred-stat-row" id="traj-stats"></div>
          <div id="traj-list"></div>
        </div>
      </div>

      <!-- ══ TAB: BASE AREAS / HEATMAP ══ -->
      <div class="pred-tab-content" id="pred-tab-heatmap">
        <div class="pred-section-desc">
          Identifies persistent activity zones from 30-day hotspot recurrence.
          Night-only clusters indicate likely base/camp locations.
        </div>

        <div class="pred-empty" id="heat-empty">
          <div class="pred-empty-icon">◉</div>
          <div class="pred-empty-title">No base area data</div>
          <div class="pred-empty-desc">Run analysis to map persistent presence zones</div>
        </div>

        <div id="heat-results" class="hidden">
          <div class="pred-stat-row" id="heat-stats"></div>
          <div id="heat-list"></div>
        </div>
      </div>

      <!-- ══ TAB: STRIKE PREDICTION ══ -->
      <div class="pred-tab-content" id="pred-tab-strike">
        <div class="pred-section-desc">
          Estimates next activation window per zone using inter-event intervals 
          and pattern-of-life analysis. Based on historical FIRMS clusters.
        </div>

        <div class="pred-empty" id="strike-empty">
          <div class="pred-empty-icon">◇</div>
          <div class="pred-empty-title">No strike forecast</div>
          <div class="pred-empty-desc">Run analysis to compute zone activation windows</div>
        </div>

        <div id="strike-results" class="hidden">
          <div class="pred-stat-row" id="strike-stats"></div>
          <div id="strike-timeline"></div>
        </div>
      </div>

      <!-- ══ TAB: INTEL BRIEF ══ -->
      <div class="pred-tab-content" id="pred-tab-summary">
        <div class="pred-empty" id="summary-empty">
          <div class="pred-empty-icon">≡</div>
          <div class="pred-empty-title">No intelligence brief</div>
          <div class="pred-empty-desc">Run analysis to generate actionable brief</div>
        </div>
        <div id="summary-content" class="hidden"></div>
      </div>

      <!-- ── Footer ── -->
      <div class="pred-footer">
        <button class="pred-ghost-btn" id="pred-clear-btn">
          ✕ Clear layers
        </button>
        <div class="pred-footer-meta" id="pred-footer-meta">—</div>
        <button class="pred-ghost-btn" id="pred-export-btn">
          ↓ Export JSON
        </button>
      </div>
    `;

    document.body.appendChild(panel);
    _injectStyles();
  }

  /* ══════════════════════════════════════════════════
     TOOLBAR BUTTON
     ══════════════════════════════════════════════════ */
  function _bindToolbarButton() {
    // Button is now rendered by StatsBar — just bind keyboard shortcut
    document.addEventListener('keydown', (e) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;
      if (e.key.toLowerCase() === 'p') togglePanel();
      if (e.key === 'Escape') closePanel();
    });
  }

  /* ══════════════════════════════════════════════════
     EVENTS
     ══════════════════════════════════════════════════ */
  function _bindEvents() {
    document
      .getElementById('pred-close-btn')
      ?.addEventListener('click', closePanel);

    document
      .getElementById('pred-run-btn')
      ?.addEventListener('click', runAnalysis);

    document
      .getElementById('pred-clear-btn')
      ?.addEventListener('click', clearAllLayers);

    document
      .getElementById('pred-export-btn')
      ?.addEventListener('click', _exportJSON);

    document.querySelectorAll('.pred-tab').forEach((tab) => {
      tab.addEventListener('click', () => _switchTab(tab.dataset.tab));
    });
  }

  /* ══════════════════════════════════════════════════
     OPEN / CLOSE / TOGGLE
     ══════════════════════════════════════════════════ */
  function togglePanel() {
    const p = document.getElementById('prediction-panel');
    p?.classList.contains('open') ? closePanel() : openPanel();
  }
  function openPanel() {
    document.getElementById('prediction-panel')?.classList.add('open');
    document.getElementById('pred-open-btn')?.classList.add('active');
  }
  function closePanel() {
    document.getElementById('prediction-panel')?.classList.remove('open');
    document.getElementById('pred-open-btn')?.classList.remove('active');
  }

  /* ══════════════════════════════════════════════════
     TAB SWITCHER
     ══════════════════════════════════════════════════ */
  function _switchTab(tabId) {
    _activeTab = tabId;
    document
      .querySelectorAll('.pred-tab')
      .forEach((t) => t.classList.toggle('active', t.dataset.tab === tabId));
    document
      .querySelectorAll('.pred-tab-content')
      .forEach((c) =>
        c.classList.toggle('active', c.id === `pred-tab-${tabId}`),
      );
  }

  /* ══════════════════════════════════════════════════
     MAIN ANALYSIS RUNNER
     ══════════════════════════════════════════════════ */
  async function runAnalysis() {
    if (_isComputing) return;
    _isComputing = true;

    const days = parseInt(document.getElementById('pred-days')?.value || 7);
    const horizonHrs = parseInt(
      document.getElementById('pred-horizon')?.value || 24,
    );
    const minConf = parseFloat(
      document.getElementById('pred-min-conf')?.value || 0.65,
    );

    _setRunning(true, 'COMPUTING…');
    clearAllLayers();

    try {
      // Fetch hotspot data
      _setStatus('FETCHING DATA');
      const hotspotData = await API.getHotspots(days);
      const features = hotspotData?.features || [];

      if (features.length === 0) {
        showToast('No hotspot data available for prediction', 'warning');
        _setRunning(false, 'RUN ANALYSIS');
        _isComputing = false;
        return;
      }

      // Also fetch movement data
      let movementData = State.get('movementData');
      if (!movementData) {
        try {
          movementData = await API.getMovementData(days);
          State.set('movementData', movementData);
        } catch (_) {
          movementData = { movements: [] };
        }
      }
      const movements = movementData?.movements || [];

      // ── Run all three engines ──
      _setStatus('PROJECTING TRAJECTORIES');
      _predictionData = _computeTrajectories(
        features,
        movements,
        horizonHrs,
        minConf,
      );

      _setStatus('MAPPING BASE AREAS');
      _heatmapData = _computeRecurrenceHeatmap(features);

      _setStatus('FORECASTING STRIKES');
      _strikeData = _computeStrikePrediction(features);

      // ── Render results ──
      _renderTrajectoryTab(_predictionData);
      _renderHeatmapTab(_heatmapData);
      _renderStrikeTab(_strikeData);
      _renderSummaryTab(_predictionData, _heatmapData, _strikeData, features);

      // ── Plot on map ──
      _plotTrajectoryLayer(_predictionData);
      _plotHeatmapLayer(_heatmapData);
      _plotStrikeLayer(_strikeData);

      const totalThreats =
        _predictionData.projections.length +
        _heatmapData.base_areas.length +
        _strikeData.zones.filter((z) => z.status === 'DUE').length;

      document.getElementById('pred-footer-meta').textContent =
        `${features.length} hotspots analysed · ${totalThreats} threats identified · ${days}d window`;

      _setStatus('LIVE');
      showToast(
        `Prediction complete — ${_predictionData.projections.length} trajectories, ` +
          `${_heatmapData.base_areas.length} base areas, ` +
          `${_strikeData.zones.filter((z) => z.status === 'DUE').length} zones due`,
        'success',
      );
    } catch (err) {
      console.error('[PredictionView] Analysis failed:', err);
      showToast('Analysis failed: ' + err.message, 'error');
      _setStatus('ERROR');
    } finally {
      _setRunning(false, 'RUN ANALYSIS');
      _isComputing = false;
    }
  }

  /* ══════════════════════════════════════════════════
     ENGINE 1: TRAJECTORY PROJECTION
     
     Algorithm:
     - Group hotspots into spatial clusters (0.3° radius)
     - For each cluster with movement vectors, compute
       mean bearing and speed
     - Project forward: pos + bearing × speed × horizonHrs
     - Generate probability cone (±bearing_std dev)
     ══════════════════════════════════════════════════ */
  function _computeTrajectories(features, movements, horizonHrs, minConf) {
    const projections = [];

    // Use movement vectors if available
    if (movements.length > 0) {
      movements.forEach((mv, i) => {
        if (!mv.origin_lat || !mv.destination_lat) return;
        if ((mv.confidence || 0) < minConf) return;

        const speedKmh = mv.speed_kmh || 15;
        const bearing = mv.bearing_degrees || 0;
        const distKm = speedKmh * horizonHrs;

        // Project destination forward
        const projected = _projectPoint(
          mv.destination_lat,
          mv.destination_lon,
          bearing,
          distKm,
        );

        // Confidence decays with time
        const conf = Math.max(
          0.1,
          (mv.confidence || 0.7) * Math.exp(-horizonHrs / 72),
        );

        // Cone angle based on confidence (lower conf = wider cone)
        const coneAngle = 15 + (1 - conf) * 45;

        projections.push({
          id: `mv-${i}`,
          origin: { lat: mv.origin_lat, lon: mv.origin_lon },
          last_known: { lat: mv.destination_lat, lon: mv.destination_lon },
          projected: projected,
          bearing: bearing,
          cone_angle: coneAngle,
          speed_kmh: speedKmh,
          distance_km: Math.round(distKm),
          confidence: Math.round(conf * 100),
          horizon_hrs: horizonHrs,
          classification: mv.classification || 'movement',
          origin_state: mv.origin_state || '—',
          destination_state: mv.destination_state || '—',
          threat_level: _classifyThreatLevel(conf, speedKmh, mv.classification),
        });
      });
    }

    // Fallback: derive from high-priority CRITICAL hotspot clusters
    if (projections.length === 0) {
      const clusters = _clusterHotspots(
        features.filter((f) =>
          ['CRITICAL', 'HIGH'].includes(f.properties.priority),
        ),
        0.3,
      );

      clusters.forEach((cluster, i) => {
        if (cluster.points.length < 2) return;

        // Sort by acquisition date to get temporal sequence
        const sorted = cluster.points.sort((a, b) =>
          (a.properties.acq_date || '').localeCompare(
            b.properties.acq_date || '',
          ),
        );

        if (sorted.length < 2) return;

        // Compute mean bearing from sequential pairs
        const bearings = [];
        for (let j = 1; j < sorted.length; j++) {
          const [lon1, lat1] = sorted[j - 1].geometry.coordinates;
          const [lon2, lat2] = sorted[j].geometry.coordinates;
          if (Math.abs(lat2 - lat1) < 0.001 && Math.abs(lon2 - lon1) < 0.001)
            continue;
          bearings.push(_bearing(lat1, lon1, lat2, lon2));
        }

        if (bearings.length === 0) return;

        const meanBearing = _meanAngle(bearings);
        const lastPt = sorted[sorted.length - 1];
        const [lastLon, lastLat] = lastPt.geometry.coordinates;

        const estimatedSpeedKmh = 12; // conservative estimate
        const distKm = estimatedSpeedKmh * horizonHrs;
        const projected = _projectPoint(lastLat, lastLon, meanBearing, distKm);
        const conf = Math.min(0.9, 0.4 + cluster.points.length * 0.05);
        const coneAngle = 20 + (1 - conf) * 50;

        projections.push({
          id: `cluster-${i}`,
          origin: { lat: cluster.centroid.lat, lon: cluster.centroid.lon },
          last_known: { lat: lastLat, lon: lastLon },
          projected: projected,
          bearing: Math.round(meanBearing),
          cone_angle: coneAngle,
          speed_kmh: estimatedSpeedKmh,
          distance_km: Math.round(distKm),
          confidence: Math.round(conf * 100),
          horizon_hrs: horizonHrs,
          classification: 'cluster_derived',
          origin_state: lastPt.properties.state || '—',
          destination_state: '?',
          threat_level: _classifyThreatLevel(
            conf,
            estimatedSpeedKmh,
            'cluster',
          ),
          hotspot_count: cluster.points.length,
        });
      });
    }

    // Sort by confidence desc
    projections.sort((a, b) => b.confidence - a.confidence);

    return {
      projections,
      horizon_hrs: horizonHrs,
      computed_at: new Date().toISOString(),
      critical_count: projections.filter((p) => p.threat_level === 'CRITICAL')
        .length,
      high_count: projections.filter((p) => p.threat_level === 'HIGH').length,
    };
  }

  /* ══════════════════════════════════════════════════
     ENGINE 2: RECURRENCE HEATMAP
     
     Algorithm:
     - Grid Nigeria into 0.05° cells (~5.5km)
     - Count hotspot hits per cell across 30 days
     - Flag cells with ≥3 hits as persistent presence
     - Night-only ratio > 0.6 → classify as BASE AREA
     - Night-only ratio < 0.4 → classify as TRANSIT
     - Otherwise → STAGING AREA
     ══════════════════════════════════════════════════ */
  function _computeRecurrenceHeatmap(features) {
    const CELL_SIZE = 0.05; // degrees (~5.5km)
    const cellMap = {};

    features.forEach((f) => {
      const [lon, lat] = f.geometry.coordinates;
      const p = f.properties;

      const cellLat = Math.floor(lat / CELL_SIZE) * CELL_SIZE;
      const cellLon = Math.floor(lon / CELL_SIZE) * CELL_SIZE;
      const key = `${cellLat.toFixed(3)},${cellLon.toFixed(3)}`;

      if (!cellMap[key]) {
        cellMap[key] = {
          lat: cellLat + CELL_SIZE / 2,
          lon: cellLon + CELL_SIZE / 2,
          cell_lat: cellLat,
          cell_lon: cellLon,
          count: 0,
          night_count: 0,
          dates: new Set(),
          max_brightness: 0,
          states: {},
          priority_counts: { CRITICAL: 0, HIGH: 0, ELEVATED: 0, MONITOR: 0 },
        };
      }

      const cell = cellMap[key];
      cell.count++;
      if (p.daynight === 'N') cell.night_count++;
      if (p.acq_date) cell.dates.add(p.acq_date);
      if ((p.brightness || 0) > cell.max_brightness)
        cell.max_brightness = p.brightness;
      if (p.state) cell.states[p.state] = (cell.states[p.state] || 0) + 1;
      if (p.priority && cell.priority_counts[p.priority] !== undefined) {
        cell.priority_counts[p.priority]++;
      }
    });

    // Classify cells
    const base_areas = [];
    const transit_zones = [];
    const staging_areas = [];

    Object.values(cellMap).forEach((cell) => {
      if (cell.count < 2) return; // single-hit cells ignored

      const nightRatio = cell.count > 0 ? cell.night_count / cell.count : 0;
      const daySpread = cell.dates.size;
      const dominantState =
        Object.entries(cell.states).sort((a, b) => b[1] - a[1])[0]?.[0] || '—';

      const intensity = Math.min(1.0, cell.count / 10);
      const persistence = Math.min(1.0, daySpread / 7);

      let type, label, threat;
      if (nightRatio >= 0.6 && daySpread >= 2) {
        type = 'BASE';
        label = 'Probable Base Area';
        threat = 'CRITICAL';
      } else if (nightRatio < 0.35 && cell.count >= 3) {
        type = 'TRANSIT';
        label = 'Transit Corridor';
        threat = 'HIGH';
      } else if (cell.count >= 3) {
        type = 'STAGING';
        label = 'Staging Area';
        threat = 'HIGH';
      } else {
        type = 'ACTIVITY';
        label = 'Activity Zone';
        threat = 'ELEVATED';
      }

      const entry = {
        lat: cell.lat,
        lon: cell.lon,
        cell_size: CELL_SIZE,
        count: cell.count,
        night_count: cell.night_count,
        night_ratio: Math.round(nightRatio * 100),
        day_spread: daySpread,
        max_brightness: cell.max_brightness,
        state: dominantState,
        intensity,
        persistence,
        type,
        label,
        threat,
        priority_counts: cell.priority_counts,
      };

      if (type === 'BASE') base_areas.push(entry);
      else if (type === 'TRANSIT') transit_zones.push(entry);
      else staging_areas.push(entry);
    });

    // Sort by count desc
    base_areas.sort((a, b) => b.count - a.count);
    transit_zones.sort((a, b) => b.count - a.count);
    staging_areas.sort((a, b) => b.count - a.count);

    return {
      base_areas,
      transit_zones,
      staging_areas,
      total_cells: Object.keys(cellMap).length,
      computed_at: new Date().toISOString(),
    };
  }

  /* ══════════════════════════════════════════════════
     ENGINE 3: STRIKE PREDICTION TIMELINE
     
     Algorithm:
     - Per red zone / state, collect CRITICAL hotspot 
       clusters ordered by date
     - Compute mean inter-event interval (days)
     - Last event date + mean interval = predicted next
     - Flag as: OVERDUE / DUE / UPCOMING / QUIET
     ══════════════════════════════════════════════════ */
  function _computeStrikePrediction(features) {
    // Group CRITICAL+HIGH features by state
    const stateEvents = {};
    const now = new Date();

    features.forEach((f) => {
      const p = f.properties;
      if (!['CRITICAL', 'HIGH'].includes(p.priority)) return;
      const state = p.state || 'Unknown';
      if (!stateEvents[state]) stateEvents[state] = [];
      if (p.acq_date) {
        stateEvents[state].push({
          date: new Date(p.acq_date),
          priority: p.priority,
          score: p.threat_score || 0,
          lat: f.geometry.coordinates[1],
          lon: f.geometry.coordinates[0],
          red_zone: p.red_zone || '',
        });
      }
    });

    const zones = [];

    Object.entries(stateEvents).forEach(([state, events]) => {
      if (events.length === 0) return;

      // Sort by date
      events.sort((a, b) => a.date - b.date);

      // Deduplicate: collapse events within 24hrs as one cluster
      const clusters = [];
      let lastClusterDate = null;

      events.forEach((evt) => {
        if (!lastClusterDate || evt.date - lastClusterDate > 24 * 3600 * 1000) {
          clusters.push({
            date: evt.date,
            events: [evt],
            maxScore: evt.score,
            priority: evt.priority,
          });
          lastClusterDate = evt.date;
        } else {
          const last = clusters[clusters.length - 1];
          last.events.push(evt);
          if (evt.score > last.maxScore) last.maxScore = evt.score;
        }
      });

      if (clusters.length === 0) return;

      const lastCluster = clusters[clusters.length - 1];
      const lastEventDate = lastCluster.date;
      const daysSinceLast = (now - lastEventDate) / (1000 * 3600 * 24);

      // Compute inter-event interval
      let meanIntervalDays = null;
      if (clusters.length >= 2) {
        const intervals = [];
        for (let i = 1; i < clusters.length; i++) {
          const diff =
            (clusters[i].date - clusters[i - 1].date) / (1000 * 3600 * 24);
          if (diff > 0) intervals.push(diff);
        }
        if (intervals.length > 0) {
          meanIntervalDays =
            intervals.reduce((s, v) => s + v, 0) / intervals.length;
        }
      }

      // Predicted next date
      let predictedNext = null;
      let daysUntilNext = null;
      let status = 'INSUFFICIENT_DATA';
      let urgency = 0;

      if (meanIntervalDays !== null) {
        predictedNext = new Date(
          lastEventDate.getTime() + meanIntervalDays * 24 * 3600 * 1000,
        );
        daysUntilNext = (predictedNext - now) / (1000 * 3600 * 24);

        if (daysUntilNext < -2) {
          status = 'OVERDUE';
          urgency = 1.0;
        } else if (daysUntilNext < 1) {
          status = 'DUE';
          urgency = 0.9;
        } else if (daysUntilNext < 3) {
          status = 'UPCOMING';
          urgency = 0.7;
        } else if (daysUntilNext < 7) {
          status = 'WATCH';
          urgency = 0.4;
        } else {
          status = 'QUIET';
          urgency = 0.1;
        }
      } else if (clusters.length === 1) {
        status = 'SINGLE_EVENT';
        urgency = 0.3;
      }

      // Representative location (centroid of most recent cluster)
      const recentLats = lastCluster.events.map((e) => e.lat);
      const recentLons = lastCluster.events.map((e) => e.lon);
      const centLat = recentLats.reduce((s, v) => s + v, 0) / recentLats.length;
      const centLon = recentLons.reduce((s, v) => s + v, 0) / recentLons.length;

      zones.push({
        state,
        red_zone: lastCluster.events[0]?.red_zone || '',
        cluster_count: clusters.length,
        last_event_date: lastEventDate.toISOString().split('T')[0],
        days_since_last: Math.round(daysSinceLast * 10) / 10,
        mean_interval_days: meanIntervalDays
          ? Math.round(meanIntervalDays * 10) / 10
          : null,
        predicted_next: predictedNext
          ? predictedNext.toISOString().split('T')[0]
          : null,
        days_until_next: daysUntilNext
          ? Math.round(daysUntilNext * 10) / 10
          : null,
        status,
        urgency,
        max_score: lastCluster.maxScore,
        lat: centLat,
        lon: centLon,
        event_count: events.length,
      });
    });

    // Sort by urgency desc
    zones.sort((a, b) => b.urgency - a.urgency);

    const overdue = zones.filter((z) => z.status === 'OVERDUE').length;
    const due = zones.filter((z) => z.status === 'DUE').length;
    const upcoming = zones.filter((z) => z.status === 'UPCOMING').length;

    return {
      zones,
      overdue,
      due,
      upcoming,
      computed_at: new Date().toISOString(),
    };
  }

  /* ══════════════════════════════════════════════════
     RENDER: TRAJECTORY TAB
     ══════════════════════════════════════════════════ */
  function _renderTrajectoryTab(data) {
    const empty = document.getElementById('traj-empty');
    const results = document.getElementById('traj-results');
    const stats = document.getElementById('traj-stats');
    const list = document.getElementById('traj-list');

    if (!data || data.projections.length === 0) {
      empty?.classList.remove('hidden');
      results?.classList.add('hidden');
      return;
    }

    empty?.classList.add('hidden');
    results?.classList.remove('hidden');

    stats.innerHTML = `
      <div class="pred-stat-cell critical">
        <span class="pred-stat-val">${data.critical_count}</span>
        <span class="pred-stat-lbl">CRITICAL</span>
      </div>
      <div class="pred-stat-cell high">
        <span class="pred-stat-val">${data.high_count}</span>
        <span class="pred-stat-lbl">HIGH</span>
      </div>
      <div class="pred-stat-cell">
        <span class="pred-stat-val">${data.projections.length}</span>
        <span class="pred-stat-lbl">VECTORS</span>
      </div>
      <div class="pred-stat-cell">
        <span class="pred-stat-val">${data.horizon_hrs}h</span>
        <span class="pred-stat-lbl">HORIZON</span>
      </div>
    `;

    list.innerHTML = data.projections
      .slice(0, 15)
      .map(
        (p) => `
      <div class="pred-card pred-card-${p.threat_level.toLowerCase()}"
           onclick="PredictionView.focusTrajectory('${p.id}')">
        <div class="pred-card-header">
          <span class="pred-badge pred-badge-${p.threat_level.toLowerCase()}">${p.threat_level}</span>
          <span class="pred-card-title">${p.origin_state} → ${p.destination_state || '?'}</span>
          <span class="pred-card-conf">${p.confidence}%</span>
        </div>
        <div class="pred-card-body">
          <div class="pred-card-row">
            <span class="pred-card-lbl">BEARING</span>
            <span class="pred-card-val">${p.bearing}° · ${_bearingLabel(p.bearing)}</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">SPEED EST.</span>
            <span class="pred-card-val">${p.speed_kmh} km/h</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">PROJ. DISTANCE</span>
            <span class="pred-card-val">${p.distance_km} km in ${p.horizon_hrs}h</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">PROJECTED TO</span>
            <span class="pred-card-val mono">${p.projected.lat.toFixed(3)}°N, ${p.projected.lon.toFixed(3)}°E</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">TYPE</span>
            <span class="pred-card-val">${(p.classification || '').replace(/_/g, ' ').toUpperCase()}</span>
          </div>
        </div>
        <div class="pred-confidence-bar">
          <div class="pred-confidence-fill pred-conf-${p.threat_level.toLowerCase()}" 
               style="width:${p.confidence}%"></div>
        </div>
        <div class="pred-card-arrow">→ TAP TO FOCUS</div>
      </div>
    `,
      )
      .join('');
  }

  /* ══════════════════════════════════════════════════
     RENDER: HEATMAP TAB
     ══════════════════════════════════════════════════ */
  function _renderHeatmapTab(data) {
    const empty = document.getElementById('heat-empty');
    const results = document.getElementById('heat-results');
    const stats = document.getElementById('heat-stats');
    const list = document.getElementById('heat-list');

    if (
      !data ||
      data.base_areas.length +
        data.transit_zones.length +
        data.staging_areas.length ===
        0
    ) {
      empty?.classList.remove('hidden');
      results?.classList.add('hidden');
      return;
    }

    empty?.classList.add('hidden');
    results?.classList.remove('hidden');

    stats.innerHTML = `
      <div class="pred-stat-cell critical">
        <span class="pred-stat-val">${data.base_areas.length}</span>
        <span class="pred-stat-lbl">BASE AREAS</span>
      </div>
      <div class="pred-stat-cell high">
        <span class="pred-stat-val">${data.staging_areas.length}</span>
        <span class="pred-stat-lbl">STAGING</span>
      </div>
      <div class="pred-stat-cell">
        <span class="pred-stat-val">${data.transit_zones.length}</span>
        <span class="pred-stat-lbl">TRANSIT</span>
      </div>
      <div class="pred-stat-cell">
        <span class="pred-stat-val">${data.total_cells}</span>
        <span class="pred-stat-lbl">CELLS</span>
      </div>
    `;

    const allZones = [
      ...data.base_areas
        .slice(0, 6)
        .map((z) => ({ ...z, _typeLabel: 'BASE AREA' })),
      ...data.staging_areas
        .slice(0, 4)
        .map((z) => ({ ...z, _typeLabel: 'STAGING' })),
      ...data.transit_zones
        .slice(0, 4)
        .map((z) => ({ ...z, _typeLabel: 'TRANSIT' })),
    ];

    list.innerHTML = allZones
      .map(
        (z) => `
      <div class="pred-card pred-card-${z.threat.toLowerCase()}"
           onclick="PredictionView.focusHeatCell(${z.lat}, ${z.lon})">
        <div class="pred-card-header">
          <span class="pred-badge pred-badge-${z.threat.toLowerCase()}">${z._typeLabel}</span>
          <span class="pred-card-title">${z.state}</span>
          <span class="pred-card-conf">${z.count} hits</span>
        </div>
        <div class="pred-card-body">
          <div class="pred-card-row">
            <span class="pred-card-lbl">NIGHT RATIO</span>
            <span class="pred-card-val ${z.night_ratio >= 60 ? 'text-critical' : ''}">${z.night_ratio}% night activity</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">DAY SPREAD</span>
            <span class="pred-card-val">${z.day_spread} distinct days</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">LOCATION</span>
            <span class="pred-card-val mono">${z.lat.toFixed(3)}°N, ${z.lon.toFixed(3)}°E</span>
          </div>
          <div class="pred-card-row">
            <span class="pred-card-lbl">ASSESSMENT</span>
            <span class="pred-card-val">${z.label}</span>
          </div>
        </div>
        <div class="pred-intensity-bar">
          <div class="pred-intensity-fill" style="width:${Math.round(z.intensity * 100)}%;
               background: ${z.type === 'BASE' ? '#ff2d2d' : z.type === 'STAGING' ? '#ff6520' : '#f0a500'}">
          </div>
        </div>
        <div class="pred-card-arrow">→ TAP TO FOCUS</div>
      </div>
    `,
      )
      .join('');
  }

  /* ══════════════════════════════════════════════════
     RENDER: STRIKE TAB
     ══════════════════════════════════════════════════ */
  function _renderStrikeTab(data) {
    const empty = document.getElementById('strike-empty');
    const results = document.getElementById('strike-results');
    const stats = document.getElementById('strike-stats');
    const timeline = document.getElementById('strike-timeline');

    if (!data || data.zones.length === 0) {
      empty?.classList.remove('hidden');
      results?.classList.add('hidden');
      return;
    }

    empty?.classList.add('hidden');
    results?.classList.remove('hidden');

    stats.innerHTML = `
      <div class="pred-stat-cell critical">
        <span class="pred-stat-val">${data.overdue}</span>
        <span class="pred-stat-lbl">OVERDUE</span>
      </div>
      <div class="pred-stat-cell high">
        <span class="pred-stat-val">${data.due}</span>
        <span class="pred-stat-lbl">DUE NOW</span>
      </div>
      <div class="pred-stat-cell elevated">
        <span class="pred-stat-val">${data.upcoming}</span>
        <span class="pred-stat-lbl">UPCOMING</span>
      </div>
      <div class="pred-stat-cell">
        <span class="pred-stat-val">${data.zones.length}</span>
        <span class="pred-stat-lbl">ZONES</span>
      </div>
    `;

    const statusMeta = {
      OVERDUE: { cls: 'critical', icon: '⚠', label: 'OVERDUE' },
      DUE: { cls: 'high', icon: '◆', label: 'DUE NOW' },
      UPCOMING: { cls: 'elevated', icon: '◇', label: 'UPCOMING' },
      WATCH: { cls: 'monitor', icon: '○', label: 'WATCH' },
      QUIET: { cls: 'quiet', icon: '·', label: 'QUIET' },
      SINGLE_EVENT: { cls: 'monitor', icon: '·', label: 'SINGLE EVENT' },
      INSUFFICIENT_DATA: { cls: 'quiet', icon: '—', label: 'NO DATA' },
    };

    timeline.innerHTML = data.zones
      .map((z) => {
        const meta = statusMeta[z.status] || statusMeta['QUIET'];
        const intervalStr = z.mean_interval_days
          ? `every ${z.mean_interval_days}d avg`
          : 'interval unknown';
        const nextStr = z.predicted_next
          ? z.days_until_next < 0
            ? `${Math.abs(z.days_until_next)}d ago (OVERDUE)`
            : `in ${z.days_until_next}d (${z.predicted_next})`
          : '—';

        return `
        <div class="pred-strike-card pred-strike-${meta.cls}"
             onclick="PredictionView.focusZone(${z.lat}, ${z.lon}, '${z.state}')">
          <div class="pred-strike-status-col">
            <span class="pred-strike-icon">${meta.icon}</span>
            <span class="pred-strike-status-lbl pred-strike-lbl-${meta.cls}">${meta.label}</span>
          </div>
          <div class="pred-strike-data-col">
            <div class="pred-strike-state">${z.state}</div>
            <div class="pred-strike-meta">
              ${z.cluster_count} clusters · ${intervalStr} · last: ${z.last_event_date}
            </div>
            <div class="pred-strike-next ${meta.cls === 'critical' || meta.cls === 'high' ? 'text-critical' : ''}">
              ▶ Next predicted: ${nextStr}
            </div>
          </div>
          <div class="pred-strike-urgency-bar">
            <div class="pred-strike-urgency-fill pred-urg-${meta.cls}"
                 style="height:${Math.round(z.urgency * 100)}%"></div>
          </div>
        </div>
      `;
      })
      .join('');
  }

  /* ══════════════════════════════════════════════════
     RENDER: SUMMARY / INTEL BRIEF TAB
     ══════════════════════════════════════════════════ */
  function _renderSummaryTab(traj, heat, strike, features) {
    const empty = document.getElementById('summary-empty');
    const content = document.getElementById('summary-content');

    empty?.classList.add('hidden');
    content?.classList.remove('hidden');

    const now = new Date().toUTCString().replace('GMT', 'UTC');
    const criticalZones = strike.zones.filter((z) =>
      ['OVERDUE', 'DUE'].includes(z.status),
    );
    const baseAreas = heat.base_areas.slice(0, 3);
    const topTraj = traj.projections
      .filter((p) => p.threat_level === 'CRITICAL')
      .slice(0, 3);

    content.innerHTML = `
      <div class="pred-brief">
        <div class="pred-brief-header">
          <div class="pred-brief-classification">// INTELLIGENCE BRIEF — UNCLASSIFIED //</div>
          <div class="pred-brief-timestamp">Generated: ${now}</div>
        </div>

        <div class="pred-brief-section">
          <div class="pred-brief-section-title">1. SITUATION ASSESSMENT</div>
          <div class="pred-brief-text">
            Analysis of <strong>${features.length}</strong> thermal detections identified 
            <strong>${traj.projections.length}</strong> active movement vector(s), 
            <strong>${heat.base_areas.length}</strong> probable base area(s), and 
            <strong>${strike.overdue + strike.due}</strong> zone(s) at immediate activation risk.
            ${
              strike.overdue > 0
                ? `<span class="text-critical"> ${strike.overdue} zone(s) are OVERDUE for strike activity.</span>`
                : ''
            }
          </div>
        </div>

        ${
          criticalZones.length > 0
            ? `
        <div class="pred-brief-section">
          <div class="pred-brief-section-title">2. IMMEDIATE THREATS</div>
          ${criticalZones
            .map(
              (z) => `
            <div class="pred-brief-item pred-brief-item-critical">
              <span class="pred-brief-bullet">◆</span>
              <span><strong>${z.state}</strong> — ${z.status} 
                (last activity ${z.days_since_last}d ago, predicted interval ${z.mean_interval_days || '?'}d)
                ${z.predicted_next ? ` · Next: ${z.predicted_next}` : ''}
              </span>
            </div>
          `,
            )
            .join('')}
        </div>`
            : ''
        }

        ${
          topTraj.length > 0
            ? `
        <div class="pred-brief-section">
          <div class="pred-brief-section-title">3. PROJECTED MOVEMENT</div>
          ${topTraj
            .map(
              (p) => `
            <div class="pred-brief-item pred-brief-item-high">
              <span class="pred-brief-bullet">⟶</span>
              <span>
                <strong>${p.origin_state}</strong> bearing ${p.bearing}° (${_bearingLabel(p.bearing)}) 
                at est. ${p.speed_kmh}km/h — projected ${p.distance_km}km in ${p.horizon_hrs}h 
                to <span class="mono">${p.projected.lat.toFixed(3)}°N, ${p.projected.lon.toFixed(3)}°E</span>
                (${p.confidence}% confidence)
              </span>
            </div>
          `,
            )
            .join('')}
        </div>`
            : ''
        }

        ${
          baseAreas.length > 0
            ? `
        <div class="pred-brief-section">
          <div class="pred-brief-section-title">4. IDENTIFIED BASE AREAS</div>
          ${baseAreas
            .map(
              (z) => `
            <div class="pred-brief-item pred-brief-item-base">
              <span class="pred-brief-bullet">◉</span>
              <span>
                <strong>${z.state}</strong> — ${z.count} detections over ${z.day_spread} days, 
                ${z.night_ratio}% night activity at 
                <span class="mono">${z.lat.toFixed(3)}°N, ${z.lon.toFixed(3)}°E</span>
              </span>
            </div>
          `,
            )
            .join('')}
        </div>`
            : ''
        }

        <div class="pred-brief-section">
          <div class="pred-brief-section-title">5. RECOMMENDED ACTIONS</div>
          ${
            strike.overdue > 0
              ? `
          <div class="pred-brief-item pred-brief-item-critical">
            <span class="pred-brief-bullet">!</span>
            <span>IMMEDIATE: Deploy surveillance assets to ${criticalZones
              .slice(0, 2)
              .map((z) => z.state)
              .join(', ')} — zones are overdue for activation</span>
          </div>`
              : ''
          }
          ${
            heat.base_areas.length > 0
              ? `
          <div class="pred-brief-item pred-brief-item-high">
            <span class="pred-brief-bullet">!</span>
            <span>PRIORITY: Conduct aerial reconnaissance of ${heat.base_areas
              .slice(0, 2)
              .map((z) => z.state)
              .join(
                ', ',
              )} — persistent night-activity patterns confirm probable base areas</span>
          </div>`
              : ''
          }
          ${
            traj.critical_count > 0
              ? `
          <div class="pred-brief-item pred-brief-item-elevated">
            <span class="pred-brief-bullet">!</span>
            <span>MONITOR: Establish observation posts along projected corridors. Re-run trajectory analysis in 6 hours to update projections.</span>
          </div>`
              : ''
          }
          <div class="pred-brief-item">
            <span class="pred-brief-bullet">·</span>
            <span>Continue FIRMS thermal monitoring at 1-day resolution for all flagged zones. Cross-reference with ACLED for ground-truth validation.</span>
          </div>
        </div>

        <div class="pred-brief-footer">
          // END OF BRIEF // AUTO-GENERATED // NOT FOR PUBLIC RELEASE //
        </div>
      </div>
    `;
  }

  /* ══════════════════════════════════════════════════
     MAP PLOTTING: TRAJECTORY LAYER
     ══════════════════════════════════════════════════ */
  function _plotTrajectoryLayer(data) {
    if (!window._map || !data?.projections?.length) return;

    if (!_trajectoryLayer) {
      _trajectoryLayer = L.layerGroup().addTo(window._map);
    }
    _trajectoryLayer.clearLayers();

    data.projections.forEach((p) => {
      const color =
        p.threat_level === 'CRITICAL'
          ? '#ff2d2d'
          : p.threat_level === 'HIGH'
            ? '#ff6520'
            : '#f0a500';

      // Last-known position marker
      const pulseIcon = L.divIcon({
        className: '',
        html: `<div class="pred-pulse-marker" style="background:${color};box-shadow:0 0 10px ${color}88"></div>`,
        iconSize: [14, 14],
        iconAnchor: [7, 7],
      });
      L.marker([p.last_known.lat, p.last_known.lon], { icon: pulseIcon })
        .bindPopup(_trajectoryPopup(p))
        .addTo(_trajectoryLayer);

      // Bearing line to projected point
      L.polyline(
        [
          [p.last_known.lat, p.last_known.lon],
          [p.projected.lat, p.projected.lon],
        ],
        { color, weight: 2, opacity: 0.85, dashArray: '8 5' },
      ).addTo(_trajectoryLayer);

      // Probability cone (two boundary lines)
      const coneLeft = _projectPoint(
        p.last_known.lat,
        p.last_known.lon,
        p.bearing - p.cone_angle / 2,
        p.distance_km,
      );
      const coneRight = _projectPoint(
        p.last_known.lat,
        p.last_known.lon,
        p.bearing + p.cone_angle / 2,
        p.distance_km,
      );

      const conePolygon = L.polygon(
        [
          [p.last_known.lat, p.last_known.lon],
          [coneLeft.lat, coneLeft.lon],
          [p.projected.lat, p.projected.lon],
          [coneRight.lat, coneRight.lon],
        ],
        {
          color,
          weight: 1,
          fillColor: color,
          fillOpacity: 0.07,
          dashArray: '4 4',
        },
      ).addTo(_trajectoryLayer);

      // Projected endpoint marker
      const arrowIcon = L.divIcon({
        className: '',
        html: `<div class="pred-arrow-marker" style="color:${color};transform:rotate(${p.bearing - 90}deg)">➤</div>`,
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      });
      L.marker([p.projected.lat, p.projected.lon], { icon: arrowIcon })
        .bindPopup(_trajectoryPopup(p))
        .addTo(_trajectoryLayer);

      // Confidence label at midpoint
      const midLat = (p.last_known.lat + p.projected.lat) / 2;
      const midLon = (p.last_known.lon + p.projected.lon) / 2;
      const labelIcon = L.divIcon({
        className: '',
        html: `<div class="pred-traj-label" style="border-color:${color};color:${color}">${p.confidence}%</div>`,
        iconSize: [32, 16],
        iconAnchor: [16, 8],
      });
      L.marker([midLat, midLon], { icon: labelIcon }).addTo(_trajectoryLayer);
    });
  }

  /* ══════════════════════════════════════════════════
     MAP PLOTTING: HEATMAP LAYER
     ══════════════════════════════════════════════════ */
  function _plotHeatmapLayer(data) {
    if (!window._map || !data) return;

    if (!_heatmapLayer) {
      _heatmapLayer = L.layerGroup().addTo(window._map);
    }
    _heatmapLayer.clearLayers();

    const allZones = [
      ...data.base_areas,
      ...data.staging_areas,
      ...data.transit_zones,
    ];

    allZones.forEach((zone) => {
      const color =
        zone.type === 'BASE'
          ? '#ff2d2d'
          : zone.type === 'STAGING'
            ? '#ff6520'
            : '#f0a500';

      const opacity = 0.1 + zone.intensity * 0.35;
      const half = zone.cell_size / 2;

      // Cell rectangle
      L.rectangle(
        [
          [zone.lat - half, zone.lon - half],
          [zone.lat + half, zone.lon + half],
        ],
        {
          color,
          weight: 1,
          fillColor: color,
          fillOpacity: opacity,
          opacity: 0.4,
        },
      )
        .bindTooltip(
          `<strong>${zone.label}</strong><br>${zone.state}<br>` +
            `${zone.count} hits · ${zone.night_ratio}% night · ${zone.day_spread} days`,
          { sticky: true },
        )
        .addTo(_heatmapLayer);

      // Base area gets a special icon
      if (zone.type === 'BASE') {
        const baseIcon = L.divIcon({
          className: '',
          html: `<div class="pred-base-marker" style="border-color:${color}">⬡</div>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        });
        L.marker([zone.lat, zone.lon], { icon: baseIcon })
          .bindPopup(
            `
            <div style="font-family:monospace;min-width:220px">
              <div style="color:#ff2d2d;font-weight:700;margin-bottom:6px">◉ ${zone.label.toUpperCase()}</div>
              <table style="width:100%;border-collapse:collapse;font-size:11px">
                <tr><td style="color:#6a82a0">State</td><td>${zone.state}</td></tr>
                <tr><td style="color:#6a82a0">Detections</td><td>${zone.count} total</td></tr>
                <tr><td style="color:#6a82a0">Night activity</td><td style="color:${zone.night_ratio >= 60 ? '#ff2d2d' : '#c9d1d9'}">${zone.night_ratio}%</td></tr>
                <tr><td style="color:#6a82a0">Active days</td><td>${zone.day_spread}</td></tr>
                <tr><td style="color:#6a82a0">Coords</td><td>${zone.lat.toFixed(4)}°N, ${zone.lon.toFixed(4)}°E</td></tr>
              </table>
            </div>`,
          )
          .addTo(_heatmapLayer);
      }
    });
  }

  /* ══════════════════════════════════════════════════
     MAP PLOTTING: STRIKE PREDICTION LAYER
     ══════════════════════════════════════════════════ */
  function _plotStrikeLayer(data) {
    if (!window._map || !data?.zones?.length) return;

    if (!_strikeLayer) {
      _strikeLayer = L.layerGroup().addTo(window._map);
    }
    _strikeLayer.clearLayers();

    const statusColors = {
      OVERDUE: '#ff2d2d',
      DUE: '#ff6520',
      UPCOMING: '#f0a500',
      WATCH: '#3b9eff',
      QUIET: '#30363d',
    };

    data.zones.forEach((z) => {
      if (['QUIET', 'INSUFFICIENT_DATA', 'SINGLE_EVENT'].includes(z.status))
        return;

      const color = statusColors[z.status] || '#30363d';
      const size = z.status === 'OVERDUE' ? 28 : z.status === 'DUE' ? 22 : 16;

      const strikeIcon = L.divIcon({
        className: '',
        html: `
          <div class="pred-strike-marker" style="
            width:${size}px; height:${size}px;
            border: 2px solid ${color};
            box-shadow: 0 0 12px ${color}88;
            color: ${color};
            font-size: ${size > 20 ? 12 : 9}px;
          ">${z.status === 'OVERDUE' ? '!' : z.status === 'DUE' ? '◆' : '◇'}</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      });

      L.marker([z.lat, z.lon], { icon: strikeIcon })
        .bindPopup(
          `
          <div style="font-family:monospace;min-width:240px">
            <div style="color:${color};font-weight:700;margin-bottom:6px">${z.status} — ${z.state}</div>
            <table style="width:100%;border-collapse:collapse;font-size:11px">
              <tr><td style="color:#6a82a0">Clusters</td><td>${z.cluster_count}</td></tr>
              <tr><td style="color:#6a82a0">Last event</td><td>${z.last_event_date} (${z.days_since_last}d ago)</td></tr>
              <tr><td style="color:#6a82a0">Avg interval</td><td>${z.mean_interval_days || '?'} days</td></tr>
              <tr><td style="color:#6a82a0">Predicted next</td><td style="color:${color}">${z.predicted_next || '—'}</td></tr>
              <tr><td style="color:#6a82a0">Days until</td><td style="color:${color}">${
                z.days_until_next !== null
                  ? z.days_until_next < 0
                    ? `${Math.abs(z.days_until_next)}d OVERDUE`
                    : `${z.days_until_next}d`
                  : '—'
              }</td></tr>
            </table>
          </div>`,
        )
        .addTo(_strikeLayer);
    });
  }

  /* ══════════════════════════════════════════════════
     PUBLIC: FOCUS HELPERS (called from panel cards)
     ══════════════════════════════════════════════════ */
  function focusTrajectory(id) {
    if (!_predictionData) return;
    const p = _predictionData.projections.find((x) => x.id === id);
    if (!p || !window._map) return;

    window._map.fitBounds(
      [
        [
          Math.min(p.last_known.lat, p.projected.lat) - 0.3,
          Math.min(p.last_known.lon, p.projected.lon) - 0.3,
        ],
        [
          Math.max(p.last_known.lat, p.projected.lat) + 0.3,
          Math.max(p.last_known.lon, p.projected.lon) + 0.3,
        ],
      ],
      { animate: true, duration: 0.6 },
    );

    closePanel();
    showToast(
      `⟶ Trajectory: ${p.origin_state} → ${p.destination_state || '?'} · ${p.confidence}% confidence`,
      'info',
    );
  }

  function focusHeatCell(lat, lon) {
    if (!window._map) return;
    window._map.setView([lat, lon], 13, { animate: true, duration: 0.6 });
    closePanel();
    showToast(`◉ Base area: ${lat.toFixed(3)}°N, ${lon.toFixed(3)}°E`, 'info');
  }

  function focusZone(lat, lon, state) {
    if (!window._map) return;
    window._map.setView([lat, lon], 10, { animate: true, duration: 0.6 });
    closePanel();
    showToast(`◇ Strike zone: ${state}`, 'info');
  }

  /* ══════════════════════════════════════════════════
     CLEAR ALL LAYERS
     ══════════════════════════════════════════════════ */
  function clearAllLayers() {
    _trajectoryLayer?.clearLayers();
    _heatmapLayer?.clearLayers();
    _strikeLayer?.clearLayers();
    showToast('Prediction layers cleared', 'info');
  }

  /* ══════════════════════════════════════════════════
     EXPORT JSON
     ══════════════════════════════════════════════════ */
  function _exportJSON() {
    if (!_predictionData && !_heatmapData && !_strikeData) {
      showToast('No prediction data to export — run analysis first', 'warning');
      return;
    }
    const payload = {
      exported_at: new Date().toISOString(),
      trajectory: _predictionData,
      heatmap: _heatmapData,
      strike_prediction: _strikeData,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `eagleeye-prediction-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Prediction data exported', 'success');
  }

  /* ══════════════════════════════════════════════════
     POPUP TEMPLATES
     ══════════════════════════════════════════════════ */
  function _trajectoryPopup(p) {
    return `
      <div style="font-family:monospace;min-width:240px;font-size:11px">
        <div style="color:#f0a500;font-weight:700;margin-bottom:8px">
          ⟶ PROJECTED TRAJECTORY
        </div>
        <table style="width:100%;border-collapse:collapse">
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">From</td><td>${p.origin_state}</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Bearing</td><td>${p.bearing}° (${_bearingLabel(p.bearing)})</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Speed est.</td><td>${p.speed_kmh} km/h</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Projected</td><td>${p.distance_km}km in ${p.horizon_hrs}h</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Target</td><td>${p.projected.lat.toFixed(4)}°N, ${p.projected.lon.toFixed(4)}°E</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Confidence</td><td style="color:#f0a500;font-weight:700">${p.confidence}%</td></tr>
          <tr><td style="color:#6a82a0;padding:2px 10px 2px 0">Threat</td><td style="color:${p.threat_level === 'CRITICAL' ? '#ff2d2d' : '#ff6520'}">${p.threat_level}</td></tr>
        </table>
      </div>`;
  }

  /* ══════════════════════════════════════════════════
     UI HELPERS
     ══════════════════════════════════════════════════ */
  function _setRunning(loading, label) {
    const btn = document.getElementById('pred-run-btn');
    const lbl = document.getElementById('pred-run-label');
    const icon = btn?.querySelector('.pred-run-icon');
    if (!btn) return;
    btn.disabled = loading;
    if (lbl) lbl.textContent = label;
    if (icon) {
      icon.style.animation = loading
        ? 'pred-spin 0.8s linear infinite'
        : 'none';
      icon.textContent = loading ? '◌' : '▶';
    }
    btn.classList.toggle('pred-run-btn-loading', loading);
  }

  function _setStatus(label) {
    const el = document.getElementById('pred-status-label');
    if (el) el.textContent = label;
  }

  /* ══════════════════════════════════════════════════
     GEO MATH UTILITIES
     ══════════════════════════════════════════════════ */
  function _toRad(deg) {
    return (deg * Math.PI) / 180;
  }
  function _toDeg(rad) {
    return (rad * 180) / Math.PI;
  }

  function _projectPoint(lat, lon, bearingDeg, distKm) {
    const R = 6371;
    const d = distKm / R;
    const b = _toRad(bearingDeg);
    const lat1 = _toRad(lat);
    const lon1 = _toRad(lon);

    const lat2 = Math.asin(
      Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(b),
    );
    const lon2 =
      lon1 +
      Math.atan2(
        Math.sin(b) * Math.sin(d) * Math.cos(lat1),
        Math.cos(d) - Math.sin(lat1) * Math.sin(lat2),
      );

    return { lat: _toDeg(lat2), lon: _toDeg(lon2) };
  }

  function _bearing(lat1, lon1, lat2, lon2) {
    const dLon = _toRad(lon2 - lon1);
    const y = Math.sin(dLon) * Math.cos(_toRad(lat2));
    const x =
      Math.cos(_toRad(lat1)) * Math.sin(_toRad(lat2)) -
      Math.sin(_toRad(lat1)) * Math.cos(_toRad(lat2)) * Math.cos(dLon);
    return (_toDeg(Math.atan2(y, x)) + 360) % 360;
  }

  function _meanAngle(angles) {
    const sin =
      angles.reduce((s, a) => s + Math.sin(_toRad(a)), 0) / angles.length;
    const cos =
      angles.reduce((s, a) => s + Math.cos(_toRad(a)), 0) / angles.length;
    return (_toDeg(Math.atan2(sin, cos)) + 360) % 360;
  }

  function _bearingLabel(deg) {
    const dirs = [
      'N',
      'NNE',
      'NE',
      'ENE',
      'E',
      'ESE',
      'SE',
      'SSE',
      'S',
      'SSW',
      'SW',
      'WSW',
      'W',
      'WNW',
      'NW',
      'NNW',
    ];
    return dirs[Math.round(deg / 22.5) % 16];
  }

  function _clusterHotspots(features, radiusDeg) {
    const visited = new Set();
    const clusters = [];

    features.forEach((f, i) => {
      if (visited.has(i)) return;
      const [lon, lat] = f.geometry.coordinates;
      const cluster = { points: [f], centroid: { lat, lon } };
      visited.add(i);

      features.forEach((f2, j) => {
        if (visited.has(j)) return;
        const [lon2, lat2] = f2.geometry.coordinates;
        if (
          Math.abs(lat - lat2) < radiusDeg &&
          Math.abs(lon - lon2) < radiusDeg
        ) {
          cluster.points.push(f2);
          visited.add(j);
        }
      });

      const lats = cluster.points.map((p) => p.geometry.coordinates[1]);
      const lons = cluster.points.map((p) => p.geometry.coordinates[0]);
      cluster.centroid = {
        lat: lats.reduce((s, v) => s + v, 0) / lats.length,
        lon: lons.reduce((s, v) => s + v, 0) / lons.length,
      };

      clusters.push(cluster);
    });

    return clusters;
  }

  function _classifyThreatLevel(confidence, speedKmh, classification) {
    if (confidence >= 0.8 || classification === 'rapid_relocation')
      return 'CRITICAL';
    if (confidence >= 0.6 || speedKmh >= 25) return 'HIGH';
    return 'ELEVATED';
  }

  /* ══════════════════════════════════════════════════
     STYLES
     ══════════════════════════════════════════════════ */
  function _injectStyles() {
    if (document.getElementById('prediction-styles')) return;
    const style = document.createElement('style');
    style.id = 'prediction-styles';
    style.textContent = `
      /* ── Panel shell ── */
      #prediction-panel {
        position: fixed;
        top: 60px; left: -480px;
        width: 460px;
        max-height: calc(100vh - 80px);
        overflow-y: auto;
        background: #060a10;
        border: 1px solid #1a2535;
        border-left: none;
        border-radius: 0 6px 6px 0;
        z-index: 1100;
        display: flex;
        flex-direction: column;
        transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        font-family: 'Courier New', monospace;
        font-size: 12px;
        color: #8faab5;
        box-shadow: 4px 0 32px rgba(0,0,0,0.8);
      }
      #prediction-panel.open { left: 0; }

      /* ── Header ── */
      .pred-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 16px;
        border-bottom: 1px solid #1a2535;
        flex-shrink: 0;
        background: linear-gradient(135deg, #060a10 0%, #0d1520 100%);
      }
      .pred-header-left { display: flex; align-items: center; gap: 12px; }
      .pred-icon {
        font-size: 22px;
        color: #f0a500;
        text-shadow: 0 0 12px #f0a50088;
        animation: pred-pulse-icon 3s ease-in-out infinite;
      }
      @keyframes pred-pulse-icon {
        0%,100% { text-shadow: 0 0 8px #f0a50066; }
        50%      { text-shadow: 0 0 20px #f0a500cc; }
      }
      .pred-title {
        font-size: 13px;
        font-weight: 800;
        color: #e8eef8;
        letter-spacing: 2px;
      }
      .pred-subtitle {
        font-size: 9px;
        color: #3a5068;
        letter-spacing: 1.5px;
        margin-top: 2px;
      }
      .pred-header-right {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .pred-live-dot {
        width: 6px; height: 6px;
        background: #f0a500;
        border-radius: 50%;
        animation: pred-blink 1.5s ease-in-out infinite;
      }
      @keyframes pred-blink {
        0%,100% { opacity: 1; }
        50%      { opacity: 0.2; }
      }
      .pred-live-label {
        font-size: 9px;
        letter-spacing: 1.5px;
        color: #f0a500;
      }
      .pred-close {
        background: none; border: none;
        color: #3a5068; cursor: pointer;
        font-size: 14px; padding: 2px 6px;
        transition: color .15s;
      }
      .pred-close:hover { color: #e8eef8; }

      /* ── Controls ── */
      .pred-controls {
        display: flex;
        align-items: flex-end;
        gap: 8px;
        padding: 12px 16px;
        border-bottom: 1px solid #1a2535;
        flex-shrink: 0;
        flex-wrap: wrap;
        background: #080d14;
      }
      .pred-ctrl-group {
        display: flex;
        flex-direction: column;
        gap: 4px;
        flex: 1;
        min-width: 80px;
      }
      .pred-ctrl-label {
        font-size: 8px;
        letter-spacing: 1.5px;
        color: #3a5068;
      }
      .pred-select {
        background: #0d1520;
        border: 1px solid #1a2535;
        color: #8faab5;
        border-radius: 3px;
        padding: 5px 6px;
        font-size: 11px;
        font-family: 'Courier New', monospace;
        width: 100%;
      }
      .pred-select:focus {
        outline: none;
        border-color: #f0a500;
      }
      .pred-run-btn {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        background: linear-gradient(135deg, #1a2800 0%, #2a3f00 100%);
        border: 1px solid #4a7000;
        color: #8dc800;
        border-radius: 3px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: 1px;
        font-family: 'Courier New', monospace;
        transition: all .15s;
        white-space: nowrap;
        align-self: flex-end;
      }
      .pred-run-btn:hover:not(:disabled) {
        background: linear-gradient(135deg, #2a3f00 0%, #3a5500 100%);
        border-color: #6aaa00;
        box-shadow: 0 0 10px #4a700044;
      }
      .pred-run-btn:disabled {
        opacity: 0.5; cursor: not-allowed;
      }
      .pred-run-btn-loading { border-color: #f0a500; color: #f0a500;
        background: linear-gradient(135deg, #1a1400 0%, #2a2000 100%); }
      .pred-run-icon { font-size: 12px; }
      @keyframes pred-spin {
        from { transform: rotate(0deg); }
        to   { transform: rotate(360deg); }
      }

      /* ── Tabs ── */
      .pred-tabs {
        display: flex;
        border-bottom: 1px solid #1a2535;
        flex-shrink: 0;
        background: #060a10;
      }
      .pred-tab {
        flex: 1;
        padding: 9px 4px;
        background: none;
        border: none;
        color: #3a5068;
        cursor: pointer;
        font-size: 9px;
        font-weight: 800;
        letter-spacing: 0.8px;
        font-family: 'Courier New', monospace;
        transition: color .15s, border-bottom .15s;
        border-bottom: 2px solid transparent;
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 4px;
      }
      .pred-tab-icon { font-size: 11px; }
      .pred-tab:hover  { color: #8faab5; }
      .pred-tab.active { color: #f0a500; border-bottom-color: #f0a500; }

      /* ── Tab content ── */
      .pred-tab-content { display: none; padding: 12px; }
      .pred-tab-content.active { display: block; }
      .pred-section-desc {
        font-size: 10px; color: #3a5068;
        margin-bottom: 12px; line-height: 1.6;
        border-left: 2px solid #1a2535;
        padding-left: 8px;
      }

      /* ── Empty state ── */
      .pred-empty {
        text-align: center;
        padding: 40px 20px;
      }
      .pred-empty-icon {
        font-size: 32px; color: #1a2535;
        margin-bottom: 10px;
      }
      .pred-empty-title {
        font-size: 12px; color: #3a5068;
        font-weight: 700; letter-spacing: 1px;
        margin-bottom: 4px;
      }
      .pred-empty-desc {
        font-size: 10px; color: #1a2535;
      }

      /* ── Stat row ── */
      .pred-stat-row {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 6px;
        margin-bottom: 12px;
      }
      .pred-stat-cell {
        background: #080d14;
        border: 1px solid #1a2535;
        border-radius: 3px;
        padding: 8px 4px;
        text-align: center;
      }
      .pred-stat-cell.critical { border-color: #ff2d2d44; }
      .pred-stat-cell.high     { border-color: #ff652044; }
      .pred-stat-cell.elevated { border-color: #f0a50044; }
      .pred-stat-val {
        display: block;
        font-size: 20px;
        font-weight: 800;
        color: #e8eef8;
        line-height: 1;
      }
      .pred-stat-lbl {
        display: block;
        font-size: 8px;
        color: #3a5068;
        letter-spacing: 0.8px;
        margin-top: 3px;
      }

      /* ── Prediction cards ── */
      .pred-card {
        background: #080d14;
        border: 1px solid #1a2535;
        border-radius: 3px;
        margin-bottom: 8px;
        padding: 10px;
        cursor: pointer;
        transition: border-color .15s, background .15s;
        position: relative;
      }
      .pred-card:hover {
        background: #0d1520;
      }
      .pred-card-critical { border-left: 3px solid #ff2d2d; }
      .pred-card-high      { border-left: 3px solid #ff6520; }
      .pred-card-elevated  { border-left: 3px solid #f0a500; }
      .pred-card-monitor   { border-left: 3px solid #3b9eff; }

      .pred-card-header {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-bottom: 8px;
      }
      .pred-card-title {
        flex: 1;
        font-size: 11px;
        font-weight: 700;
        color: #c9d1d9;
      }
      .pred-card-conf {
        font-size: 11px;
        font-weight: 800;
        color: #f0a500;
      }
      .pred-card-body { }
      .pred-card-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 2px 0;
        border-bottom: 1px solid #0d1520;
      }
      .pred-card-row:last-child { border-bottom: none; }
      .pred-card-lbl { font-size: 9px; color: #3a5068; letter-spacing: 0.8px; }
      .pred-card-val { font-size: 10px; color: #8faab5; }
      .pred-card-val.mono { font-family: 'Courier New', monospace; }

      .pred-card-arrow {
        font-size: 8px; color: #1a2535;
        text-align: right; margin-top: 6px;
        letter-spacing: 1px;
      }
      .pred-card:hover .pred-card-arrow { color: #3a5068; }

      /* ── Confidence bar ── */
      .pred-confidence-bar, .pred-intensity-bar {
        height: 2px;
        background: #1a2535;
        border-radius: 1px;
        margin-top: 8px;
        overflow: hidden;
      }
      .pred-confidence-fill, .pred-intensity-fill {
        height: 100%;
        border-radius: 1px;
        transition: width .5s ease;
      }
      .pred-conf-critical { background: #ff2d2d; }
      .pred-conf-high     { background: #ff6520; }
      .pred-conf-elevated { background: #f0a500; }

      /* ── Badges ── */
      .pred-badge {
        font-size: 8px;
        font-weight: 800;
        letter-spacing: 1px;
        padding: 2px 6px;
        border-radius: 2px;
        border: 1px solid;
        white-space: nowrap;
      }
      .pred-badge-critical { color:#ff2d2d; border-color:#ff2d2d44; background:#ff2d2d11; }
      .pred-badge-high     { color:#ff6520; border-color:#ff652044; background:#ff652011; }
      .pred-badge-elevated { color:#f0a500; border-color:#f0a50044; background:#f0a50011; }
      .pred-badge-monitor  { color:#3b9eff; border-color:#3b9eff44; background:#3b9eff11; }

      /* ── Strike cards ── */
      .pred-strike-card {
        display: flex;
        align-items: stretch;
        gap: 0;
        background: #080d14;
        border: 1px solid #1a2535;
        border-radius: 3px;
        margin-bottom: 6px;
        cursor: pointer;
        transition: background .15s;
        overflow: hidden;
      }
      .pred-strike-card:hover { background: #0d1520; }
      .pred-strike-critical { border-left: 3px solid #ff2d2d; }
      .pred-strike-high     { border-left: 3px solid #ff6520; }
      .pred-strike-elevated { border-left: 3px solid #f0a500; }
      .pred-strike-monitor  { border-left: 3px solid #3b9eff; }
      .pred-strike-quiet    { border-left: 3px solid #1a2535; opacity: 0.6; }

      .pred-strike-status-col {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 10px 12px;
        min-width: 60px;
        border-right: 1px solid #1a2535;
      }
      .pred-strike-icon { font-size: 16px; }
      .pred-strike-status-lbl {
        font-size: 7px;
        font-weight: 800;
        letter-spacing: 0.5px;
        margin-top: 3px;
      }
      .pred-strike-lbl-critical { color: #ff2d2d; }
      .pred-strike-lbl-high     { color: #ff6520; }
      .pred-strike-lbl-elevated { color: #f0a500; }
      .pred-strike-lbl-monitor  { color: #3b9eff; }
      .pred-strike-lbl-quiet    { color: #3a5068; }

      .pred-strike-data-col {
        flex: 1;
        padding: 10px 10px;
      }
      .pred-strike-state {
        font-size: 12px;
        font-weight: 700;
        color: #c9d1d9;
        margin-bottom: 3px;
      }
      .pred-strike-meta {
        font-size: 9px;
        color: #3a5068;
        margin-bottom: 4px;
        line-height: 1.4;
      }
      .pred-strike-next {
        font-size: 10px;
        color: #8faab5;
        font-weight: 600;
      }

      .pred-strike-urgency-bar {
        width: 6px;
        background: #1a2535;
        display: flex;
        align-items: flex-end;
      }
      .pred-strike-urgency-fill {
        width: 100%;
        border-radius: 0;
        transition: height .5s ease;
      }
      .pred-urg-critical { background: #ff2d2d; }
      .pred-urg-high     { background: #ff6520; }
      .pred-urg-elevated { background: #f0a500; }
      .pred-urg-monitor  { background: #3b9eff; }
      .pred-urg-quiet    { background: #1a2535; }

      /* ── Intel brief ── */
      .pred-brief {
        font-size: 11px;
        line-height: 1.6;
      }
      .pred-brief-header {
        border: 1px solid #f0a50033;
        padding: 8px 12px;
        margin-bottom: 12px;
        background: #f0a50009;
        border-radius: 3px;
      }
      .pred-brief-classification {
        font-size: 9px;
        letter-spacing: 2px;
        color: #f0a500;
        font-weight: 800;
        margin-bottom: 3px;
      }
      .pred-brief-timestamp {
        font-size: 9px;
        color: #3a5068;
      }
      .pred-brief-section {
        margin-bottom: 14px;
      }
      .pred-brief-section-title {
        font-size: 9px;
        letter-spacing: 2px;
        color: #3a5068;
        font-weight: 800;
        border-bottom: 1px solid #1a2535;
        padding-bottom: 4px;
        margin-bottom: 8px;
      }
      .pred-brief-text {
        color: #8faab5;
        line-height: 1.7;
      }
      .pred-brief-item {
        display: flex;
        gap: 8px;
        margin-bottom: 6px;
        padding: 6px 8px;
        border-radius: 2px;
        background: #080d14;
        border: 1px solid #1a2535;
      }
      .pred-brief-item-critical { border-left: 2px solid #ff2d2d; }
      .pred-brief-item-high     { border-left: 2px solid #ff6520; }
      .pred-brief-item-elevated { border-left: 2px solid #f0a500; }
      .pred-brief-item-base     { border-left: 2px solid #3b9eff; }
      .pred-brief-bullet { color: #f0a500; flex-shrink: 0; }
      .pred-brief-footer {
        font-size: 8px;
        letter-spacing: 1.5px;
        color: #1a2535;
        text-align: center;
        margin-top: 16px;
        padding-top: 12px;
        border-top: 1px solid #1a2535;
      }

      /* ── Text utilities ── */
      .text-critical { color: #ff2d2d !important; font-weight: 700; }
      .mono { font-family: 'Courier New', monospace; }

      /* ── Footer ── */
      .pred-footer {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 16px;
        border-top: 1px solid #1a2535;
        flex-shrink: 0;
        background: #060a10;
      }
      .pred-footer-meta {
        flex: 1;
        text-align: center;
        font-size: 9px;
        color: #1a2535;
        letter-spacing: 0.5px;
      }
      .pred-ghost-btn {
        background: none;
        border: 1px solid #1a2535;
        color: #3a5068;
        padding: 5px 10px;
        border-radius: 3px;
        cursor: pointer;
        font-size: 9px;
        font-family: 'Courier New', monospace;
        letter-spacing: 0.5px;
        transition: all .15s;
      }
      .pred-ghost-btn:hover {
        border-color: #3a5068;
        color: #8faab5;
      }

      /* ── Map markers ── */
      .pred-pulse-marker {
        width: 14px; height: 14px;
        border-radius: 50%;
        border: 2px solid rgba(255,255,255,0.3);
        animation: pred-map-pulse 2s ease-in-out infinite;
      }
      @keyframes pred-map-pulse {
        0%,100% { transform: scale(1); opacity: 1; }
        50%      { transform: scale(1.3); opacity: 0.7; }
      }
      .pred-arrow-marker {
        font-size: 18px;
        filter: drop-shadow(0 0 4px currentColor);
      }
      .pred-traj-label {
        font-size: 9px;
        font-weight: 800;
        font-family: 'Courier New', monospace;
        border: 1px solid;
        border-radius: 2px;
        padding: 1px 4px;
        background: rgba(6,10,16,0.85);
        white-space: nowrap;
      }
      .pred-base-marker {
        width: 22px; height: 22px;
        background: rgba(6,10,16,0.85);
        border: 2px solid;
        border-radius: 3px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        font-weight: 800;
      }
      .pred-strike-marker {
        border-radius: 2px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        background: rgba(6,10,16,0.85);
        animation: pred-strike-pulse 2s ease-in-out infinite;
      }
      @keyframes pred-strike-pulse {
        0%,100% { transform: scale(1); }
        50%      { transform: scale(1.15); }
      }

      /* ── Toolbar button ── */
      .pred-toolbar-btn {
        font-family: 'Courier New', monospace;
        font-size: 10px;
        font-weight: 800;
        letter-spacing: 1px;
      }
      .pred-toolbar-btn.active {
        color: #f0a500 !important;
        border-color: #f0a500 !important;
      }

      /* ── Responsive ── */
      @media (max-width: 480px) {
        #prediction-panel {
          width: 100vw;
          left: -100vw;
          border-radius: 0;
        }
        #prediction-panel.open { left: 0; }
      }

      /* ── Hidden utility ── */
      .hidden { display: none !important; }
    `;
    document.head.appendChild(style);
  }

  /* ══════════════════════════════════════════════════
     PUBLIC API
     ══════════════════════════════════════════════════ */
  return {
    init,
    openPanel,
    closePanel,
    togglePanel,
    runAnalysis,
    clearAllLayers,
    focusTrajectory,
    focusHeatCell,
    focusZone,
  };
})();

window.PredictionView = PredictionView;
