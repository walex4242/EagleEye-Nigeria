/* ══════════════════════════════════════════
   auth.js — Authentication Management
   ══════════════════════════════════════════ */

const Auth = (() => {
  const KEYS = {
    token: 'ee_access_token',
    refresh: 'ee_refresh_token',
    user: 'ee_user',
  };

  function getToken() {
    return localStorage.getItem(KEYS.token);
  }
  function getRefreshToken() {
    return localStorage.getItem(KEYS.refresh);
  }
  function getUser() {
    const u = localStorage.getItem(KEYS.user);
    return u ? JSON.parse(u) : null;
  }

  function setSession(data) {
    localStorage.setItem(KEYS.token, data.access_token);
    localStorage.setItem(KEYS.refresh, data.refresh_token);
    localStorage.setItem(KEYS.user, JSON.stringify(data.user));
  }

  function clearSession() {
    Object.values(KEYS).forEach((k) => localStorage.removeItem(k));
  }

  function isLoggedIn() {
    return !!getToken();
  }

  function isMilitary() {
    const u = getUser();
    return u && ['superadmin', 'admin', 'military'].includes(u.role);
  }

  function isAnalyst() {
    const u = getUser();
    return u && ['superadmin', 'admin', 'military', 'analyst'].includes(u.role);
  }

  function authHeaders() {
    const t = getToken();
    return t ? { Authorization: `Bearer ${t}` } : {};
  }

  async function refreshIfNeeded() {
    const token = getToken();
    if (!token) return false;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      const msLeft = payload.exp * 1000 - Date.now();
      if (msLeft < 5 * 60 * 1000) {
        const resp = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: getRefreshToken() }),
        });
        if (resp.ok) {
          setSession(await resp.json());
          return true;
        }
        clearSession();
        return false;
      }
      return true;
    } catch {
      return false;
    }
  }

  async function login(emailOrUser, password) {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: emailOrUser, password }),
    });
    if (resp.ok) {
      const data = await resp.json();
      setSession(data);
      return { ok: true, user: data.user };
    }
    const err = await resp.json().catch(() => ({ detail: 'Login failed' }));
    return { ok: false, error: err.detail || 'Login failed' };
  }

  function logout() {
    clearSession();
    AuthModal.show();
    Navbar.updateUserWidget();
  }

  // Periodic token refresh
  setInterval(refreshIfNeeded, 60_000);

  return {
    getToken,
    getUser,
    isLoggedIn,
    isMilitary,
    isAnalyst,
    authHeaders,
    refreshIfNeeded,
    login,
    logout,
    setSession,
    clearSession,
  };
})();

// ── Authenticated fetch wrapper ──
async function authFetch(url, options = {}) {
  await Auth.refreshIfNeeded();
  const resp = await fetch(url, {
    ...options,
    headers: { ...options.headers, ...Auth.authHeaders() },
  });
  if (resp.status === 401) {
    Auth.clearSession();
    AuthModal.show();
    throw new Error('Authentication required');
  }
  return resp;
}

window.Auth = Auth;
window.authFetch = authFetch;
