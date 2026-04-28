/* ══════════════════════════════════════════
   mlView.js — ML Analysis Panel v1.3
   Changes from v1.2:
   • Added _LEVEL_CONFIG — single source of truth
     for human-readable level names, descriptions,
     action items, colors, and icons
   • Added _formatReport() — generates clean,
     readable HTML reports replacing raw backend
     labels like "CRITICAL -- IMMEDIATE_INVESTIGATION"
   • Added _normalizeLevel() — maps any backend
     level string to a known enum safely
   • Added _confidenceBar() — visual confidence
     indicator with color gradient
   • Added _formatTimestamp() — readable dates
   • Replaced all calls to API.formatMLResult()
     with _formatReport() for consistency
   • Kept API.getRecommendationColor/Icon as
     fallbacks but primary styling now comes
     from _LEVEL_CONFIG
   • Popup and panel results now show:
       – Plain-English threat level name
       – Clear action recommendation
       – Confidence bar with percentage
       – Classification label in readable form
       – Timestamp of analysis
   ══════════════════════════════════════════ */

const MLView = (() => {
  /* ══════════════════════════════════════
     STATE
     ══════════════════════════════════════ */
  let _mlResultsLayer = null;
  let _clickListenerActive = false;
  let _drawRect = null;
  let _drawStart = null;
  let _drawHandlers = null;
  let _modelReady = false;

  /* ══════════════════════════════════════
     LEVEL CONFIGURATION
     Single source of truth for every
     threat level the backend can return.
     ══════════════════════════════════════ */
  const _LEVEL_CONFIG = {
    critical: {
      key: 'critical',
      label: 'Critical Threat',
      summary: 'Immediate attention required',
      description:
        'This location shows strong indicators consistent with ' +
        'illegal encampment activity. High-confidence detection ' +
        'suggests urgent verification is warranted.',
      action:
        'Dispatch a verification team as soon as possible. ' +
        'Coordinate with local authorities and document findings.',
      color: '#f85149',
      bgColor: 'rgba(248, 81, 73, 0.08)',
      borderColor: 'rgba(248, 81, 73, 0.4)',
      icon: 'fa-exclamation-triangle',
      cssClass: 'ml-level-critical',
    },
    high: {
      key: 'high',
      label: 'High Concern',
      summary: 'Investigation recommended',
      description:
        'This location exhibits notable features that may indicate ' +
        'encampment presence. The detection confidence supports ' +
        'prioritized follow-up.',
      action:
        'Schedule a review within 24–48 hours. Cross-reference ' +
        'with recent patrol data and neighboring hotspot reports.',
      color: '#fb8f44',
      bgColor: 'rgba(251, 143, 68, 0.08)',
      borderColor: 'rgba(251, 143, 68, 0.4)',
      icon: 'fa-exclamation-circle',
      cssClass: 'ml-level-high',
    },
    medium: {
      key: 'medium',
      label: 'Moderate Interest',
      summary: 'Worth monitoring',
      description:
        'Some features at this location are consistent with potential ' +
        'activity, but confidence is moderate. This may reflect ' +
        'ambiguous terrain or partial indicators.',
      action:
        'Add to the monitoring queue. Re-scan in the next ' +
        'scheduled cycle or if new hotspot data emerges nearby.',
      color: '#d29922',
      bgColor: 'rgba(210, 153, 34, 0.08)',
      borderColor: 'rgba(210, 153, 34, 0.4)',
      icon: 'fa-info-circle',
      cssClass: 'ml-level-medium',
    },
    low: {
      key: 'low',
      label: 'Low Concern',
      summary: 'No significant indicators',
      description:
        'This location does not show strong signs of encampment ' +
        'activity. The classification suggests normal terrain or ' +
        'vegetation patterns.',
      action:
        'No immediate action needed. Location will be ' +
        'revisited in routine scanning cycles.',
      color: '#3fb950',
      bgColor: 'rgba(63, 185, 80, 0.08)',
      borderColor: 'rgba(63, 185, 80, 0.4)',
      icon: 'fa-check-circle',
      cssClass: 'ml-level-low',
    },
    unknown: {
      key: 'unknown',
      label: 'Unclassified',
      summary: 'Could not determine threat level',
      description:
        'The model returned a result but the threat level could not ' +
        'be mapped to a known category. This may indicate a backend ' +
        'version mismatch or an unexpected classification label.',
      action:
        'Review the raw model output manually. Consider ' +
        're-running the analysis or checking model status.',
      color: '#8b949e',
      bgColor: 'rgba(139, 148, 158, 0.08)',
      borderColor: 'rgba(139, 148, 158, 0.4)',
      icon: 'fa-question-circle',
      cssClass: 'ml-level-unknown',
    },
  };

  /* ══════════════════════════════════════
     LEVEL NORMALIZER
     Maps any backend level string to a
     known _LEVEL_CONFIG key.
     Handles shapes like:
       "CRITICAL"
       "IMMEDIATE_INVESTIGATION"
       "CRITICAL -- IMMEDIATE_INVESTIGATION"
       "high_priority"
       "LOW_CONCERN"
     ══════════════════════════════════════ */
  function _normalizeLevel(raw) {
    if (!raw || typeof raw !== 'string') return 'unknown';

    const s = raw
      .toLowerCase()
      .replace(/[^a-z]/g, ' ')
      .trim();

    // Direct match first
    if (_LEVEL_CONFIG[s]) return s;

    // Keyword scanning — order matters (most severe first)
    if (/critical|immediate|emergency|urgent/.test(s)) return 'critical';
    if (/high|elevated|priority|investigate/.test(s)) return 'high';
    if (/medium|moderate|watch|monitor|caution/.test(s)) return 'medium';
    if (/low|minimal|normal|clear|none|no.?concern/.test(s)) return 'low';

    return 'unknown';
  }

  /* ══════════════════════════════════════
     CLASSIFICATION LABEL FORMATTER
     Turns raw model labels like
     "illegal_encampment" into
     "Illegal Encampment"
     ══════════════════════════════════════ */
  function _formatClassLabel(raw) {
    if (!raw || typeof raw !== 'string') return 'Unknown';
    return raw
      .replace(/[_-]/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
      .trim();
  }

  /* ══════════════════════════════════════
     CONFIDENCE BAR
     Visual indicator with gradient color
     ══════════════════════════════════════ */
  function _confidenceBar(confidence, levelConfig) {
    const pct =
      confidence != null
        ? (confidence > 1 ? confidence : confidence * 100).toFixed(1)
        : null;

    if (pct === null) return '';

    const color = levelConfig.color;
    return `
      <div class="ml-confidence-row">
        <span class="ml-confidence-label">Confidence</span>
        <div class="ml-confidence-track">
          <div class="ml-confidence-fill"
               style="width:${pct}%;background:${color};"></div>
        </div>
        <span class="ml-confidence-pct">${pct}%</span>
      </div>`;
  }

  /* ══════════════════════════════════════
     TIMESTAMP FORMATTER
     ══════════════════════════════════════ */
  function _formatTimestamp(ts) {
    if (!ts) return null;
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return null;
      return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return null;
    }
  }

  /* ══════════════════════════════════════
     REPORT FORMATTER — the core change
     Replaces API.formatMLResult() usage
     with a clean, readable HTML report.
     ══════════════════════════════════════ */
  function _formatReport(result, recommendation) {
    if (!result) {
      return `<div class="ml-report ml-report-empty">
                <p>No analysis data available.</p>
              </div>`;
    }

    // ── Pull fields from either shape ──
    const rawLevel =
      recommendation?.level ||
      result?.level ||
      result?.threat_level ||
      result?.recommendation?.level ||
      '';
    const levelKey = _normalizeLevel(rawLevel);
    const cfg = _LEVEL_CONFIG[levelKey];

    const classLabel = _formatClassLabel(
      result.label || result.class || result.classification || '',
    );

    const confidence =
      result.confidence ?? result.score ?? result.probability ?? null;

    const rawMessage =
      recommendation?.message ||
      result?.message ||
      recommendation?.description ||
      '';

    const timestamp =
      _formatTimestamp(result.timestamp || result.analyzed_at) ||
      _formatTimestamp(new Date().toISOString());

    // ── Build HTML ──
    return `
      <div class="ml-report" style="
        background:${cfg.bgColor};
        border:1px solid ${cfg.borderColor};
        border-left:4px solid ${cfg.color};
        border-radius:6px;
        padding:12px 14px;
      ">
        <!-- Header: icon + level label -->
        <div class="ml-report-header">
          <div class="ml-report-icon" style="color:${cfg.color}">
            <i class="fas ${cfg.icon}"></i>
          </div>
          <div class="ml-report-title-block">
            <div class="ml-report-level ${cfg.cssClass}">
              ${cfg.label}
            </div>
            <div class="ml-report-summary">${cfg.summary}</div>
          </div>
        </div>

        <!-- Classification -->
        <div class="ml-report-classification">
          <span class="ml-report-field-label">Classification</span>
          <span class="ml-report-field-value">${classLabel}</span>
        </div>

        <!-- Confidence bar -->
        ${_confidenceBar(confidence, cfg)}

        <!-- Description -->
        <div class="ml-report-desc">
          ${cfg.description}
        </div>

        <!-- Recommended action -->
        <div class="ml-report-action">
          <i class="fas fa-clipboard-list"></i>
          <div>
            <strong>Recommended Action</strong>
            <p>${cfg.action}</p>
          </div>
        </div>

        ${
          rawMessage && rawMessage !== cfg.description
            ? `<div class="ml-report-raw-note">
                 <span class="ml-report-field-label">Model note</span>
                 <span>${rawMessage}</span>
               </div>`
            : ''
        }

        <!-- Timestamp -->
        ${
          timestamp
            ? `<div class="ml-report-meta">
                 <i class="fas fa-clock"></i> Analyzed ${timestamp}
               </div>`
            : ''
        }
      </div>`;
  }

  /* ══════════════════════════════════════
     BOOTSTRAP
     ══════════════════════════════════════ */
  async function init() {
    _buildPanel();
    _bindToolbarButton();
    _bindPanelEvents();
    await _checkModelStatus();
    console.log('[MLView] Initialized ✓');
  }

  /* ══════════════════════════════════════
     MODEL STATUS CHECK
     ══════════════════════════════════════ */
  async function _checkModelStatus() {
    try {
      const status = await API.getMLStatus();
      _modelReady = status.model_loaded === true;

      const badge = document.getElementById('ml-status-badge');
      if (badge) {
        badge.textContent = _modelReady ? '● Model ready' : '○ Model offline';
        badge.style.color = _modelReady ? 'var(--monitor)' : 'var(--elevated)';
      }

      if (_modelReady && status.capabilities) {
        const cap = status.capabilities;
        _setText('ml-cap-classes', cap.classes?.join(', ') || '—');
        _setText('ml-cap-zoom', cap.zoom_levels?.join(', ') || '—');
        _setText('ml-cap-tta', cap.tta_enabled ? 'Yes' : 'No');
        _setText(
          'ml-cap-threshold',
          cap.confidence_threshold
            ? (cap.confidence_threshold * 100).toFixed(0) + '%'
            : '—',
        );
      }

      console.log('[MLView] Model status:', status);
    } catch (err) {
      console.warn('[MLView] Status check failed:', err);
    }
  }

  /* ══════════════════════════════════════
     PANEL HTML
     ══════════════════════════════════════ */
  function _buildPanel() {
    document.getElementById('ml-panel')?.remove();

    const panel = document.createElement('div');
    panel.id = 'ml-panel';
    panel.className = 'ml-panel';
    panel.setAttribute('aria-label', 'ML Analysis Panel');

    panel.innerHTML = `
      <div class="ml-panel-header">
        <span class="ml-panel-title">
          <i class="fas fa-brain"></i> ML Analysis
        </span>
        <span id="ml-status-badge" class="ml-status-badge">○ Checking…</span>
        <button id="ml-panel-close" class="ml-close-btn" title="Close (Escape)">✕</button>
      </div>

      <div class="ml-caps">
        <span>Classes: <strong id="ml-cap-classes">…</strong></span>
        <span>Zoom: <strong id="ml-cap-zoom">…</strong></span>
        <span>TTA: <strong id="ml-cap-tta">…</strong></span>
        <span>Threshold: <strong id="ml-cap-threshold">…</strong></span>
      </div>

      <div class="ml-tabs" role="tablist">
        <button class="ml-tab active" data-tab="hotspots"   role="tab">Hotspot Scan</button>
        <button class="ml-tab"        data-tab="coordinate" role="tab">Coordinate</button>
        <button class="ml-tab"        data-tab="area"       role="tab">Area Scan</button>
        <button class="ml-tab"        data-tab="upload"     role="tab">Upload</button>
      </div>

      <!-- ══ TAB: Hotspot Scan ══ -->
      <div class="ml-tab-content active" id="ml-tab-hotspots">
        <p class="ml-tab-desc">
          Runs ML classification on the most recent NASA FIRMS hotspots.
          Downloads a satellite tile for each location and classifies it.
        </p>
        <div class="ml-form-row">
          <label>Days of FIRMS data
            <select id="ml-scan-days">
              <option value="1" selected>1 day</option>
              <option value="3">3 days</option>
              <option value="7">7 days</option>
            </select>
          </label>
          <label>Max hotspots
            <select id="ml-scan-limit">
              <option value="25">25</option>
              <option value="50" selected>50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
        <button id="ml-scan-btn" class="ml-primary-btn">
          <i class="fas fa-satellite-dish"></i> Scan Hotspots
        </button>
        <div id="ml-scan-progress" class="ml-progress hidden"></div>
        <div id="ml-scan-summary"  class="ml-summary hidden"></div>
      </div>

      <!-- ══ TAB: Coordinate ══ -->
      <div class="ml-tab-content" id="ml-tab-coordinate">
        <p class="ml-tab-desc">
          Analyze a specific latitude / longitude.
          Or click <strong>Pick on map</strong> then click anywhere.
        </p>
        <div class="ml-form-row">
          <label>Latitude
            <input id="ml-coord-lat" type="number" step="0.0001"
                   placeholder="e.g. 11.8" min="-90" max="90">
          </label>
          <label>Longitude
            <input id="ml-coord-lon" type="number" step="0.0001"
                   placeholder="e.g. 13.2" min="-180" max="180">
          </label>
          <label>Zoom
            <select id="ml-coord-zoom">
              <option value="15">15</option>
              <option value="16">16</option>
              <option value="17" selected>17</option>
              <option value="18">18</option>
            </select>
          </label>
        </div>
        <div class="ml-btn-row">
          <button id="ml-pick-btn" class="ml-secondary-btn">
            <i class="fas fa-crosshairs"></i> Pick on map
          </button>
          <button id="ml-coord-btn" class="ml-primary-btn">
            <i class="fas fa-search-location"></i> Analyze
          </button>
        </div>
        <div id="ml-coord-progress" class="ml-progress hidden"></div>
        <div id="ml-coord-result"   class="ml-result-block hidden"></div>
      </div>

      <!-- ══ TAB: Area Scan ══ -->
      <div class="ml-tab-content" id="ml-tab-area">
        <p class="ml-tab-desc">
          Draw a rectangle on the map, or enter bounds manually.
          Creates a grid and classifies every tile.
        </p>
        <button id="ml-draw-btn" class="ml-secondary-btn">
          <i class="fas fa-draw-polygon"></i> Draw rectangle on map
        </button>
        <div class="ml-form-row" style="margin-top:8px">
          <label>Lat min <input id="ml-lat-min" type="number" step="0.01" placeholder="S"></label>
          <label>Lat max <input id="ml-lat-max" type="number" step="0.01" placeholder="N"></label>
          <label>Lon min <input id="ml-lon-min" type="number" step="0.01" placeholder="W"></label>
          <label>Lon max <input id="ml-lon-max" type="number" step="0.01" placeholder="E"></label>
        </div>
        <div class="ml-form-row">
          <label>Grid step (°)
            <select id="ml-grid-step">
              <option value="0.005">0.005 — fine</option>
              <option value="0.01" selected>0.01 — normal</option>
              <option value="0.02">0.02 — coarse</option>
            </select>
          </label>
        </div>
        <button id="ml-area-btn" class="ml-primary-btn">
          <i class="fas fa-th"></i> Scan Area
        </button>
        <div id="ml-area-progress" class="ml-progress hidden"></div>
        <div id="ml-area-summary"  class="ml-summary hidden"></div>
      </div>

      <!-- ══ TAB: Upload ══ -->
      <div class="ml-tab-content" id="ml-tab-upload">
        <p class="ml-tab-desc">
          Upload a satellite image (JPEG / PNG) for instant classification.
          Supports single or batch upload.
        </p>
        <div id="ml-drop-zone" class="ml-drop-zone" role="button"
             tabindex="0" aria-label="Drop satellite images here">
          <i class="fas fa-cloud-upload-alt fa-2x"></i>
          <p>Drop images here or <u>click to browse</u></p>
          <p style="font-size:10px;color:var(--text-muted)">JPEG / PNG · max 10MB each</p>
          <input id="ml-file-input" type="file" accept="image/jpeg,image/png"
                 multiple style="display:none">
        </div>
        <div id="ml-upload-queue"    class="ml-upload-queue hidden"></div>
        <button id="ml-upload-btn"   class="ml-primary-btn hidden">
          <i class="fas fa-microscope"></i> Classify Images
        </button>
        <div id="ml-upload-progress" class="ml-progress hidden"></div>
        <div id="ml-upload-results"  class="ml-result-block hidden"></div>
      </div>

      <!-- ── Footer ── -->
      <div class="ml-footer">
        <button id="ml-clear-btn" class="ml-ghost-btn">
          <i class="fas fa-trash-alt"></i> Clear ML layer
        </button>
        <span id="ml-marker-count" class="ml-marker-count">0 markers</span>
        <button id="ml-refresh-model" class="ml-ghost-btn" title="Re-check model status">
          <i class="fas fa-sync-alt"></i>
        </button>
      </div>
    `;

    document.body.appendChild(panel);
    _injectStyles();
  }

  /* ══════════════════════════════════════
     TOOLBAR BUTTON
     ══════════════════════════════════════ */
  function _bindToolbarButton() {
    console.log('[MLView] Toolbar button managed by StatsBar ✓');
  }

  /* ══════════════════════════════════════
     PANEL EVENT BINDINGS
     ══════════════════════════════════════ */
  function _bindPanelEvents() {
    document
      .getElementById('ml-panel-close')
      ?.addEventListener('click', closePanel);

    document
      .getElementById('ml-refresh-model')
      ?.addEventListener('click', _checkModelStatus);

    document
      .getElementById('ml-clear-btn')
      ?.addEventListener('click', clearMLLayer);

    document.querySelectorAll('.ml-tab').forEach((tab) => {
      tab.addEventListener('click', () => _switchTab(tab.dataset.tab));
    });

    document
      .getElementById('ml-scan-btn')
      ?.addEventListener('click', _runHotspotScan);

    document
      .getElementById('ml-coord-btn')
      ?.addEventListener('click', _runCoordinateAnalysis);

    document
      .getElementById('ml-pick-btn')
      ?.addEventListener('click', _startMapPick);

    document
      .getElementById('ml-draw-btn')
      ?.addEventListener('click', _startAreaDraw);

    document
      .getElementById('ml-area-btn')
      ?.addEventListener('click', _runAreaScan);

    const dropZone = document.getElementById('ml-drop-zone');
    const fileInput = document.getElementById('ml-file-input');

    dropZone?.addEventListener('click', () => fileInput?.click());
    dropZone?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') fileInput?.click();
    });
    dropZone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
    dropZone?.addEventListener('dragleave', () =>
      dropZone.classList.remove('drag-over'),
    );
    dropZone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      _handleFiles(e.dataTransfer.files);
    });
    fileInput?.addEventListener('change', (e) => _handleFiles(e.target.files));

    document
      .getElementById('ml-upload-btn')
      ?.addEventListener('click', _runUploadClassify);
  }

  /* ══════════════════════════════════════
     TAB SWITCHER
     ══════════════════════════════════════ */
  function _switchTab(tabId) {
    document
      .querySelectorAll('.ml-tab')
      .forEach((t) => t.classList.toggle('active', t.dataset.tab === tabId));
    document
      .querySelectorAll('.ml-tab-content')
      .forEach((c) => c.classList.toggle('active', c.id === `ml-tab-${tabId}`));
  }

  /* ══════════════════════════════════════
     PANEL OPEN / CLOSE
     ══════════════════════════════════════ */
  function togglePanel() {
    const panel = document.getElementById('ml-panel');
    if (!panel) return;
    panel.classList.contains('open') ? closePanel() : openPanel();
  }

  function openPanel() {
    document.getElementById('ml-panel')?.classList.add('open');
    if (typeof StatsBar !== 'undefined' && StatsBar.setMLActive) {
      StatsBar.setMLActive(true);
    }
  }

  function closePanel() {
    document.getElementById('ml-panel')?.classList.remove('open');
    _cancelMapPick();
    _cancelAreaDraw();
    if (typeof StatsBar !== 'undefined' && StatsBar.setMLActive) {
      StatsBar.setMLActive(false);
    }
  }

  /* ══════════════════════════════════════
     ERROR HELPER
     ══════════════════════════════════════ */
  function _extractError(err) {
    if (!err) return 'Unknown error';
    if (err instanceof Error) {
      try {
        const parsed = JSON.parse(err.message);
        return parsed.detail || parsed.message || err.message;
      } catch {
        return err.message || 'Unknown error';
      }
    }
    if (typeof err === 'string') return err;
    if (err.detail) return err.detail;
    if (err.message) return err.message;
    return JSON.stringify(err);
  }

  /* ══════════════════════════════════════
     RESULT UNWRAPPER
     ══════════════════════════════════════ */
  function _unwrapResult(raw) {
    if (!raw) return null;
    if (raw.result && typeof raw.result === 'object') return raw.result;
    if (raw.prediction && typeof raw.prediction === 'object')
      return raw.prediction;
    if (raw.label !== undefined) return raw;
    return raw;
  }

  /* ══════════════════════════════════════
     TOAST LEVEL — readable toast messages
     ══════════════════════════════════════ */
  function _toastLevel(levelKey) {
    const map = {
      critical: 'Critical Threat detected',
      high: 'High Concern flagged',
      medium: 'Moderate Interest noted',
      low: 'Low Concern — area appears clear',
      unknown: 'Analysis complete (unclassified)',
    };
    return map[levelKey] || map.unknown;
  }

  /* ══════════════════════════════════════
     HOTSPOT SCAN
     ══════════════════════════════════════ */
  async function _runHotspotScan() {
    if (!_assertModelReady()) return;

    const days = parseInt(document.getElementById('ml-scan-days')?.value || 1);
    const limit = parseInt(
      document.getElementById('ml-scan-limit')?.value || 50,
    );
    const btn = document.getElementById('ml-scan-btn');
    const prog = document.getElementById('ml-scan-progress');
    const summ = document.getElementById('ml-scan-summary');

    _setLoading(btn, prog, true, `Scanning ${limit} hotspots over ${days}d…`);
    summ?.classList.add('hidden');

    try {
      const raw = await API.scanHotspots(days, limit);
      console.log('[MLView] scanHotspots raw response:', raw);

      const result = {
        ...raw,
        total_scanned: raw.total_scanned ?? raw.scanned ?? 0,
        flagged_count: raw.flagged_count ?? raw.flagged ?? 0,
        skipped: raw.skipped ?? raw.tile_failures ?? 0,
        duration_seconds: raw.duration_seconds ?? null,
        flagged_locations: _extractFlaggedLocations(raw),
      };

      _setLoading(btn, prog, false);
      _renderScanResults(result, summ);
      _plotResultsOnMap(result.flagged_locations, null, null);

      const msg = result.flagged_count
        ? `Scan complete — ${result.flagged_count} location${result.flagged_count > 1 ? 's' : ''} flagged for review`
        : 'Scan complete — no suspicious locations detected';
      showToast(msg, result.flagged_count ? 'warning' : 'success');
    } catch (err) {
      _setLoading(btn, prog, false);
      showToast('Hotspot scan failed: ' + _extractError(err), 'error');
      console.error('[MLView] scanHotspots error:', err);
    }
  }

  function _extractFlaggedLocations(raw) {
    if (Array.isArray(raw.flagged_locations)) return raw.flagged_locations;
    if (Array.isArray(raw.results)) {
      return raw.results.filter(
        (r) => r.status === 'analyzed' && r.prediction?.flag === true,
      );
    }
    return [];
  }

  function _renderScanResults(result, container) {
    if (!container) return;

    const total = result.total_scanned || 0;
    const flagged = result.flagged_count || 0;
    const skipped = result.skipped || 0;
    const dur = result.duration_seconds
      ? `${result.duration_seconds.toFixed(1)}s`
      : '—';

    container.innerHTML = `
      <div class="ml-summary-grid">
        <div class="ml-summ-cell">
          <span class="ml-summ-val">${total}</span>
          <span class="ml-summ-lbl">Scanned</span>
        </div>
        <div class="ml-summ-cell flagged">
          <span class="ml-summ-val">${flagged}</span>
          <span class="ml-summ-lbl">Flagged</span>
        </div>
        <div class="ml-summ-cell">
          <span class="ml-summ-val">${skipped}</span>
          <span class="ml-summ-lbl">Skipped</span>
        </div>
        <div class="ml-summ-cell">
          <span class="ml-summ-val">${dur}</span>
          <span class="ml-summ-lbl">Duration</span>
        </div>
      </div>
      ${
        flagged
          ? `<p class="ml-summ-note">
               <i class="fas fa-map-marker-alt"></i>
               ${flagged} location${flagged > 1 ? 's' : ''} flagged for review
               — markers placed on the map.
             </p>`
          : `<p class="ml-summ-note ok">
               <i class="fas fa-check-circle"></i>
               No suspicious encampment indicators detected across all scanned locations.
             </p>`
      }
    `;
    container.classList.remove('hidden');
  }

  /* ══════════════════════════════════════
     COORDINATE ANALYSIS
     ══════════════════════════════════════ */
  async function _runCoordinateAnalysis() {
    if (!_assertModelReady()) return;

    const lat = parseFloat(document.getElementById('ml-coord-lat')?.value);
    const lon = parseFloat(document.getElementById('ml-coord-lon')?.value);
    const zoom = parseInt(
      document.getElementById('ml-coord-zoom')?.value || 17,
    );

    if (isNaN(lat) || isNaN(lon)) {
      showToast('Please enter valid coordinates', 'warning');
      return;
    }
    if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
      showToast('Coordinates out of range', 'warning');
      return;
    }

    await _analyzeWithCoords(lat, lon, zoom);
  }

  async function _analyzeWithCoords(lat, lon, zoom) {
    const btn = document.getElementById('ml-coord-btn');
    const prog = document.getElementById('ml-coord-progress');
    const res = document.getElementById('ml-coord-result');

    _setLoading(
      btn,
      prog,
      true,
      `Analyzing ${lat.toFixed(4)}, ${lon.toFixed(4)}…`,
    );
    if (res) res.classList.add('hidden');

    try {
      const raw = await API.analyzeLocation(lat, lon, zoom);
      const result = _unwrapResult(raw);
      const rec = raw.recommendation || result?.recommendation || {};

      _setLoading(btn, prog, false);
      _renderCoordResult(result, rec, res);
      _plotResultsOnMap([raw], lat, lon);
      window._map?.setView([lat, lon], 14, { animate: true });

      // ── Readable toast ──
      const levelKey = _normalizeLevel(rec.level);
      showToast(
        _toastLevel(levelKey),
        levelKey === 'low' ? 'success' : 'warning',
      );
    } catch (err) {
      _setLoading(btn, prog, false);
      showToast('Analysis failed: ' + _extractError(err), 'error');
      console.error('[MLView] analyzeLocation error:', err);
    }
  }

  function _renderCoordResult(result, rec, container) {
    if (!container) return;
    if (!result) {
      container.innerHTML =
        '<p style="color:var(--text-muted)">No result data returned.</p>';
      container.classList.remove('hidden');
      return;
    }
    // ── Use our own _formatReport instead of API.formatMLResult ──
    container.innerHTML = _formatReport(result, rec);
    container.style.borderLeft = 'none';
    container.classList.remove('hidden');
  }

  /* ══════════════════════════════════════
     MAP CLICK — "PICK ON MAP" MODE
     ══════════════════════════════════════ */
  function _startMapPick() {
    if (_clickListenerActive) {
      _cancelMapPick();
      return;
    }

    _clickListenerActive = true;
    const btn = document.getElementById('ml-pick-btn');
    if (btn) {
      btn.textContent = '⊠ Cancel pick';
      btn.classList.add('picking');
    }

    showToast('Click anywhere on the map to analyze that location', 'info');
    window._map?.getContainer().classList.add('ml-crosshair');

    window._map?.once('click', (e) => {
      _clickListenerActive = false;
      window._map?.getContainer().classList.remove('ml-crosshair');
      if (btn) {
        btn.innerHTML = '<i class="fas fa-crosshairs"></i> Pick on map';
        btn.classList.remove('picking');
      }

      const { lat, lng } = e.latlng;
      const latInput = document.getElementById('ml-coord-lat');
      const lonInput = document.getElementById('ml-coord-lon');
      if (latInput) latInput.value = lat.toFixed(5);
      if (lonInput) lonInput.value = lng.toFixed(5);

      showToast(
        `Selected ${lat.toFixed(4)}, ${lng.toFixed(4)} — running analysis…`,
        'info',
      );
      _runCoordinateAnalysis();
    });
  }

  function _cancelMapPick() {
    _clickListenerActive = false;
    window._map?.getContainer().classList.remove('ml-crosshair');
    window._map?.off('click');
    const btn = document.getElementById('ml-pick-btn');
    if (btn) {
      btn.innerHTML = '<i class="fas fa-crosshairs"></i> Pick on map';
      btn.classList.remove('picking');
    }
  }

  /* ══════════════════════════════════════
     AREA DRAW
     ══════════════════════════════════════ */
  function _startAreaDraw() {
    if (_drawStart !== null || _drawHandlers !== null) {
      _cancelAreaDraw();
      return;
    }

    const btn = document.getElementById('ml-draw-btn');
    if (btn) {
      btn.innerHTML = '⊠ Cancel draw';
      btn.classList.add('picking');
    }

    showToast('Click the first corner of the scan area', 'info');
    window._map?.getContainer().classList.add('ml-crosshair');

    function onFirstClick(e) {
      _drawStart = { lat: e.latlng.lat, lon: e.latlng.lng };
      showToast('Now click the opposite corner', 'info');
      window._map?.on('mousemove', _updateDrawRect);
      window._map?.once('click', _drawHandlers.onSecondClick);
    }

    function onSecondClick(e) {
      if (_drawStart === null) return;
      _finishAreaDraw(e.latlng.lat, e.latlng.lng);
    }

    _drawHandlers = { onFirstClick, onSecondClick };
    window._map?.once('click', onFirstClick);
  }

  function _updateDrawRect(e) {
    if (!_drawStart) return;
    const latMin = Math.min(_drawStart.lat, e.latlng.lat);
    const latMax = Math.max(_drawStart.lat, e.latlng.lat);
    const lonMin = Math.min(_drawStart.lon, e.latlng.lng);
    const lonMax = Math.max(_drawStart.lon, e.latlng.lng);
    if (_drawRect) window._map?.removeLayer(_drawRect);
    _drawRect = L.rectangle(
      [
        [latMin, lonMin],
        [latMax, lonMax],
      ],
      { color: '#3b9eff', weight: 2, fillOpacity: 0.1, dashArray: '6 4' },
    ).addTo(window._map);
  }

  function _finishAreaDraw(lat2, lon2) {
    if (_drawStart === null) {
      console.warn('[MLView] _finishAreaDraw called with null _drawStart');
      return;
    }

    const latMin = Math.min(_drawStart.lat, lat2);
    const latMax = Math.max(_drawStart.lat, lat2);
    const lonMin = Math.min(_drawStart.lon, lon2);
    const lonMax = Math.max(_drawStart.lon, lon2);

    _cancelAreaDraw(true);

    const latMinEl = document.getElementById('ml-lat-min');
    const latMaxEl = document.getElementById('ml-lat-max');
    const lonMinEl = document.getElementById('ml-lon-min');
    const lonMaxEl = document.getElementById('ml-lon-max');

    if (latMinEl) latMinEl.value = latMin.toFixed(4);
    if (latMaxEl) latMaxEl.value = latMax.toFixed(4);
    if (lonMinEl) lonMinEl.value = lonMin.toFixed(4);
    if (lonMaxEl) lonMaxEl.value = lonMax.toFixed(4);

    showToast('Area selected — click "Scan Area" to run ML analysis', 'info');
  }

  function _cancelAreaDraw(keepRect = false) {
    if (_drawHandlers) {
      window._map?.off('click', _drawHandlers.onFirstClick);
      window._map?.off('click', _drawHandlers.onSecondClick);
      _drawHandlers = null;
    }

    _drawStart = null;
    window._map?.off('mousemove', _updateDrawRect);
    window._map?.getContainer().classList.remove('ml-crosshair');

    if (!keepRect && _drawRect) {
      window._map?.removeLayer(_drawRect);
      _drawRect = null;
    }

    const btn = document.getElementById('ml-draw-btn');
    if (btn) {
      btn.innerHTML =
        '<i class="fas fa-draw-polygon"></i> Draw rectangle on map';
      btn.classList.remove('picking');
    }
  }

  /* ══════════════════════════════════════
     AREA SCAN
     ══════════════════════════════════════ */
  async function _runAreaScan() {
    if (!_assertModelReady()) return;

    const latMin = parseFloat(document.getElementById('ml-lat-min')?.value);
    const latMax = parseFloat(document.getElementById('ml-lat-max')?.value);
    const lonMin = parseFloat(document.getElementById('ml-lon-min')?.value);
    const lonMax = parseFloat(document.getElementById('ml-lon-max')?.value);
    const gridStep = parseFloat(
      document.getElementById('ml-grid-step')?.value || 0.01,
    );

    if ([latMin, latMax, lonMin, lonMax].some(isNaN)) {
      showToast('Please fill all four bounds (or draw on map)', 'warning');
      return;
    }
    if (latMin >= latMax || lonMin >= lonMax) {
      showToast('Min must be less than Max for each axis', 'warning');
      return;
    }

    const latTiles = Math.ceil((latMax - latMin) / gridStep);
    const lonTiles = Math.ceil((lonMax - lonMin) / gridStep);
    const estTiles = latTiles * lonTiles;

    if (estTiles > 400) {
      showToast(
        `Area too large (≈${estTiles} tiles). Reduce area or increase grid step.`,
        'warning',
      );
      return;
    }

    const btn = document.getElementById('ml-area-btn');
    const prog = document.getElementById('ml-area-progress');
    const summ = document.getElementById('ml-area-summary');

    if (!btn || !prog) {
      console.error('[MLView] Area scan UI elements not found');
      return;
    }

    _setLoading(btn, prog, true, `Scanning approximately ${estTiles} tiles…`);
    summ?.classList.add('hidden');

    if (_drawRect) {
      window._map?.removeLayer(_drawRect);
      _drawRect = null;
    }

    try {
      console.log('[MLView] Calling API.scanArea…', {
        latMin,
        latMax,
        lonMin,
        lonMax,
        gridStep,
      });

      const raw = await API.scanArea(latMin, latMax, lonMin, lonMax, gridStep);
      console.log('[MLView] scanArea raw response:', raw);

      const scanned = raw.grid_points_scanned ?? raw.total_scanned ?? 0;
      const total = raw.grid_points_total ?? scanned;
      const flagged = raw.flagged ?? raw.flagged_count ?? 0;
      const skipped = raw.skipped ?? total - scanned ?? 0;

      const result = {
        ...raw,
        total_scanned: scanned,
        flagged_count: flagged,
        skipped: skipped,
        duration_seconds: raw.duration_seconds ?? null,
        flagged_locations: raw.flagged_locations ?? [],
      };

      _setLoading(btn, prog, false);
      _renderScanResults(result, summ);
      _plotResultsOnMap(result.flagged_locations, null, null);

      window._map?.fitBounds(
        [
          [latMin, lonMin],
          [latMax, lonMax],
        ],
        { animate: true, duration: 0.6 },
      );

      const msg = flagged
        ? `Area scan complete — ${flagged} of ${scanned} locations flagged for review`
        : `Area scan complete — all ${scanned} locations appear clear`;
      showToast(msg, flagged ? 'warning' : 'success');
    } catch (err) {
      console.error('[MLView] scanArea error:', err);
      _setLoading(btn, prog, false);
      showToast('Area scan failed: ' + _extractError(err), 'error');
    }
  }

  /* ══════════════════════════════════════
     IMAGE UPLOAD
     ══════════════════════════════════════ */
  let _stagedFiles = [];

  function _handleFiles(fileList) {
    _stagedFiles = Array.from(fileList).filter(
      (f) => f.type === 'image/jpeg' || f.type === 'image/png',
    );
    if (_stagedFiles.length === 0) {
      showToast('No valid images selected (JPEG or PNG only)', 'warning');
      return;
    }

    const queue = document.getElementById('ml-upload-queue');
    const btn = document.getElementById('ml-upload-btn');

    if (queue) {
      queue.innerHTML = _stagedFiles
        .map(
          (f) => `
          <div class="ml-queue-item">
            <i class="fas fa-image"></i>
            <span>${f.name}</span>
            <span class="ml-queue-size">${(f.size / 1024).toFixed(0)} KB</span>
          </div>`,
        )
        .join('');
      queue.classList.remove('hidden');
    }
    if (btn) btn.classList.remove('hidden');
    showToast(
      `${_stagedFiles.length} image${_stagedFiles.length > 1 ? 's' : ''} ready — click Classify to analyze`,
      'info',
    );
  }

  async function _runUploadClassify() {
    if (_stagedFiles.length === 0) {
      showToast('No images staged for classification', 'warning');
      return;
    }
    if (!_assertModelReady()) return;

    const btn = document.getElementById('ml-upload-btn');
    const prog = document.getElementById('ml-upload-progress');
    const res = document.getElementById('ml-upload-results');

    _setLoading(
      btn,
      prog,
      true,
      `Classifying ${_stagedFiles.length} image${_stagedFiles.length > 1 ? 's' : ''}…`,
    );
    if (res) res.classList.add('hidden');

    try {
      let results;
      if (_stagedFiles.length === 1) {
        const single = await API.predictImage(_stagedFiles[0]);
        results = { predictions: [single], total: 1 };
      } else {
        results = await API.predictBatch(_stagedFiles);
      }
      _setLoading(btn, prog, false);
      _renderUploadResults(results, res);
      _stagedFiles = [];
      showToast('Classification complete — results shown below', 'success');
    } catch (err) {
      _setLoading(btn, prog, false);
      showToast('Classification failed: ' + _extractError(err), 'error');
      console.error('[MLView] upload classify error:', err);
    }
  }

  function _renderUploadResults(results, container) {
    if (!container) return;
    const preds = results.predictions || results.results || [];
    if (!preds.length) {
      container.innerHTML =
        '<p style="color:var(--text-muted)">No results returned by the model.</p>';
      container.classList.remove('hidden');
      return;
    }
    container.innerHTML = preds
      .map((p) => {
        const inner = _unwrapResult(p);
        const rec = p.recommendation || inner?.recommendation || {};
        return `
          <div class="ml-upload-pred">
            ${p.filename ? `<div class="ml-pred-file"><i class="fas fa-image"></i> ${p.filename}</div>` : ''}
            ${_formatReport(inner, rec)}
          </div>`;
      })
      .join('');
    container.classList.remove('hidden');
  }

  /* ══════════════════════════════════════
     MAP MARKERS — ML Results Layer
     ══════════════════════════════════════ */
  function _plotResultsOnMap(locations, fallbackLat, fallbackLon) {
    if (!window._map || !locations?.length) return;

    if (!_mlResultsLayer) {
      _mlResultsLayer = L.layerGroup().addTo(window._map);
    }

    locations.forEach((raw) => {
      const lat =
        raw.lat ??
        raw.latitude ??
        raw.location?.lat ??
        raw.location?.latitude ??
        fallbackLat;

      const lon =
        raw.lon ??
        raw.longitude ??
        raw.lng ??
        raw.location?.lon ??
        raw.location?.longitude ??
        raw.location?.lng ??
        fallbackLon;

      if (lat == null || lon == null || isNaN(lat) || isNaN(lon)) {
        console.warn('[MLView] Skipping marker — no coordinates:', raw);
        return;
      }

      const inner = _unwrapResult(raw.result ?? raw.prediction ?? raw);
      const rec = raw.recommendation ?? inner?.recommendation ?? {};

      // ── Use _LEVEL_CONFIG for consistent styling ──
      const levelKey = _normalizeLevel(rec.level);
      const cfg = _LEVEL_CONFIG[levelKey];

      const markerIcon = L.divIcon({
        className: '',
        html: `<div class="ml-map-marker"
                    style="background:${cfg.color};box-shadow:0 0 8px ${cfg.color}99;">
                 <i class="fas ${cfg.icon}"></i>
               </div>`,
        iconSize: [28, 28],
        iconAnchor: [14, 14],
        popupAnchor: [0, -16],
      });

      const marker = L.marker([lat, lon], { icon: markerIcon });

      // ── Popup uses _formatReport for readable output ──
      marker.bindPopup(
        `<div style="min-width:260px;max-width:340px;">
           <div style="font-size:11px;color:#8b949e;margin-bottom:6px;">
             <i class="fas fa-map-pin"></i>
             ${parseFloat(lat).toFixed(5)}, ${parseFloat(lon).toFixed(5)}
           </div>
           ${_formatReport(inner, rec)}
         </div>`,
        { maxWidth: 380 },
      );

      _mlResultsLayer.addLayer(marker);
    });

    _updateMarkerCount();
  }

  function clearMLLayer() {
    _mlResultsLayer?.clearLayers();
    _updateMarkerCount();
    showToast('ML markers cleared from map', 'info');
  }

  function _updateMarkerCount() {
    const count = _mlResultsLayer
      ? Object.keys(_mlResultsLayer._layers || {}).length
      : 0;
    _setText('ml-marker-count', `${count} marker${count !== 1 ? 's' : ''}`);
  }

  /* ══════════════════════════════════════
     HELPERS
     ══════════════════════════════════════ */
  function _assertModelReady() {
    if (_modelReady) return true;
    showToast('ML model is not loaded — please check server status', 'error');
    _checkModelStatus();
    return false;
  }

  function _setLoading(btn, progEl, loading, message = '') {
    if (btn) {
      btn.disabled = loading;
      if (loading) {
        btn.dataset.originalText = btn.innerHTML;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Working…';
      } else {
        btn.innerHTML = btn.dataset.originalText || btn.innerHTML;
      }
    }
    if (progEl) {
      progEl.textContent = message;
      progEl.classList.toggle('hidden', !loading);
    }
  }

  function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  /* ══════════════════════════════════════
     CSS — injected once
     Includes new report + confidence styles
     ══════════════════════════════════════ */
  function _injectStyles() {
    if (document.getElementById('ml-panel-styles')) return;
    const style = document.createElement('style');
    style.id = 'ml-panel-styles';
    style.textContent = `
      /* ── Base panel ── */
      .ml-panel {
        position:fixed; top:60px; right:-420px; width:400px;
        max-height:calc(100vh - 80px); overflow-y:auto;
        background:#0d1117; border:1px solid #1e2d3d;
        border-radius:8px 0 0 8px; z-index:1100;
        display:flex; flex-direction:column;
        transition:right 0.28s ease; font-size:13px;
        color:#c9d1d9; box-shadow:-4px 0 24px rgba(0,0,0,.6);
      }
      .ml-panel.open { right:0; }

      /* ── Header ── */
      .ml-panel-header {
        display:flex; align-items:center; gap:8px;
        padding:12px 14px 10px; border-bottom:1px solid #1e2d3d; flex-shrink:0;
      }
      .ml-panel-title { font-weight:700; font-size:14px; color:#e8eef8; flex:1; }
      .ml-status-badge { font-size:11px; }
      .ml-close-btn {
        background:none; border:none; color:#6e7681;
        cursor:pointer; font-size:16px; padding:0 4px; transition:color .15s;
      }
      .ml-close-btn:hover { color:#e8eef8; }

      /* ── Capabilities row ── */
      .ml-caps {
        display:flex; flex-wrap:wrap; gap:6px 12px;
        padding:8px 14px; border-bottom:1px solid #1e2d3d;
        font-size:11px; color:#8b949e; flex-shrink:0;
      }
      .ml-caps strong { color:#c9d1d9; }

      /* ── Tabs ── */
      .ml-tabs { display:flex; border-bottom:1px solid #1e2d3d; flex-shrink:0; }
      .ml-tab {
        flex:1; padding:8px 4px; background:none; border:none;
        color:#8b949e; cursor:pointer; font-size:11px; font-weight:600;
        letter-spacing:.3px; transition:color .15s, border-bottom .15s;
        border-bottom:2px solid transparent;
      }
      .ml-tab:hover  { color:#c9d1d9; }
      .ml-tab.active { color:#3b9eff; border-bottom-color:#3b9eff; }
      .ml-tab-content { display:none; padding:14px; }
      .ml-tab-content.active { display:block; }
      .ml-tab-desc { font-size:11px; color:#8b949e; margin:0 0 12px; line-height:1.5; }

      /* ── Form elements ── */
      .ml-form-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }
      .ml-form-row label {
        display:flex; flex-direction:column; gap:4px;
        font-size:11px; color:#8b949e; flex:1; min-width:80px;
      }
      .ml-form-row input,
      .ml-form-row select {
        background:#161b22; border:1px solid #30363d;
        color:#c9d1d9; border-radius:5px; padding:5px 7px; font-size:12px; width:100%;
      }
      .ml-form-row input:focus,
      .ml-form-row select:focus { outline:none; border-color:#3b9eff; }

      /* ── Buttons ── */
      .ml-primary-btn, .ml-secondary-btn, .ml-ghost-btn {
        width:100%; padding:8px 12px; border-radius:5px; font-size:12px;
        font-weight:600; cursor:pointer; display:flex; align-items:center;
        justify-content:center; gap:6px;
        transition:background .15s, color .15s, opacity .15s; margin-top:4px;
      }
      .ml-primary-btn { background:#1f6feb; border:1px solid #388bfd; color:#fff; }
      .ml-primary-btn:hover:not(:disabled) { background:#388bfd; }
      .ml-primary-btn:disabled { opacity:.45; cursor:not-allowed; }
      .ml-secondary-btn { background:#161b22; border:1px solid #30363d; color:#8b949e; }
      .ml-secondary-btn:hover { border-color:#3b9eff; color:#3b9eff; }
      .ml-secondary-btn.picking { border-color:var(--elevated); color:var(--elevated); }
      .ml-ghost-btn { background:none; border:1px solid #21262d; color:#6e7681; flex:1; margin-top:0; }
      .ml-ghost-btn:hover { border-color:#30363d; color:#8b949e; }
      .ml-btn-row { display:flex; gap:8px; }
      .ml-btn-row .ml-secondary-btn,
      .ml-btn-row .ml-primary-btn { flex:1; }

      /* ── Progress ── */
      .ml-progress {
        font-size:11px; color:#8b949e; margin-top:8px; padding:6px;
        background:#161b22; border-radius:4px; border-left:3px solid #3b9eff;
      }

      /* ── Summary grid ── */
      .ml-summary-grid {
        display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:8px;
      }
      .ml-summ-cell {
        background:#161b22; border:1px solid #21262d;
        border-radius:5px; padding:8px 4px; text-align:center;
      }
      .ml-summ-cell.flagged { border-color:var(--high); }
      .ml-summ-val { display:block; font-size:18px; font-weight:700; color:#e8eef8; }
      .ml-summ-lbl { display:block; font-size:10px; color:#8b949e; margin-top:2px; }
      .ml-summ-note { font-size:11px; color:#8b949e; margin:0; }
      .ml-summ-note.ok { color:#3fb950; }

      /* ── Result block ── */
      .ml-result-block {
        margin-top:10px; padding:10px; background:#161b22;
        border-radius:5px;
      }

      /* ── Report card (NEW in v1.3) ── */
      .ml-report {
        font-size:12px; line-height:1.5;
      }
      .ml-report-empty {
        color:#8b949e; padding:12px; text-align:center;
      }
      .ml-report-header {
        display:flex; align-items:flex-start; gap:10px; margin-bottom:10px;
      }
      .ml-report-icon {
        font-size:20px; flex-shrink:0; margin-top:1px;
      }
      .ml-report-title-block { flex:1; }
      .ml-report-level {
        font-weight:700; font-size:14px; line-height:1.2;
      }
      .ml-report-summary {
        font-size:11px; color:#8b949e; margin-top:2px;
      }
      .ml-report-classification {
        display:flex; justify-content:space-between; align-items:center;
        padding:6px 8px; background:rgba(255,255,255,.03);
        border-radius:4px; margin-bottom:8px;
      }
      .ml-report-field-label {
        font-size:10px; color:#6e7681; text-transform:uppercase;
        letter-spacing:.5px;
      }
      .ml-report-field-value {
        font-weight:600; color:#e8eef8;
      }

      /* ── Confidence bar ── */
      .ml-confidence-row {
        display:flex; align-items:center; gap:8px; margin-bottom:10px;
      }
      .ml-confidence-label {
        font-size:10px; color:#6e7681; text-transform:uppercase;
        letter-spacing:.5px; flex-shrink:0; width:68px;
      }
      .ml-confidence-track {
        flex:1; height:6px; background:#21262d;
        border-radius:3px; overflow:hidden;
      }
      .ml-confidence-fill {
        height:100%; border-radius:3px;
        transition:width .4s ease;
      }
      .ml-confidence-pct {
        font-size:11px; font-weight:600; color:#c9d1d9;
        min-width:40px; text-align:right;
      }

            /* ── Description & action ── */
      .ml-report-desc {
        font-size:11px; color:#8b949e; margin-bottom:10px;
        line-height:1.55;
      }
      .ml-report-action {
        display:flex; gap:8px; padding:8px 10px;
        background:rgba(255,255,255,.03); border-radius:4px;
        margin-bottom:8px; align-items:flex-start;
      }
      .ml-report-action i {
        color:#3b9eff; margin-top:3px; flex-shrink:0;
      }
      .ml-report-action div {
        flex:1;
      }
      .ml-report-action strong {
        font-size:11px; color:#c9d1d9; display:block; margin-bottom:2px;
      }
      .ml-report-action p {
        font-size:11px; color:#8b949e; margin:0; line-height:1.5;
      }

      /* ── Raw note from model ── */
      .ml-report-raw-note {
        display:flex; flex-direction:column; gap:2px;
        padding:6px 8px; background:rgba(255,255,255,.02);
        border-radius:4px; margin-bottom:8px;
        font-size:11px; color:#8b949e;
        border-left:2px solid #30363d;
      }

      /* ── Timestamp meta ── */
      .ml-report-meta {
        font-size:10px; color:#6e7681; margin-top:4px;
        display:flex; align-items:center; gap:5px;
      }
      .ml-report-meta i {
        font-size:10px;
      }

      /* ── Level color classes ── */
      .ml-level-critical { color:#f85149; }
      .ml-level-high     { color:#fb8f44; }
      .ml-level-medium   { color:#d29922; }
      .ml-level-low      { color:#3fb950; }
      .ml-level-unknown  { color:#8b949e; }

      /* ── Drop zone ── */
      .ml-drop-zone {
        border:2px dashed #30363d; border-radius:6px; padding:24px 12px;
        text-align:center; cursor:pointer; color:#8b949e;
        transition:border-color .15s, background .15s;
      }
      .ml-drop-zone:hover, .ml-drop-zone.drag-over {
        border-color:#3b9eff; background:#161b22;
      }
      .ml-drop-zone p { margin:6px 0 0; font-size:12px; }

      /* ── Upload queue ── */
      .ml-upload-queue { margin:8px 0; }
      .ml-queue-item {
        display:flex; align-items:center; gap:8px; padding:5px 6px;
        background:#161b22; border-radius:4px; margin-bottom:3px; font-size:11px;
      }
      .ml-queue-item .fa-image { color:#3b9eff; }
      .ml-queue-item span:nth-child(2) {
        flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
      }
      .ml-queue-size { color:#6e7681; }

      /* ── Upload prediction cards ── */
      .ml-upload-pred {
        margin-bottom:8px; padding:8px; background:#0d1117;
        border-radius:4px; border:1px solid #21262d;
      }
      .ml-pred-file {
        font-size:10px; color:#8b949e; margin-bottom:6px;
        display:flex; align-items:center; gap:5px;
      }

      /* ── Footer ── */
      .ml-footer {
        display:flex; align-items:center; gap:8px;
        padding:8px 14px; border-top:1px solid #1e2d3d; flex-shrink:0;
      }
      .ml-marker-count {
        font-size:11px; color:#6e7681; flex:1; text-align:center;
      }

      /* ── Map marker ── */
      .ml-map-marker {
        width:28px; height:28px; border-radius:50%;
        display:flex; align-items:center; justify-content:center;
        color:#fff; font-size:14px; border:2px solid rgba(255,255,255,.25);
      }

      /* ── Crosshair cursor for map picking ── */
      .ml-crosshair,
      .ml-crosshair .leaflet-interactive { cursor:crosshair !important; }

      /* ── Utility ── */
      .hidden { display:none !important; }

      /* ── Leaflet popup overrides for ML reports ── */
      .leaflet-popup-content .ml-report {
        font-size:11px;
      }
      .leaflet-popup-content .ml-report-level {
        font-size:13px;
      }
      .leaflet-popup-content .ml-report-action p,
      .leaflet-popup-content .ml-report-desc {
        font-size:10px;
      }
      .leaflet-popup-content .ml-confidence-label {
        width:58px;
      }

      /* ── Mobile ── */
      @media (max-width:480px) {
        .ml-panel { width:100vw; border-radius:0; }
        .ml-panel.open { right:0; }
        .ml-summary-grid { grid-template-columns:repeat(2,1fr); }
        .ml-report-action { flex-direction:column; }
      }
    `;
    document.head.appendChild(style);
  }

  /* ══════════════════════════════════════
     PUBLIC API
     ══════════════════════════════════════ */
  return {
    init,
    openPanel,
    closePanel,
    togglePanel,
    clearMLLayer,

    /**
     * Called from hotspot popup "Analyze with ML" button.
     * Coordinates arrive as strings from inline onclick attributes.
     */
    analyzeCoordinate: async (lat, lon, zoom = 17) => {
      const numLat = parseFloat(lat);
      const numLon = parseFloat(lon);
      const numZoom = parseInt(zoom) || 17;

      if (isNaN(numLat) || isNaN(numLon)) {
        showToast('Invalid coordinates from hotspot data', 'warning');
        return;
      }

      _switchTab('coordinate');
      openPanel();

      const latInput = document.getElementById('ml-coord-lat');
      const lonInput = document.getElementById('ml-coord-lon');
      const zoomInput = document.getElementById('ml-coord-zoom');
      if (latInput) latInput.value = numLat.toFixed(5);
      if (lonInput) lonInput.value = numLon.toFixed(5);
      if (zoomInput) zoomInput.value = numZoom;

      if (!_modelReady) await _checkModelStatus();

      if (!_modelReady) {
        showToast(
          'ML model is not loaded — please check server status',
          'error',
        );
        return;
      }

      return _analyzeWithCoords(numLat, numLon, numZoom);
    },

    /**
     * Programmatic access to plot results on the map layer.
     */
    plotResults: _plotResultsOnMap,

    /**
     * Expose level config for external consumers
     * (e.g. legend builders, export tools).
     */
    getLevelConfig: () => ({ ..._LEVEL_CONFIG }),

    /**
     * Expose the normalizer so other modules can
     * translate backend levels consistently.
     */
    normalizeLevel: _normalizeLevel,
  };
})();

window.MLView = MLView;