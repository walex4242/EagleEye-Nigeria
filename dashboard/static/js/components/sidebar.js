/* ══════════════════════════════════════════
   sidebar.js — Intelligence Panel v3.2
   Auto-close + map focus on item click
   ══════════════════════════════════════════ */

const Sidebar = (() => {
  function render() {
    el('sidebar').innerHTML = `
      <div class="sb-header">
        <span class="sb-title">📊 Intelligence</span>
        <button class="btn btn-icon btn-sm" onclick="Sidebar.close()" title="Close panel (I)" aria-label="Close intelligence panel">✕</button>
      </div>
      <div class="sb-tabs" role="tablist" aria-label="Intelligence tabs">
        <div class="sb-tab active" data-tab="states"     onclick="Sidebar.switchTab('states',this)"     role="tab" aria-selected="true">🏛 States</div>
        <div class="sb-tab"        data-tab="threats"    onclick="Sidebar.switchTab('threats',this)"    role="tab">🎯 Threats</div>
        <div class="sb-tab"        data-tab="alerts"     onclick="Sidebar.switchTab('alerts',this)"     role="tab">🚨 Alerts</div>
        <div class="sb-tab"        data-tab="vegetation" onclick="Sidebar.switchTab('vegetation',this)" role="tab">🌿 Veg</div>
        <div class="sb-tab"        data-tab="tiers"      onclick="Sidebar.switchTab('tiers',this)"      role="tab">⚔ Tiers</div>
      </div>
      <div class="sb-body" id="sb-content" role="tabpanel"></div>
    `;

    // ═══════════════════════════════════════
    // REMOVE any old backdrop wherever it is
    // (fixes stale cached elements)
    // ═══════════════════════════════════════
    document.querySelectorAll('#sidebar-backdrop').forEach((b) => b.remove());

    // ═══════════════════════════════════════
    // Create FRESH backdrop on document.body
    // with inline styles to GUARANTEE no blur
    // ═══════════════════════════════════════
    const bd = document.createElement('div');
    bd.id = 'sidebar-backdrop';
    bd.className = 'sidebar-backdrop';
    bd.setAttribute('aria-hidden', 'true');
    bd.onclick = () => Sidebar.close();

    // Force critical styles inline — cannot be overridden by CSS
    bd.style.backdropFilter = 'none';
    bd.style.webkitBackdropFilter = 'none';

    document.body.appendChild(bd);

    updateAuthState();
  }

  // ══════════════════════════════════════
  // OPEN / CLOSE / TOGGLE
  // ══════════════════════════════════════

  function toggle() {
    const sb = el('sidebar');
    if (!sb) return;
    const isOpen =
      sb.classList.contains('open') || !sb.classList.contains('collapsed');
    isOpen ? close() : open();
  }

  function open() {
    const sb = el('sidebar');
    if (!sb) return;
    sb.classList.remove('collapsed');
    sb.classList.add('open');
    el('sidebar-backdrop')?.classList.add('visible');
    el('panel-toggle')?.classList.add('active');
    updateContent();
  }

  function close() {
    const sb = el('sidebar');
    if (!sb) return;
    sb.classList.remove('open');
    sb.classList.add('collapsed');
    el('sidebar-backdrop')?.classList.remove('visible');
    el('panel-toggle')?.classList.remove('active');
  }

  // ══════════════════════════════════════════
  // CLOSE-AND-FOCUS HELPER
  // Auto-closes sidebar (mobile), then zooms
  // map, then shows toast confirmation
  // ══════════════════════════════════════════
  function _closeAndFocus(mapAction, toastMsg) {
    // ALWAYS close — both mobile AND desktop
    close();

    // Longer delay on mobile for animation to complete
    const delay = window.innerWidth <= 768 ? 400 : 150;

    setTimeout(() => {
      // Tell Leaflet the container size changed
      if (window._map) {
        window._map.invalidateSize({ animate: false });
      }

      // Small extra delay then execute map action
      setTimeout(() => {
        if (typeof mapAction === 'function') {
          mapAction();
        }
        if (toastMsg) {
          showToast(toastMsg, 'info');
        }
      }, 50);
    }, delay);
  }

  // ══════════════════════════════════════════
  // CLICK HANDLERS — called from onclick
  // ══════════════════════════════════════════
  function _onStateClick(stateName) {
    _closeAndFocus(
      () => MapView.zoomToState(stateName),
      `🗺️ Zoomed to ${stateName}`,
    );
  }

  function _onThreatClick(lat, lon, priority, score) {
    _closeAndFocus(
      () => MapView.zoomTo(lat, lon),
      `🎯 ${priority} threat · Score ${score}`,
    );
  }

  function _onAlertClick(lat, lon, title) {
    _closeAndFocus(() => MapView.zoomTo(lat, lon), `🚨 ${title || 'Alert'}`);
  }

  function _onMovementClick(lat, lon, classification) {
    _closeAndFocus(
      () => MapView.zoomTo(lat, lon),
      `🧭 ${(classification || 'movement').replace(/_/g, ' ')}`,
    );
  }

  function _onVegEventClick(lat, lon, classification) {
    _closeAndFocus(
      () => MapView.zoomTo(lat, lon),
      `🌿 ${(classification || 'vegetation').replace(/_/g, ' ')} event`,
    );
  }

  function _onZoneClick(bbox, zoneName) {
    _closeAndFocus(() => MapView.zoomToBbox(bbox), `📐 Zoomed to ${zoneName}`);
  }

  // ══════════════════════════════════════
  // TAB SWITCHING
  // ══════════════════════════════════════

  function switchTab(tab, tabEl) {
    State.set('currentTab', tab);
    document.querySelectorAll('.sb-tab').forEach((t) => {
      t.classList.remove('active');
      t.setAttribute('aria-selected', 'false');
    });
    if (tabEl) {
      tabEl.classList.add('active');
      tabEl.setAttribute('aria-selected', 'true');
    }
    updateContent();
  }

  function updateAuthState() {
    updateContent();
  }

  function updateContent() {
    const container = el('sb-content');
    if (!container) return;

    const tab = State.get('currentTab') || 'states';
    const isLoggedIn = Auth.isLoggedIn();
    const publicTabs = ['states'];

    if (!isLoggedIn && !publicTabs.includes(tab)) {
      renderLocked(container);
      return;
    }

    switch (tab) {
      case 'states':
        renderStates(container);
        break;
      case 'threats':
        renderThreats(container);
        break;
      case 'alerts':
        renderAlerts(container);
        break;
      case 'vegetation':
        renderVegetation(container);
        break;
      case 'tiers':
        renderTiers(container);
        break;
    }
  }

  // ══════════════════════════════════════
  // LOCKED VIEW
  // ══════════════════════════════════════

  function renderLocked(c) {
    c.innerHTML = `
      <div class="intel-locked">
        <span class="intel-locked-icon" aria-hidden="true">🔒</span>
        <h3>Intelligence Access Required</h3>
        <p>This panel contains classified threat data, movement analysis, and vegetation intelligence. Sign in with your credentials to access.</p>
        <div class="intel-locked-features">
          <div class="intel-feature"><span class="intel-feature-icon">🎯</span> Threat scoring &amp; rankings</div>
          <div class="intel-feature"><span class="intel-feature-icon">🚨</span> Active alerts &amp; movement</div>
          <div class="intel-feature"><span class="intel-feature-icon">🌿</span> Vegetation change detection</div>
          <div class="intel-feature"><span class="intel-feature-icon">⚔</span> Tier classification system</div>
        </div>
        <button class="intel-cta" onclick="AuthModal.show()">🔐 Sign In for Full Access</button>
        <div style="font-size:9.5px;color:var(--text-muted);font-family:var(--font-mono);line-height:1.6;margin-top:4px">
          PUBLIC · Map view only<br>
          ANALYST / MILITARY · Full intelligence
        </div>
      </div>`;
  }

  // ══════════════════════════════════════
  // STATES TAB — uses _onStateClick
  // ══════════════════════════════════════

  function renderStates(c) {
    const stateMap = {};
    State.get('allFeatures').forEach((f) => {
      const s = f.properties.state || 'Unknown';
      if (!stateMap[s])
        stateMap[s] = { count: 0, critical: 0, maxScore: 0, tier: '', high: 0 };
      stateMap[s].count++;
      if (f.properties.priority === 'CRITICAL') stateMap[s].critical++;
      if (f.properties.confidence === 'H') stateMap[s].high++;
      if (!stateMap[s].tier && f.properties.threat_tier)
        stateMap[s].tier = f.properties.threat_tier;
      if ((f.properties.threat_score || 0) > stateMap[s].maxScore)
        stateMap[s].maxScore = f.properties.threat_score;
    });
    const sorted = Object.entries(stateMap).sort(
      (a, b) => b[1].maxScore - a[1].maxScore,
    );

    if (!sorted.length) {
      c.innerHTML = emptyHTML(
        '🗺️',
        'No hotspot data',
        'Refresh to load satellite data.',
      );
      return;
    }

    c.innerHTML = `
      <div style="font-size:10px;color:var(--text-secondary);margin-bottom:10px;font-family:var(--font-mono)">
        ${sorted.length} STATES WITH ACTIVE HOTSPOTS — TAP TO ZOOM
      </div>
      <ul style="list-style:none">
        ${sorted
          .map(
            ([name, d]) => `
          <li class="list-item list-item-clickable" 
              onclick="Sidebar._onStateClick('${name.replace(/'/g, "\\'")}')">
            <div class="list-item-header">
              <div style="flex:1;overflow:hidden">
                <div class="list-item-title">${name} ${tierBadge(d.tier)}</div>
                <div class="list-item-meta">
                  ${d.critical ? `<span style="color:var(--critical)">● ${d.critical} critical&ensp;</span>` : ''}
                  ${d.high ? `<span style="color:var(--elevated)">${d.high} high conf&ensp;</span>` : ''}
                  Score: <span style="color:${scoreColor(d.maxScore)}">${d.maxScore}</span>
                </div>
              </div>
              <div class="list-item-score" style="color:${scoreColor(d.maxScore)}">${d.count}</div>
            </div>
            <div class="list-item-arrow">→</div>
          </li>`,
          )
          .join('')}
      </ul>`;
  }

  // ══════════════════════════════════════
  // THREATS TAB — uses _onThreatClick
  // ══════════════════════════════════════

  function renderThreats(c) {
    const top = State.get('allFeatures')
      .filter((f) => f.properties.threat_score > 0)
      .sort(
        (a, b) =>
          (b.properties.threat_score || 0) - (a.properties.threat_score || 0),
      )
      .slice(0, 30);

    if (!top.length) {
      c.innerHTML = emptyHTML(
        '🎯',
        'No threat data',
        'Load hotspot data to see threat scores.',
      );
      return;
    }

    c.innerHTML = `
      <div style="font-size:10px;color:var(--text-secondary);margin-bottom:8px;font-family:var(--font-mono)">
        TOP ${top.length} THREATS BY SCORE — TAP TO ZOOM
      </div>
      ${top
        .map((f, i) => {
          const p = f.properties;
          const [lon, lat] = f.geometry.coordinates;
          return `
          <div class="list-item list-item-clickable" 
               onclick="Sidebar._onThreatClick(${lat},${lon},'${p.priority}',${p.threat_score})">
            <div class="list-item-header">
              <span class="list-rank">#${i + 1}</span>
              <div class="list-item-score" style="color:${scoreColor(p.threat_score)}">${p.threat_score}</div>
              <span class="badge badge-${p.priority?.toLowerCase()}">${p.priority}</span>
              <span class="badge badge-info" style="margin-left:auto">${confidenceLabel(p.confidence)}</span>
            </div>
            <div class="list-item-meta">📍 ${p.state || '—'} · ${p.red_zone || '—'} · ${p.acq_date}</div>
            <div class="list-item-arrow">→</div>
          </div>`;
        })
        .join('')}`;
  }

  // ══════════════════════════════════════
  // ALERTS TAB — uses _onMovementClick & _onAlertClick
  // ══════════════════════════════════════

  function renderAlerts(c) {
    const movData = State.get('movementData');
    const alerts = State.get('activeAlerts');
    let html = '';

    // Movement summary
    html += `<div class="section-lbl">Movement Analysis</div>`;
    if (!movData) {
      html += `<div class="move-item">
        ${emptyHTML('🧭', 'No movement data loaded', 'Analyse movement patterns from hotspot data.')}
        <button class="btn btn-primary btn-full" style="margin-top:8px"
          onclick="MapView.loadMovementData().then(()=>Sidebar.updateContent())">▶ Analyse Movement</button>
      </div>`;
    } else {
      const s = movData.summary || {};
      html += `
        <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px">
          <span class="badge badge-critical">⚡ ${s.rapid_relocations || 0} Rapid</span>
          <span class="badge badge-high">🏕 ${s.camp_relocations || 0} Relocations</span>
          <span class="badge badge-elevated">🛤 ${s.corridor_movements || 0} Corridors</span>
        </div>`;
      const mvs = movData.movements || [];
      if (mvs.length) {
        html += mvs
          .slice(0, 20)
          .map((m, i) => {
            const cls =
              m.classification === 'rapid_relocation'
                ? 'critical'
                : m.classification === 'corridor'
                  ? 'elevated'
                  : 'high';
            return `
            <div class="move-item list-item-clickable"
                 onclick="Sidebar._onMovementClick(${m.destination_lat},${m.destination_lon},'${m.classification}')">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
                <span class="list-rank">#${i + 1}</span>
                <span class="badge badge-${cls}">${m.classification.replace(/_/g, ' ')}</span>
                <span style="margin-left:auto;font-family:var(--font-mono);font-size:12px;font-weight:700;color:var(--text-bright)">${m.distance_km}km</span>
              </div>
              <div class="list-item-meta">📍 ${m.origin_state || '—'} → ${m.destination_state || '—'} · 🧭 ${m.bearing_degrees}° · ⏱ ${m.speed_kmh}km/h</div>
              <div class="list-item-arrow">→</div>
            </div>`;
          })
          .join('');
      } else {
        html += `<div class="list-item-meta" style="padding:8px 0">No movements detected in this period.</div>`;
      }
    }

    // Active alerts
    html += `<div class="div-h"></div><div class="section-lbl">Active Alerts</div>`;
    if (!alerts.length) {
      html += emptyHTML(
        '✅',
        'No active alerts',
        'Alerts are generated from movement pattern analysis.',
      );
    } else {
      const sorted = [...alerts].sort((a, b) => {
        const o = { critical: 0, high: 1, medium: 2, low: 3 };
        return (o[a.priority] ?? 4) - (o[b.priority] ?? 4);
      });
      const counts = { critical: 0, high: 0, medium: 0, low: 0 };
      alerts.forEach((a) => {
        if (counts[a.priority] !== undefined) counts[a.priority]++;
      });

      html += `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px">
        ${counts.critical ? `<span class="badge badge-critical">● ${counts.critical} Critical</span>` : ''}
        ${counts.high ? `<span class="badge badge-high">● ${counts.high} High</span>` : ''}
        ${counts.medium ? `<span class="badge badge-elevated">● ${counts.medium} Medium</span>` : ''}
        ${counts.low ? `<span class="badge badge-monitor">● ${counts.low} Low</span>` : ''}
      </div>`;

      html += sorted
        .slice(0, 30)
        .map((alert) => {
          const evidence = (alert.evidence || []).slice(0, 3);
          return `
          <div class="alert-item list-item-clickable"
               onclick="Sidebar._onAlertClick(${alert.latitude || 0},${alert.longitude || 0},'${(alert.title || 'Alert').replace(/'/g, "\\'")}')">
            <div class="list-item-header">
              <span class="badge badge-${alert.priority}">${(alert.priority || 'low').toUpperCase()}</span>
              <span class="list-item-title">${alert.title || 'Alert'}</span>
            </div>
            <div class="list-item-meta">${alert.description || ''}</div>
            ${evidence.length ? `<div style="margin-top:4px;font-size:10px;color:var(--info);line-height:1.6">${evidence.map((e) => `• ${e}`).join('<br>')}</div>` : ''}
            ${alert.recommended_action ? `<div class="alert-action-box">⚡ ${alert.recommended_action}</div>` : ''}
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:6px">
              <span class="list-item-meta">📍 ${alert.state || '—'} · ${alert.zone || '—'}</span>
              <button class="dismiss-btn" onclick="event.stopPropagation();Sidebar.dismissAlert('${alert.alert_id}',this)">Dismiss</button>
            </div>
            <div class="list-item-arrow">→</div>
          </div>`;
        })
        .join('');
    }

    html += `<div class="div-h"></div><div class="section-lbl">Quick Actions</div>
      <div style="display:flex;flex-direction:column;gap:5px">
        <button class="btn btn-primary btn-full" onclick="MapView.loadMovementData().then(()=>Sidebar.updateContent())">🧭 Refresh Movement</button>
        <button class="btn btn-full" onclick="MapView.loadActiveAlerts().then(()=>Sidebar.updateContent())">↻ Refresh Alerts</button>
        <button class="btn btn-full" id="clear-exp-btn" onclick="Sidebar.clearExpired(this)">🧹 Clear Expired</button>
        <a href="/api/alerts/summary" target="_blank" rel="noopener" style="text-align:center;font-size:11px;color:var(--info);padding:5px;display:block">📥 Alert Summary JSON</a>
        <a href="/api/v1/hotspots/intel/brief" target="_blank" rel="noopener" style="text-align:center;font-size:11px;color:var(--info);padding:5px;display:block">📋 Intelligence Brief</a>
      </div>`;

    c.innerHTML = html;
  }

  // ══════════════════════════════════════
  // VEGETATION TAB — uses _onZoneClick & _onVegEventClick
  // ══════════════════════════════════════

  function renderVegetation(c) {
    const zones = State.get('monitoringZones');
    const events = State.get('vegEvents');
    const s2 = State.get('sentinel2Available');
    let html = '';

    html += `<div class="section-lbl">Monitoring Zones</div>`;
    if (!zones.length) {
      html += `<div class="list-item-meta" style="margin-bottom:12px">Loading zones…</div>`;
      MapView.loadMonitoringZones().then(() => Sidebar.updateContent());
    } else {
      html += zones
        .map((z) => {
          const risk =
            z.risk_level === 'critical'
              ? 'critical'
              : z.risk_level === 'high'
                ? 'high'
                : 'elevated';
          const evtsIn = events.filter((e) => {
            const [w, s, ea, n] = z.bbox;
            return (
              e.latitude >= s &&
              e.latitude <= n &&
              e.longitude >= w &&
              e.longitude <= ea
            );
          });
          return `
          <div class="veg-card list-item-clickable" 
               onclick="Sidebar._onZoneClick([${z.bbox}],'${z.name.replace(/'/g, "\\'")}')">
            <div class="veg-card-header">
              <span class="veg-card-name">${z.name}</span>
              <span class="badge badge-${risk}">${z.risk_level.toUpperCase()}</span>
            </div>
            <div class="list-item-meta">${z.description}</div>
            ${evtsIn.length ? `<div style="font-size:10px;color:var(--info);margin-top:4px">🌿 ${evtsIn.length} change event(s)</div>` : ''}
            <button class="btn btn-primary btn-sm" style="margin-top:8px"
              onclick="event.stopPropagation();Sidebar.runZoneAnalysis('${z.zone_id}',this)"
              ${s2 ? '' : 'disabled title="Sentinel-2 not configured"'}>▶ Run Analysis</button>
            <div class="list-item-arrow">→</div>
          </div>`;
        })
        .join('');
    }

    html += `<div class="div-h"></div><div class="section-lbl">Detected Changes</div>`;
    if (!events.length) {
      html += emptyHTML(
        '🌿',
        'No vegetation changes loaded',
        s2
          ? 'Run zone analysis above or enable the 🌿 Veg layer.'
          : 'Sentinel-2 credentials not configured. Set COPERNICUS_USER/PASSWORD.',
      );
    } else {
      const cls = { clearing: 0, burn_scar: 0, regrowth: 0 };
      events.forEach((e) => {
        if (cls[e.classification] !== undefined) cls[e.classification]++;
      });
      html += `<div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px">
        <span class="badge badge-critical">🪓 ${cls.clearing} Clearings</span>
        <span class="badge badge-high">🔥 ${cls.burn_scar} Burn Scars</span>
        <span class="badge badge-monitor">🌱 ${cls.regrowth} Regrowth</span>
      </div>`;
      const sorted = [...events].sort(
        (a, b) =>
          (({ critical: 0, high: 1, moderate: 2, low: 3 })[a.severity] ?? 4) -
          ({ critical: 0, high: 1, moderate: 2, low: 3 }[b.severity] ?? 4),
      );
      html += sorted
        .map((evt, i) => {
          const cc = vegClassColor(evt.classification);
          const sc = vegSeverityColor(evt.severity);
          const cf = (evt.confidence * 100).toFixed(0);
          return `
          <div class="list-item list-item-clickable" 
               onclick="Sidebar._onVegEventClick(${evt.latitude},${evt.longitude},'${evt.classification}')">
            <div class="list-item-header">
              <span class="list-rank">#${i + 1}</span>
              <span class="badge" style="background:${cc}18;color:${cc};border-color:${cc}44">${evt.classification.replace('_', ' ')}</span>
              <span class="badge" style="background:${sc}18;color:${sc};border-color:${sc}44">${evt.severity.toUpperCase()}</span>
              <span style="margin-left:auto;font-family:var(--font-mono);font-size:11px;font-weight:700;color:${sc}">${cf}%</span>
            </div>
            <div class="list-item-meta">📍 ${evt.latitude.toFixed(3)}°N, ${evt.longitude.toFixed(3)}°E · ${evt.area_hectares}ha · ${evt.date_before} → ${evt.date_after}${evt.thermal_correlation ? ' · 🔥' : ''}${evt.conflict_correlation ? ' · ⚔' : ''}</div>
            <div class="list-item-arrow">→</div>
          </div>`;
        })
        .join('');
    }

    html += `<div class="div-h"></div>
      <div style="display:flex;flex-direction:column;gap:5px">
        <button class="btn btn-primary btn-full" onclick="Sidebar.runAllZones(this)" ${s2 ? '' : 'disabled'}>🌍 Analyse All Zones</button>
        <button class="btn btn-full" onclick="MapView.loadVegetationEvents().then(()=>Sidebar.updateContent())">↻ Refresh Events</button>
        <a href="/api/v1/sentinel2/events/geojson" target="_blank" rel="noopener" style="text-align:center;font-size:11px;color:var(--info);padding:5px;display:block">📥 Export GeoJSON</a>
      </div>`;

    c.innerHTML = html;
  }

  // ══════════════════════════════════════
  // TIERS TAB
  // ══════════════════════════════════════

  function renderTiers(c) {
    const tierMap = {};
    State.get('allFeatures').forEach((f) => {
      const t = f.properties.threat_tier || 'Unknown';
      if (!tierMap[t])
        tierMap[t] = { count: 0, critical: 0, maxScore: 0, states: new Set() };
      tierMap[t].count++;
      if (f.properties.priority === 'CRITICAL') tierMap[t].critical++;
      if ((f.properties.threat_score || 0) > tierMap[t].maxScore)
        tierMap[t].maxScore = f.properties.threat_score;
      if (f.properties.state) tierMap[t].states.add(f.properties.state);
    });

    if (!Object.keys(tierMap).length) {
      c.innerHTML = emptyHTML('⚔', 'No tier data', 'Load hotspot data first.');
      return;
    }

    c.innerHTML =
      `
      <div style="font-size:10px;color:var(--text-secondary);margin-bottom:10px;font-family:var(--font-mono)">
        ${Object.keys(tierMap).length} THREAT TIERS ACTIVE
      </div>` +
      Object.entries(tierMap)
        .sort((a, b) => b[1].maxScore - a[1].maxScore)
        .map(([tier, d]) => {
          // Get all states for this tier to enable zoom
          const stateList = [...d.states];
          const firstState = stateList[0] || '';
          return `
            <div class="list-item list-item-clickable"
                 onclick="Sidebar._onStateClick('${firstState.replace(/'/g, "\\'")}')">
              <div class="list-item-header">
                <div style="flex:1">
                  <div class="list-item-title">${tier}</div>
                  <div class="list-item-meta">
                    ${d.critical ? `<span style="color:var(--critical)">● ${d.critical} critical&ensp;</span>` : ''}
                    Score: <span style="color:${scoreColor(d.maxScore)}">${d.maxScore}</span>
                  </div>
                  <div class="list-item-meta" style="margin-top:2px;font-size:9.5px">${stateList.join(', ')}</div>
                </div>
                <div class="list-item-score" style="color:${scoreColor(d.maxScore)}">${d.count}</div>
              </div>
              <div class="list-item-arrow">→</div>
            </div>`;
        })
        .join('');
  }

  // ══════════════════════════════════════
  // HELPERS
  // ══════════════════════════════════════

  function emptyHTML(icon, title, desc) {
    return `<div class="empty-state">
      <span class="empty-icon">${icon}</span>
      <h4>${title}</h4>
      <p>${desc}</p>
    </div>`;
  }

  // ══════════════════════════════════════
  // ACTIONS
  // ══════════════════════════════════════

  async function dismissAlert(alertId, btn) {
    try {
      btn.disabled = true;
      btn.textContent = '…';
      if (await API.dismissAlert(alertId)) {
        const updated = State.get('activeAlerts').filter(
          (a) => a.alert_id !== alertId,
        );
        State.set('activeAlerts', updated);
        setText('stat-alerts', updated.length);
        updateContent();
        showToast('Alert dismissed', 'success');
      }
    } catch {
      btn.disabled = false;
      btn.textContent = 'Dismiss';
    }
  }

  async function clearExpired(btn) {
    try {
      btn.disabled = true;
      btn.textContent = '⏳ Clearing…';
      const d = await API.clearExpiredAlerts();
      btn.textContent = `✓ ${d.removed} removed`;
      await MapView.loadActiveAlerts();
      updateContent();
      showToast(`Cleared ${d.removed} expired alerts`, 'success');
    } catch {
      btn.textContent = '✕ Failed';
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = '🧹 Clear Expired';
    }, 3000);
  }

  async function runZoneAnalysis(zoneId, btn) {
    if (!State.get('sentinel2Available')) {
      showToast('Sentinel-2 not configured.', 'error');
      return;
    }
    btn.disabled = true;
    btn.textContent = '⏳ Analysing…';
    try {
      const job = await API.runZoneAnalysis(zoneId);
      btn.textContent = `✓ ${job.events_found} events`;
      await MapView.loadVegetationEvents();
      if (!State.get('vegLayerVisible') && job.events_found > 0)
        MapView.toggleVegetationLayer();
      const zone = State.get('monitoringZones').find(
        (z) => z.zone_id === zoneId,
      );
      if (zone) MapView.zoomToBbox(zone.bbox);
      updateContent();
      showToast(`Zone: ${job.events_found} events detected`, 'success');
    } catch (err) {
      btn.textContent = '✕ Failed';
      showToast(err.message, 'error');
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = '▶ Run Analysis';
    }, 3000);
  }

  async function runAllZones(btn) {
    if (!State.get('sentinel2Available')) {
      showToast('Sentinel-2 not configured.', 'error');
      return;
    }
    btn.disabled = true;
    btn.textContent = '⏳ Analysing all zones…';
    try {
      const jobs = await API.runAllZones();
      const total = jobs.reduce((s, j) => s + (j.events_found || 0), 0);
      btn.textContent = `✓ ${jobs.length} zones · ${total} events`;
      await MapView.loadVegetationEvents();
      if (!State.get('vegLayerVisible') && total > 0)
        MapView.toggleVegetationLayer();
      updateContent();
      showToast(`All zones: ${total} events found`, 'success');
    } catch (err) {
      btn.textContent = '✕ Failed';
      showToast(err.message, 'error');
    }
    setTimeout(() => {
      btn.disabled = false;
      btn.textContent = '🌍 Analyse All Zones';
    }, 4000);
  }

  return {
    render,
    toggle,
    open,
    close,
    switchTab,
    updateAuthState,
    updateContent,
    dismissAlert,
    clearExpired,
    runZoneAnalysis,
    runAllZones,
    _onStateClick,
    _onThreatClick,
    _onAlertClick,
    _onMovementClick,
    _onVegEventClick,
    _onZoneClick,
    _closeAndFocus,
  };
})();

window.Sidebar = Sidebar;
