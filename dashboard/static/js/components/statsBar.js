/* ══════════════════════════════════════════
   statsBar.js — Stats Bar Component v3.2
   ══════════════════════════════════════════ */

const StatsBar = (() => {
  /* ── Track active priority filter ── */
  let _activePriority = null;

  function render() {
    el('stats-bar').innerHTML = `
      <!-- Total hotspots -->
      <div class="stat-block">
        <div class="stat-lbl">Hotspots</div>
        <div class="stat-val" id="stat-total">—</div>
      </div>

      <div class="div-v hide-mobile"></div>

      <!-- Confidence -->
      <div class="stat-block">
        <div class="stat-lbl">Confidence</div>
        <div class="conf-row">
          <span class="conf-chip">
            <span class="conf-dot" style="background:var(--critical)"></span>
            <span id="stat-high-val">—</span>
          </span>
          <span class="conf-chip">
            <span class="conf-dot" style="background:var(--elevated)"></span>
            <span id="stat-medium-val">—</span>
          </span>
          <span class="conf-chip">
            <span class="conf-dot" style="background:var(--monitor)"></span>
            <span id="stat-low-val">—</span>
          </span>
        </div>
      </div>

      <div class="div-v hide-mobile hide-tablet"></div>

      <!-- Threat priority pills (desktop only) -->
      <div class="stat-block hide-mobile hide-tablet">
        <div class="stat-lbl">Threat Priority</div>
        <div class="threat-row" id="threat-pills-row">
          <span class="tpill critical" data-priority="CRITICAL" role="button" tabindex="0">
            <span class="tpill-count" id="pill-critical">—</span> CRITICAL
          </span>
          <span class="tpill high" data-priority="HIGH" role="button" tabindex="0">
            <span class="tpill-count" id="pill-high">—</span> HIGH
          </span>
          <span class="tpill elevated" data-priority="ELEVATED" role="button" tabindex="0">
            <span class="tpill-count" id="pill-elevated">—</span> ELEVATED
          </span>
          <span class="tpill monitor" data-priority="MONITOR" role="button" tabindex="0">
            <span class="tpill-count" id="pill-monitor">—</span> MONITOR
          </span>
        </div>
      </div>

      <div class="div-v hide-mobile"></div>

      <!-- Top score -->
      <div class="stat-block hide-mobile" id="stat-top-score-block">
        <div class="stat-lbl">Top Score</div>
        <div class="stat-val" id="stat-top-score">—</div>
      </div>

      <div class="div-v hide-mobile"></div>

      <!-- Alerts -->
      <div class="stat-block">
        <div class="stat-lbl">Alerts</div>
        <div class="stat-val md" id="stat-alerts" style="color:var(--critical)">—</div>
      </div>

      <div class="div-v hide-mobile"></div>

      <!-- Veg events -->
      <div class="stat-block hide-mobile">
        <div class="stat-lbl">Veg Events</div>
        <div class="stat-val md" id="stat-veg-events" style="color:var(--info)">—</div>
      </div>

      <div class="div-v hide-mobile"></div>

      <!-- Updated -->
      <div class="stat-block hide-mobile">
        <div class="stat-lbl">Updated</div>
        <div class="stat-val sm" id="stat-updated">—</div>
      </div>

      <!-- ── Controls ── -->
      <div class="stats-controls">
        <div class="ctrl-select">
          <label for="days-select">Days</label>
          <select id="days-select" title="Data time range">
            <option value="1">24h</option>
            <option value="2">2d</option>
            <option value="3">3d</option>
            <option value="5">5d</option>
            <option value="7" selected>7d</option>
            <option value="10">10d</option>
          </select>
        </div>

        <div class="ctrl-select">
          <label for="confidence-filter">Filter</label>
          <select id="confidence-filter" title="Filter hotspots">
            <option value="all">All</option>
            <option value="H">High Conf</option>
            <option value="HN">High+Med</option>
            <option value="L">Low only</option>
            <option value="critical">CRITICAL</option>
            <option value="high+">HIGH+</option>
          </select>
        </div>

        <!-- Layer toggles (hidden on mobile, accessible via drawer) -->
        <div class="layer-btns hide-mobile">
          <button class="lbtn active" id="cluster-toggle"  title="Toggle clusters (C)" type="button">⬡ Clusters</button>
          <button class="lbtn"        id="veg-toggle"      title="Vegetation layer (V)" type="button">🌿 Veg</button>
          <button class="lbtn"        id="zones-toggle"    title="Zones overlay (Z)" type="button">📐 Zones</button>
          <button class="lbtn"        id="movement-toggle" title="Movement vectors (M)" type="button">🧭 Move</button>
          <button class="lbtn"        id="panel-toggle"    title="Intelligence panel (I)" type="button">📊 Intel</button>
        </div>

        <!-- Intel panel button on mobile -->
        <div class="layer-btns show-mobile">
          <button class="lbtn" id="panel-toggle-mobile" type="button">📊 Intel</button>
        </div>

        <button class="refresh-btn" id="refresh-btn" type="button"
                title="Refresh all data (R)" aria-label="Refresh">
          <span id="refresh-icon">↻</span> Refresh
        </button>
      </div>
    `;

    /* ── Bind ALL events programmatically (no inline onclick) ── */
    _bindEvents();
  }

  /* ══════════════════════════════════════
     Event Binding — Single source of truth
     ══════════════════════════════════════ */
  function _bindEvents() {
    // ── Refresh button ──
    const refreshBtn = el('refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', _handleRefresh);
    }

    // ── Days select ──
    const daysSelect = el('days-select');
    if (daysSelect) {
      daysSelect.addEventListener('change', _handleDaysChange);
    }

    // ── Confidence filter ──
    const confFilter = el('confidence-filter');
    if (confFilter) {
      confFilter.addEventListener('change', _handleFilterChange);
    }

    // ── Threat priority pills (event delegation) ──
    const pillsRow = el('threat-pills-row');
    if (pillsRow) {
      pillsRow.addEventListener('click', _handlePillClick);
      pillsRow.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          _handlePillClick(e);
        }
      });
    }

    // ── Layer toggle buttons ──
    _bindBtn('cluster-toggle', () => {
      if (typeof MapView !== 'undefined' && MapView.toggleClustering) {
        MapView.toggleClustering();
        showToast(
          State.get('useClustering') ? '⬡ Clustering ON' : '⬡ Clustering OFF',
          'info',
        );
      }
    });

    _bindBtn('veg-toggle', () => {
      if (typeof MapView !== 'undefined' && MapView.toggleVegetationLayer) {
        MapView.toggleVegetationLayer();
      }
    });

    _bindBtn('zones-toggle', () => {
      if (typeof MapView !== 'undefined' && MapView.toggleMonitoringZones) {
        MapView.toggleMonitoringZones();
      }
    });

    _bindBtn('movement-toggle', () => {
      if (typeof MapView !== 'undefined' && MapView.toggleMovementLayer) {
        MapView.toggleMovementLayer();
      }
    });

    _bindBtn('panel-toggle', () => {
      if (typeof Sidebar !== 'undefined' && Sidebar.toggle) {
        Sidebar.toggle();
      }
    });

    _bindBtn('panel-toggle-mobile', () => {
      if (typeof Sidebar !== 'undefined' && Sidebar.toggle) {
        Sidebar.toggle();
      }
    });
  }

  /* ── Helper: safe button binding ── */
  function _bindBtn(id, handler) {
    const button = el(id);
    if (button) {
      button.addEventListener('click', handler);
    }
  }

  /* ══════════════════════════════════════
     Refresh Handler — THE FIX
     ══════════════════════════════════════ */
  async function _handleRefresh() {
    const refreshBtn = el('refresh-btn');

    // Prevent double-clicks
    if (refreshBtn?.disabled) {
      console.log('[StatsBar] Refresh already in progress');
      return;
    }

    console.log('[StatsBar] ── Refresh triggered ──');

    try {
      // 1. Visual feedback immediately
      setRefreshing(true);
      showToast('🔄 Refreshing satellite data...', 'info');

      // 2. Update navbar status
      if (typeof Navbar !== 'undefined' && Navbar.setStatus) {
        Navbar.setStatus('loading');
      }

      // 3. Check if MapView exists and has loadAllData
      if (typeof MapView === 'undefined') {
        throw new Error('MapView not initialized');
      }

      if (typeof MapView.loadAllData !== 'function') {
        throw new Error('MapView.loadAllData is not a function');
      }

      // 4. Get the selected days value
      const daysSelect = el('days-select');
      const days = daysSelect ? parseInt(daysSelect.value, 10) : 2;
      console.log(`[StatsBar] Refreshing with days=${days}`);

      // 5. Actually call the data load
      await MapView.loadAllData();

      // 6. Success feedback
      console.log('[StatsBar] ✓ Refresh complete');
      showToast('✅ Data refreshed successfully', 'success');

      if (typeof Navbar !== 'undefined' && Navbar.setStatus) {
        Navbar.setStatus('live');
      }
    } catch (err) {
      console.error('[StatsBar] ✗ Refresh failed:', err);
      showToast(`❌ Refresh failed: ${err.message}`, 'error');

      if (typeof Navbar !== 'undefined' && Navbar.setStatus) {
        Navbar.setStatus('error');
      }
    } finally {
      // 7. Always stop spinner
      setRefreshing(false);
    }
  }

  /* ── Days select change ── */
  async function _handleDaysChange() {
    const val = el('days-select')?.value;
    console.log(`[StatsBar] Days changed to: ${val}`);

    try {
      setRefreshing(true);
      showToast(`📅 Loading ${val}-day data...`, 'info');

      if (typeof MapView !== 'undefined' && MapView.loadAllData) {
        await MapView.loadAllData();
      }

      showToast(`✅ ${val}-day data loaded`, 'success');
    } catch (err) {
      console.error('[StatsBar] Days change failed:', err);
      showToast('❌ Failed to load data', 'error');
    } finally {
      setRefreshing(false);
    }
  }

  /* ── Filter change ── */
  function _handleFilterChange() {
    const val = el('confidence-filter')?.value;
    console.log(`[StatsBar] Filter changed to: ${val}`);

    try {
      if (typeof MapView !== 'undefined' && MapView.applyFilter) {
        MapView.applyFilter();
        showToast(`🔍 Filter: ${val === 'all' ? 'Showing all' : val}`, 'info');
      }
    } catch (err) {
      console.error('[StatsBar] Filter failed:', err);
    }
  }

  /* ── Pill click ── */
  function _handlePillClick(e) {
    const pill = e.target.closest('.tpill');
    if (!pill) return;

    const priority = pill.dataset.priority;
    if (!priority) return;

    console.log(`[StatsBar] Priority pill clicked: ${priority}`);

    // Toggle: clicking same pill again resets to "all"
    if (_activePriority === priority) {
      _activePriority = null;
      _clearPillHighlights();
      filterByPriority('ALL');
      showToast('🔍 Showing all priorities', 'info');
    } else {
      _activePriority = priority;
      _highlightPill(priority);
      filterByPriority(priority);
      showToast(`🔍 Filtering: ${priority}`, 'info');
    }
  }

  function _highlightPill(priority) {
    const pills = document.querySelectorAll('#threat-pills-row .tpill');
    pills.forEach((p) => {
      if (p.dataset.priority === priority) {
        p.classList.add('tpill-active');
      } else {
        p.classList.remove('tpill-active');
        p.style.opacity = '0.4';
      }
    });
    const active = document.querySelector(
      `#threat-pills-row .tpill[data-priority="${priority}"]`,
    );
    if (active) {
      active.style.opacity = '1';
    }
  }

  function _clearPillHighlights() {
    const pills = document.querySelectorAll('#threat-pills-row .tpill');
    pills.forEach((p) => {
      p.classList.remove('tpill-active');
      p.style.opacity = '1';
    });
  }

  /* ══════════════════════════════════════
     Public: update()
     ══════════════════════════════════════ */
  function update(summary, features) {
    if (!summary && !features) {
      console.warn('[StatsBar] update() called with no data');
      return;
    }

    summary = summary || {};
    features = features || [];

    const total = summary.total || features.length || 0;
    setText('stat-total', total || '—');
    setText('stat-high-val', summary.high_confidence ?? '—');
    setText('stat-medium-val', summary.medium_confidence ?? '—');
    setText('stat-low-val', summary.low_confidence ?? '—');

    // Threat breakdown
    const tb = summary.threat_breakdown || {};
    setText('pill-critical', tb.critical ?? 0);
    setText('pill-high', tb.high ?? 0);
    setText('pill-elevated', tb.elevated ?? 0);
    setText('pill-monitor', tb.monitor ?? 0);

    // Top score
    const topScore = summary.top_threat_score;
    const scoreEl = el('stat-top-score');
    if (scoreEl) {
      scoreEl.textContent = topScore != null ? topScore : '—';
      if (topScore != null && typeof scoreColor === 'function') {
        scoreEl.style.color = scoreColor(topScore);
      }
    }

    // Alert count
    const alertCount = summary.alert_count ?? summary.alerts ?? '—';
    setText('stat-alerts', alertCount);

    // Timestamp
    setText(
      'stat-updated',
      new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    );

    console.log(`[StatsBar] Updated — ${total} hotspots`);
  }

  /* ══════════════════════════════════════
     Public: filterByPriority()
     ══════════════════════════════════════ */
  function filterByPriority(level) {
    const f = el('confidence-filter');
    if (!f) return;

    if (level === 'ALL') {
      f.value = 'all';
    } else if (level === 'CRITICAL') {
      f.value = 'critical';
    } else if (level === 'HIGH') {
      f.value = 'high+';
    } else {
      f.value = 'all';
    }

    if (typeof MapView !== 'undefined' && MapView.applyFilter) {
      MapView.applyFilter();
    }
  }

  /* ══════════════════════════════════════
     Public: setRefreshing()
     ══════════════════════════════════════ */
  function setRefreshing(loading) {
    const btn = el('refresh-btn');
    const icon = el('refresh-icon');
    if (!btn) return;

    btn.disabled = !!loading;
    btn.classList.toggle('refreshing', !!loading);

    if (icon) {
      icon.style.display = loading ? 'none' : '';
    }

    // Manage spinner element
    const existingSpinner = btn.querySelector('.spin');

    if (loading && !existingSpinner) {
      const s = document.createElement('span');
      s.className = 'spin';
      s.textContent = '↻';
      s.setAttribute('aria-hidden', 'true');
      btn.prepend(s);
    } else if (!loading && existingSpinner) {
      existingSpinner.remove();
    }
  }

  /* ══════════════════════════════════════
     Public: getDays() — helper for other
     modules to read the selected range
     ══════════════════════════════════════ */
  function getDays() {
    const sel = el('days-select');
    return sel ? parseInt(sel.value, 10) : 2;
  }

  function getFilter() {
    const sel = el('confidence-filter');
    return sel ? sel.value : 'all';
  }

  return {
    render,
    update,
    filterByPriority,
    setRefreshing,
    getDays,
    getFilter,
  };
})();

window.StatsBar = StatsBar;
