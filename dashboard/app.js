/**
 * GreenOps Dashboard v2.0
 * Production-ready, clean JS — no inline chaos
 * Auto-refresh every 10s | Toast notifications | Sleep/Shutdown commands
 */

class GreenOpsApp {
  constructor() {
    // Use relative URL so it works behind nginx, python http.server, or any origin
    this.apiUrl = '';
    this.token = localStorage.getItem('greenops_token');
    this.currentUser = localStorage.getItem('greenops_user');
    this.machines = [];
    this.filterStatus = '';
    this.searchQuery = '';
    this.refreshInterval = null;
    this.isLoading = false;
    this.REFRESH_MS = 10_000;

    this._init();
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  _init() {
    // Initialise lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();

    this._bindLogin();
    this._bindChangePw();
    this._bindDashboard();

    if (this.token) {
      this._verifyToken();
    } else {
      this._showScreen('login');
    }
  }

  // ── Screen management ──────────────────────────────────────────────────────

  _showScreen(name) {
    document.querySelectorAll('.screen').forEach(el => el.classList.remove('active'));
    const ids = { login: 'login-screen', changepw: 'change-pw-screen', dashboard: 'dashboard-screen' };
    const el = document.getElementById(ids[name]);
    if (el) el.classList.add('active');
    if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 0);
  }

  // ── Login ──────────────────────────────────────────────────────────────────

  _bindLogin() {
    document.getElementById('login-form')?.addEventListener('submit', e => {
      e.preventDefault();
      this._handleLogin();
    });
  }

  async _handleLogin() {
    const username = document.getElementById('username')?.value.trim() || '';
    const password = document.getElementById('password')?.value || '';
    const errorEl  = document.getElementById('login-error');
    const errorTxt = document.getElementById('login-error-text');
    const btn      = document.getElementById('login-btn');

    if (!username || !password) return;

    this._setLoginLoading(btn, true);
    this._hideError(errorEl);

    try {
      const res = await fetch(`${this.apiUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json().catch(() => ({}));

      if (res.ok) {
        this.token = data.token;
        this.currentUser = data.username || username;
        localStorage.setItem('greenops_token', data.token);
        localStorage.setItem('greenops_user', this.currentUser);

        if (data.must_change_password) {
          this._showScreen('changepw');
          const curPwEl = document.getElementById('cur-pw');
          if (curPwEl) curPwEl.value = password;
        } else {
          this._initDashboard();
        }
      } else {
        this._showError(errorEl, errorTxt, data.error || 'Invalid credentials');
      }
    } catch {
      this._showError(errorEl, errorTxt, 'Cannot connect to server. Please try again.');
    } finally {
      this._setLoginLoading(btn, false);
    }
  }

  _setLoginLoading(btn, loading) {
    if (!btn) return;
    const text    = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.btn-spinner');
    const icon    = btn.querySelector('.btn-icon');
    btn.disabled  = loading;
    if (text)    text.style.opacity    = loading ? '0.5' : '1';
    if (spinner) spinner.classList.toggle('hidden', !loading);
    if (icon)    icon.style.opacity    = loading ? '0' : '1';
  }

  _showError(el, textEl, msg) {
    if (!el) return;
    if (textEl) textEl.textContent = msg;
    el.classList.remove('hidden');
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  _hideError(el) {
    el?.classList.add('hidden');
  }

  // ── Change Password ────────────────────────────────────────────────────────

  _bindChangePw() {
    document.getElementById('change-pw-form')?.addEventListener('submit', e => {
      e.preventDefault();
      this._handleChangePw();
    });
  }

  async _handleChangePw() {
    const curPw     = document.getElementById('cur-pw')?.value     || '';
    const newPw     = document.getElementById('new-pw')?.value     || '';
    const confirmPw = document.getElementById('confirm-pw')?.value || '';
    const errorEl   = document.getElementById('change-pw-error');
    const errorTxt  = document.getElementById('change-pw-error-text');

    this._hideError(errorEl);

    if (newPw !== confirmPw) return this._showError(errorEl, errorTxt, 'Passwords do not match.');
    if (newPw.length < 8)    return this._showError(errorEl, errorTxt, 'Password must be at least 8 characters.');

    try {
      const res = await fetch(`${this.apiUrl}/api/auth/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.token}`,
        },
        body: JSON.stringify({ current_password: curPw, new_password: newPw }),
      });

      if (res.ok) {
        this._toast('Password updated successfully.', 'ok');
        this._initDashboard();
      } else {
        const data = await res.json().catch(() => ({}));
        this._showError(errorEl, errorTxt, data.error || 'Failed to change password.');
      }
    } catch {
      this._showError(errorEl, errorTxt, 'Cannot connect to server.');
    }
  }

  // ── Token verification ─────────────────────────────────────────────────────

  async _verifyToken() {
    try {
      const res = await fetch(`${this.apiUrl}/api/auth/verify`, {
        headers: { 'Authorization': `Bearer ${this.token}` },
      });
      if (res.ok) {
        this._initDashboard();
      } else {
        this._logout();
      }
    } catch {
      // Network error — still show login rather than leaving blank
      this._showScreen('login');
    }
  }

  // ── Dashboard init ─────────────────────────────────────────────────────────

  _initDashboard() {
    this._showScreen('dashboard');

    const userEl = document.getElementById('sidebar-user');
    if (userEl) userEl.textContent = this.currentUser || 'admin';

    const initEl = document.getElementById('sidebar-user-initial');
    if (initEl) initEl.textContent = (this.currentUser || 'A')[0].toUpperCase();

    if (typeof lucide !== 'undefined') setTimeout(() => lucide.createIcons(), 0);

    this._showSkeletons();
    this._loadDashboard();
    this._startRefresh();
  }

  // ── Dashboard bindings ─────────────────────────────────────────────────────

  _bindDashboard() {
    document.getElementById('logout-btn')?.addEventListener('click', () => this._logout());

    document.getElementById('refresh-btn')?.addEventListener('click', () => {
      const btn = document.getElementById('refresh-btn');
      btn?.classList.add('spinning');
      this._loadDashboard().finally(() => {
        setTimeout(() => btn?.classList.remove('spinning'), 600);
      });
    });

    document.getElementById('search-input')?.addEventListener('input', e => {
      this.searchQuery = e.target.value.toLowerCase().trim();
      this._renderMachines();
    });

    document.querySelectorAll('.pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        this.filterStatus = pill.dataset.status || '';
        this._renderMachines();
      });
    });
  }

  _logout() {
    this.token = null;
    this.currentUser = null;
    localStorage.removeItem('greenops_token');
    localStorage.removeItem('greenops_user');
    this._stopRefresh();
    this._showScreen('login');
    // Clear any sensitive field values
    const pwEl = document.getElementById('password');
    if (pwEl) pwEl.value = '';
  }

  // ── Data loading ───────────────────────────────────────────────────────────

  async _loadDashboard() {
    if (!this.token) return;
    await Promise.allSettled([this._loadStats(), this._loadMachines()]);
  }

  async _loadStats() {
    try {
      const res = await fetch(`${this.apiUrl}/api/dashboard/stats`, {
        headers: { 'Authorization': `Bearer ${this.token}` },
      });
      if (!res.ok) {
        if (res.status === 401) { this._logout(); return; }
        return;
      }
      const s = await res.json();

      this._setText('stat-total',  s.total_machines   ?? '—');
      this._setText('stat-online', s.online_machines  ?? '—');
      this._setText('stat-idle',   s.idle_machines    ?? '—');
      this._setText('stat-offline',s.offline_machines ?? '—');

      const kwh  = (s.total_energy_wasted_kwh || 0).toFixed(3);
      const cost = (s.estimated_cost_usd || 0).toFixed(2);
      this._setText('stat-energy', `${kwh} kWh`);
      this._setText('stat-cost',   `$${cost} estimated cost`);

      // Progress bars
      const total = s.total_machines || 1;
      this._setWidth('bar-online',  ((s.online_machines  || 0) / total) * 100);
      this._setWidth('bar-idle',    ((s.idle_machines    || 0) / total) * 100);
      this._setWidth('bar-offline', ((s.offline_machines || 0) / total) * 100);

    } catch { /* keep previous values on transient network error */ }
  }

  async _loadMachines() {
    try {
      const res = await fetch(`${this.apiUrl}/api/machines`, {
        headers: { 'Authorization': `Bearer ${this.token}` },
      });
      if (!res.ok) {
        if (res.status === 401) { this._logout(); return; }
        return;
      }
      const data = await res.json();
      this.machines = Array.isArray(data.machines) ? data.machines : [];
      this._renderMachines();
    } catch { /* keep previous render */ }
  }

  // ── Rendering ──────────────────────────────────────────────────────────────

  _showSkeletons() {
    const grid = document.getElementById('machine-grid');
    if (!grid) return;
    grid.innerHTML = Array.from({ length: 6 }).map(() =>
      '<div class="skeleton-card"></div>'
    ).join('');
  }

  _renderMachines() {
    const grid = document.getElementById('machine-grid');
    if (!grid) return;

    let list = [...this.machines];

    if (this.filterStatus) {
      list = list.filter(m => m.status === this.filterStatus);
    }

    if (this.searchQuery) {
      list = list.filter(m =>
        (m.hostname    || '').toLowerCase().includes(this.searchQuery) ||
        (m.mac_address || '').toLowerCase().includes(this.searchQuery) ||
        (m.os_type     || '').toLowerCase().includes(this.searchQuery)
      );
    }

    if (list.length === 0) {
      grid.innerHTML = `
        <div class="empty-state">
          <div class="empty-state-icon">
            <i data-lucide="server-off"></i>
          </div>
          <h3>No machines found</h3>
          <p>${this.filterStatus || this.searchQuery ? 'Try adjusting your search or filter.' : 'No machines have registered yet.'}</p>
        </div>`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
      return;
    }

    grid.innerHTML = list.map((m, i) => this._cardHtml(m, i)).join('');

    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Bind action buttons
    grid.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const { machineId, action } = btn.dataset;
        if (machineId && action) this._sendCommand(parseInt(machineId, 10), action, btn);
      });
    });
  }

  _cardHtml(m, i) {
    const badge    = this._badgeHtml(m.status);
    const lastSeen = this._relativeTime(m.last_seen);
    const uptime   = this._fmtUptime(m.uptime_seconds ?? m.uptime_hours);
    const idle     = this._fmtDuration(m.total_idle_seconds || 0);
    const energy   = (m.energy_wasted_kwh || 0).toFixed(3);
    const canAct   = m.status !== 'offline';
    const delay    = `animation-delay:${Math.min(i * 0.04, 0.4)}s`;
    const statusClass = `status-${m.status || 'offline'}`;

    return `
    <div class="machine-card ${statusClass}" style="${delay}">
      <div class="card-head">
        <div style="min-width:0;flex:1">
          <div class="card-title" title="${this._esc(m.hostname)}">${this._esc(m.hostname || 'Unknown')}</div>
          <div class="card-os">${this._esc(m.os_type || '—')}</div>
          <div class="card-mac">${this._esc(m.mac_address || '—')}</div>
        </div>
        ${badge}
      </div>

      <div class="card-metrics">
        <div class="metric">
          <span class="metric-val">${this._esc(uptime)}</span>
          <span class="metric-lbl">Uptime</span>
        </div>
        <div class="metric">
          <span class="metric-val">${this._esc(idle)}</span>
          <span class="metric-lbl">Idle</span>
        </div>
        <div class="metric">
          <span class="metric-val">${this._esc(energy)}</span>
          <span class="metric-lbl">kWh</span>
        </div>
      </div>

      <div class="card-last-seen">
        <i data-lucide="clock"></i>
        <span>Last seen ${this._esc(lastSeen)}</span>
      </div>

      <div class="card-actions">
        <button
          class="action-btn btn-sleep"
          data-action="sleep"
          data-machine-id="${m.id}"
          ${!canAct ? 'disabled' : ''}
          title="${canAct ? 'Send sleep command' : 'Machine is offline'}"
        >
          <i data-lucide="moon"></i>
          Sleep
        </button>
        <button
          class="action-btn btn-shutdown"
          data-action="shutdown"
          data-machine-id="${m.id}"
          ${!canAct ? 'disabled' : ''}
          title="${canAct ? 'Send shutdown command' : 'Machine is offline'}"
        >
          <i data-lucide="power"></i>
          Shutdown
        </button>
      </div>
    </div>`;
  }

  _badgeHtml(status) {
    const map = {
      online:  ['badge-online',  'online-dot',  'Online'],
      idle:    ['badge-idle',    'idle-dot',    'Idle'],
      offline: ['badge-offline', 'offline-dot', 'Offline'],
    };
    const [cls, dot, label] = map[status] || map['offline'];
    return `<span class="status-badge ${cls}">
      <span class="status-dot ${dot}"></span>${label}
    </span>`;
  }

  // ── Commands ───────────────────────────────────────────────────────────────

  async _sendCommand(machineId, action, btn) {
    const label = action === 'sleep' ? 'Sleep' : 'Shutdown';
    const confirmed = window.confirm(
      `Send ${label} command to this machine?\n\nThe machine agent will execute this on its next heartbeat poll.`
    );
    if (!confirmed) return;

    const prevHtml = btn.innerHTML;
    btn.classList.add('loading');
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin" width="13" height="13" viewBox="0 0 16 16" fill="none">
      <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="2" stroke-dasharray="30" stroke-dashoffset="10"/>
    </svg> Sending…`;

    try {
      const res = await fetch(`${this.apiUrl}/api/machines/${machineId}/${action}`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${this.token}` },
      });

      if (res.ok) {
        this._toast(`${label} command queued. Agent will execute on next poll.`, 'ok');
        setTimeout(() => this._loadDashboard(), 3000);
      } else {
        const data = await res.json().catch(() => ({}));
        this._toast(data.error || `Failed to send ${label} command.`, 'err');
      }
    } catch {
      this._toast('Cannot connect to server.', 'err');
    } finally {
      btn.classList.remove('loading');
      btn.innerHTML = prevHtml;
      btn.disabled = false;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }

  // ── Auto-refresh ───────────────────────────────────────────────────────────

  _startRefresh() {
    this._stopRefresh();
    this.refreshInterval = setInterval(() => this._loadDashboard(), this.REFRESH_MS);
  }

  _stopRefresh() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
      this.refreshInterval = null;
    }
  }

  // ── Toast ──────────────────────────────────────────────────────────────────

  _toast(msg, type = 'ok') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = msg;
    container.appendChild(el);

    const remove = () => {
      el.classList.add('toast-leaving');
      setTimeout(() => el.remove(), 220);
    };
    const timer = setTimeout(remove, 3500);
    el.addEventListener('click', () => { clearTimeout(timer); remove(); });
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  _setText(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  _setWidth(id, pct) {
    const el = document.getElementById(id);
    if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  _esc(text) {
    if (text == null) return '';
    const d = document.createElement('div');
    d.textContent = String(text);
    return d.innerHTML;
  }

  _relativeTime(ts) {
    if (!ts) return 'never';
    const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000);
    if (isNaN(diff) || diff < 0) return 'just now';
    if (diff < 10)    return 'just now';
    if (diff < 60)    return `${diff}s ago`;
    if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  _fmtUptime(val) {
    if (val == null || val === '') return '—';
    let secs = Number(val);
    if (isNaN(secs)) return '—';
    // If passed as hours (small float with decimal), convert
    if (secs < 1000 && String(val).includes('.') && secs !== 0) {
      secs = secs * 3600;
    }
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m`;
    return `${Math.floor(secs)}s`;
  }

  _fmtDuration(seconds) {
    const secs = Number(seconds) || 0;
    if (secs === 0) return '0m';
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }
}

// Boot on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new GreenOpsApp();
});
