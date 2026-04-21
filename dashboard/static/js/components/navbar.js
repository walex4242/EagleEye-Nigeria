/* ══════════════════════════════════════════
   navbar.js — Navbar Component v3.2
   Now with:
   • Delay indicator on status pill
   • Delay-aware drawer actions
   • Movement blocked for anonymous users
   ══════════════════════════════════════════ */
const Navbar = (() => {
  function render() {
    el('navbar').innerHTML = `
      <!-- Logo -->
      <a class="nav-logo" href="/" aria-label="EagleEye Nigeria Home">
        <span class="nav-logo-eagle" aria-hidden="true">🦅</span>
        <div class="nav-logo-text">
          <span class="nav-logo-name">EagleEye</span>
          <span class="nav-logo-sub">Nigeria · Sat Intel</span>
        </div>
      </a>

      <div class="nav-sep hide-mobile" aria-hidden="true"></div>

      <!-- Component status pills (desktop) -->
      <div class="nav-pills hide-mobile" role="status" aria-label="System components">
        <span class="comp-pill" id="comp-firms"    title="NASA FIRMS Thermal Data">FIRMS</span>
        <span class="comp-pill" id="comp-sentinel" title="Sentinel-2 Vegetation">S2</span>
        <span class="comp-pill" id="comp-acled"    title="ACLED Conflict Data">ACLED</span>
        <span class="comp-pill" id="comp-alerts"   title="Intelligence Alerts">Alerts</span>
      </div>

      <!-- Right side -->
      <div class="nav-right">
        <div class="status-pill live" id="status-pill" role="status"
             title="Real-time data access">
          <span class="status-dot live"></span>
          <span id="status-text">LIVE</span>
        </div>
        <div class="nav-user" id="nav-user-btn" onclick="Navbar.toggleUserMenu()"
             role="button" tabindex="0" aria-label="User account">
          <span id="nav-user-label" class="nav-user-name">🔒 Sign In</span>
        </div>
      </div>

      <!-- Mobile hamburger -->
      <button class="nav-hamburger show-mobile" id="hamburger-btn"
        onclick="Navbar.toggleDrawer()" aria-label="Open menu" aria-expanded="false">
        <span></span><span></span><span></span>
      </button>
    `;

    // ── Drawer: append to BODY (not inside #navbar) ──
    if (!el('nav-drawer')) {
      const drawer = document.createElement('div');
      drawer.className = 'nav-drawer';
      drawer.id = 'nav-drawer';
      drawer.setAttribute('aria-hidden', 'true');
      drawer.innerHTML = `
        <!-- Delay notice (hidden by default, shown for anonymous) -->
        <div class="drawer-delay-notice" id="drawer-delay-notice" style="display:none">
          <span>🔒</span>
          <span id="drawer-delay-text">Data delayed 60 min · Sign in for real-time</span>
        </div>

        <div class="drawer-section-title">System Status</div>
        <div class="drawer-pills">
          <span class="comp-pill" id="mob-firms">FIRMS · Thermal</span>
          <span class="comp-pill" id="mob-sentinel">S2 · Sentinel-2</span>
          <span class="comp-pill" id="mob-acled">ACLED · Conflict</span>
          <span class="comp-pill" id="mob-alerts">Alerts</span>
        </div>
        <div class="div-h"></div>
        <div id="drawer-user-section"></div>
        <div class="div-h"></div>
        <button class="btn btn-full" onclick="Sidebar.toggle(); Navbar.closeDrawer()">
          📊 Intelligence Panel
        </button>
        <button class="btn btn-full" style="margin-top:4px"
          onclick="Navbar._drawerAction('refresh')">
          ↻ Refresh Data
        </button>
        <button class="btn btn-full" style="margin-top:4px" id="drawer-veg-btn"
          onclick="Navbar._drawerAction('vegetation')">
          🌿 Toggle Vegetation
        </button>
        <button class="btn btn-full" style="margin-top:4px" id="drawer-move-btn"
          onclick="Navbar._drawerAction('movement')">
          🧭 Toggle Movement
        </button>
        <button class="btn btn-full" style="margin-top:4px"
          onclick="Navbar._drawerAction('clusters')">
          ⬡ Toggle Clusters
        </button>
        <button class="btn btn-full" style="margin-top:4px"
          onclick="Navbar._drawerAction('zones')">
          📐 Toggle Zones
        </button>
      `;
      document.body.appendChild(drawer);
    }

    // ── Backdrop: append to BODY ──
    if (!el('nav-drawer-backdrop')) {
      const bd = document.createElement('div');
      bd.id = 'nav-drawer-backdrop';
      bd.className = 'nav-drawer-backdrop';
      bd.onclick = closeDrawer;
      document.body.appendChild(bd);
    }

    _updateUserWidget();
  }

  /* ══════════════════════════════════════════
     DRAWER ACTIONS — Now delay-aware
     ══════════════════════════════════════════ */
  async function _drawerAction(action) {
    const btn = event?.target;

    // Close drawer first so map is visible
    closeDrawer();

    // Small delay to let drawer animation complete
    await new Promise((r) => setTimeout(r, 150));

    // ── Check delay status for restricted actions ──
    const delayStatus = State.get('dataDelayStatus');
    const isAnonymous = delayStatus?.isDelayed === true;

    try {
      switch (action) {
        case 'refresh':
          showToast('Refreshing data...', 'info');
          await MapView.loadAllData();
          break;

        case 'vegetation': {
          const vegVisible = !State.get('vegLayerVisible');
          State.set('vegLayerVisible', vegVisible);
          el('veg-toggle')?.classList.toggle('veg-on', vegVisible);

          if (vegVisible) {
            if (State.get('vegEvents').length === 0) {
              showToast('Loading vegetation data...', 'info');
              await MapView.loadVegetationEvents();
            } else {
              MapView.renderVegetationLayer();
            }
            showToast('🌿 Vegetation layer ON', 'success');
          } else {
            MapView.renderVegetationLayer();
            showToast('🌿 Vegetation layer OFF', 'info');
          }
          _updateDrawerButtonStates();
          break;
        }

        case 'movement': {
          // ── Block for anonymous users ──
          if (isAnonymous) {
            showToast(
              '🔒 Movement intelligence requires authorized access. Please sign in.',
              'warning',
            );
            // Offer to open auth modal
            setTimeout(() => {
              if (typeof AuthModal !== 'undefined') {
                AuthModal.show();
              }
            }, 1500);
            return;
          }

          const moveVisible = !State.get('movementLayerVisible');
          State.set('movementLayerVisible', moveVisible);
          el('movement-toggle')?.classList.toggle('move-on', moveVisible);

          if (moveVisible) {
            if (!State.get('movementData')) {
              showToast('Loading movement data...', 'info');
              await MapView.loadMovementData();
            }
            MapView.renderMovementLayer();
            showToast('🧭 Movement layer ON', 'success');
          } else {
            MapView.renderMovementLayer();
            showToast('🧭 Movement layer OFF', 'info');
          }
          _updateDrawerButtonStates();
          break;
        }

        case 'clusters':
          MapView.toggleClustering();
          showToast(
            State.get('useClustering') ? '⬡ Clustering ON' : '⬡ Clustering OFF',
            'info',
          );
          break;

        case 'zones': {
          const zonesVisible = !State.get('zonesVisible');
          State.set('zonesVisible', zonesVisible);
          el('zones-toggle')?.classList.toggle('active', zonesVisible);

          if (zonesVisible) {
            if (State.get('monitoringZones').length === 0) {
              showToast('Loading monitoring zones...', 'info');
              await MapView.loadMonitoringZones();
            } else {
              MapView.renderMonitoringZones();
            }
            showToast('📐 Zones ON', 'success');
          } else {
            MapView.renderMonitoringZones();
            showToast('📐 Zones OFF', 'info');
          }
          break;
        }
      }
    } catch (err) {
      console.warn(`[Drawer] ${action} failed:`, err);
      showToast(`Failed to toggle ${action}`, 'error');
    }
  }

  /* ══════════════════════════════════════════
     DRAWER BUTTON STATES — Delay-aware
     ══════════════════════════════════════════ */
  function _updateDrawerButtonStates() {
    const vegBtn = el('drawer-veg-btn');
    const moveBtn = el('drawer-move-btn');
    const delayStatus = State.get('dataDelayStatus');
    const isAnonymous = delayStatus?.isDelayed === true;

    if (vegBtn) {
      vegBtn.style.borderColor = State.get('vegLayerVisible')
        ? 'rgba(0,212,106,0.5)'
        : '';
    }

    if (moveBtn) {
      if (isAnonymous) {
        // Show locked state
        moveBtn.textContent = '🔒 Movement (Sign In Required)';
        moveBtn.style.opacity = '0.5';
        moveBtn.style.borderColor = 'rgba(240,165,0,0.3)';
      } else {
        moveBtn.textContent = '🧭 Toggle Movement';
        moveBtn.style.opacity = '1';
        moveBtn.style.borderColor = State.get('movementLayerVisible')
          ? 'rgba(0,212,106,0.5)'
          : '';
      }
    }

    // Update delay notice in drawer
    _updateDrawerDelayNotice();
  }

  function _updateDrawerDelayNotice() {
    const notice = el('drawer-delay-notice');
    const noticeText = el('drawer-delay-text');
    if (!notice) return;

    const delayStatus = State.get('dataDelayStatus');

    if (delayStatus?.isDelayed) {
      notice.style.display = 'flex';
      if (noticeText) {
        noticeText.textContent = `Data delayed ${delayStatus.delayMinutes} min · Sign in for real-time`;
      }
    } else {
      notice.style.display = 'none';
    }
  }

  /* ══════════════════════════════════════════
     STATUS PILL — Live / Loading / Error / Delay
     ══════════════════════════════════════════ */
  function setStatus(s) {
    const pill = el('status-pill');
    const dot = pill?.querySelector('.status-dot');
    const text = el('status-text');
    if (!pill) return;

    // Don't override delay indicator with 'live' — delay takes priority
    if (s === 'live') {
      const delayStatus = State.get('dataDelayStatus');
      if (delayStatus?.isDelayed) {
        // Keep delay indicator, don't switch to 'live'
        return;
      }
    }

    pill.className = `status-pill ${s}`;
    if (dot) dot.className = `status-dot ${s}`;

    const labels = {
      live: 'LIVE',
      loading: 'LOADING',
      error: 'ERROR',
      mock: 'MOCK DATA',
    };
    if (text) text.textContent = labels[s] || s.toUpperCase();

    const titles = {
      live: 'Real-time data access',
      loading: 'Loading data...',
      error: 'Data load failed',
      mock: 'Using mock/cached data',
    };
    pill.title = titles[s] || '';
  }

  /* ══════════════════════════════════════════
     DELAY INDICATOR — Amber pill for anonymous
     ══════════════════════════════════════════ */
  function setDelayIndicator(isDelayed, delayMinutes = 60) {
    const pill = el('status-pill');
    const text = el('status-text');
    const dot = pill?.querySelector('.status-dot');
    if (!pill || !text) return;

    if (isDelayed) {
      pill.className = 'status-pill delayed';
      if (dot) dot.className = 'status-dot delayed';
      text.textContent = `⏱ ${delayMinutes}m DELAY`;
      pill.title =
        `Data delayed by ${delayMinutes} minutes for security. ` +
        `Sign in with authorized credentials for real-time access.`;

      // Also update drawer states
      _updateDrawerButtonStates();

      console.log(`[Navbar] Delay indicator ON — ${delayMinutes}min`);
    } else {
      // Only reset if currently showing delay
      if (pill.className.includes('delayed')) {
        pill.className = 'status-pill live';
        if (dot) dot.className = 'status-dot live';
        text.textContent = 'LIVE';
        pill.title = 'Real-time data access';

        // Update drawer states
        _updateDrawerButtonStates();

        console.log('[Navbar] Delay indicator OFF — LIVE');
      }
    }
  }

  /* ══════════════════════════════════════════
     COMPONENT PILLS
     ══════════════════════════════════════════ */
  function updateCompPill(id, active, tooltip) {
    [`comp-${id}`, `mob-${id}`].forEach((pid) => {
      const p = el(pid);
      if (!p) return;
      p.classList.toggle('active', active === true);
      p.classList.toggle('inactive', active === false);
      if (tooltip) p.title = tooltip;
    });
  }

  /* ══════════════════════════════════════════
     USER WIDGET — Delay-aware messaging
     ══════════════════════════════════════════ */
  function _updateUserWidget() {
    const user = typeof Auth !== 'undefined' ? Auth.getUser() : null;
    const label = el('nav-user-label');
    const drawer = el('drawer-user-section');

    if (!label) return;

    if (user) {
      const icons = {
        superadmin: '👑',
        admin: '🛡️',
        military: '⭐',
        analyst: '📊',
        public: '👤',
      };
      const icon = icons[user.role] || '👤';

      // Show real-time badge for authorized roles
      const isRealtime = [
        'superadmin',
        'admin',
        'military',
        'analyst',
      ].includes(user.role);
      const accessBadge = isRealtime
        ? '<span class="access-badge realtime">REALTIME</span>'
        : '<span class="access-badge delayed">DELAYED</span>';

      label.innerHTML =
        `${icon}&nbsp;<span class="nav-user-name">${user.full_name}</span>` +
        `&nbsp;<span class="role-badge ${user.role}">${user.role}</span>`;

      if (drawer) {
        drawer.innerHTML = `
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
            <div>
              <div style="font-size:12px;font-weight:600;color:var(--text-bright)">${icon} ${user.full_name}</div>
              <div style="font-size:9.5px;color:var(--text-muted);font-family:var(--font-mono)">
                ${user.role.toUpperCase()} · ${isRealtime ? '🟢 REALTIME' : '🟡 DELAYED'}
              </div>
            </div>
            <button class="btn btn-danger btn-sm" onclick="Auth.logout()">Sign Out</button>
          </div>`;
      }
    } else {
      label.innerHTML = '🔒 Sign In';
      if (drawer) {
        drawer.innerHTML = `
          <div class="drawer-anon-notice">
            <div style="font-size:11px;color:var(--elevated);margin-bottom:6px;font-family:var(--font-mono)">
              ⏱ Anonymous · 60min data delay
            </div>
            <button class="btn btn-full" style="background:rgba(59,158,255,0.08);border-color:rgba(59,158,255,0.3);color:var(--info)"
              onclick="AuthModal.show(); Navbar.closeDrawer()">
              🔐 Sign In for Real-Time Access
            </button>
          </div>`;
      }
    }
  }

  function updateUserWidget() {
    _updateUserWidget();
    // Also refresh delay states when user changes
    _updateDrawerButtonStates();
  }

  /* ══════════════════════════════════════════
     USER MENU DROPDOWN
     ══════════════════════════════════════════ */
  function toggleUserMenu() {
    if (typeof Auth === 'undefined' || !Auth.isLoggedIn()) {
      if (typeof AuthModal !== 'undefined') AuthModal.show();
      return;
    }

    const existing = el('nav-dropdown');
    if (existing) {
      existing.remove();
      return;
    }

    const user = Auth.getUser();
    const isRealtime = ['superadmin', 'admin', 'military', 'analyst'].includes(
      user?.role,
    );

    const dropdown = document.createElement('div');
    dropdown.id = 'nav-dropdown';
    dropdown.className = 'nav-dropdown';
    dropdown.innerHTML = `
      <div class="nav-dropdown-header">
        Signed in as <strong>${user?.full_name || 'User'}</strong><br>
        <span class="role-badge ${user?.role}" style="display:inline-flex;margin-top:3px">
          ${user?.role || ''}
        </span>
        <span style="font-size:9px;color:${isRealtime ? 'var(--monitor)' : 'var(--elevated)'};margin-left:6px;font-family:var(--font-mono)">
          ${isRealtime ? '🟢 REALTIME' : '🟡 DELAYED'}
        </span>
      </div>
      <button class="btn btn-danger btn-full"
        onclick="Auth.logout(); document.getElementById('nav-dropdown')?.remove()">
        Sign Out
      </button>`;
    el('navbar').appendChild(dropdown);

    setTimeout(() => {
      function close(e) {
        if (!dropdown.contains(e.target) && e.target !== el('nav-user-btn')) {
          dropdown.remove();
          document.removeEventListener('click', close);
        }
      }
      document.addEventListener('click', close);
    }, 0);
  }

  /* ══════════════════════════════════════════
     DRAWER TOGGLE
     ══════════════════════════════════════════ */
  function toggleDrawer() {
    const drawer = el('nav-drawer');
    const btn = el('hamburger-btn');
    const backdrop = el('nav-drawer-backdrop');
    if (!drawer) return;

    const open = drawer.classList.toggle('open');
    drawer.setAttribute('aria-hidden', String(!open));
    btn?.classList.toggle('open', open);
    btn?.setAttribute('aria-expanded', String(open));
    if (backdrop) backdrop.classList.toggle('visible', open);

    // Update drawer delay states when opening
    if (open) {
      _updateDrawerButtonStates();
    }
  }

  function closeDrawer() {
    const drawer = el('nav-drawer');
    const btn = el('hamburger-btn');
    const backdrop = el('nav-drawer-backdrop');
    drawer?.classList.remove('open');
    drawer?.setAttribute('aria-hidden', 'true');
    btn?.classList.remove('open');
    btn?.setAttribute('aria-expanded', 'false');
    backdrop?.classList.remove('visible');
  }

  return {
    render,
    setStatus,
    setDelayIndicator,
    updateCompPill,
    updateUserWidget,
    toggleUserMenu,
    toggleDrawer,
    closeDrawer,
    _drawerAction,
  };
})();

window.Navbar = Navbar;
