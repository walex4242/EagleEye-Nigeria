/* ══════════════════════════════════════════
   api.js — Data Fetching Layer v3.3
   Auto-injects Authorization header so the
   backend can distinguish authenticated vs
   anonymous users for data delay enforcement.

   v3.3: Added ML analysis endpoints
   ══════════════════════════════════════════ */

const API = (() => {
  /* ── Core fetch wrapper — injects auth token ── */
  function _headers() {
    const h = { 'Content-Type': 'application/json' };

    if (typeof Auth !== 'undefined' && Auth.isLoggedIn()) {
      const token = Auth.getToken();
      if (token && token !== 'undefined' && token !== 'null') {
        h['Authorization'] = `Bearer ${token}`;
      }
    }

    return h;
  }

  function _authHeaders() {
    const h = {};
    if (typeof Auth !== 'undefined' && Auth.isLoggedIn()) {
      const token = Auth.getToken();
      if (token && token !== 'undefined' && token !== 'null') {
        h['Authorization'] = `Bearer ${token}`;
      }
    }
    return h;
  }

  async function _get(url) {
    const res = await fetch(url, { headers: _headers() });
    return res;
  }

  async function _post(url, body = null) {
    const opts = { method: 'POST', headers: _headers() };
    if (body) opts.body = JSON.stringify(body);
    return fetch(url, opts);
  }

  async function _delete(url) {
    return fetch(url, { method: 'DELETE', headers: _headers() });
  }

  /* ══════════════════════════════════════
     Hotspot Endpoints
     ══════════════════════════════════════ */

  async function getHotspots(days = 1) {
    const r = await _get(`/api/v1/hotspots?days=${days}`);
    if (!r.ok) throw new Error(`Hotspots API: ${r.status}`);
    return r.json();
  }

  async function getSummary(days = 1) {
    const r = await _get(`/api/v1/hotspots/summary?days=${days}`);
    if (!r.ok) return {};
    return r.json();
  }

  async function getMovementData(days = 1) {
    const compareDays = Math.min(days + 2, 14);
    const r = await _get(
      `/api/v1/hotspots/movement?days=${days}&compare_days=${compareDays}`,
    );
    if (!r.ok) return null;
    return r.json();
  }

  /* ══════════════════════════════════════
     Sentinel-2 / Vegetation Endpoints
     ══════════════════════════════════════ */

  async function getVegetationEvents(limit = 200) {
    const r = await _get(`/api/v1/sentinel2/events?limit=${limit}`);
    if (!r.ok) return [];
    return r.json();
  }

  async function getMonitoringZones() {
    const r = await _get('/api/v1/sentinel2/zones');
    if (!r.ok) return [];
    return r.json();
  }

  async function getSentinel2Health() {
    const r = await _get('/api/v1/sentinel2/health');
    if (!r.ok) return { sentinel2_configured: false };
    return r.json();
  }

  async function runZoneAnalysis(zoneId) {
    const r = await _post('/api/v1/sentinel2/change-detection', {
      zone_name: zoneId,
      index: 'ndvi',
      correlate_hotspots: true,
      correlate_acled: false,
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    return r.json();
  }

  async function runAllZones() {
    const r = await _post('/api/v1/sentinel2/change-detection/all-zones');
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    return r.json();
  }

  /* ══════════════════════════════════════
     Alert Endpoints
     ══════════════════════════════════════ */

  async function getActiveAlerts() {
    const r = await _get('/api/alerts');
    if (!r.ok) return { alerts: [] };
    return r.json();
  }

  async function dismissAlert(alertId) {
    const r = await _delete(`/api/alerts/${alertId}`);
    return r.ok;
  }

  async function clearExpiredAlerts() {
    const r = await _post('/api/alerts/clear-expired');
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  /* ══════════════════════════════════════
     ML Analysis Endpoints
     ══════════════════════════════════════ */

  /**
   * Analyze a specific coordinate.
   * Downloads satellite imagery and runs ML classification.
   * @param {number} lat - Latitude
   * @param {number} lon - Longitude
   * @param {number} zoom - Tile zoom level (15-18)
   * @returns {Promise<Object>} Classification result with recommendation
   */
  async function analyzeLocation(lat, lon, zoom = 17) {
    const params = new URLSearchParams({
      lat: lat.toString(),
      lon: lon.toString(),
      zoom: zoom.toString(),
      use_tta: 'true',
    });
    const r = await _post(`/api/v1/ml/analyze-location?${params}`);
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    return r.json();
  }

  /**
   * Auto-scan recent FIRMS hotspots with ML model.
   * Downloads satellite tile for each hotspot and classifies it.
   * @param {number} days - Days of FIRMS data (1-10)
   * @param {number} limit - Max hotspots to scan (1-100)
   * @returns {Promise<Object>} Scan results with flagged locations
   */
  async function scanHotspots(days = 1, limit = 50) {
    const params = new URLSearchParams({
      days: days.toString(),
      limit: limit.toString(),
    });
    const r = await _post(`/api/v1/ml/scan-hotspots?${params}`);
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    return r.json();
  }

  /**
   * Scan a rectangular area for suspicious encampments.
   * Creates a grid of satellite tiles and classifies each one.
   * @param {number} latMin - South latitude bound
   * @param {number} latMax - North latitude bound
   * @param {number} lonMin - West longitude bound
   * @param {number} lonMax - East longitude bound
   * @param {number} gridStep - Distance between points in degrees
   * @returns {Promise<Object>} Flagged locations within the area
   */
  async function scanArea(latMin, latMax, lonMin, lonMax, gridStep = 0.01) {
    const params = new URLSearchParams({
      lat_min: latMin.toString(),
      lat_max: latMax.toString(),
      lon_min: lonMin.toString(),
      lon_max: lonMax.toString(),
      grid_step: gridStep.toString(),
      zoom: '17',
    });
    const r = await _post(`/api/v1/ml/scan-area?${params}`);
    if (!r.ok) {
      const e = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    return r.json();
  }

  /**
   * Get ML model status and capabilities.
   * @returns {Promise<Object>} Model status info
   */
  async function getMLStatus() {
    const r = await _get('/api/v1/ml/status');
    if (!r.ok) return { model_loaded: false, capabilities: {} };
    return r.json();
  }

  /**
   * Upload a satellite image for ML prediction.
   * Uses FormData (not JSON) for file upload.
   * @param {File} file - Image file (JPEG/PNG)
   * @returns {Promise<Object>} Classification result
   */
  async function predictImage(file) {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch('/api/v1/ml/predict', {
      method: 'POST',
      headers: _authHeaders(),
      body: formData,
    });

    if (!res.ok) {
      const e = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(e.detail || `ML predict: ${res.status}`);
    }
    return res.json();
  }

  /**
   * Upload multiple satellite images for batch ML prediction.
   * @param {FileList|File[]} files - Image files
   * @returns {Promise<Object>} Batch classification results
   */
  async function predictBatch(files) {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }

    const res = await fetch('/api/v1/ml/predict-batch', {
      method: 'POST',
      headers: _authHeaders(),
      body: formData,
    });

    if (!res.ok) {
      const e = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(e.detail || `ML batch: ${res.status}`);
    }
    return res.json();
  }

  /* ══════════════════════════════════════
     System Endpoints
     ══════════════════════════════════════ */

  async function checkHealth() {
    const r = await _get('/health');
    if (!r.ok) return {};
    return r.json();
  }

  /* ══════════════════════════════════════
     Security Metadata Helper
     ══════════════════════════════════════ */

  function checkDelayStatus(data) {
    if (!data || !data.security) return null;

    const sec = data.security;
    return {
      isDelayed: sec.data_delayed === true,
      delayMinutes: sec.delay_minutes || 0,
      accessLevel: sec.access_level || 'UNKNOWN',
      userRole: sec.user_role || 'anonymous',
      withheld: sec.features_withheld || 0,
      notice: sec.notice || null,
    };
  }

  /* ══════════════════════════════════════
     ML Result Helpers
     ══════════════════════════════════════ */

  /**
   * Get a color for a recommendation level.
   * For use in map markers and UI badges.
   */
  function getRecommendationColor(level) {
    const colors = {
      CRITICAL: '#dc2626',
      HIGH: '#ea580c',
      MEDIUM: '#d97706',
      LOW: '#16a34a',
    };
    return colors[level] || '#6b7280';
  }

  /**
   * Get an icon name for a recommendation level.
   */
  function getRecommendationIcon(level) {
    const icons = {
      CRITICAL: 'fa-exclamation-triangle',
      HIGH: 'fa-exclamation-circle',
      MEDIUM: 'fa-info-circle',
      LOW: 'fa-check-circle',
    };
    return icons[level] || 'fa-question-circle';
  }

  /**
   * Format an ML result for display in a popup or card.
   */
  function formatMLResult(result, recommendation) {
    if (!result) return 'No result available';

    const label =
      result.label === 'suspicious_encampment'
        ? '⚠️ Suspicious Encampment'
        : '✅ Legal Activity';

    const conf = (result.confidence * 100).toFixed(1);
    const level = recommendation ? recommendation.level : 'UNKNOWN';
    const action = recommendation ? recommendation.action : '';
    const message = recommendation ? recommendation.message : '';

    return `
      <div class="ml-result">
        <div class="ml-label">${label}</div>
        <div class="ml-confidence">Confidence: ${conf}%</div>
        <div class="ml-level ml-level-${level.toLowerCase()}">
          ${level} — ${action}
        </div>
        <div class="ml-message">${message}</div>
      </div>
    `;
  }

  /* ══════════════════════════════════════
     Public API
     ══════════════════════════════════════ */

  return {
    // Hotspots
    getHotspots,
    getSummary,
    getMovementData,

    // Sentinel-2
    getVegetationEvents,
    getMonitoringZones,
    getSentinel2Health,
    runZoneAnalysis,
    runAllZones,

    // Alerts
    getActiveAlerts,
    dismissAlert,
    clearExpiredAlerts,

    // ML Analysis
    analyzeLocation,
    scanHotspots,
    scanArea,
    getMLStatus,
    predictImage,
    predictBatch,

    // ML Helpers
    getRecommendationColor,
    getRecommendationIcon,
    formatMLResult,

    // System
    checkHealth,

    // Security
    checkDelayStatus,

    // Low-level (for custom calls)
    _get,
    _post,
    _delete,
  };
})();

window.API = API;
