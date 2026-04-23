/* ══════════════════════════════════════════
   mapView.js — Map Initialization & Layers v3.4
   Changes from v3.3:
   • Legend shortcuts updated to include X (ML panel)
   • _updateLegendStates syncs ML button in StatsBar
   • loadAllData passes map reference to MLView
     so ML markers layer is always on top
   ══════════════════════════════════════════ */

const MapView = (() => {
  let map;

  /* ── Nigeria default bounds ── */
  const NIGERIA_BOUNDS = [
    [4.0, 2.7],
    [14.0, 15.0],
  ];
  const NIGERIA_CENTER = [9.5, 8.0];
  const NIGERIA_ZOOM = 6;

  // ══════════════════════════════════════════
  // INIT MAP
  // ══════════════════════════════════════════
  function init() {
    map = L.map('map', { zoomControl: true, preferCanvas: true }).setView(
      NIGERIA_CENTER,
      NIGERIA_ZOOM,
    );

    const dark = L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
      { attribution: '© OpenStreetMap © CARTO', maxZoom: 19 },
    );
    const satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: '© Esri', maxZoom: 19 },
    );
    dark.addTo(map);
    L.control
      .layers(
        { '🌑 Dark': dark, '🛰️ Satellite': satellite },
        {},
        { position: 'topright' },
      )
      .addTo(map);

    const redZones = [
      {
        name: 'Northwest Corridor',
        bounds: [
          [11.0, 4.0],
          [14.0, 9.0],
        ],
        color: '#ff2d2d',
      },
      {
        name: 'Northeast Corridor',
        bounds: [
          [10.0, 11.0],
          [14.0, 15.0],
        ],
        color: '#ff2d2d',
      },
      {
        name: 'North Central',
        bounds: [
          [8.0, 5.0],
          [11.0, 10.0],
        ],
        color: '#f0a500',
      },
    ];
    redZones.forEach((z) => {
      L.rectangle(z.bounds, {
        color: z.color,
        weight: 1.5,
        fillOpacity: 0.04,
        dashArray: '6 4',
      })
        .addTo(map)
        .bindTooltip(z.name, { sticky: true });
    });
    L.rectangle(NIGERIA_BOUNDS, {
      color: '#1e2d3d',
      weight: 1,
      fillOpacity: 0,
      dashArray: '2 4',
    }).addTo(map);

    addLegend();
    _addHomeButton();
    window._map = map;
  }

  /* ══════════════════════════════════════════
     HOME BUTTON
     ══════════════════════════════════════════ */
  function _addHomeButton() {
    const HomeControl = L.Control.extend({
      options: { position: 'topleft' },
      onAdd: function () {
        const container = L.DomUtil.create(
          'div',
          'leaflet-bar leaflet-control leaflet-control-home',
        );
        const button = L.DomUtil.create('a', 'leaflet-home-btn', container);

        button.innerHTML = '⌂';
        button.href = '#';
        button.title = 'Reset view to Nigeria (H)';
        button.setAttribute('role', 'button');
        button.setAttribute('aria-label', 'Reset map view to Nigeria');

        Object.assign(button.style, {
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '30px',
          height: '30px',
          fontSize: '18px',
          fontWeight: '700',
          lineHeight: '30px',
          textDecoration: 'none',
          background: '#1a1f2e',
          color: '#e8eef8',
          cursor: 'pointer',
          transition: 'background 0.2s, color 0.2s',
        });

        L.DomEvent.disableClickPropagation(container);
        L.DomEvent.disableScrollPropagation(container);

        L.DomEvent.on(button, 'click', function (e) {
          L.DomEvent.preventDefault(e);
          const features = State.get('allFeatures');
          if (features && features.length > 0) {
            resetView(features);
            showToast(
              `🏠 View reset — ${features.length} hotspots in bounds`,
              'info',
            );
          } else {
            map.setView(NIGERIA_CENTER, NIGERIA_ZOOM, {
              animate: true,
              duration: 0.6,
            });
            showToast('🏠 View reset to Nigeria', 'info');
          }
        });

        L.DomEvent.on(button, 'mouseenter', function () {
          button.style.background = '#2a3550';
          button.style.color = '#3b9eff';
        });
        L.DomEvent.on(button, 'mouseleave', function () {
          button.style.background = '#1a1f2e';
          button.style.color = '#e8eef8';
        });

        return container;
      },
    });

    new HomeControl().addTo(map);
  }

  /* ══════════════════════════════════════════
     RESET MAP VIEW
     ══════════════════════════════════════════ */
  function resetView(features) {
    if (!map) return;

    if (features && features.length > 0) {
      try {
        const lats = features.map((f) => f.geometry.coordinates[1]);
        const lons = features.map((f) => f.geometry.coordinates[0]);

        const minLat = Math.min(...lats);
        const maxLat = Math.max(...lats);
        const minLon = Math.min(...lons);
        const maxLon = Math.max(...lons);

        const latPad = (maxLat - minLat) * 0.1 || 0.5;
        const lonPad = (maxLon - minLon) * 0.1 || 0.5;

        map.fitBounds(
          [
            [minLat - latPad, minLon - lonPad],
            [maxLat + latPad, maxLon + lonPad],
          ],
          { maxZoom: 12, padding: [30, 30], animate: true, duration: 0.8 },
        );

        console.log(
          `[MapView] View reset to fit ${features.length} hotspots ` +
            `(${minLat.toFixed(2)}–${maxLat.toFixed(2)}°N, ` +
            `${minLon.toFixed(2)}–${maxLon.toFixed(2)}°E)`,
        );
      } catch (err) {
        console.warn('[MapView] fitBounds failed, using default view:', err);
        map.setView(NIGERIA_CENTER, NIGERIA_ZOOM, { animate: true });
      }
    } else {
      map.setView(NIGERIA_CENTER, NIGERIA_ZOOM, { animate: true });
      console.log('[MapView] View reset to Nigeria default (no features)');
    }
  }

  /* ══════════════════════════════════════════
     DELAY BANNER
     ══════════════════════════════════════════ */
  function _showDelayBanner(delayStatus) {
    const banner = el('alert-banner');
    const bannerText = el('alert-banner-text');
    if (!banner || !bannerText) return;

    const withheldMsg =
      delayStatus.withheld > 0
        ? ` · ${delayStatus.withheld} recent hotspots withheld`
        : '';

    bannerText.textContent =
      `🔒 Data delayed by ${delayStatus.delayMinutes} min for security` +
      withheldMsg +
      ` · Sign in for real-time access`;

    banner.classList.add('visible', 'delay-banner');
    banner.classList.remove('threat-banner');

    const sourceNote = el('source-note');
    if (sourceNote) {
      sourceNote.innerHTML =
        `Source: NASA FIRMS · VIIRS SNPP NRT · ` +
        `<span style="color:var(--elevated)">⏱ ${delayStatus.delayMinutes}min delay</span>`;
    }

    console.log(
      `[SECURITY] Anonymous access — data delayed ${delayStatus.delayMinutes}min` +
        (delayStatus.withheld > 0
          ? `, ${delayStatus.withheld} features withheld`
          : ''),
    );
  }

  function _hideDelayBanner() {
    const banner = el('alert-banner');
    if (banner) {
      banner.classList.remove('delay-banner');
      if (!banner.classList.contains('threat-banner')) {
        banner.classList.remove('visible');
      }
    }
    const sourceNote = el('source-note');
    if (sourceNote) {
      sourceNote.textContent = 'Source: NASA FIRMS · VIIRS SNPP NRT';
    }
  }

  /* ══════════════════════════════════════════
     LEGEND
     ══════════════════════════════════════════ */
  function addLegend() {
    const legend = L.control({ position: 'bottomright' });
    legend.onAdd = () => {
      const div = L.DomUtil.create('div', 'map-legend');
      div.innerHTML = `
        <div class="legend-group-title">
          Threat Priority
          <span class="legend-filter-reset" id="leg-reset"
                style="display:none; float:right; cursor:pointer;
                       font-size:9px; color:var(--info)"
                title="Clear filter">✕ CLEAR</span>
        </div>

        <div class="legend-row legend-clickable" data-filter="CRITICAL">
          <div class="legend-dot" style="background:var(--critical)"></div>
          <span>CRITICAL</span>
          <span class="legend-count" id="leg-critical">0</span>
        </div>
        <div class="legend-row legend-clickable" data-filter="HIGH">
          <div class="legend-dot" style="background:var(--high)"></div>
          <span>HIGH</span>
          <span class="legend-count" id="leg-high">0</span>
        </div>
        <div class="legend-row legend-clickable" data-filter="ELEVATED">
          <div class="legend-dot" style="background:var(--elevated)"></div>
          <span>ELEVATED</span>
          <span class="legend-count" id="leg-elevated">0</span>
        </div>
        <div class="legend-row legend-clickable" data-filter="MONITOR">
          <div class="legend-dot" style="background:var(--monitor)"></div>
          <span>MONITOR</span>
          <span class="legend-count" id="leg-monitor">0</span>
        </div>

        <div class="legend-group-title">
          Vegetation
          <span class="legend-toggle" id="leg-veg-toggle"
                style="float:right; cursor:pointer; font-size:9px"
                title="Toggle vegetation layer">OFF</span>
        </div>

        <div class="legend-row legend-clickable" data-veg="clearing">
          <div class="legend-diamond" style="background:var(--critical)"></div>
          <span>Clearing</span>
          <span class="legend-count" id="leg-clearing">0</span>
        </div>
        <div class="legend-row legend-clickable" data-veg="burn_scar">
          <div class="legend-diamond" style="background:var(--high)"></div>
          <span>Burn Scar</span>
          <span class="legend-count" id="leg-burn">0</span>
        </div>
        <div class="legend-row legend-clickable" data-veg="regrowth">
          <div class="legend-diamond" style="background:var(--monitor)"></div>
          <span>Regrowth</span>
          <span class="legend-count" id="leg-regrowth">0</span>
        </div>

        <div class="legend-group-title">
          Movement
          <span class="legend-toggle" id="leg-move-toggle"
                style="float:right; cursor:pointer; font-size:9px"
                title="Toggle movement layer">OFF</span>
        </div>

        <div class="legend-row legend-clickable" data-action="movement">
          <div class="legend-line" style="border-color:var(--high)"></div>
          <span>Vector</span>
          <span class="legend-count" id="leg-movements">0</span>
        </div>

        <div class="legend-shortcuts">
          <kbd>R</kbd> refresh &nbsp;<kbd>C</kbd> clusters<br>
          <kbd>V</kbd> veg &nbsp;<kbd>M</kbd> move &nbsp;<kbd>I</kbd> intel &nbsp;<kbd>X</kbd> ML
        </div>
      `;

      div.addEventListener('click', _handleLegendClick);
      L.DomEvent.disableClickPropagation(div);
      L.DomEvent.disableScrollPropagation(div);

      return div;
    };
    legend.addTo(map);
  }

  /* ══════════════════════════════════════════
     LEGEND CLICK HANDLER
     ══════════════════════════════════════════ */
  function _handleLegendClick(e) {
    const row = e.target.closest('[data-filter]');
    const vegRow = e.target.closest('[data-veg]');
    const actionRow = e.target.closest('[data-action]');
    const vegToggle = e.target.closest('#leg-veg-toggle');
    const moveToggle = e.target.closest('#leg-move-toggle');
    const resetBtn = e.target.closest('#leg-reset');

    if (row) {
      _filterByPriority(row.dataset.filter);
      return;
    }
    if (resetBtn) {
      _clearPriorityFilter();
      return;
    }
    if (vegRow) {
      _handleVegClick(vegRow.dataset.veg);
      return;
    }
    if (vegToggle) {
      toggleVegetationLayer();
      _updateLegendStates();
      return;
    }
    if (moveToggle) {
      toggleMovementLayer();
      _updateLegendStates();
      return;
    }
    if (actionRow && actionRow.dataset.action === 'movement') {
      _handleMovementClick();
    }
  }

  /* ══════════════════════════════════════════
     PRIORITY FILTERING
     ══════════════════════════════════════════ */
  let _activePriorityFilter = null;

  function _filterByPriority(priority) {
    const allFeatures = State.get('allFeatures');
    if (!allFeatures || allFeatures.length === 0) {
      showToast('No hotspot data loaded yet', 'warning');
      return;
    }

    if (_activePriorityFilter === priority) {
      _clearPriorityFilter();
      return;
    }

    _activePriorityFilter = priority;

    const filtered = allFeatures.filter(
      (f) => f.properties.priority === priority,
    );

    if (filtered.length === 0) {
      showToast(`No ${priority} threats found`, 'info');
      _clearPriorityFilter();
      return;
    }

    renderHotspots(filtered);

    const lats = filtered.map((f) => f.geometry.coordinates[1]);
    const lons = filtered.map((f) => f.geometry.coordinates[0]);
    map.fitBounds(
      [
        [Math.min(...lats) - 0.2, Math.min(...lons) - 0.2],
        [Math.max(...lats) + 0.2, Math.max(...lons) + 0.2],
      ],
      { maxZoom: 10, animate: true, duration: 0.6 },
    );

    _updateLegendHighlight(priority);
    showToast(`Showing ${filtered.length} ${priority} threats`, 'info');

    const resetBtn = document.getElementById('leg-reset');
    if (resetBtn) resetBtn.style.display = 'inline';
  }

  function _clearPriorityFilter() {
    _activePriorityFilter = null;
    const allFeatures = State.get('allFeatures');
    renderHotspots(allFeatures);
    _updateLegendHighlight(null);
    resetView(allFeatures);

    const resetBtn = document.getElementById('leg-reset');
    if (resetBtn) resetBtn.style.display = 'none';

    showToast('Showing all threats', 'info');
  }

  function _updateLegendHighlight(activePriority) {
    document.querySelectorAll('[data-filter]').forEach((row) => {
      if (!activePriority) {
        row.style.opacity = '1';
        row.style.borderLeft = 'none';
        row.style.paddingLeft = '';
      } else if (row.dataset.filter === activePriority) {
        row.style.opacity = '1';
        row.style.borderLeft = '3px solid var(--info)';
        row.style.paddingLeft = '6px';
      } else {
        row.style.opacity = '0.35';
        row.style.borderLeft = 'none';
        row.style.paddingLeft = '';
      }
    });
  }

  /* ══════════════════════════════════════════
     VEGETATION CLICK
     ══════════════════════════════════════════ */
  async function _handleVegClick(classification) {
    if (!State.get('vegLayerVisible')) {
      showToast('Enabling vegetation layer...', 'info');
      State.set('vegLayerVisible', true);
      el('veg-toggle')?.classList.add('veg-on');

      if (State.get('vegEvents').length === 0) {
        await loadVegetationEvents();
      } else {
        renderVegetationLayer();
      }
    }

    const events = State.get('vegEvents');
    if (!events || events.length === 0) {
      showToast('No vegetation data available', 'warning');
      return;
    }

    const matching = events.filter((e) => e.classification === classification);

    if (matching.length === 0) {
      showToast(`No ${classification.replace('_', ' ')} events found`, 'info');
      return;
    }

    const lats = matching.map((e) => e.latitude);
    const lons = matching.map((e) => e.longitude);
    map.fitBounds(
      [
        [Math.min(...lats) - 0.3, Math.min(...lons) - 0.3],
        [Math.max(...lats) + 0.3, Math.max(...lons) + 0.3],
      ],
      { maxZoom: 11, animate: true, duration: 0.6 },
    );

    showToast(
      `🌿 Zoomed to ${matching.length} ${classification.replace('_', ' ')} events`,
      'success',
    );
    _updateLegendStates();
  }

  /* ══════════════════════════════════════════
     MOVEMENT CLICK
     ══════════════════════════════════════════ */
  async function _handleMovementClick() {
    const delayStatus = State.get('dataDelayStatus');
    if (delayStatus?.isDelayed) {
      showToast(
        '🔒 Movement intel requires sign-in for real-time access',
        'warning',
      );
      return;
    }

    if (!State.get('movementLayerVisible')) {
      showToast('Enabling movement layer...', 'info');
      State.set('movementLayerVisible', true);
      el('movement-toggle')?.classList.add('move-on');

      if (!State.get('movementData')) {
        await loadMovementData();
      }
      renderMovementLayer();
    }

    const data = State.get('movementData');
    const mvs = data?.movements || [];

    if (mvs.length === 0) {
      showToast('No movement vectors detected', 'info');
      return;
    }

    const allLats = [];
    const allLons = [];
    mvs.forEach((mv) => {
      allLats.push(mv.origin_lat, mv.destination_lat);
      allLons.push(mv.origin_lon, mv.destination_lon);
    });

    map.fitBounds(
      [
        [Math.min(...allLats) - 0.3, Math.min(...allLons) - 0.3],
        [Math.max(...allLats) + 0.3, Math.max(...allLons) + 0.3],
      ],
      { maxZoom: 10, animate: true, duration: 0.6 },
    );

    showToast(`🧭 Showing ${mvs.length} movement vectors`, 'success');
    _updateLegendStates();
  }

  /* ══════════════════════════════════════════
     UPDATE LEGEND TOGGLE LABELS
     Also keeps StatsBar ML button in sync
     ══════════════════════════════════════════ */
  function _updateLegendStates() {
    const vegToggle = document.getElementById('leg-veg-toggle');
    const moveToggle = document.getElementById('leg-move-toggle');
    const delayStatus = State.get('dataDelayStatus');

    if (vegToggle) {
      const on = State.get('vegLayerVisible');
      vegToggle.textContent = on ? '● ON' : 'OFF';
      vegToggle.style.color = on ? 'var(--monitor)' : 'var(--text-muted)';
    }

    if (moveToggle) {
      const on = State.get('movementLayerVisible');
      if (delayStatus?.isDelayed) {
        moveToggle.textContent = '🔒';
        moveToggle.style.color = 'var(--text-muted)';
        moveToggle.title = 'Sign in for movement intel';
      } else {
        moveToggle.textContent = on ? '● ON' : 'OFF';
        moveToggle.style.color = on ? 'var(--monitor)' : 'var(--text-muted)';
        moveToggle.title = 'Toggle movement layer';
      }
    }

    document.querySelectorAll('[data-veg]').forEach((row) => {
      row.style.opacity = State.get('vegLayerVisible') ? '1' : '0.4';
    });

    document.querySelectorAll('[data-action="movement"]').forEach((row) => {
      if (delayStatus?.isDelayed) {
        row.style.opacity = '0.3';
        row.title = 'Sign in for movement intel';
      } else {
        row.style.opacity = State.get('movementLayerVisible') ? '1' : '0.4';
        row.title = '';
      }
    });

    // ── Keep StatsBar ML button active state in sync ──
    if (typeof StatsBar !== 'undefined' && StatsBar.setMLActive) {
      const mlPanelOpen =
        document.getElementById('ml-panel')?.classList.contains('open') ??
        false;
      StatsBar.setMLActive(mlPanelOpen);
    }
  }

  /* ══════════════════════════════════════════
     CLEAR ALL DYNAMIC LAYERS
     ══════════════════════════════════════════ */
  function _clearAllDynamicLayers() {
    const hotspotLayer = State.get('hotspotLayer');
    if (hotspotLayer) {
      map.removeLayer(hotspotLayer);
      State.set('hotspotLayer', null);
    }

    const clusterLayer = State.get('clusterLayer');
    if (clusterLayer) {
      map.removeLayer(clusterLayer);
      State.set('clusterLayer', null);
    }

    const vegLayerGroup = State.get('vegLayerGroup');
    if (vegLayerGroup) {
      map.removeLayer(vegLayerGroup);
      State.set('vegLayerGroup', null);
    }

    const movementLayerGroup = State.get('movementLayerGroup');
    if (movementLayerGroup) {
      map.removeLayer(movementLayerGroup);
      State.set('movementLayerGroup', null);
    }

    const zonesLayerGroup = State.get('zonesLayerGroup');
    if (zonesLayerGroup) {
      map.removeLayer(zonesLayerGroup);
      State.set('zonesLayerGroup', null);
    }

    _activePriorityFilter = null;
    _updateLegendHighlight(null);
    const resetBtn = document.getElementById('leg-reset');
    if (resetBtn) resetBtn.style.display = 'none';

    console.log('[MapView] All dynamic layers cleared');
  }

  /* ══════════════════════════════════════════
     HOTSPOT MARKER
     ══════════════════════════════════════════ */
  function createHotspotMarker(f) {
    const [lon, lat] = f.geometry.coordinates;
    const p = f.properties;
    const priority = p.priority || 'MONITOR';
    const color = priorityColor(priority);

    const radius =
      priority === 'CRITICAL'
        ? 9
        : priority === 'HIGH'
          ? 7
          : priority === 'ELEVATED'
            ? 6
            : 4;

    const weight =
      priority === 'CRITICAL' ? 2.5 : priority === 'HIGH' ? 1.5 : 1;

    const marker = L.circleMarker([lat, lon], {
      radius,
      fillColor: color,
      color,
      weight,
      opacity: 0.9,
      fillOpacity: 0.75,
    });

    marker.bindPopup(buildHotspotPopup(f), { maxWidth: 380 });
    return marker;
  }

  /* ══════════════════════════════════════════
     VEGETATION MARKER
     ══════════════════════════════════════════ */
  function createVegMarker(evt) {
    const lat = evt.latitude;
    const lon = evt.longitude;
    const color = vegClassColor(evt.classification);
    const size =
      evt.severity === 'critical' ? 16 : evt.severity === 'high' ? 13 : 10;

    const icon = L.divIcon({
      className: '',
      html: `<div style="
        width:${size}px; height:${size}px;
        background:${color}; border:2px solid ${color};
        transform:rotate(45deg); border-radius:2px;
        opacity:0.85; box-shadow:0 0 6px ${color}66;
      "></div>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    });

    const marker = L.marker([lat, lon], { icon });
    marker.bindPopup(buildVegPopup(evt), { maxWidth: 380 });
    return marker;
  }

  /* ══════════════════════════════════════════
     RENDER HOTSPOTS
     ══════════════════════════════════════════ */
  function renderHotspots(features) {
    const hotspotLayer = State.get('hotspotLayer');
    const clusterLayer = State.get('clusterLayer');
    if (hotspotLayer) {
      map.removeLayer(hotspotLayer);
      State.set('hotspotLayer', null);
    }
    if (clusterLayer) {
      map.removeLayer(clusterLayer);
      State.set('clusterLayer', null);
    }

    if (!features || features.length === 0) {
      console.log('[MapView] No features to render');
      setText('leg-critical', 0);
      setText('leg-high', 0);
      setText('leg-elevated', 0);
      setText('leg-monitor', 0);
      return;
    }

    const useClustering = State.get('useClustering');

    if (useClustering) {
      const cl = L.markerClusterGroup({
        maxClusterRadius: 40,
        spiderfyOnMaxZoom: true,
        showCoverageOnHover: false,
        iconCreateFunction: (cluster) => {
          const n = cluster.getChildCount();
          const sz = n > 50 ? 'large' : n > 20 ? 'medium' : 'small';
          return L.divIcon({
            html: `<div>${n}</div>`,
            className: `marker-cluster marker-cluster-${sz}`,
            iconSize: L.point(40, 40),
          });
        },
      });
      features.forEach((f) => cl.addLayer(createHotspotMarker(f)));
      map.addLayer(cl);
      State.set('clusterLayer', cl);
    } else {
      const hl = L.layerGroup();
      features.forEach((f) => hl.addLayer(createHotspotMarker(f)));
      hl.addTo(map);
      State.set('hotspotLayer', hl);
    }

    const counts = { CRITICAL: 0, HIGH: 0, ELEVATED: 0, MONITOR: 0 };
    features.forEach((f) => {
      counts[f.properties.priority || 'MONITOR']++;
    });
    setText('leg-critical', counts.CRITICAL);
    setText('leg-high', counts.HIGH);
    setText('leg-elevated', counts.ELEVATED);
    setText('leg-monitor', counts.MONITOR);
  }

  /* ══════════════════════════════════════════
     VEGETATION LAYER
     ══════════════════════════════════════════ */
  function renderVegetationLayer() {
    const vgl = State.get('vegLayerGroup');
    if (vgl) {
      map.removeLayer(vgl);
      State.set('vegLayerGroup', null);
    }
    if (!State.get('vegLayerVisible') || State.get('vegEvents').length === 0) {
      _updateLegendStates();
      return;
    }

    const gl = L.layerGroup();
    State.get('vegEvents').forEach((evt) => gl.addLayer(createVegMarker(evt)));
    gl.addTo(map);
    State.set('vegLayerGroup', gl);

    const cls = { clearing: 0, burn_scar: 0, regrowth: 0 };
    State.get('vegEvents').forEach((e) => {
      if (cls[e.classification] !== undefined) cls[e.classification]++;
    });
    setText('leg-clearing', cls.clearing);
    setText('leg-burn', cls.burn_scar);
    setText('leg-regrowth', cls.regrowth);

    _updateLegendStates();
  }

  /* ══════════════════════════════════════════
     MOVEMENT LAYER
     ══════════════════════════════════════════ */
  function renderMovementLayer() {
    const mgl = State.get('movementLayerGroup');
    if (mgl) {
      map.removeLayer(mgl);
      State.set('movementLayerGroup', null);
    }
    if (!State.get('movementLayerVisible') || !State.get('movementData')) {
      _updateLegendStates();
      return;
    }

    const gl = L.layerGroup();
    const mvs = State.get('movementData').movements || [];

    mvs.forEach((mv) => {
      const color =
        mv.classification === 'rapid_relocation'
          ? '#ff2d2d'
          : mv.classification === 'corridor'
            ? '#f0a500'
            : '#ff6520';

      const line = L.polyline(
        [
          [mv.origin_lat, mv.origin_lon],
          [mv.destination_lat, mv.destination_lon],
        ],
        { color, weight: 2.5, opacity: 0.8, dashArray: '8 6' },
      );

      const arrowIcon = L.divIcon({
        className: '',
        html: `<div style="font-size:16px;color:${color};transform:rotate(${mv.bearing_degrees - 90}deg);text-shadow:0 0 4px rgba(0,0,0,0.6)">➤</div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });
      const arrow = L.marker([mv.destination_lat, mv.destination_lon], {
        icon: arrowIcon,
      });

      const origin = L.circleMarker([mv.origin_lat, mv.origin_lon], {
        radius: 5,
        color,
        weight: 2,
        fillOpacity: 0,
        opacity: 0.8,
      });

      const popupHtml = buildMovementPopup(mv);
      line.bindPopup(popupHtml, { maxWidth: 360 });
      arrow.bindPopup(popupHtml, { maxWidth: 360 });
      origin.bindPopup(popupHtml, { maxWidth: 360 });

      gl.addLayer(line);
      gl.addLayer(arrow);
      gl.addLayer(origin);
    });

    gl.addTo(map);
    State.set('movementLayerGroup', gl);
    setText('leg-movements', mvs.length);

    _updateLegendStates();
  }

  /* ══════════════════════════════════════════
     MONITORING ZONES
     ══════════════════════════════════════════ */
  function renderMonitoringZones() {
    const zgl = State.get('zonesLayerGroup');
    if (zgl) {
      map.removeLayer(zgl);
      State.set('zonesLayerGroup', null);
    }
    if (!State.get('zonesVisible') || State.get('monitoringZones').length === 0)
      return;

    const gl = L.layerGroup();
    State.get('monitoringZones').forEach((z) => {
      const [w, s, e, n] = z.bbox;
      const color =
        z.risk_level === 'critical'
          ? '#ff2d2d'
          : z.risk_level === 'high'
            ? '#ff6520'
            : '#f0a500';
      L.rectangle(
        [
          [s, w],
          [n, e],
        ],
        {
          color: '#4fa3ff',
          weight: 2,
          fillColor: color,
          fillOpacity: 0.07,
          dashArray: '8 4',
        },
      )
        .bindTooltip(
          `<strong>${z.name}</strong><br>${z.risk_level.toUpperCase()} — ${z.description}`,
          { sticky: true },
        )
        .addTo(gl);
    });
    gl.addTo(map);
    State.set('zonesLayerGroup', gl);
  }

  /* ══════════════════════════════════════════
     TOGGLE FUNCTIONS
     ══════════════════════════════════════════ */
  function toggleClustering() {
    const val = !State.get('useClustering');
    State.set('useClustering', val);
    const btn = el('cluster-toggle');
    if (btn) {
      btn.classList.toggle('active', val);
      btn.textContent = val ? '⬡ Clusters' : '⬡ Points';
    }
    applyFilter();
  }

  async function toggleVegetationLayer() {
    const val = !State.get('vegLayerVisible');
    State.set('vegLayerVisible', val);
    el('veg-toggle')?.classList.toggle('veg-on', val);
    if (val && State.get('vegEvents').length === 0) {
      await loadVegetationEvents();
    } else {
      renderVegetationLayer();
    }
    _updateLegendStates();
  }

  async function toggleMonitoringZones() {
    const val = !State.get('zonesVisible');
    State.set('zonesVisible', val);
    el('zones-toggle')?.classList.toggle('active', val);
    if (val && State.get('monitoringZones').length === 0) {
      await loadMonitoringZones();
    } else {
      renderMonitoringZones();
    }
  }

  async function toggleMovementLayer() {
    const delayStatus = State.get('dataDelayStatus');
    if (delayStatus?.isDelayed) {
      showToast(
        '🔒 Movement intelligence requires authorized access. Please sign in.',
        'warning',
      );
      return;
    }
    const val = !State.get('movementLayerVisible');
    State.set('movementLayerVisible', val);
    el('movement-toggle')?.classList.toggle('move-on', val);
    if (val && !State.get('movementData')) {
      await loadMovementData();
    }
    renderMovementLayer();
    _updateLegendStates();
  }

  /* ══════════════════════════════════════════
     FILTER
     ══════════════════════════════════════════ */
  function getFilteredFeatures() {
    const f = el('confidence-filter')?.value || 'all';
    const all = State.get('allFeatures');
    if (!all) return [];
    if (f === 'all') return all;
    if (f === 'H') return all.filter((x) => x.properties.confidence === 'H');
    if (f === 'HN')
      return all.filter((x) => ['H', 'N'].includes(x.properties.confidence));
    if (f === 'L') return all.filter((x) => x.properties.confidence === 'L');
    if (f === 'critical')
      return all.filter((x) => x.properties.priority === 'CRITICAL');
    if (f === 'high+')
      return all.filter((x) =>
        ['CRITICAL', 'HIGH'].includes(x.properties.priority),
      );
    return all;
  }

  function applyFilter() {
    _activePriorityFilter = null;
    _updateLegendHighlight(null);
    const resetBtn = document.getElementById('leg-reset');
    if (resetBtn) resetBtn.style.display = 'none';
    const filtered = getFilteredFeatures();
    renderHotspots(filtered);
    resetView(filtered);
  }

  /* ══════════════════════════════════════════
     NAVIGATION
     ══════════════════════════════════════════ */
  function zoomTo(lat, lon) {
    map.setView([lat, lon], 12, { animate: true, duration: 0.6 });
  }

  function zoomToState(name) {
    const sf = State.get('allFeatures').filter(
      (f) => f.properties.state === name,
    );
    if (!sf.length) return;
    const lats = sf.map((f) => f.geometry.coordinates[1]);
    const lons = sf.map((f) => f.geometry.coordinates[0]);
    map.fitBounds(
      [
        [Math.min(...lats) - 0.3, Math.min(...lons) - 0.3],
        [Math.max(...lats) + 0.3, Math.max(...lons) + 0.3],
      ],
      { animate: true, duration: 0.6 },
    );
  }

  function zoomToBbox(bbox) {
    const [w, s, e, n] = bbox;
    map.fitBounds(
      [
        [s, w],
        [n, e],
      ],
      { animate: true, duration: 0.6 },
    );
  }

  /* ══════════════════════════════════════════
     DATA LOADERS
     ══════════════════════════════════════════ */
  async function loadVegetationEvents() {
    try {
      const events = await API.getVegetationEvents(200);
      if (!events || !Array.isArray(events)) return;
      State.set('vegEvents', events);
      setText('stat-veg-events', `🌿 ${events.length}`);
      renderVegetationLayer();
      if (typeof Sidebar !== 'undefined' && Sidebar.updateContent)
        Sidebar.updateContent();
      console.log(`[EagleEye] ${events.length} vegetation events loaded`);
    } catch (err) {
      console.warn('[Veg] Failed:', err);
    }
  }

  async function loadMonitoringZones() {
    try {
      const zones = await API.getMonitoringZones();
      if (!zones || !Array.isArray(zones)) return;
      State.set('monitoringZones', zones);
      renderMonitoringZones();
    } catch (err) {
      console.warn('[Zones] Failed:', err);
    }
  }

  async function loadMovementData() {
    try {
      const days = parseInt(el('days-select')?.value || 1);
      const data = await API.getMovementData(days);

      if (!data) {
        State.set('movementData', { movements: [], alerts: [] });
        return;
      }

      const delayStatus = API.checkDelayStatus(data);
      if (delayStatus?.isDelayed) {
        console.log('[Movement] Blocked for anonymous — delayed access');
        State.set('movementData', { movements: [], alerts: [] });
        setText('leg-movements', '🔒');
        return;
      }

      if (data.error) {
        console.warn('[Movement] Backend degraded:', data.error);
      }

      State.set('movementData', data);

      if (data.alerts?.length) {
        const existing = State.get('activeAlerts') || [];
        const existingIds = new Set(existing.map((a) => a.alert_id));
        const merged = [
          ...existing,
          ...data.alerts.filter((a) => !existingIds.has(a.alert_id)),
        ];
        State.set('activeAlerts', merged);
        setText('stat-alerts', `🚨 ${merged.length}`);
      }

      setText('leg-movements', (data.movements || []).length);
      console.log(
        `[EagleEye] Movement: ${(data.movements || []).length} vectors, ` +
          `${(data.alerts || []).length} alerts`,
      );
    } catch (err) {
      console.warn('[Movement] Failed:', err);
      if (!State.get('movementData')) {
        State.set('movementData', { movements: [], alerts: [] });
      }
    }
  }

  async function loadActiveAlerts() {
    try {
      const data = await API.getActiveAlerts();
      const alerts = data.alerts || [];
      State.set('activeAlerts', alerts);
      setText('stat-alerts', `🚨 ${alerts.length}`);
      Navbar.updateCompPill(
        'alerts',
        alerts.length > 0,
        `${alerts.length} active alerts`,
      );
    } catch {
      setText('stat-alerts', '🚨 —');
    }
  }

  /* ══════════════════════════════════════════
     ALERT BANNER (delay-aware)
     ══════════════════════════════════════════ */
  function checkAlerts(features, summary) {
    const banner = el('alert-banner');
    const text = el('alert-banner-text');
    if (!banner || !text) return;

    const critCount = summary.threat_breakdown?.critical || 0;
    const critVeg = (State.get('vegEvents') || []).filter(
      (e) => e.severity === 'critical',
    );
    const critAlerts = (State.get('activeAlerts') || []).filter(
      (a) => a.priority === 'critical',
    );

    const msgs = [];
    if (critCount > 0) {
      const zones = {};
      features
        .filter((f) => f.properties.priority === 'CRITICAL')
        .forEach((f) => {
          const k = f.properties.state || 'Unknown';
          zones[k] = (zones[k] || 0) + 1;
        });
      const list = Object.entries(zones)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([z, c]) => `${z} (${c})`)
        .join(', ');
      msgs.push(`⚡ ${critCount} CRITICAL threats — ${list}`);
    }
    if (critVeg.length)
      msgs.push(`🌿 ${critVeg.length} CRITICAL vegetation events`);
    if (critAlerts.length)
      msgs.push(`🚨 ${critAlerts.length} CRITICAL movement alerts`);

    const delayStatus = State.get('dataDelayStatus');

    if (msgs.length) {
      text.textContent = delayStatus?.isDelayed
        ? `🔒 ${delayStatus.delayMinutes}min delay · ` +
          msgs.join('  ·  ') +
          ` · Sign in for real-time`
        : msgs.join('  ·  ');
      banner.classList.add('visible', 'threat-banner');
    } else if (!banner.classList.contains('delay-banner')) {
      banner.classList.remove('visible', 'threat-banner');
    }
  }

  /* ══════════════════════════════════════════
     HEALTH CHECKS
     ══════════════════════════════════════════ */
  async function checkHealth() {
    try {
      const data = await API.checkHealth();
      if (!data || !data.components) return;
      const c = data.components;
      Navbar.updateCompPill('firms', !!c.firms_data, 'NASA FIRMS thermal data');
      Navbar.updateCompPill('acled', !!c.acled, 'ACLED conflict data');
    } catch {}
  }

  async function loadSentinel2Health() {
    try {
      const data = await API.getSentinel2Health();
      if (!data) return;
      State.set('sentinel2Available', data.sentinel2_configured);
      Navbar.updateCompPill(
        'sentinel',
        data.sentinel2_configured,
        data.sentinel2_configured
          ? `S2 OK · ${data.cached_files} cached · ${data.monitoring_zones} zones`
          : 'Sentinel-2 not configured — set COPERNICUS_USER/PASSWORD',
      );
    } catch {}
  }

  /* ══════════════════════════════════════════
     MAIN DATA LOAD
     ══════════════════════════════════════════ */
  async function loadAllData() {
    const loading = el('loading-overlay');
    const loadingText = el('loading-text');
    StatsBar.setRefreshing(true);
    if (loading) loading.classList.remove('hidden');
    Navbar.setStatus('loading');

    const days = el('days-select')?.value || 1;

    try {
      if (loadingText)
        loadingText.textContent =
          'Fetching thermal hotspots from NASA FIRMS...';

      // 1. Clear all existing layers
      _clearAllDynamicLayers();

      // 2. Reset confidence filter
      const confFilter = el('confidence-filter');
      if (confFilter) confFilter.value = 'all';

      // 3. Fetch data
      const [hotspotData, summaryData] = await Promise.all([
        API.getHotspots(days),
        API.getSummary(days),
      ]);

      const features = hotspotData.features || [];
      State.set('allFeatures', features);

      // 4. Check security delay metadata
      const delayStatus = API.checkDelayStatus(hotspotData);
      State.set('dataDelayStatus', delayStatus);

      if (delayStatus && delayStatus.isDelayed) {
        _showDelayBanner(delayStatus);
        if (typeof Navbar !== 'undefined' && Navbar.setDelayIndicator) {
          Navbar.setDelayIndicator(true, delayStatus.delayMinutes);
        }
      } else {
        _hideDelayBanner();
        if (typeof Navbar !== 'undefined' && Navbar.setDelayIndicator) {
          Navbar.setDelayIndicator(false);
        }
      }

      State.set('summaryData', summaryData);

      // 5. Render hotspots
      renderHotspots(features);

      // 6. Reset map view
      resetView(features);

      // 7. Update stats bar
      StatsBar.update(summaryData, features);

      if (loadingText)
        loadingText.textContent = 'Loading intelligence layers...';

      // 8. Load secondary layers
      const secondaryResults = await Promise.allSettled([
        checkHealth(),
        loadSentinel2Health(),
        loadVegetationEvents(),
        loadMonitoringZones(),
        loadActiveAlerts(),
        loadMovementData(),
      ]);

      secondaryResults.forEach((result, i) => {
        if (result.status === 'rejected') {
          const names = [
            'health',
            'sentinel2',
            'vegetation',
            'zones',
            'alerts',
            'movement',
          ];
          console.warn(`[EagleEye] ${names[i]} layer failed:`, result.reason);
        }
      });

      checkAlerts(features, summaryData);
      _updateLegendStates();

      Navbar.setStatus('live');
      if (loading) loading.classList.add('hidden');

      console.log(
        `[EagleEye] ✓ Loaded: ${features.length} hotspots (${days}d range)` +
          (delayStatus?.isDelayed
            ? ` [DELAYED ${delayStatus.delayMinutes}min]`
            : ' [REALTIME]'),
      );
    } catch (err) {
      console.error('[EagleEye] Load failed:', err);
      Navbar.setStatus('error');
      showToast('Failed to load data: ' + err.message, 'error');
      if (loading) loading.classList.add('hidden');
      resetView(null);
    } finally {
      StatsBar.setRefreshing(false);
    }
  }

  return {
    init,
    resetView,
    renderHotspots,
    renderVegetationLayer,
    renderMovementLayer,
    renderMonitoringZones,
    toggleClustering,
    toggleVegetationLayer,
    toggleMonitoringZones,
    toggleMovementLayer,
    applyFilter,
    getFilteredFeatures,
    zoomTo,
    zoomToState,
    zoomToBbox,
    loadAllData,
    loadVegetationEvents,
    loadMonitoringZones,
    loadMovementData,
    loadActiveAlerts,
  };
})();

window.MapView = MapView;
