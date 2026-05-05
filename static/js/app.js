/* ═══════════════════════════════════════════════════════════
   SchediQ — Full Frontend Application
   Features: Auth, Admin, Teacher, Voice NLP, PDF/Image Export
   ═══════════════════════════════════════════════════════════ */

// ── API HELPER ──────────────────────────────────────────────
async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
  if (body) opts.body = JSON.stringify(body);
  try {
    const res = await fetch('/api' + path, opts);
    return res.json();
  } catch (e) {
    return { ok: false, msg: 'Network error' };
  }
}

// ── STATE ────────────────────────────────────────────────────
const S = {
  user: null,
  teachers: [],
  departments: [],
  timetables: [],
  currentTT: null,
  selectedCell: null,
  genSubjects: [],
  genTeachers: [],
  selectedGenTT: null,
  genResults: [],
  isDark: localStorage.getItem('schediq_theme') !== 'light',
  recognition: null,
  globalRecognition: null,
  aiChatHistory: [],
};

const DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
const DAY_NAMES = { MON: 'Monday', TUE: 'Tuesday', WED: 'Wednesday', THU: 'Thursday', FRI: 'Friday', SAT: 'Saturday' };
const TIME_SLOTS = [
  { id: 't1', label: '9:40AM–10:40AM', short: '9:40–10:40' },
  { id: 't2', label: '10:40AM–11:40AM', short: '10:40–11:40' },
  { id: 't3', label: '11:40AM–12:40PM', short: '11:40–12:40' },
  { id: 't4', label: '12:40PM–1:20PM', short: '12:40–1:20', isLunch: true },
  { id: 't5', label: '1:20PM–2:20PM', short: '1:20–2:20' },
  { id: 't6', label: '2:20PM–3:20PM', short: '2:20–3:20' },
  { id: 't7', label: '3:20PM–4:20PM', short: '3:20–4:20' },
];

// ── THEME ────────────────────────────────────────────────────
function applyTheme() {
  document.body.classList.toggle('light', !S.isDark);
  const btn = document.getElementById('theme-btn');
  if (btn) btn.textContent = S.isDark ? '🌙' : '☀️';
}
function toggleTheme() {
  S.isDark = !S.isDark;
  localStorage.setItem('schediq_theme', S.isDark ? 'dark' : 'light');
  applyTheme();
}

// ── AUTH ─────────────────────────────────────────────────────
function switchAuthTab(tab) {
  ['login', 'register', 'forgot'].forEach(t => {
    document.getElementById('auth-' + t).style.display = t === tab ? 'block' : 'none';
    const btn = document.getElementById('atab-' + t);
    if (btn) btn.classList.toggle('active', t === tab);
  });
}

function showMsg(id, msg, type) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.className = 'auth-msg show ' + type;
}
function hideMsg(id) {
  const el = document.getElementById(id);
  if (el) el.className = 'auth-msg';
}

async function doLogin() {
  hideMsg('login-msg');
  const username = document.getElementById('l-user').value.trim();
  const password = document.getElementById('l-pass').value;
  const remember = document.getElementById('remember-login')?.checked;
  if (!username || !password) { showMsg('login-msg', 'Please enter credentials', 'error'); return; }
  const r = await api('POST', '/auth/login', { username, password });
  if (r.ok) {
    if (remember) saveLoginCredentials(username);
    else clearSavedLoginCredentials();
    loginSuccess(r.user);
  } else {
    showMsg('login-msg', r.msg || 'Invalid credentials', 'error');
  }
}

function saveLoginCredentials(username) {
  localStorage.setItem('savedUsername', username);
  localStorage.setItem('rememberLogin', 'true');
}

function clearSavedLoginCredentials() {
  localStorage.removeItem('savedUsername');
  localStorage.removeItem('rememberLogin');
}

function restoreSavedLoginCredentials() {
  const userField = document.getElementById('l-user');
  const passField = document.getElementById('l-pass');
  const rememberCheckbox = document.getElementById('remember-login');
  const remember = localStorage.getItem('rememberLogin') === 'true';
  if (rememberCheckbox) rememberCheckbox.checked = remember;
  if (userField) userField.value = '';
  if (passField) passField.value = '';
}

function clearLoginForm(forceRememberUnchecked = false) {
  const userField = document.getElementById('l-user');
  const passField = document.getElementById('l-pass');
  const rememberCheckbox = document.getElementById('remember-login');
  if (userField) {
    userField.value = '';
    userField.setAttribute('value', '');
  }
  if (passField) {
    passField.value = '';
    passField.setAttribute('value', '');
  }
  if (forceRememberUnchecked && rememberCheckbox) rememberCheckbox.checked = false;
}

function getPasswordValidationMessage(password, username = '', email = '', name = '') {
  const lowered = (password || '').toLowerCase();
  const forbiddenBits = [
    'password', 'admin', 'teacher', 'schediq', '123456', 'qwerty',
    username.trim().toLowerCase(),
    (email.split('@')[0] || '').trim().toLowerCase(),
    ...name.split(/\s+/).filter(part => part.length >= 3).map(part => part.toLowerCase()),
  ].filter(Boolean);
  if (password.length < 8) return 'Password must be at least 8 characters';
  if (!/[A-Z]/.test(password)) return 'Password must include at least one uppercase letter';
  if (!/[a-z]/.test(password)) return 'Password must include at least one lowercase letter';
  if (!/[0-9]/.test(password)) return 'Password must include at least one number';
  if (!/[^A-Za-z0-9]/.test(password)) return 'Password must include at least one special character';
  if (forbiddenBits.some(part => part.length >= 3 && lowered.includes(part))) {
    return 'Password is too easy to guess. Avoid names, usernames, and common words.';
  }
  return '';
}

async function doRegister() {
  hideMsg('register-msg');
  const name = document.getElementById('r-name').value.trim();
  const role = document.getElementById('r-role').value;
  const email = document.getElementById('r-email').value.trim();
  const username = document.getElementById('r-username').value.trim();
  const dept = document.getElementById('r-dept').value.trim();
  const password = document.getElementById('r-pass').value;
  const confirmPass = document.getElementById('r-pass-confirm').value;

  // Validation
  if (!name || !email || !username || !password) {
    showMsg('register-msg', 'All fields are required', 'error'); return;
  }
  const emailRe = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!emailRe.test(email)) {
    showMsg('register-msg', 'Please enter a valid email address', 'error'); return;
  }
  const passwordError = getPasswordValidationMessage(password, username, email, name);
  if (passwordError) {
    showMsg('register-msg', passwordError, 'error'); return;
  }
  if (password !== confirmPass) {
    showMsg('register-msg', 'Passwords do not match', 'error'); return;
  }

  const r = await api('POST', '/auth/register', { name, role, email, username, department: dept, password });
  if (r.ok) {
    showMsg('register-msg', 'Account created! Signing in...', 'success');
    // Direct login API call instead of filling hidden fields
    setTimeout(async () => {
      const lr = await api('POST', '/auth/login', { username, password });
      if (lr.ok) {
        loginSuccess(lr.user);
      } else {
        showMsg('register-msg', 'Account created! Please log in.', 'success');
        switchAuthTab('login');
        document.getElementById('l-user').value = username;
      }
    }, 700);
  } else showMsg('register-msg', r.msg || 'Registration failed', 'error');
}

async function logout() {
  await api('POST', '/auth/logout');
  S.user = null; S.currentTT = null;
  S.aiChatHistory = [];
  restoreSavedLoginCredentials();
  showPage('page-auth');
  ['nav-sep', 'app-nav-links', 'nav-username', 'btn-logout', 'nav-role', 'btn-profile', 'btn-ai-chat', 'notif-nav-badge']
    .forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
}

function loginSuccess(user) {
  S.user = user;
  document.getElementById('nav-sep').style.display = 'block';
  document.getElementById('nav-username').textContent = user.name || user.username;
  document.getElementById('nav-username').style.display = 'block';
  document.getElementById('btn-logout').style.display = 'block';
  document.getElementById('btn-profile').style.display = 'block';
  document.getElementById('btn-ai-chat').style.display = 'inline-flex';
  const roleBadge = document.getElementById('nav-role');
  roleBadge.textContent = user.role.toUpperCase();
  roleBadge.className = 'nav-role-badge role-' + user.role;
  roleBadge.style.display = 'block';
  if (user.role === 'admin') {
    document.getElementById('app-nav-links').style.display = 'flex';
    showPage('page-admin');
    loadAdminDashboard();
    showAppSection('dashboard');
  } else {
    document.getElementById('app-nav-links').style.display = 'none';
    showPage('page-teacher');
    loadTeacherView();
  }
  if (user.first_login) {
    setTimeout(() => {
      toast('Welcome! Please change your default password in Profile.', 'info');
      openPanel('panel-profile');
    }, 1200);
  }
}

function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}
function goHome() {
  if (S.user && (S.user.role === 'admin' || S.user.role === 'teacher')) {
    if (S.user.role === 'admin') showAppSection('dashboard');
    else showPage('page-teacher');
  } else {
    goHomePage();
  }
}
function goHomePage() {
  showPage('page-auth');
  switchAuthTab('login');
}
function showAbout() {
  alert('SchediQ: Smart institute timetable management with voice commands, auto-fill, clash detection, and leave management.');
}
function showHelp() {
  alert('Help:\n- Login as admin/teacher\n- Create timetable\n- Use Clash Detector to find conflicts\n- Use Auto Fill for empty slots.');
}
function showSignIn() {
  showPage('page-auth');
  switchAuthTab('login');
}
function showAppSection(sec) {
  document.getElementById('sec-dashboard').style.display = sec === 'dashboard' ? 'block' : 'none';
  document.getElementById('sec-timetable').style.display = sec === 'timetable' ? 'block' : 'none';
  document.getElementById('nl-dashboard').classList.toggle('active', sec === 'dashboard');
  document.getElementById('nl-timetable').classList.toggle('active', sec === 'timetable');
}

// Forgot / Reset password
async function doForgotPwd() {
  const email = document.getElementById('fp-email').value.trim();
  if (!email) { showMsg('fp-msg', 'Enter your email', 'error'); return; }
  const r = await api('POST', '/auth/forgot-password', { email });
  showMsg('fp-msg', r.msg || (r.ok ? 'Token sent' : 'Failed'), r.ok ? 'success' : 'error');
  if (r.ok) {
    document.getElementById('forgot-step2').style.display = 'block';
    if (r.demo_token) {
      document.getElementById('fp-token').value = r.demo_token;
      toast('Demo mode: token auto-filled', 'info');
    }
  }
}
async function doResetPwd() {
  const token = document.getElementById('fp-token').value.trim();
  const new_password = document.getElementById('fp-newpw').value.trim();
  if (!token || !new_password) { showMsg('fp-msg2', 'Fill all fields', 'error'); return; }
  const passwordError = getPasswordValidationMessage(new_password);
  if (passwordError) { showMsg('fp-msg2', passwordError, 'error'); return; }
  const r = await api('POST', '/auth/reset-password', { token, new_password });
  showMsg('fp-msg2', r.msg || (r.ok ? 'Password reset!' : 'Failed'), r.ok ? 'success' : 'error');
  if (r.ok) setTimeout(() => switchAuthTab('login'), 1500);
}

// ── ADMIN DASHBOARD ──────────────────────────────────────────
async function loadAdminDashboard() {
  document.getElementById('dash-welcome').textContent = `Welcome back, ${S.user.name || S.user.username}`;
  document.getElementById('dash-date').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  const [statsR, teachersR, deptsR, ttR] = await Promise.all([
    api('GET', '/stats'), api('GET', '/teachers'), api('GET', '/departments'), api('GET', '/timetables')
  ]);
  if (statsR.ok) {
    document.getElementById('stat-tt').textContent        = statsR.timetables;
    document.getElementById('stat-teachers').textContent  = statsR.teachers;
    document.getElementById('stat-depts').textContent     = statsR.departments;
    document.getElementById('stat-subjects').textContent  = statsR.subjects;
    const lEl = document.getElementById('stat-leaves');
    const cEl = document.getElementById('stat-clashes');
    if (lEl) lEl.textContent = statsR.pending_leaves  || 0;
    if (cEl) cEl.textContent = statsR.cross_clashes   || 0;
  }
  if (teachersR.ok) { S.teachers = teachersR.teachers; renderTeacherList(); updateTeacherDatalistCell(); }
  if (deptsR.ok)    { S.departments = deptsR.departments; renderDeptList(); }
  if (ttR.ok)       { S.timetables = ttR.timetables; renderTTListAdmin(); }
  loadNotificationsNav();
  loadAnnouncements();
  loadLeaves();
  loadActivityLog();
}

function renderTeacherList() {
  const el = document.getElementById('teacher-list');
  if (!S.teachers.length) { el.innerHTML = '<div class="empty-state"><div class="icon">👩‍🏫</div><p>No teachers yet.</p></div>'; return; }
  el.innerHTML = S.teachers.map(t => `
    <div class="teacher-item">
      <div class="teacher-avatar">${(t.name || 'T')[0].toUpperCase()}</div>
      <div style="flex:1;min-width:0">
        <div class="teacher-name">${t.name}</div>
        <div class="teacher-meta">${t.email} · ${t.dept || '—'} · ${t.phone || '—'}</div>
        <div class="teacher-meta" style="color:var(--text3)">${t.subjects || ''}</div>
      </div>
      <div class="teacher-actions">
        <button class="icon-btn" onclick="openEditTeacher(${t.id})" title="Edit">✏️</button>
        <button class="icon-btn red-h" onclick="deleteTeacher(${t.id})" title="Remove">🗑</button>
      </div>
    </div>`).join('');
}

function renderDeptList() {
  const el = document.getElementById('dept-list');
  if (!S.departments.length) { el.innerHTML = '<div class="empty-state" style="padding:12px 0"><div class="icon">🏛</div><p>No departments.</p></div>'; return; }
  el.innerHTML = S.departments.map(d => `
    <div class="dept-item">
      <div><div class="dept-name">${d.name}</div><div class="dept-meta">Code: ${d.code} · Sections: ${d.sections || '—'}</div></div>
      <div style="display:flex;align-items:center;gap:6px">
        <span class="dept-badge">${(d.sections || '').split(',').filter(s => s.trim()).length} sec</span>
        <button class="icon-btn red-h" onclick="deleteDepartment(${d.id})" title="Delete">🗑</button>
      </div>
    </div>`).join('');
}

function renderTTListAdmin() {
  const el = document.getElementById('tt-list-admin');
  if (!S.timetables.length) { el.innerHTML = '<div class="empty-state" style="padding:12px 0"><div class="icon">📅</div><p>No timetables.</p></div>'; return; }
  el.innerHTML = S.timetables.map(tt => `
    <div class="hist-item">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div class="hist-name">${tt.name}</div>
        <span style="font-size:10px;color:var(--text3);font-family:var(--font-mono)">${tt.department || ''}</span>
      </div>
      <div class="hist-meta"><span>Room: ${tt.room || '—'}</span><span>${tt.year_sem || ''}</span><span>${tt.academic_year || ''}</span></div>
      <div class="hist-actions">
        <button class="btn-action filled" style="font-size:11px;padding:5px 10px" onclick="openTimetable(${tt.id})">Open →</button>
        <button class="btn-action red" style="font-size:11px;padding:5px 10px" onclick="deleteTimetable(${tt.id})">Delete</button>
      </div>
    </div>`).join('');
}

// ── TEACHER CRUD ─────────────────────────────────────────────
async function addTeacher() {
  const btn = document.getElementById('at-btn');
  btn.disabled = true; btn.textContent = 'Adding...';
  const name = document.getElementById('at-name').value.trim();
  const email = document.getElementById('at-email').value.trim();
  const dept = document.getElementById('at-dept').value.trim();
  const phone = document.getElementById('at-phone').value.trim();
  const subjects = document.getElementById('at-subjects').value.trim();
  const password = document.getElementById('at-password').value.trim();
  if (phone && !/^\d{10}$/.test(phone)) {
    btn.disabled = false; btn.textContent = 'Add Teacher';
    showMsg('at-msg', 'Phone number must contain exactly 10 digits', 'error');
    return;
  }
  const r = await api('POST', '/teachers', { name, email, dept, phone, subjects, password });
  btn.disabled = false; btn.textContent = 'Add Teacher';
  if (r.ok) {
    closeModal('modal-add-teacher');
    ['at-name', 'at-email', 'at-dept', 'at-phone', 'at-subjects', 'at-password'].forEach(id => document.getElementById(id).value = '');
    await loadAdminDashboard();
    toast(`${r.msg} Credentials: ${r.credentials.username} / ${r.credentials.password}`, r.email_sent ? 'success' : 'info');
  } else showMsg('at-msg', r.msg || 'Failed to add teacher', 'error');
}

function openEditTeacher(id) {
  const t = S.teachers.find(x => x.id === id);
  if (!t) return;
  document.getElementById('et-id').value = t.id;
  document.getElementById('et-name').value = t.name;
  document.getElementById('et-phone').value = t.phone || '';
  document.getElementById('et-dept').value = t.dept || '';
  document.getElementById('et-subjects').value = t.subjects || '';
  openModal('modal-edit-teacher');
}

async function saveTeacherEdit() {
  const id = document.getElementById('et-id').value;
  const name = document.getElementById('et-name').value.trim();
  const phone = document.getElementById('et-phone').value.trim();
  const dept = document.getElementById('et-dept').value.trim();
  const subjects = document.getElementById('et-subjects').value.trim();
  const r = await api('PUT', `/teachers/${id}`, { name, phone, dept, subjects });
  if (r.ok) { closeModal('modal-edit-teacher'); await loadAdminDashboard(); toast('Teacher updated', 'success'); }
  else showMsg('et-msg', r.msg || 'Failed', 'error');
}

async function deleteTeacher(id) {
  if (!confirm('Remove this teacher? Their account will be deleted.')) return;
  const r = await api('DELETE', `/teachers/${id}`);
  if (r.ok) { await loadAdminDashboard(); toast('Teacher removed', 'info'); }
}

// ── DEPARTMENT CRUD ──────────────────────────────────────────
async function addDepartment() {
  const name = document.getElementById('ad-name').value.trim();
  const code = document.getElementById('ad-code').value.trim();
  const sections = document.getElementById('ad-sections').value.trim();
  if (!name || !code) { toast('Name and code required', 'error'); return; }
  const r = await api('POST', '/departments', { name, code, sections });
  if (r.ok) {
    closeModal('modal-add-dept');
    ['ad-name', 'ad-code', 'ad-sections'].forEach(id => document.getElementById(id).value = '');
    await loadAdminDashboard(); toast('Department added', 'success');
  } else toast(r.msg || 'Failed', 'error');
}

async function deleteDepartment(id) {
  if (!confirm('Delete this department?')) return;
  const r = await api('DELETE', `/departments/${id}`);
  if (r.ok) { await loadAdminDashboard(); toast('Department deleted', 'info'); }
}

// ── TIMETABLE CRUD ───────────────────────────────────────────
async function createTimetable() {
  const name = document.getElementById('ntt-name').value.trim();
  const department = document.getElementById('ntt-dept').value.trim();
  const room = document.getElementById('ntt-room').value.trim();
  const wef_date = document.getElementById('ntt-wef').value;
  const year_sem = document.getElementById('ntt-year').value.trim();
  const academic_year = document.getElementById('ntt-ay').value.trim();
  if (!name) { toast('Name required', 'error'); return; }
  const r = await api('POST', '/timetables', { name, department, room, wef_date, year_sem, academic_year });
  if (r.ok) {
    closeModal('modal-new-tt');
    ['ntt-name', 'ntt-dept', 'ntt-room', 'ntt-year', 'ntt-ay'].forEach(id => document.getElementById(id).value = '');
    await loadAdminDashboard(); toast('Timetable created', 'success');
    openTimetable(r.timetable.id);
  } else toast(r.msg || 'Failed', 'error');
}

async function openTimetable(id) {
  const r = await api('GET', `/timetables/${id}`);
  if (!r.ok) { toast('Failed to load timetable', 'error'); return; }
  S.currentTT = r.timetable;
  updateTTHeader();
  renderTimetableGrid('tt-table-container', true);
  showAppSection('timetable');
  updateTeacherDatalistCell();
  prefillTTSettings();
  updatePublishBtn();
}

function updateTTHeader() {
  const tt = S.currentTT; if (!tt) return;
  document.getElementById('tt-display-name').textContent = tt.name;
  document.getElementById('tt-dept-badge').textContent = tt.department || '—';
  document.getElementById('tt-room-display').textContent = tt.room || '—';
  document.getElementById('tt-year-display').textContent = tt.year_sem || '—';
  document.getElementById('tt-wef-display').textContent = tt.wef_date ? new Date(tt.wef_date).toLocaleDateString('en-GB') : '—';
  document.getElementById('ic-branch').textContent = tt.department || '—';
  document.getElementById('ic-room').textContent = tt.room || '—';
  document.getElementById('ic-year').textContent = tt.year_sem || '—';
  document.getElementById('ic-ay').textContent = tt.academic_year || '—';
  document.getElementById('tt-breadcrumb').textContent = `Admin → ${tt.department || 'Timetable'}`;
}

function prefillTTSettings() {
  const tt = S.currentTT; if (!tt) return;
  document.getElementById('ts-name').value = tt.name || '';
  document.getElementById('ts-dept').value = tt.department || '';
  document.getElementById('ts-room').value = tt.room || '';
  document.getElementById('ts-wef').value = tt.wef_date || '';
  document.getElementById('ts-year').value = tt.year_sem || '';
  document.getElementById('ts-ay').value = tt.academic_year || '';
}

async function saveTTSettings() {
  if (!S.currentTT) return;
  const body = {
    name: document.getElementById('ts-name').value.trim(),
    department: document.getElementById('ts-dept').value.trim(),
    room: document.getElementById('ts-room').value.trim(),
    wef_date: document.getElementById('ts-wef').value,
    year_sem: document.getElementById('ts-year').value.trim(),
    academic_year: document.getElementById('ts-ay').value.trim(),
  };
  const r = await api('PUT', `/timetables/${S.currentTT.id}`, body);
  if (r.ok) { S.currentTT = r.timetable; updateTTHeader(); closeModal('modal-tt-settings'); toast('Saved', 'success'); }
  else toast(r.msg || 'Failed', 'error');
}

async function deleteTimetable(id) {
  if (!confirm('Delete this timetable?')) return;
  const r = await api('DELETE', `/timetables/${id}`);
  if (r.ok) { await loadAdminDashboard(); toast('Deleted', 'info'); }
}

// ── TIMETABLE GRID ───────────────────────────────────────────
function renderTimetableGrid(containerId, editable = false) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const tt = S.currentTT;
  if (!tt) { container.innerHTML = ''; return; }
  const cells = tt.cells || {};

  const thead = `<tr>
    <th class="day-header">DAY / TIME</th>
    ${TIME_SLOTS.map(s => `<th class="${s.isLunch ? 'lunch-col' : ''}">${s.label}</th>`).join('')}
  </tr>`;

  let tbody = '';
  for (const day of DAYS) {
    const tds = TIME_SLOTS.map(slot => {
      if (slot.isLunch) return `<td><div class="tt-cell lunch">🍽<span>LUNCH</span></div></td>`;
      const key = `${day}|${slot.id}`;
      const cell = cells[key];
      const onclick = editable ? `onclick="openCellModal('${day}','${slot.id}')"` : '';
      if (cell?.subject) {
        const isLab = cell.type === 'lab';
        return `<td><div class="tt-cell has-subject${isLab ? ' lab' : ''}" ${onclick}>
          <span class="sub-name">${cell.subject}</span>
          <span class="sub-teacher">${cell.teacher || ''}</span>
        </div></td>`;
      }
      return `<td><div class="tt-cell" ${onclick}><span class="cell-add-hint">${editable ? '＋' : ''}</span></div></td>`;
    }).join('');
    tbody += `<tr>
      <td class="day-cell"><div class="day-label">${day}</div><div class="day-short">${DAY_NAMES[day]}</div></td>
      ${tds}
    </tr>`;
  }
  container.innerHTML = `<table class="tt-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>`;
}

// ── CELL EDITOR ──────────────────────────────────────────────
function openCellModal(day, slotId) {
  S.selectedCell = { day, slotId };
  const cell = (S.currentTT?.cells || {})[`${day}|${slotId}`] || {};
  const slot = TIME_SLOTS.find(s => s.id === slotId);
  document.getElementById('cell-modal-title').textContent = `${day} · ${slot.label}`;
  document.getElementById('cell-modal-sub').textContent = `${DAY_NAMES[day]} · ${slot.label}`;
  document.getElementById('cell-subject').value = cell.subject || '';
  document.getElementById('cell-teacher').value = cell.teacher || '';
  document.getElementById('cell-type').value = cell.type || 'lecture';
  hideMsg('cell-msg');
  openModal('modal-cell');
}

function openEditSelectedCell() {
  if (!S.selectedCell) {
    toast('Select a timetable cell first', 'error');
    return;
  }
  openCellModal(S.selectedCell.day, S.selectedCell.slotId);
}

async function deleteSelectedCell() {
  if (!S.selectedCell) {
    toast('Select a timetable cell first', 'error');
    return;
  }
  if (!confirm('Delete the selected timetable cell?')) return;
  await clearCell();
}

async function saveCellEdit() {
  if (!S.currentTT || !S.selectedCell) return;
  const subject = document.getElementById('cell-subject').value.trim();
  const teacher = document.getElementById('cell-teacher').value.trim();
  const type = document.getElementById('cell-type').value;
  if (!subject) { showMsg('cell-msg', 'Subject name required', 'error'); return; }
  const key = `${S.selectedCell.day}|${S.selectedCell.slotId}`;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells`, { key, subject, teacher, type });
  if (r.ok) {
    S.currentTT.cells = r.cells;
    closeModal('modal-cell');
    renderTimetableGrid('tt-table-container', true);
    toast('Saved', 'success');
  } else toast('Failed to save', 'error');
}

async function clearCell() {
  if (!S.currentTT || !S.selectedCell) return;
  const key = `${S.selectedCell.day}|${S.selectedCell.slotId}`;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells`, { key, subject: '', teacher: '', type: 'lecture' });
  if (r.ok) {
    S.currentTT.cells = r.cells;
    closeModal('modal-cell');
    renderTimetableGrid('tt-table-container', true);
    toast('Cleared', 'info');
  }
}

async function clearTimetable() {
  if (!S.currentTT || !confirm('Clear all entries in this timetable?')) return;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells/clear`);
  if (r.ok) { S.currentTT.cells = {}; renderTimetableGrid('tt-table-container', true); toast('Cleared', 'info'); }
}

function updateTeacherDatalistCell() {
  const dl = document.getElementById('teacher-datalist-cell');
  if (dl) dl.innerHTML = S.teachers.map(t => `<option value="${t.name}">`).join('');
}

// ── BULK ADD ─────────────────────────────────────────────────
function openBulkAdd() { openModal('modal-bulk'); }

async function doBulkAdd() {
  if (!S.currentTT) { toast('No timetable open', 'error'); return; }
  const lines = document.getElementById('bulk-text').value.split('\n').filter(l => l.trim());
  const entries = []; const errors = [];
  for (const line of lines) {
    const parts = line.split(',').map(p => p.trim());
    if (parts.length < 3) { errors.push(`Bad format: "${line}"`); continue; }
    const [dayRaw, idxRaw, subject, teacher = ''] = parts;
    const day = dayRaw.toUpperCase().substring(0, 3);
    const idx = parseInt(idxRaw) - 1;
    if (!DAYS.includes(day) || isNaN(idx) || idx < 0 || idx >= TIME_SLOTS.length) {
      errors.push(`Bad day/slot: "${line}"`); continue;
    }
    entries.push({ key: `${day}|${TIME_SLOTS[idx].id}`, subject, teacher, type: 'lecture' });
  }
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells/bulk`, { entries });
  if (r.ok) {
    S.currentTT.cells = r.cells;
    if (errors.length) showMsg('bulk-msg', `Added ${r.count}. Issues: ${errors.join('; ')}`, 'error');
    else { closeModal('modal-bulk'); toast(`Added ${r.count} entries`, 'success'); }
    renderTimetableGrid('tt-table-container', true);
  }
}

// ── AUTO FILL ────────────────────────────────────────────────
async function autoFill() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  // Count empty slots
  const cells = S.currentTT.cells || {};
  const emptyCount = DAYS.reduce((n, day) =>
    n + TIME_SLOTS.filter(s => !s.isLunch && !cells[`${day}|${s.id}`]?.subject).length, 0);
  if (emptyCount === 0) { toast('All slots are already filled', 'info'); return; }

  // Show strategy picker modal
  openModal('modal-autofill');
  document.getElementById('af-empty-count').textContent = emptyCount;
  // Populate assigned teachers preview
  const assigned = (S.currentTT.assigned || []).map(tid => S.teachers.find(t => t.id === tid)).filter(Boolean);
  const pairs = assigned.flatMap(t => (t.subjects || '').split(',').map(s => s.trim()).filter(Boolean).map(s => `${s} (${t.name})`));
  document.getElementById('af-pairs-preview').innerHTML = pairs.length
    ? pairs.map(p => `<span class="tag" style="margin:2px">${p}</span>`).join('')
    : '<span style="color:var(--text3);font-size:12px">No subjects found on assigned teachers. Edit teachers to add subjects.</span>';
}

async function doAutoFill() {
  if (!S.currentTT) return;
  const strategy = document.getElementById('af-strategy').value;
  const btn = document.getElementById('af-btn');
  btn.disabled = true; btn.textContent = 'Filling...';
  const r = await api('POST', `/timetables/${S.currentTT.id}/autofill`, { strategy });
  btn.disabled = false; btn.textContent = '⚡ Auto-Fill Now';
  if (r.ok) {
    S.currentTT.cells = r.cells;
    closeModal('modal-autofill');
    renderTimetableGrid('tt-table-container', true);
    toast(r.msg || `Auto-filled ${r.count} slot(s)`, 'success');
    // Refresh history panel if open
    if (document.getElementById('panel-history')?.classList.contains('open')) renderHistory();
  } else {
    toast(r.msg || 'Auto-fill failed', 'error');
  }
}

function suggestFreeSlot() {
  const cells = S.currentTT?.cells || {};
  for (const day of DAYS) {
    for (const slot of TIME_SLOTS) {
      if (slot.isLunch) continue;
      if (!cells[`${day}|${slot.id}`]?.subject) { toast(`Free slot: ${day} at ${slot.label}`, 'info'); return; }
    }
  }
  toast('No free slots found', 'info');
}

// ── SMART GENERATION ─────────────────────────────────────────
function addGenTag(type) {
  const inputId = type === 'subject' ? 'gen-subject-input' : 'gen-teacher-input';
  const arr = type === 'subject' ? S.genSubjects : S.genTeachers;
  const val = document.getElementById(inputId).value.trim();
  if (!val) return;
  if (arr.includes(val)) { toast('Already added', 'info'); return; }
  arr.push(val);
  document.getElementById(inputId).value = '';
  renderGenTags(type);
}
function removeGenTag(type, idx) {
  (type === 'subject' ? S.genSubjects : S.genTeachers).splice(idx, 1);
  renderGenTags(type);
}
function renderGenTags(type) {
  const arr = type === 'subject' ? S.genSubjects : S.genTeachers;
  const id = type === 'subject' ? 'gen-subjects-tags' : 'gen-teachers-tags';
  document.getElementById(id).innerHTML = arr.map((v, i) =>
    `<span class="tag">${v}<button class="tag-x" onclick="removeGenTag('${type}',${i})">×</button></span>`
  ).join('');
}

async function generateTimetables() {
  if (!S.genSubjects.length) { toast('Add at least one subject', 'error'); return; }
  document.getElementById('gen-results').innerHTML = `<div style="text-align:center;padding:20px;color:var(--text3)"><span class="spinner"></span>Generating...</div>`;
  const r = await api('POST', '/generate', {
    subjects: S.genSubjects,
    teachers: S.genTeachers,
    sections: parseInt(document.getElementById('gen-sections').value)
  });
  if (r.ok) {
    S.genResults = r.results;
    S.selectedGenTT = null;
    document.getElementById('gen-results').innerHTML = r.results.map((g, i) => `
      <div class="gen-tt-card" id="gcard-${i}" onclick="selectGenTT(${i})">
        <h4>⚡ ${g.name}</h4>
        <div class="gen-mini-grid">
          ${DAYS.slice(0, 5).map(d => TIME_SLOTS.slice(0, 3).map(s => {
      const c = g.cells[`${d}|${s.id}`];
      return `<div class="gen-mini-cell ${c ? 'filled' : ''}">${c ? c.subject.substring(0, 5) : ''}</div>`;
    }).join('')).join('')}
        </div>
      </div>`).join('');
    document.getElementById('gen-footer').style.display = 'flex';
    toast(`Generated ${r.results.length} clash-free option(s)`, 'success');
  } else toast(r.msg || 'Generation failed', 'error');
}

function selectGenTT(i) {
  S.selectedGenTT = i;
  document.querySelectorAll('.gen-tt-card').forEach((el, idx) => el.classList.toggle('selected', idx === i));
}

async function applyGenerated() {
  if (S.selectedGenTT === null || S.selectedGenTT === undefined) { toast('Select an option first', 'error'); return; }
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  const gen = S.genResults[S.selectedGenTT];
  const r = await api('PUT', `/timetables/${S.currentTT.id}`, { cells: gen.cells });
  if (r.ok) {
    S.currentTT = r.timetable;
    closeModal('modal-generate');
    renderTimetableGrid('tt-table-container', true);
    toast('Applied: ' + gen.name, 'success');
    S.selectedGenTT = null;
  }
}

// ── TEACHER ASSIGNMENT ───────────────────────────────────────
async function openAssignModal() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  // Always fetch fresh teacher list
  const tR = await api('GET', '/teachers');
  if (tR.ok) S.teachers = tR.teachers;

  const sel = document.getElementById('assign-teacher-select');
  if (!S.teachers.length) {
    sel.innerHTML = '<option value="">No teachers found — add teachers first</option>';
  } else {
    sel.innerHTML = '<option value="">— Choose teacher —</option>' +
      S.teachers.map(t => `<option value="${t.id}">${t.name} (${t.dept || 'No dept'})</option>`).join('');
  }
  await renderAssignedList();
  // Open the modal (just add class, don't call openModal to avoid loop)
  document.getElementById('modal-assign-teacher').classList.add('open');
}

async function assignTeacher() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  const id = parseInt(document.getElementById('assign-teacher-select').value);
  if (!id) { toast('Please select a teacher', 'error'); return; }
  const r = await api('POST', `/timetables/${S.currentTT.id}/assign`, { teacher_id: id });
  if (r.ok) {
    S.currentTT.assigned = r.assigned;
    await renderAssignedList();
    // Reset dropdown
    document.getElementById('assign-teacher-select').value = '';
    toast('Teacher assigned successfully', 'success');
  } else {
    toast(r.msg || 'Failed to assign teacher', 'error');
  }
}

async function renderAssignedList() {
  const el = document.getElementById('assigned-list');
  if (!el) return;
  if (!S.currentTT?.assigned?.length) {
    el.innerHTML = '<div class="empty-state" style="padding:12px 0"><p>No teachers assigned yet.</p></div>';
    return;
  }
  // Fetch fresh teacher list if needed
  if (!S.teachers.length) {
    const tR = await api('GET', '/teachers');
    if (tR.ok) S.teachers = tR.teachers;
  }
  el.innerHTML = S.currentTT.assigned.map(tid => {
    const t = S.teachers.find(x => x.id === tid);
    if (!t) return '';
    return `<div class="assign-item">
      <div class="assign-avatar">${t.name[0].toUpperCase()}</div>
      <div><div class="assign-name">${t.name}</div><div class="assign-sub">${t.dept || ''} · ${t.subjects || ''}</div></div>
      <button class="assign-remove" onclick="unassignTeacher(${tid})">✕</button>
    </div>`;
  }).join('');
}

async function unassignTeacher(tid) {
  if (!S.currentTT) return;
  const r = await api('POST', `/timetables/${S.currentTT.id}/unassign`, { teacher_id: tid });
  if (r.ok) {
    S.currentTT.assigned = S.currentTT.assigned.filter(id => id !== tid);
    await renderAssignedList();
    toast('Teacher unassigned', 'info');
  }
}

// ── TEACHER VIEW ─────────────────────────────────────────────
async function loadTeacherView() {
  const ttR = await api('GET', '/timetables');
  const todayDayIdx = new Date().getDay();
  const todayKey    = ['SUN','MON','TUE','WED','THU','FRI','SAT'][todayDayIdx];
  const dayNames    = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
  document.getElementById('today-day-name').textContent = dayNames[todayDayIdx];
  document.getElementById('today-date-str').textContent = new Date().toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' });

  if (!ttR.ok || !ttR.timetables.length) {
    document.getElementById('t-tt-title').textContent  = 'No Timetable Assigned';
    document.getElementById('t-tt-meta').textContent   = 'Admin has not assigned a timetable to you yet.';
    document.getElementById('today-classes').innerHTML = '<div class="no-class-today">📭 No timetable assigned yet.</div>';
    const grid = document.getElementById('tt-table-container-teacher');
    if (grid) grid.innerHTML = '';
    loadNotifications();
    loadAnnouncements();
    loadLeaves();
    return;
  }

  // Load ALL assigned timetables and show the first published one
  const ttInfo = ttR.timetables[0];
  const fullR  = await api('GET', `/timetables/${ttInfo.id}`);
  if (!fullR.ok) {
    document.getElementById('t-tt-meta').textContent = 'Could not load timetable.';
    loadNotifications();
    loadAnnouncements();
    loadLeaves();
    return;
  }

  S.currentTT = fullR.timetable;
  document.getElementById('t-tt-title').textContent   = S.currentTT.name;
  document.getElementById('t-tt-meta').textContent    = `Room: ${S.currentTT.room || '—'} · ${S.currentTT.year_sem || ''} · A.Y ${S.currentTT.academic_year || ''}`;
  document.getElementById('t-breadcrumb').textContent = `Teacher → ${S.currentTT.department || 'My Schedule'}`;

  const cells      = S.currentTT.cells || {};
  const todaySlots = TIME_SLOTS.filter(s => !s.isLunch && cells[`${todayKey}|${s.id}`]?.subject);
  const todayEl    = document.getElementById('today-classes');
  if (!todaySlots.length) {
    todayEl.innerHTML = '<div class="no-class-today">📭 No classes today — enjoy your day!</div>';
  } else {
    todayEl.innerHTML = todaySlots.map(s => {
      const c = cells[`${todayKey}|${s.id}`];
      return `<div class="today-class"><div class="today-class-time">${s.short}</div><div class="today-class-sub">${c.subject}</div></div>`;
    }).join('');
  }

  // Show timetable switcher if multiple timetables assigned
  if (ttR.timetables.length > 1) {
    const switcherEl = document.getElementById('tt-switcher');
    if (switcherEl) {
      switcherEl.style.display = 'flex';
      switcherEl.innerHTML = ttR.timetables.map(tt =>
        `<button class="btn-action ${tt.id === S.currentTT.id ? 'filled' : 'outline'}"
          style="font-size:11px;padding:5px 10px"
          onclick="switchTeacherTT(${tt.id})">${tt.name}</button>`
      ).join('');
    }
  }

  renderTimetableGrid('tt-table-container-teacher', false);
  loadNotifications();
  loadAnnouncements();
  loadLeaves();
}

async function switchTeacherTT(id) {
  const r = await api('GET', `/timetables/${id}`);
  if (!r.ok) { toast('Failed to load timetable', 'error'); return; }
  S.currentTT = r.timetable;
  document.getElementById('t-tt-title').textContent   = S.currentTT.name;
  document.getElementById('t-tt-meta').textContent    = `Room: ${S.currentTT.room || '—'} · ${S.currentTT.year_sem || ''} · A.Y ${S.currentTT.academic_year || ''}`;
  document.getElementById('t-breadcrumb').textContent = `Teacher → ${S.currentTT.department || 'My Schedule'}`;
  renderTimetableGrid('tt-table-container-teacher', false);
  // Update switcher buttons
  document.querySelectorAll('#tt-switcher button').forEach(btn => {
    btn.className = btn.onclick?.toString().includes(String(id)) ? 'btn-action filled' : 'btn-action outline';
    btn.style.fontSize = '11px'; btn.style.padding = '5px 10px';
  });
}

// ── NOTIFICATIONS ────────────────────────────────────────────
async function loadNotifications() {
  const r = await api('GET', '/notifications');
  if (!r.ok) return;
  updateNotifBadges(r.unread);
  renderNotifPanel(r.notifications);
}

async function loadNotificationsNav() {
  const r = await api('GET', '/notifications');
  if (!r.ok) return;
  updateNotifBadges(r.unread);
}

function updateNotifBadges(count) {
  const badge = document.getElementById('notif-badge');
  const navBadge = document.getElementById('notif-nav-badge');
  if (badge) { badge.textContent = count; badge.style.display = count ? 'inline' : 'none'; }
  if (navBadge) { navBadge.textContent = count; navBadge.style.display = count ? 'inline' : 'none'; }
}

function renderNotifPanel(notifs) {
  const el = document.getElementById('notif-body');
  if (!notifs || !notifs.length) { el.innerHTML = '<div class="empty-state"><div class="icon">🔔</div><p>No notifications.</p></div>'; return; }
  el.innerHTML = notifs.map(n => `
    <div class="notif-item">
      <div class="notif-dot ${n.read ? 'read' : ''}"></div>
      <div><div class="notif-text">${n.message}</div><div class="notif-time">${n.time}</div></div>
    </div>`).join('');
}

async function markAllRead() {
  await api('POST', '/notifications/read');
  updateNotifBadges(0);
  const r = await api('GET', '/notifications');
  if (r.ok) renderNotifPanel(r.notifications);
}

async function broadcastNotification() {
  const msg = prompt('Enter broadcast message for all teachers:');
  if (!msg) return;
  const r = await api('POST', '/notifications/broadcast', { message: msg });
  if (r.ok) toast(`Broadcast sent to ${r.sent} teachers`, 'success');
}

async function sendDailyReminders() {
  if (!confirm('Send daily schedule reminders to all teachers?')) return;
  const r = await api('POST', '/notifications/daily');
  if (r.ok) toast('Daily reminders sent to all teachers', 'success');
  else toast(r.msg || 'Failed', 'error');
}

// ── PROFILE ──────────────────────────────────────────────────
async function renderProfile() {
  const r = await api('GET', '/profile');
  if (!r.ok) return;
  const u = r.user, t = r.teacher;
  document.getElementById('profile-av').textContent = (u.name || 'U')[0].toUpperCase();
  document.getElementById('profile-name').textContent = u.name || u.username;
  const badge = document.getElementById('profile-role-badge');
  badge.textContent = u.role.toUpperCase();
  badge.className = 'nav-role-badge role-' + u.role;
  document.getElementById('ps-tt').textContent = r.timetable_count;
  document.getElementById('ps-since').textContent = u.created_at;
  document.getElementById('pi-email').textContent = u.email;
  document.getElementById('pi-username').textContent = u.username;
  document.getElementById('pi-dept').textContent = u.department || t?.dept || '—';
  document.getElementById('pi-phone').textContent = u.phone || t?.phone || '—';
  // Pre-fill edit fields
  document.getElementById('ep-name').value = u.name || '';
  document.getElementById('ep-phone').value = u.phone || t?.phone || '';
  document.getElementById('ep-dept').value = u.department || t?.dept || '';
}

async function saveProfileEdit() {
  const name = document.getElementById('ep-name').value.trim();
  const phone = document.getElementById('ep-phone').value.trim();
  const department = document.getElementById('ep-dept').value.trim();
  const r = await api('POST', '/profile/update', { name, phone, department });
  if (r.ok) {
    S.user = r.user;
    document.getElementById('nav-username').textContent = r.user.name;
    showMsg('ep-msg', 'Profile updated!', 'success');
    await renderProfile();
  } else showMsg('ep-msg', r.msg || 'Failed', 'error');
}

async function changePassword() {
  const old_password = document.getElementById('cp-old').value;
  const new_password = document.getElementById('cp-new').value.trim();
  const confirm_pw = document.getElementById('cp-confirm').value.trim();
  if (new_password !== confirm_pw) { showMsg('cp-msg', 'Passwords do not match', 'error'); return; }
  const passwordError = getPasswordValidationMessage(new_password, S.user?.username || '', S.user?.email || '', S.user?.name || '');
  if (passwordError) { showMsg('cp-msg', passwordError, 'error'); return; }
  const r = await api('POST', '/auth/change-password', { old_password, new_password });
  if (r.ok) {
    showMsg('cp-msg', 'Password updated!', 'success');
    ['cp-old', 'cp-new', 'cp-confirm'].forEach(id => document.getElementById(id).value = '');
  } else showMsg('cp-msg', r.msg || 'Failed', 'error');
}

window.addEventListener('DOMContentLoaded', () => {
  restoreSavedLoginCredentials();
});

// ── HISTORY (audit log) ──────────────────────────────────────
const ACTION_ICONS = {
  cell_set:         '✏️',
  cell_clear:       '🗑',
  bulk_add:         '📋',
  clear_all:        '🧹',
  settings:         '⚙️',
  autofill:         '⚡',
  generate_applied: '🤖',
};
const ACTION_LABELS = {
  cell_set:         'Cell edited',
  cell_clear:       'Cell cleared',
  bulk_add:         'Bulk added',
  clear_all:        'All cleared',
  settings:         'Settings changed',
  autofill:         'Auto-filled',
  generate_applied: 'Generated',
};

let historyFilter = 'all';   // 'all' | action key
let historyTTId   = null;    // which timetable we're viewing history for

async function renderHistory(ttId) {
  const targetId = ttId || historyTTId || S.currentTT?.id;
  historyTTId = targetId;
  const el = document.getElementById('history-body');

  if (!targetId) {
    // No specific timetable — show timetable list as before
    const r = await api('GET', '/timetables');
    if (!r.ok || !r.timetables.length) {
      el.innerHTML = '<div class="empty-state"><div class="icon">📂</div><p>No timetables yet.</p></div>';
      return;
    }
    el.innerHTML = `
      <div style="margin-bottom:10px;font-size:12px;color:var(--text3)">Click a timetable to view its change log.</div>
      ${r.timetables.map(tt => `
        <div class="hist-item" style="cursor:pointer" onclick="renderHistory(${tt.id})">
          <div class="hist-name">${tt.name}</div>
          <div class="hist-meta">
            <span>${tt.department || '—'}</span>
            <span>Room ${tt.room || '—'}</span>
            <span>Updated ${tt.updated_at}</span>
          </div>
          <div class="hist-actions" style="margin-top:8px">
            ${S.user?.role === 'admin' ? `<button class="btn-action filled" style="font-size:11px;padding:5px 10px" onclick="event.stopPropagation();openTimetable(${tt.id});closePanel('panel-history')">Open →</button>` : ''}
            <button class="btn-action outline" style="font-size:11px;padding:5px 10px" onclick="event.stopPropagation();exportImage(${tt.id})">Image</button>
            <button class="btn-action outline" style="font-size:11px;padding:5px 10px;border-color:var(--accent)" onclick="event.stopPropagation();renderHistory(${tt.id})">📋 Log</button>
          </div>
        </div>`).join('')}`;
    return;
  }

  // Load audit log for this timetable
  el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3)"><span class="spinner"></span> Loading history...</div>';
  const r = await api('GET', `/timetables/${targetId}/history?limit=80`);
  if (!r.ok) { el.innerHTML = '<div class="empty-state"><p>Failed to load history.</p></div>'; return; }

  const entries = r.history || [];
  const ttName  = S.timetables.find(t => t.id === targetId)?.name || `TT #${targetId}`;

  // Filter bar
  const allActions = [...new Set(entries.map(e => e.action))];
  const filterBar = `
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;align-items:center">
      <button class="btn-action outline" style="font-size:11px;padding:4px 8px" onclick="renderHistory(null)">← All Timetables</button>
      <span style="font-size:12px;font-weight:600;flex:1;color:var(--text1)">${ttName}</span>
      <select id="hist-filter" onchange="historyFilter=this.value;renderHistory(${targetId})" style="font-size:11px;padding:3px 6px;border-radius:6px;background:var(--bg2);color:var(--text1);border:1px solid var(--border)">
        <option value="all">All actions</option>
        ${allActions.map(a => `<option value="${a}" ${historyFilter===a?'selected':''}>${ACTION_LABELS[a]||a}</option>`).join('')}
      </select>
    </div>`;

  const filtered = historyFilter === 'all' ? entries : entries.filter(e => e.action === historyFilter);
  if (!filtered.length) {
    el.innerHTML = filterBar + '<div class="empty-state"><div class="icon">📋</div><p>No changes logged yet.</p></div>';
    return;
  }

  const rows = filtered.map(e => {
    const icon  = ACTION_ICONS[e.action] || '📝';
    const label = ACTION_LABELS[e.action] || e.action;
    const canRestore = !!e.snapshot && e.action !== 'settings';
    return `
      <div class="hist-item" style="padding:10px 12px">
        <div style="display:flex;align-items:flex-start;gap:10px">
          <span style="font-size:18px;flex-shrink:0">${icon}</span>
          <div style="flex:1;min-width:0">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
              <span style="font-size:12px;font-weight:600;color:var(--accent)">${label}</span>
              <span style="font-size:10px;color:var(--text3);font-family:var(--font-mono);white-space:nowrap">${e.time}</span>
            </div>
            <div style="font-size:12px;color:var(--text2);margin-top:2px">${e.detail || '—'}</div>
            <div style="font-size:11px;color:var(--text3);margin-top:2px">by ${e.user || 'System'} (${e.role || ''})</div>
          </div>
          ${canRestore && S.user?.role === 'admin' ? `
            <button class="btn-action outline" style="font-size:10px;padding:3px 7px;flex-shrink:0;color:var(--amber)"
              onclick="restoreSnapshot(${targetId},${e.id})" title="Restore timetable to this point">↩ Restore</button>` : ''}
        </div>
      </div>`;
  }).join('');

  el.innerHTML = filterBar +
    `<div style="font-size:11px;color:var(--text3);margin-bottom:8px">${filtered.length} of ${r.total} entries</div>` +
    rows;
}

async function restoreSnapshot(ttId, entryId) {
  if (!confirm('Restore timetable to this snapshot? Current cells will be overwritten.')) return;
  const r = await api('POST', `/timetables/${ttId}/history/${entryId}/restore`);
  if (r.ok) {
    if (S.currentTT?.id === ttId) {
      S.currentTT = r.timetable;
      renderTimetableGrid('tt-table-container', true);
    }
    toast('Timetable restored to selected snapshot', 'success');
    renderHistory(ttId);
  } else toast(r.msg || 'Restore failed', 'error');
}

// ── EXPORT ───────────────────────────────────────────────────
function exportPDF(id) {
  const ttId = id || S.currentTT?.id;
  if (!ttId) { toast('Open a timetable first', 'error'); return; }
  window.open(`/api/timetables/${ttId}/export/pdf`, '_blank');
  toast('Opening PDF...', 'info');
}

function exportImage(id) {
  const ttId = id || S.currentTT?.id;
  if (!ttId) { toast('Open a timetable first', 'error'); return; }
  const a = document.createElement('a');
  a.href = `/api/timetables/${ttId}/export/image`;
  a.download = '';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  toast('Downloading image...', 'info');
}

// ── VOICE — SINGLE FIELD ─────────────────────────────────────
function voiceField(inputId, fieldLabel) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice not supported. Use Chrome/Edge.', 'error'); return; }
  const r = new SR(); r.lang = 'en-IN'; r.continuous = false; r.interimResults = false;
  const btn = document.querySelector(`button[onclick*="${inputId}"]`);
  if (btn) btn.classList.add('listening');
  toast(`Listening for ${fieldLabel}...`, 'info');
  r.onresult = e => {
    const t = e.results[0][0].transcript.trim();
    document.getElementById(inputId).value = t;
    toast(`Captured: "${t}"`, 'success');
  };
  r.onerror = e => { toast('Voice error: ' + e.error, 'error'); };
  r.onend = () => { if (btn) btn.classList.remove('listening'); };
  r.start();
}

// ── VOICE — TIMETABLE COMMANDS ───────────────────────────────
function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice not supported. Use Chrome or Edge.', 'error'); return null; }
  const r = new SR(); r.lang = 'en-IN'; r.continuous = false; r.interimResults = true;
  return r;
}

function toggleVoice() {
  if (S.recognition) stopVoice();
  else startVoiceWizard();
}

// ── 4-STEP VOICE WIZARD ──────────────────────────────────────
// Step 1: Subject name
// Step 2: Day (Monday–Saturday)
// Step 3: Period number (1–7)
// Step 4: Teacher name

const DAY_MAP_VOICE = {
  monday:'MON', tuesday:'TUE', wednesday:'WED', thursday:'THU',
  friday:'FRI', saturday:'SAT',
  mon:'MON', tue:'TUE', wed:'WED', thu:'THU', fri:'FRI', sat:'SAT'
};
const ORDINALS_VOICE = {
  one:1, two:2, three:3, four:4, five:5, six:6, seven:7,
  first:1, second:2, third:3, fourth:4, fifth:5, sixth:6, seventh:7,
  '1st':1,'2nd':2,'3rd':3,'4th':4,'5th':5,'6th':6,'7th':7
};

// Wizard state
let VW = { step: 1, subject: '', day: '', slot: null, teacher: '' };

function startVoiceWizard() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  // Reset state
  VW = { step: 1, subject: '', day: '', slot: null, teacher: '' };
  _vwResetUI();
  openModal('modal-voice');
  const vbar = document.getElementById('voice-bar');
  if (vbar) vbar.classList.add('listening');
  const vbarText = document.getElementById('vbar-text');
  if (vbarText) vbarText.textContent = '🎙 Listening...';
  _vwAskStep(1);
}

function _vwResetUI() {
  // Reset all dots and values
  for (let i = 1; i <= 4; i++) {
    const dot = document.getElementById(`vstep-dot-${i}`);
    const row = document.getElementById(`vstep-row-${i}`);
    const val = document.getElementById(`vstep-val-${i}`);
    if (dot) dot.className = 'vstep-dot' + (i === 1 ? ' active' : '');
    if (row) row.className = 'vstep-row';
    if (val) val.textContent = '—';
  }
  const t = document.getElementById('voice-transcript');
  if (t) t.textContent = 'Listening...';
  const q = document.getElementById('voice-question');
  if (q) q.textContent = '';
  const title = document.getElementById('voice-modal-title');
  if (title) title.textContent = '🎙 Voice Input';
}

function _vwAskStep(step) {
  const questions = {
    1: 'Say the Subject name',
    2: 'Say the Day  (Monday – Saturday)',
    3: 'Say the Period number  (1 – 7)',
    4: 'Say the Teacher name  (or "skip")'
  };

  // Update dots
  for (let i = 1; i <= 4; i++) {
    const dot = document.getElementById(`vstep-dot-${i}`);
    const row = document.getElementById(`vstep-row-${i}`);
    if (!dot) continue;
    if (i < step)  { dot.className = 'vstep-dot done'; if (row) row.classList.remove('active'); }
    if (i === step) { dot.className = 'vstep-dot active'; if (row) row.classList.add('active'); }
    if (i > step)  { dot.className = 'vstep-dot'; if (row) row.classList.remove('active'); }
  }

  // Update question
  const q = document.getElementById('voice-question');
  if (q) q.textContent = questions[step];

  const t = document.getElementById('voice-transcript');
  if (t) t.textContent = 'Listening...';

  const title = document.getElementById('voice-modal-title');
  const stepLabels = { 1:'Subject', 2:'Day', 3:'Period', 4:'Teacher' };
  if (title) title.textContent = `🎙 Step ${step} of 4 — ${stepLabels[step]}`;

  // Start listening
  _vwListen(step);
}

function _vwListen(step) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice not supported. Use Chrome/Edge.', 'error'); stopVoice(); return; }
  const r = new SR();
  r.lang = 'en-IN';
  r.continuous = false;
  r.interimResults = true;
  S.recognition = r;

  r.onresult = e => {
    const result = e.results[e.results.length - 1];
    const transcript = result[0].transcript.trim();
    const tEl = document.getElementById('voice-transcript');
    if (tEl) tEl.textContent = `"${transcript}"`;
    if (result.isFinal) _vwHandleResult(step, transcript).catch(e => { toast('Error: ' + e.message, 'error'); stopVoice(); });
  };

  r.onerror = e => {
    if (e.error === 'no-speech') {
      toast('No speech detected — try again', 'info');
      setTimeout(() => _vwListen(step), 400);
    } else {
      toast('Voice error: ' + e.error, 'error');
      stopVoice();
    }
  };

  r.onend = () => { S.recognition = null; };
  r.start();
}

async function _vwHandleResult(step, text) {
  const t = text.toLowerCase().trim();

  // Show "processing" while NLP runs
  const tEl = document.getElementById('voice-transcript');
  if (tEl) tEl.textContent = `⏳ Processing: "${text}"`;

  // ── Call backend NLP correction ──────────────────────────
  let nlp = null;
  try {
    const res = await fetch('/api/voice/nlp-correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ step, text })
    });
    nlp = await res.json();
  } catch (e) { nlp = null; }

  // ── Confidence badge shown in transcript ─────────────────
  function showNLP(label, confidence) {
    const badges = { exact:'✅', high:'✅', medium:'🔶', low:'⚠️', skip:'⏭', none:'❌' };
    const badge = badges[confidence] || '⚠️';
    if (tEl) tEl.textContent = `${badge} "${label}"`;
  }

  // ── STEP 1: Subject ──────────────────────────────────────
  if (step === 1) {
    let subject = text.replace(/\b\w/g, c => c.toUpperCase()).trim();

    if (nlp && nlp.ok) {
      subject = nlp.corrected || subject;
      showNLP(subject, nlp.confidence);
      if (nlp.matched && nlp.confidence !== 'low') {
        // Auto-confirm if high confidence match
      } else {
        // Low confidence — show what we got, still proceed
      }
    }

    if (!subject || subject.length < 1) {
      toast('Could not hear subject name — please say it again', 'info');
      setTimeout(() => _vwListen(1), 600); return;
    }

    VW.subject = subject;
    _vwMarkDone(1, subject + (nlp?.matched ? ' ✅' : ''));
    setTimeout(() => _vwAskStep(2), 700);

  // ── STEP 2: Day ─────────────────────────────────────────
  } else if (step === 2) {
    let day = null;
    let dayDisplay = '';

    if (nlp && nlp.ok && nlp.corrected) {
      day        = nlp.corrected;
      dayDisplay = nlp.display || nlp.corrected;
      showNLP(dayDisplay, nlp.confidence);
    } else {
      // Fallback — local map
      for (const [word, code] of Object.entries(DAY_MAP_VOICE)) {
        if (t.includes(word)) { day = code; break; }
      }
      const dayFull = { MON:'Monday', TUE:'Tuesday', WED:'Wednesday',
                        THU:'Thursday', FRI:'Friday', SAT:'Saturday' };
      dayDisplay = dayFull[day] || day || text;
    }

    if (!day) {
      toast('Day not recognised — please say Monday to Saturday', 'info');
      setTimeout(() => _vwListen(2), 600); return;
    }

    VW.day = day;
    _vwMarkDone(2, dayDisplay);
    setTimeout(() => _vwAskStep(3), 700);

  // ── STEP 3: Period ───────────────────────────────────────
  } else if (step === 3) {
    let slot = null;

    if (nlp && nlp.ok && nlp.corrected !== null) {
      slot = nlp.corrected;
      showNLP(`Period ${slot}`, nlp.confidence);
    } else {
      // Fallback local parse
      const numMatch = t.match(/\b([1-7])\b/);
      if (numMatch) slot = parseInt(numMatch[1]);
      else {
        for (const [word, num] of Object.entries(ORDINALS_VOICE)) {
          if (t.includes(word)) { slot = num; break; }
        }
      }
    }

    if (!slot || slot < 1 || slot > 7) {
      toast('Please say a period number from 1 to 7', 'info');
      setTimeout(() => _vwListen(3), 600); return;
    }

    const slotObj = TIME_SLOTS[slot - 1];
    if (slotObj && slotObj.isLunch) {
      toast('That is the lunch break (period 4) — please choose another period', 'info');
      setTimeout(() => _vwListen(3), 600); return;
    }

    VW.slot = slot;
    _vwMarkDone(3, `Period ${slot} — ${slotObj ? slotObj.label : ''}`);
    setTimeout(() => _vwAskStep(4), 700);

  // ── STEP 4: Teacher ──────────────────────────────────────
  } else if (step === 4) {
    let teacher = '';

    if (nlp && nlp.ok) {
      if (nlp.skipped) {
        // User said "skip" / "none"
        teacher = '';
        showNLP('(skipped)', 'skip');
      } else {
        teacher = nlp.corrected || text.replace(/\b\w/g, c => c.toUpperCase()).trim();
        showNLP(teacher, nlp.confidence);
        if (nlp.confidence === 'low' && !nlp.matched) {
          // Warn but don't block
          toast(`Teacher "${teacher}" not found in DB — saving anyway`, 'info');
        }
      }
    } else {
      const skipWords = ['skip','none','no','empty','blank'];
      if (!skipWords.some(w => t.includes(w))) {
        teacher = text.replace(/\b\w/g, c => c.toUpperCase()).trim();
      }
    }

    VW.teacher = teacher;
    _vwMarkDone(4, teacher || '(no teacher)');
    setTimeout(() => _vwSave(), 700);
  }
}

function _vwMarkDone(step, value) {
  const row = document.getElementById(`vstep-row-${step}`);
  const val = document.getElementById(`vstep-val-${step}`);
  const dot = document.getElementById(`vstep-dot-${step}`);
  if (row) row.className = 'vstep-row done';
  if (val) val.textContent = value;
  if (dot) dot.className = 'vstep-dot done';
}

async function _vwSave() {
  if (!S.currentTT) { stopVoice(); return; }
  const slotObj = TIME_SLOTS[VW.slot - 1];
  if (!slotObj) { stopVoice(); toast('Invalid slot', 'error'); return; }

  const key = `${VW.day}|${slotObj.id}`;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells`, {
    key,
    subject: VW.subject,
    teacher: VW.teacher,
    type: 'lecture'
  });

  if (r.ok) {
    S.currentTT.cells = r.cells;
    renderTimetableGrid('tt-table-container', true);
    const q = document.getElementById('voice-question');
    if (q) q.textContent = '✅ Successfully saved!';
    const title = document.getElementById('voice-modal-title');
    if (title) title.textContent = '✅ Done!';
    toast(`Added: ${VW.subject} — ${VW.day} Period ${VW.slot}${VW.teacher ? ' (' + VW.teacher + ')' : ''}`, 'success');
    setTimeout(() => stopVoice(), 1200);
  } else {
    toast('Save failed — ' + (r.msg || 'error'), 'error');
    stopVoice();
  }
}

// ── START VOICE ACTION (alias for backward compat) ───────────
function startVoiceAction() { startVoiceWizard(); }

function stopVoice() {
  if (S.recognition) { try { S.recognition.stop(); } catch (e) {} S.recognition = null; }
  closeModal('modal-voice');
  const vbar = document.getElementById('voice-bar');
  if (vbar) vbar.classList.remove('listening');
  const vbarText = document.getElementById('vbar-text');
  if (vbarText) vbarText.textContent = 'Voice ready — Ctrl+K or 🎙 to add subject';
}

async function processVoiceCommand(text) {
  // Kept for backward compat with non-wizard calls (clear, export, free_slot etc.)
  if (!S.currentTT) { stopVoice(); toast('Open a timetable first', 'error'); return; }
  const parsed = await parseVoiceOnServer(text);
  if (parsed.intent === 'clear' && parsed.day && parsed.slot) {
    const slotObj = TIME_SLOTS[parsed.slot - 1];
    if (slotObj) {
      const r = await api('POST', `/timetables/${S.currentTT.id}/cells`,
        { key: `${parsed.day}|${slotObj.id}`, subject: '', teacher: '', type: 'lecture' });
      if (r.ok) { S.currentTT.cells = r.cells; renderTimetableGrid('tt-table-container', true);
        toast(`Cleared ${parsed.day} slot ${parsed.slot}`, 'info'); }
    }
  } else if (parsed.intent === 'export') { exportPDF();
  } else if (parsed.intent === 'free_slot') { suggestFreeSlot();
  } else if (parsed.intent === 'generate') { openModal('modal-generate'); }
}

async function parseVoiceOnServer(text) {
  try { const r = await api('POST', '/voice/parse', { text }); if (r.ok) return r.parsed; }
  catch (e) {}
  return parseVoiceLocal(text);
}

function parseVoiceLocal(text) {
  const t = text.toLowerCase().trim();
  const DAY_MAP = { monday:'MON',tuesday:'TUE',wednesday:'WED',thursday:'THU',friday:'FRI',saturday:'SAT',
                    mon:'MON',tue:'TUE',wed:'WED',thu:'THU',fri:'FRI',sat:'SAT' };
  let intent = 'add';
  if (/clear|remove|delete/.test(t)) intent = 'clear';
  else if (/export|pdf/.test(t)) intent = 'export';
  else if (/free|available|empty/.test(t)) intent = 'free_slot';
  else if (/generate|create.*section/.test(t)) intent = 'generate';
  let day = null;
  for (const [word, code] of Object.entries(DAY_MAP)) { if (t.includes(word)) { day = code; break; } }
  let slot = null;
  const sm = t.match(/(?:slot|period|at|number)?\s*(\d+)/);
  if (sm) slot = parseInt(sm[1]);
  let subject = null;
  const addM = t.match(/(?:add|schedule|put)\s+(.+?)\s+(?:on|for|at|to)/);
  if (addM) subject = addM[1].trim().replace(/\b\w/g, c => c.toUpperCase());
  return { intent, day, slot, subject, teacher: null, raw: text };
}

// ── VOICE LOGIN ──────────────────────────────────────────────
function startVoiceLogin() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice not supported. Use Chrome or Edge.', 'error'); return; }
  let capturedUsername = '';

  function listenForUsername() {
    const r = new SR(); r.lang = 'en-IN'; r.continuous = false; r.interimResults = false;
    toast('Say your username', 'info');
    r.onresult = e => {
      if (!e.results[e.results.length - 1].isFinal) return;
      capturedUsername = e.results[e.results.length - 1][0].transcript.trim().replace(/\s+/g, '');
      r.stop();
      setTimeout(listenForPassword, 600);
    };
    r.onerror = e => { toast('Voice error: ' + e.error, 'error'); };
    r.start();
  }

  function listenForPassword() {
    const r2 = new SR(); r2.lang = 'en-IN'; r2.continuous = false; r2.interimResults = false;
    toast('Now say your password', 'info');
    r2.onresult = e => {
      if (!e.results[e.results.length - 1].isFinal) return;
      const pw = e.results[e.results.length - 1][0].transcript.trim().replace(/\s+/g, '');
      document.getElementById('l-user').value = capturedUsername;
      document.getElementById('l-pass').value = pw;
      r2.stop();
      doLogin();
    };
    r2.onerror = e => { toast('Voice error: ' + e.error, 'error'); };
    r2.start();
  }

  listenForUsername();
}

// ── GLOBAL VOICE (Admin dashboard commands) ──────────────────
let gVoiceActive = false;

function toggleGlobalVoice() {
  if (gVoiceActive) stopGlobalVoice();
  else startGlobalVoice();
}

function startGlobalVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { toast('Voice not supported', 'error'); return; }
  const r = new SR(); r.lang = 'en-IN'; r.continuous = false; r.interimResults = false;
  S.globalRecognition = r; gVoiceActive = true;
  const btn = document.getElementById('vcmd-start-btn');
  if (btn) { btn.textContent = '⏹ Stop Listening'; btn.style.background = 'var(--red)'; }
  document.getElementById('vcmd-transcript').textContent = 'Listening...';
  r.onresult = async e => {
    const t = e.results[0][0].transcript.trim();
    document.getElementById('vcmd-transcript').textContent = t;
    await processGlobalVoiceCommand(t);
    gVoiceActive = false;
    if (btn) { btn.textContent = '🎙 Start Listening'; btn.style.background = ''; }
  };
  r.onerror = e => {
    toast('Voice error: ' + e.error, 'error'); stopGlobalVoice();
  };
  r.onend = () => { gVoiceActive = false; if (btn) { btn.textContent = '🎙 Start Listening'; btn.style.background = ''; } };
  r.start();
}

function stopGlobalVoice() {
  if (S.globalRecognition) { try { S.globalRecognition.stop(); } catch (e) { } S.globalRecognition = null; }
  gVoiceActive = false;
  const btn = document.getElementById('vcmd-start-btn');
  if (btn) { btn.textContent = '🎙 Start Listening'; btn.style.background = ''; }
}

async function processGlobalVoiceCommand(text) {
  const t = text.toLowerCase().trim();
  const msgEl = document.getElementById('vcmd-msg');

  if (/broadcast/.test(t)) {
    const msg = text.replace(/broadcast/i, '').trim();
    if (msg) {
      const r = await api('POST', '/notifications/broadcast', { message: msg });
      if (r.ok) { showMsg('vcmd-msg', `Broadcast sent to ${r.sent} teachers`, 'success'); toast('Broadcast sent', 'success'); }
    } else { showMsg('vcmd-msg', 'Say "broadcast [your message]"', 'error'); }

  } else if (/daily|remind/.test(t)) {
    const r = await api('POST', '/notifications/daily');
    showMsg('vcmd-msg', r.ok ? 'Daily reminders sent!' : 'Failed', r.ok ? 'success' : 'error');
    if (r.ok) toast('Daily reminders sent', 'success');

  } else if (/generate|create.*section|smart.*timetable/.test(t)) {
    closeModal('modal-voice-cmd');
    openModal('modal-generate');

  } else if (/add.*teacher/.test(t)) {
    closeModal('modal-voice-cmd');
    openModal('modal-add-teacher');
    // Try to extract name
    const nameM = text.match(/add\s+teacher\s+([A-Za-z\s]+?)(?:\s+(?:in|at|for|dept|department)|$)/i);
    if (nameM) {
      document.getElementById('at-name').value = nameM[1].trim();
      toast(`Teacher name pre-filled: "${nameM[1].trim()}"`, 'info');
    }
  } else if (/create.*timetable|new.*timetable/.test(t)) {
    closeModal('modal-voice-cmd');
    openModal('modal-new-tt');
    const nameM = text.match(/(?:create|new)\s+timetable\s+(.+)/i);
    if (nameM) document.getElementById('ntt-name').value = nameM[1].trim();

  } else if (/open.*dashboard|go.*dashboard/.test(t)) {
    closeModal('modal-voice-cmd');
    showAppSection('dashboard');
    showMsg('vcmd-msg', 'Navigated to Dashboard', 'success');

  } else {
    showMsg('vcmd-msg', `Not recognized: "${text}". Try "broadcast ...", "add teacher ...", "generate timetable"`, 'error');
  }
}

// ── MODALS & PANELS ──────────────────────────────────────────
function openModal(id) {
  document.getElementById(id).classList.add('open');
  if (id === 'modal-generate') {
    S.genSubjects = []; S.genTeachers = [];
    ['gen-subjects-tags', 'gen-teachers-tags', 'gen-results'].forEach(i => document.getElementById(i).innerHTML = '');
    document.getElementById('gen-footer').style.display = 'none';
  }
}
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function overlayClick(e, id) { if (e.target === document.getElementById(id)) closeModal(id); }

function openPanel(id) {
  closeAllPanels();
  document.getElementById(id).classList.add('open');
  document.getElementById('sp-backdrop').classList.add('show');
  if (id === 'panel-profile') renderProfile();
  if (id === 'panel-history') {
    historyFilter = 'all';
    renderHistory(S.currentTT?.id || null);
  }
  if (id === 'panel-notif') loadNotifications();
}
function closePanel(id) {
  document.getElementById(id).classList.remove('open');
  document.getElementById('sp-backdrop').classList.remove('show');
}
function closeAllPanels() {
  ['panel-profile', 'panel-history', 'panel-notif'].forEach(id => {
    const el = document.getElementById(id); if (el) el.classList.remove('open');
  });
  document.getElementById('sp-backdrop').classList.remove('show');
}

// ── TOAST ────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<div class="t-dot"></div><span>${msg}</span>`;
  c.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add('show')));
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 400); }, 4500);
}

// ── KEYBOARD SHORTCUTS ───────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeAllPanels();
    document.querySelectorAll('.overlay.open').forEach(o => o.classList.remove('open'));
    stopVoice();
    stopGlobalVoice();
  }
  if ((e.ctrlKey || e.metaKey) && e.key === 'k' && S.currentTT) { e.preventDefault(); startVoiceAction(); }
});

// ── INIT ─────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  applyTheme();
  restoreSavedLoginCredentials();
  clearLoginForm();
  setTimeout(() => clearLoginForm(), 50);
  setTimeout(() => clearLoginForm(), 250);
  try {
    const r = await api('GET', '/auth/me');
    if (r.ok) loginSuccess(r.user);
    else clearLoginForm();
  } catch (e) { }
});

window.addEventListener('pageshow', () => {
  if (!S.user) {
    clearLoginForm();
  }
});

// ══════════════════════════════════════════════════════
// SchediQ v2 — NEW FEATURE FUNCTIONS
// ══════════════════════════════════════════════════════

// ── CLASH DETECTOR ───────────────────────────────────
async function detectClashes() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  const r = await api('GET', `/timetables/${S.currentTT.id}/clashes`);
  if (!r.ok) { toast('Failed to check clashes', 'error'); return; }
  const el = document.getElementById('clash-results');
  if (!r.clashes.length) {
    el.innerHTML = '<div style="color:var(--green);font-weight:600;padding:12px 0">✅ No clashes found in this timetable!</div>';
  } else {
    el.innerHTML = `<div style="color:var(--red);font-weight:600;margin-bottom:8px">⚠️ ${r.clash_count} clash(es) found:</div>` +
      r.clashes.map(c => `<div class="hist-item" style="padding:8px 10px;display:flex;flex-direction:column;gap:6px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span><span style="color:var(--red)">⚡</span> <strong>${c.teacher}</strong> is double-booked at <code>${c.slot}</code> (${c.subject})</span>
          <button class="btn-sm red" onclick="resolveClash('${c.slot}')">Clear</button>
        </div>
        <div style="font-size:12px;color:var(--text2)">${c.suggested_note}</div>
        <div style="font-size:12px;color:var(--text3);white-space:pre-line">Suggested available teachers: ${c.suggested_teachers.length ? c.suggested_teachers.join(', ') : 'None (all busy)'}</div>
      </div>`).join('');
  }
  // Also check cross-timetable clashes
  const cr = await api('GET', '/clashes/cross');
  if (cr.ok && cr.count) {
    const crossEl = document.getElementById('clash-cross-results');
    if (crossEl) crossEl.innerHTML =
      `<div style="color:var(--amber);font-weight:600;margin:10px 0 6px">🔀 ${cr.count} cross-timetable clash(es):</div>` +
      cr.clashes.map(c => {
        const canClear = S.currentTT && c.timetables.includes(S.currentTT.name);
        const clearButton = canClear ? `<button class="btn-sm red" onclick="resolveClash('${c.slot}')">Clear from current</button>` : '';
        return `<div class="hist-item" style="padding:8px 10px;font-size:12px;display:flex;justify-content:space-between;align-items:center">
          <span><strong>${c.teacher}</strong> at <code>${c.slot}</code> in: ${c.timetables.join(', ')}</span>${clearButton}
        </div>`;
      }).join('');
  }
  openModal('modal-clashes');
}

// ── SUBSTITUTE FINDER ────────────────────────────────
async function resolveClash(slotKey) {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  if (!confirm(`Clear slot ${slotKey} in current timetable?`)) return;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells`, { key: slotKey });
  if (r.ok) {
    S.currentTT.cells = r.cells;
    renderTimetableGrid('tt-table-container', true);
    await detectClashes();
    toast(`Cleared ${slotKey}`, 'success');
  } else {
    toast(r.msg || 'Failed to clear cell', 'error');
  }
}

async function openSubstitute() {
  if (!S.currentTT) { toast('Open a timetable first', 'error'); return; }
  // populate teacher dropdown
  const sel = document.getElementById('sub-teacher-select');
  sel.innerHTML = '<option value="">— Select absent teacher —</option>' +
    S.teachers.map(t => `<option value="${t.name}">${t.name}</option>`).join('');
  document.getElementById('sub-results').innerHTML = '';
  openModal('modal-substitute');
}

async function findSubstitute() {
  if (!S.currentTT) return;
  const absent = document.getElementById('sub-teacher-select').value;
  const day    = document.getElementById('sub-day-select').value;
  if (!absent) { toast('Select an absent teacher', 'error'); return; }
  const r = await api('POST', `/timetables/${S.currentTT.id}/substitute`, { teacher_name: absent, day });
  const el = document.getElementById('sub-results');
  if (!r.ok) { el.innerHTML = `<div style="color:var(--red)">${r.msg}</div>`; return; }
  if (!r.suggestions.length) {
    el.innerHTML = '<div style="color:var(--text3);padding:10px 0">No classes found for this teacher on selected day.</div>';
    return;
  }
  el.innerHTML = r.suggestions.map(s => `
    <div class="hist-item" style="padding:10px 12px;margin-top:6px">
      <div style="font-size:12px;font-weight:600;color:var(--accent)">${s.time} — ${s.subject}</div>
      <div style="font-size:11px;color:var(--text3);margin-top:4px">Available substitutes:</div>
      <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">
        ${s.available.length
          ? s.available.slice(0,8).map(t => `<span class="tag" style="font-size:11px;cursor:pointer"
              onclick="assignSubstitute('${s.slot}','${t.replace(/'/g,"\\'")}')">👤 ${t}</span>`).join('')
          : '<span style="color:var(--red);font-size:11px">No available substitutes</span>'}
      </div>
    </div>`).join('');
}

async function assignSubstitute(slotKey, teacherName) {
  if (!S.currentTT) return;
  const cells = S.currentTT.cells || {};
  const cell  = cells[slotKey];
  if (!cell) return;
  const r = await api('POST', `/timetables/${S.currentTT.id}/cells`,
    { key: slotKey, subject: cell.subject, teacher: teacherName, type: cell.type || 'lecture' });
  if (r.ok) {
    S.currentTT.cells = r.cells;
    renderTimetableGrid('tt-table-container', true);
    closeModal('modal-substitute');
    toast(`Substitute ${teacherName} assigned`, 'success');
  }
}

// ── CLONE TIMETABLE ───────────────────────────────────
async function cloneTimetable(id) {
  const ttId = id || S.currentTT?.id;
  if (!ttId) { toast('Open a timetable first', 'error'); return; }
  const name = prompt('Name for the cloned timetable:', (S.currentTT?.name || 'Timetable') + ' (Copy)');
  if (!name) return;
  const r = await api('POST', `/timetables/${ttId}/clone`, { name });
  if (r.ok) {
    await loadAdminDashboard();
    toast(`Cloned as "${name}" (saved as draft)`, 'success');
    openTimetable(r.timetable.id);
  } else toast(r.msg || 'Clone failed', 'error');
}

// ── PUBLISH / DRAFT TOGGLE ────────────────────────────
async function togglePublish() {
  if (!S.currentTT) return;
  const newState = !S.currentTT.is_published;
  const r = await api('PUT', `/timetables/${S.currentTT.id}`, { is_published: newState });
  if (r.ok) {
    S.currentTT = r.timetable;
    updatePublishBtn();
    toast(newState ? '✅ Timetable published — teachers can now view it' : '📋 Timetable set to draft', 'info');
  }
}

function updatePublishBtn() {
  const btn = document.getElementById('btn-publish');
  if (!btn || !S.currentTT) return;
  btn.textContent = S.currentTT.is_published ? '📋 Draft' : '✅ Publish';
  btn.title       = S.currentTT.is_published ? 'Switch to draft (hide from teachers)' : 'Publish (make visible to teachers)';
  btn.style.background = S.currentTT.is_published ? 'var(--green)' : 'var(--amber)';
}

// ── WORKLOAD ANALYTICS ────────────────────────────────
async function openWorkload() {
  openModal('modal-workload');
  const el = document.getElementById('workload-body');
  el.innerHTML = '<div style="text-align:center;padding:20px;color:var(--text3)"><span class="spinner"></span> Loading...</div>';
  const r = await api('GET', '/workload/summary');
  if (!r.ok) { el.innerHTML = '<p style="color:var(--red)">Failed to load workload data.</p>'; return; }
  const days_short = ['MON','TUE','WED','THU','FRI','SAT'];
  el.innerHTML = r.summary.map(t => {
    const bars = days_short.map(d => {
      const cnt = t.workload[d] || 0;
      const over= cnt > t.max_periods;
      const pct = Math.min(100, (cnt / (t.max_periods || 6)) * 100);
      return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">
        <span style="width:30px;font-size:10px;color:var(--text3)">${d}</span>
        <div style="flex:1;height:10px;background:var(--bg3);border-radius:4px;overflow:hidden">
          <div style="width:${pct}%;height:100%;background:${over?'var(--red)':'var(--accent)'};border-radius:4px"></div>
        </div>
        <span style="font-size:10px;color:${over?'var(--red)':'var(--text2)'}">${cnt}</span>
      </div>`;
    }).join('');
    return `<div class="hist-item" style="padding:10px 12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <strong style="font-size:13px">${t.name}</strong>
        <div style="display:flex;gap:6px">
          <span class="tag" style="font-size:10px">${t.dept}</span>
          <span class="tag" style="font-size:10px;background:${t.overloaded.length?'var(--red)':'var(--green)'}20;color:${t.overloaded.length?'var(--red)':'var(--green)'}">
            ${t.total} periods/week
          </span>
        </div>
      </div>
      ${bars}
      ${t.overloaded.length ? `<div style="font-size:11px;color:var(--red);margin-top:4px">⚠️ Overloaded: ${t.overloaded.join(', ')}</div>` : ''}
    </div>`;
  }).join('') || '<div class="empty-state"><p>No workload data yet.</p></div>';
}

// ── ANNOUNCEMENTS ────────────────────────────────────
async function loadAnnouncements() {
  const r  = await api('GET', '/announcements');
  const el = document.getElementById('ann-body');
  if (!el) return;
  if (!r.ok || !r.announcements.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">📢</div><p>No announcements.</p></div>';
    return;
  }
  el.innerHTML = r.announcements.map(a => `
    <div class="hist-item" style="border-left:3px solid ${a.priority==='urgent'?'var(--red)':'var(--accent)'}">
      <div style="display:flex;justify-content:space-between;align-items:flex-start">
        <div style="font-weight:600;color:var(--text1);font-size:13px">${a.priority==='urgent'?'🚨 ':' 📢 '}${a.title}</div>
        <div style="display:flex;gap:4px;align-items:center">
          <span style="font-size:10px;color:var(--text3)">${a.time}</span>
          ${S.user?.role==='admin'?`<button class="icon-btn red-h" style="padding:2px 6px" onclick="deleteAnnouncement(${a.id})">🗑</button>`:''}
        </div>
      </div>
      <div style="font-size:12px;color:var(--text2);margin-top:6px;line-height:1.5">${a.body}</div>
      <div style="font-size:11px;color:var(--text3);margin-top:4px">— ${a.author}${a.dept_filter?' · '+a.dept_filter:''}</div>
    </div>`).join('');
}

async function postAnnouncement() {
  const title    = document.getElementById('ann-title').value.trim();
  const body     = document.getElementById('ann-body-input').value.trim();
  const priority = document.getElementById('ann-priority').value;
  const dept     = document.getElementById('ann-dept-filter').value.trim();
  if (!title || !body) { toast('Title and body required', 'error'); return; }
  const r = await api('POST', '/announcements', { title, body, priority, dept_filter: dept });
  if (r.ok) {
    closeModal('modal-announcement');
    ['ann-title','ann-body-input','ann-dept-filter'].forEach(id => document.getElementById(id).value='');
    toast('Announcement posted', 'success');
    loadAnnouncements();
  } else toast(r.msg || 'Failed', 'error');
}

async function deleteAnnouncement(id) {
  if (!confirm('Delete this announcement?')) return;
  const r = await api('DELETE', `/announcements/${id}`);
  if (r.ok) { loadAnnouncements(); toast('Deleted', 'info'); }
}

// ── LEAVE MANAGEMENT ─────────────────────────────────
async function loadLeaves() {
  const r  = await api('GET', '/leaves');
  const el = document.getElementById('leave-body');
  if (!el) return;
  if (!r.ok || !r.leaves.length) {
    el.innerHTML = '<div class="empty-state"><div class="icon">🗓</div><p>No leave requests.</p></div>';
    return;
  }
  el.innerHTML = r.leaves.map(l => `
    <div class="hist-item" style="padding:10px 12px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-weight:600;font-size:13px">${l.teacher_name} — ${l.leave_date}</div>
          <div style="font-size:12px;color:var(--text2);margin-top:2px">${l.reason || 'No reason given'}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center">
          <span style="font-size:11px;padding:3px 8px;border-radius:99px;background:${l.approved?'#16a34a22':'#dc262622'};color:${l.approved?'#16a34a':'#dc2626'}">${l.approved?'✅ Approved':'⏳ Pending'}</span>
          ${S.user?.role==='admin' && !l.approved ? `<button class="btn-action filled" style="font-size:11px;padding:3px 8px" onclick="approveLeave(${l.id})">Approve</button>` : ''}
          <button class="icon-btn red-h" onclick="deleteLeave(${l.id})">🗑</button>
        </div>
      </div>
    </div>`).join('');
}

async function applyLeave() {
  const leave_date = document.getElementById('leave-date').value;
  const reason     = document.getElementById('leave-reason').value.trim();
  if (!leave_date) { toast('Select a date', 'error'); return; }
  const r = await api('POST', '/leaves', { leave_date, reason });
  if (r.ok) {
    document.getElementById('leave-date').value = '';
    document.getElementById('leave-reason').value = '';
    toast('Leave request submitted', 'success');
    loadLeaves();
  } else toast(r.msg || 'Failed', 'error');
}

async function approveLeave(id) {
  const r = await api('POST', `/leaves/${id}/approve`);
  if (r.ok) { toast('Leave approved', 'success'); loadLeaves(); }
}

async function deleteLeave(id) {
  if (!confirm('Remove this leave request?')) return;
  const r = await api('DELETE', `/leaves/${id}`);
  if (r.ok) { toast('Removed', 'info'); loadLeaves(); }
}

// ── ACTIVITY LOG ─────────────────────────────────────
async function loadActivityLog() {
  const el = document.getElementById('activity-body');
  if (!el) return;
  el.innerHTML = '<div style="text-align:center;padding:12px;color:var(--text3)"><span class="spinner"></span></div>';
  const r = await api('GET', '/activity?limit=60');
  if (!r.ok) { el.innerHTML = '<p style="color:var(--red)">Failed</p>'; return; }
  el.innerHTML = r.logs.map(l => `
    <div class="hist-item" style="padding:8px 12px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:12px;color:var(--text1)"><strong>${l.user}</strong> — ${l.action}</span>
        <span style="font-size:10px;color:var(--text3);font-family:var(--font-mono)">${l.time}</span>
      </div>
      ${l.detail ? `<div style="font-size:11px;color:var(--text3);margin-top:2px">${l.detail}</div>` : ''}
    </div>`).join('') || '<div class="empty-state"><p>No activity yet.</p></div>';
}









// ══════════════════════════════════════════════════════
// v2 UNIFIED OVERRIDES  (single clean version, no chains)
// ══════════════════════════════════════════════════════

// ── openPanel extended with all v2 panels ────────────
function openPanel(id) {
  closeAllPanels();
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add('open');
  document.getElementById('sp-backdrop').classList.add('show');
  if (id === 'panel-profile')       renderProfile();
  if (id === 'panel-history')       { historyFilter = 'all'; renderHistory(S.currentTT?.id || null); }
  if (id === 'panel-notif')         loadNotifications();
  if (id === 'panel-announcements') {
    loadAnnouncements();
    const btn = document.getElementById('btn-post-ann');
    if (btn) btn.style.display = S.user?.role === 'admin' ? 'block' : 'none';
  }
  if (id === 'panel-leaves') {
    const form = document.getElementById('leave-apply-form');
    if (form) form.style.display = S.user?.role === 'admin' ? 'none' : 'block';
    loadLeaves();
  }
  if (id === 'panel-activity') loadActivityLog();
  if (id === 'panel-ai-chat') renderAIChat();
}

// ── closeAllPanels extended with v2 panels ───────────
function closeAllPanels() {
  ['panel-profile','panel-history','panel-notif',
   'panel-announcements','panel-leaves','panel-activity','panel-ai-chat']
    .forEach(id => { const el = document.getElementById(id); if (el) el.classList.remove('open'); });
  const bd = document.getElementById('sp-backdrop');
  if (bd) bd.classList.remove('show');
}

function ensureAIChatSeeded() {
  if (S.aiChatHistory.length) return;
  S.aiChatHistory = [{
    role: 'assistant',
    text: 'I can help with this timetable. Ask about today, free periods, specific day-slot entries, room details, or teacher load.'
  }];
}

function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderAIChat() {
  ensureAIChatSeeded();
  const box = document.getElementById('ai-chat-messages');
  if (!box) return;
  box.innerHTML = S.aiChatHistory.map(msg => `
    <div class="ai-chat-msg ${msg.role}">
      <div class="ai-chat-role">${msg.role === 'user' ? 'You' : 'SchediQ AI'}</div>
      <div class="ai-chat-text">${escapeHtml(msg.text)}</div>
    </div>
  `).join('');
  box.scrollTop = box.scrollHeight;
}

function askAIQuick(text) {
  const input = document.getElementById('ai-chat-input');
  if (input) input.value = text;
  sendAIChat();
}

function clearAIChat() {
  S.aiChatHistory = [];
  ensureAIChatSeeded();
  renderAIChat();
  const input = document.getElementById('ai-chat-input');
  if (input) input.value = '';
  const status = document.getElementById('ai-chat-status');
  if (status) status.textContent = 'Ask about the open timetable, teacher load, free periods, room, or subject slots.';
}

function handleAIChatKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendAIChat();
  }
}

async function sendAIChat() {
  const input = document.getElementById('ai-chat-input');
  const status = document.getElementById('ai-chat-status');
  if (!input) return;
  const message = input.value.trim();
  if (!message) return;
  ensureAIChatSeeded();
  S.aiChatHistory.push({ role: 'user', text: message });
  renderAIChat();
  input.value = '';
  if (status) status.textContent = 'Thinking...';
  const r = await api('POST', '/ai/chat', { message, timetable_id: S.currentTT?.id || null });
  if (r.ok) {
    S.aiChatHistory.push({ role: 'assistant', text: r.reply });
    if (status) status.textContent = r.context || 'Answer ready.';
  } else {
    S.aiChatHistory.push({ role: 'assistant', text: r.msg || 'I could not answer that just now.' });
    if (status) status.textContent = 'The assistant hit a problem.';
  }
  renderAIChat();
}
