/* ══════════════════════════════════════════
   api.js — Data Fetching Layer v3.2
   Auto-injects Authorization header so the
   backend can distinguish authenticated vs
   anonymous users for data delay enforcement.
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
     System Endpoints
     ══════════════════════════════════════ */

  async function checkHealth() {
    const r = await _get('/health');
    if (!r.ok) return {};
    return r.json();
  }

  /* ══════════════════════════════════════
     Security Metadata Helper
     ══════════════════════════════════════
     Call after any API response to check
     if data was delayed and show UI notice.
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
