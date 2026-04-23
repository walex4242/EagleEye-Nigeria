/* ══════════════════════════════════════════
   app.js — Main Bootstrap v3.2
   Changes from v3.1:
   • DOMContentLoaded is now async
   • MLView.init() called after MapView.init()
   • Keyboard shortcut X → toggle ML panel
   • Escape also closes ML panel
   ══════════════════════════════════════════ */

// ── PWA Service Worker ──
if ('serviceWorker' in navigator) {
  navigator.serviceWorker
    .register('/service-worker.js')
    .then((reg) => {
      console.log('[PWA] Service worker registered:', reg.scope);
      localStorage.setItem('eagleeye_last_online', new Date().toISOString());
    })
    .catch((err) => console.warn('[PWA] SW registration failed:', err));
}

// ── Init on DOM ready ──
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Render shell components
  Navbar.render();
  StatsBar.render();
  Sidebar.render();
  MapView.init();

  // 2. ML panel — must init BEFORE loadAllData so the panel
  //    DOM exists when hotspot popups try to call analyzeCoordinate()
  if (typeof MLView !== 'undefined') {
    try {
      await MLView.init();
      console.log('[EagleEye] MLView initialized ✓');
    } catch (err) {
      console.warn('[EagleEye] MLView init failed (non-fatal):', err);
    }
  }

  // 3. Auth UI state
  if (typeof Auth !== 'undefined') {
    Navbar.updateUserWidget();
    if (!Auth.isLoggedIn()) {
      setTimeout(() => AuthModal.show(), 1000);
    }
  }

  // 4. Initial data load
  MapView.loadAllData();

  // 5. Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Don't intercept when typing in inputs
    if (
      e.target.tagName === 'INPUT' ||
      e.target.tagName === 'SELECT' ||
      e.target.tagName === 'TEXTAREA'
    )
      return;

    switch (e.key.toLowerCase()) {
      case 'r':
        MapView.loadAllData();
        break;

      case 'c':
        MapView.toggleClustering();
        break;

      case 'v':
        MapView.toggleVegetationLayer();
        break;

      case 'm':
        MapView.toggleMovementLayer();
        break;

      case 'z':
        MapView.toggleMonitoringZones();
        break;

      case 'i':
        Sidebar.toggle();
        break;

      case 'h':
        MapView.resetView(State.get('allFeatures'));
        showToast('🏠 Map view reset', 'info');
        break;

      // ── ML panel toggle ──
      case 'x':
        if (typeof MLView !== 'undefined') {
          MLView.togglePanel();
        }
        break;

      case 'escape':
        // Close sidebar if open
        if (document.getElementById('side-panel')?.classList.contains('open')) {
          Sidebar.close();
        }
        // Close ML panel if open
        if (typeof MLView !== 'undefined') {
          MLView.closePanel();
        }
        // Close navbar drawer
        Navbar.closeDrawer();
        break;
    }
  });

  // 6. Auto-refresh every 5 minutes
  setInterval(
    () => {
      console.log('[EagleEye] Auto-refreshing data...');
      MapView.loadAllData();
    },
    5 * 60 * 1000,
  );

  // 7. Auth token refresh every 60s
  if (typeof Auth !== 'undefined') {
    setInterval(() => Auth.refreshIfNeeded?.(), 60 * 1000);
  }

  console.log('[EagleEye] App initialized ✓');
});
