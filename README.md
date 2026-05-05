# SchediQ v2 — Institute Timetable Management System

A full-featured, voice-enabled timetable management system built with Python (Flask) + SQLite.

---

## 🆕 What's New in v2

### ✅ Gap Fixes (from audit)
| Fix | Description |
|-----|-------------|
| **Timetable Change History** | Every cell edit, bulk add, clear, auto-fill, generate, and settings change is recorded with timestamp + user + full snapshot. One-click restore to any past state. |
| **Smart Auto-Fill** | Fills empty slots using assigned teachers' subjects. Clash-free: pre-populates existing teacher bookings before placing new ones. Supports Round-Robin and Random strategies. |

### 🆕 New Features Added
| Feature | Description |
|---------|-------------|
| **Timetable Clone/Duplicate** | Clone any timetable with one click. Copies all cells + assigned teachers. Saved as draft. |
| **Publish / Draft Toggle** | Admin can hide timetables from teachers (draft mode) until ready. Teachers only see published. |
| **Clash Detector** | Scan a timetable for internal teacher double-bookings. Also detects cross-timetable clashes (same teacher, same slot, different timetables). |
| **Substitute Teacher Finder** | Select an absent teacher + day → system lists available substitutes (no clashes) for each of their slots. Click to assign instantly. |
| **Teacher Workload Analytics** | Bar chart per teacher showing periods-per-day. Highlights overloaded days (exceeds max_periods). Admin summary view. |
| **CSV Export** | Download timetable as CSV (Day, Slot, Time, Subject, Teacher, Type). |
| **Announcements Board** | Admin posts announcements (normal or urgent). Teachers receive in-app notification. Dept-filter optional. |
| **Teacher Leave Management** | Teachers apply for leave (date + reason). Admin approves or rejects. Leave requests visible in admin dashboard. |
| **Activity Log** | Tracks all key admin actions: logins, logouts, teacher add/delete, timetable create/delete. Viewable by admin. |
| **Weekly Summary Email** | Automated email to admin every Monday with timetable stats, teacher count, pending leaves, and announcement count. |
| **Max Periods per Teacher** | Each teacher has a configurable `max_periods` per day. Used in workload analytics to flag overloaded teachers. |

---

## ✨ Full Feature List

### 👨‍💼 Admin Module
- Create, edit, delete timetables for all departments
- Clone timetables (draft → publish workflow)
- Assign/unassign teachers to timetables
- Bulk add cells, voice add, auto-fill, smart generation
- Detect clashes (internal + cross-timetable)
- Find substitute teachers for absent staff
- Teacher workload analytics
- Post announcements (urgent/normal, dept-filtered)
- Manage teacher leave requests
- Broadcast notifications to all teachers
- Trigger daily reminders manually
- View full activity log

### 👨‍🏫 Teacher Module
- Login with credentials provided by Admin
- View assigned (published) timetables
- Today's class highlight with time and subject
- Apply for leave (date + reason)
- View announcements
- Receive daily notifications (in-app + email)
- Download timetable as PDF / Image / CSV

### 🔐 Authentication
- Admin creates teacher accounts → credentials auto-emailed
- First-login detection with password change prompt
- Change password from Profile panel
- Forgot password → reset token → set new password

### 🎙️ Voice + Text (everywhere)
- Every form field has a 🎙 voice button
- Timetable editor: `Ctrl+K` or 🎙 button
- Voice commands: `"Add Maths on Monday at 1"`, `"Clear Wednesday at 3"`, `"Check clashes"`, `"Auto-fill"`
- Admin Voice Command Center for dashboard actions
- Voice login (username + password by speech)
- Core NLP parsing with spaCy

### 📊 Timetable Management
- Click cell to add/edit/clear
- Bulk add: `MON, 1, Subject, Teacher`
- Auto-fill (clash-free, assigned teachers' subjects)
- Smart generation: N sections, clash-free algorithm
- Free slot finder
- Audit log with restore (full snapshot history)
- Publish/Draft toggle

### 📄 Export
- **PDF** — Professional landscape format with colored headers
- **Image (PNG)** — High-quality raster via Pillow


### 📧 Email & Notifications
- Welcome email with credentials when teacher added
- Password reset token via email
- Daily schedule reminders (auto at 7:30 AM via APScheduler)
- Weekly summary for admins (Monday 8:00 AM)
- In-app notification center with unread badge

### 🌗 UI
- Dark mode (default) / Light mode toggle, persistent
- Responsive design
- Profile panel with edit + password change

---

## 🚀 Quick Start

```bash
chmod +x run.sh
./run.sh
```

Open **http://localhost:5000**

Install the required spaCy model before starting:

```bash
python -m spacy download en_core_web_sm
```

**Demo credentials:**
- Admin: `admin` / `Admin@SchediQ2026`
- Teachers: `divya` / `Teach@SchediQ2026` (and others)

---

## ⚙️ Email Configuration

Copy `.env.example` to `.env` and fill in your SMTP credentials:

```
SECRET_KEY=change_this_to_a_long_random_secret
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=your_email@gmail.com
MAIL_PASSWORD=your_app_password
```

**Gmail**: Enable 2FA → Create App Password → use as `MAIL_PASSWORD`.

---

## 🗄️ Database

SQLite by default (`schediq.db`, auto-created). Switch to PostgreSQL:

```
DATABASE_URL=postgresql://user:pass@localhost/schediq
```

---

## 📁 Project Structure

```
SchediQ/
├── app.py                  # Flask backend — all routes, models, NLP
├── requirements.txt
├── run.sh                  # One-click startup
├── .env.example
├── README.md
├── templates/
│   └── index.html          # Single-page app
└── static/
    ├── css/style.css
    └── js/app.js
```

---

## 🔌 API Reference (v2 additions)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/timetables/:id/history` | Paginated audit log |
| POST | `/api/timetables/:id/history/:eid/restore` | Restore snapshot |
| POST | `/api/timetables/:id/autofill` | Smart clash-free auto-fill |
| POST | `/api/timetables/:id/clone` | Duplicate timetable |
| GET  | `/api/timetables/:id/clashes` | Internal clash scan |
| GET  | `/api/clashes/cross` | Cross-timetable clash scan |
| POST | `/api/timetables/:id/substitute` | Find substitute teachers |
| GET  | `/api/workload/summary` | All teachers workload |
| GET  | `/api/teachers/:id/workload` | Single teacher workload |
| GET  | `/api/announcements` | List announcements |
| POST | `/api/announcements` | Post announcement |
| DELETE | `/api/announcements/:id` | Delete announcement |
| GET  | `/api/leaves` | List leave requests |
| POST | `/api/leaves` | Apply for leave |
| POST | `/api/leaves/:id/approve` | Approve leave |
| DELETE | `/api/leaves/:id` | Delete leave request |
| GET  | `/api/activity` | Activity log (admin) |
| GET  | `/api/timetables/:id/export/csv` | CSV export |

---

*SchediQ v2 — Built with Flask · SQLAlchemy · spaCy · ReportLab · Pillow · APScheduler · Web Speech API*
