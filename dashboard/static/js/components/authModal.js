/* ══════════════════════════════════════════
   authModal.js — Login Modal v3.0
   ══════════════════════════════════════════ */

const AuthModal = (() => {
  function show() {
    el('auth-modal')?.remove();

    const overlay = document.createElement('div');
    overlay.id = 'auth-modal';
    overlay.className = 'modal-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Sign in to EagleEye Nigeria');

    overlay.innerHTML = `
      <div class="modal-card">
        <div class="modal-accent"></div>
        <div class="modal-inner">

          <!-- Logo -->
          <div class="modal-logo">
            <span class="modal-eagle" role="img" aria-label="Eagle">🦅</span>
            <div class="modal-title">EagleEye Nigeria</div>
            <div class="modal-subtitle">Satellite Intelligence Platform</div>
          </div>

          <!-- Error -->
          <div class="modal-err" id="modal-err" role="alert"></div>

          <!-- Form -->
          <div class="form-group">
            <label class="form-label" for="login-email">Email or Username</label>
            <input class="form-input" type="text" id="login-email"
              placeholder="analyst@nigeria.mil" autocomplete="username" />
          </div>
          <div class="form-group">
            <label class="form-label" for="login-password">Password</label>
            <input class="form-input" type="password" id="login-password"
              placeholder="••••••••" autocomplete="current-password" />
          </div>

          <button class="btn-login" id="login-submit" onclick="AuthModal.handleLogin()">
            Sign In
          </button>

          <button class="modal-skip" onclick="AuthModal.skipToPublic()">
            Continue as Public — limited access
          </button>

          <!-- Access tiers -->
          <div class="modal-tiers">
            <div class="modal-tiers-title">Access Levels</div>
            <div class="tier-list">
              <div class="tier-row">
                <span class="tier-icon">👤</span>
                <span class="tier-name">Public</span>
                <span style="font-size:10.5px;color:var(--text-secondary)">Map view, hotspot locations</span>
              </div>
              <div class="tier-row">
                <span class="tier-icon">📊</span>
                <span class="tier-name">Analyst</span>
                <span style="font-size:10.5px;color:var(--text-secondary)">Threat intelligence, alerts</span>
              </div>
              <div class="tier-row">
                <span class="tier-icon">⭐</span>
                <span class="tier-name">Military</span>
                <span style="font-size:10.5px;color:var(--text-secondary)">Full classified access</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    // Enter key handler
    el('login-password')?.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') handleLogin();
    });

    // Close on overlay click (not on card)
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) skipToPublic();
    });

    // Focus email
    setTimeout(() => el('login-email')?.focus(), 120);
  }

  async function handleLogin() {
    const emailEl = el('login-email');
    const passEl = el('login-password');
    const errEl = el('modal-err');
    const submitEl = el('login-submit');
    if (!emailEl || !passEl) return;

    const email = emailEl.value.trim();
    const password = passEl.value;

    if (!email || !password) {
      showErr('Please enter your email and password.');
      return;
    }

    submitEl.disabled = true;
    submitEl.textContent = 'Authenticating…';

    const result = await Auth.login(email, password);

    if (result.ok) {
      el('auth-modal')?.remove();
      Navbar.updateUserWidget();
      Sidebar.updateAuthState();
      showToast(
        `Welcome back, ${result.user?.full_name || 'Analyst'} ✓`,
        'success',
      );
      MapView.loadAllData();
    } else {
      showErr(result.error || 'Invalid credentials. Please try again.');
      submitEl.disabled = false;
      submitEl.textContent = 'Sign In';
    }
  }

  function showErr(msg) {
    const errEl = el('modal-err');
    if (!errEl) return;
    errEl.innerHTML = `⚠ ${msg}`;
    errEl.classList.add('show');
  }

  function skipToPublic() {
    el('auth-modal')?.remove();
    Sidebar.updateAuthState();
    showToast('Viewing as Public — intelligence panels restricted.', 'warning');
  }

  return { show, handleLogin, skipToPublic };
})();

window.AuthModal = AuthModal;
