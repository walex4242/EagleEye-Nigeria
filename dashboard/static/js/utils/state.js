/* ══════════════════════════════════════════
   state.js — Central Application State
   ══════════════════════════════════════════ */

const State = (() => {
  const _state = {
    // Data
    allFeatures: [],
    summaryData: {},
    vegEvents: [],
    monitoringZones: [],
    movementData: null,
    movementAlerts: [],
    activeAlerts: [],

    // Map layer groups
    hotspotLayer: null,
    clusterLayer: null,
    vegLayerGroup: null,
    zonesLayerGroup: null,
    movementLayerGroup: null,

    // Layer toggles
    useClustering: true,
    vegLayerVisible: false,
    zonesVisible: false,
    movementLayerVisible: false,

    // Feature flags
    sentinel2Available: false,

    // UI state
    currentTab: 'states',
    sidebarOpen: false,

    // Listeners
    _listeners: {},
  };

  function on(event, cb) {
    if (!_state._listeners[event]) _state._listeners[event] = [];
    _state._listeners[event].push(cb);
  }

  function emit(event, data) {
    (_state._listeners[event] || []).forEach((cb) => cb(data));
  }

  function get(key) {
    return _state[key];
  }

  function set(key, value) {
    _state[key] = value;
    emit('change', { key, value });
    emit(`change:${key}`, value);
  }

  return { get, set, on, emit };
})();

window.State = State;
