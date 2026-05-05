from flask import Flask, render_template, request, jsonify, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import os, io, json, secrets, string
import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import spacy
from xml.sax.saxutils import escape

# ── APScheduler ──────────────────────────────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False

# ── NLP (spaCy) — core requirement ───────────────────────────
try:
    nlp = spacy.load("en_core_web_sm")
except OSError as exc:
    raise RuntimeError(
        "spaCy model 'en_core_web_sm' is required. "
        "Install it with: python -m spacy download en_core_web_sm"
    ) from exc

NLP_AVAILABLE = True

def env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def configure_logging(flask_app):
    log_level_name = os.environ.get("APP_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    flask_app.logger.setLevel(log_level)
    return flask_app.logger

load_dotenv()

app = Flask(__name__)
logger = configure_logging(app)
app.secret_key = os.environ.get("SECRET_KEY", "schediq_v2_secret_change_in_prod")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///schediq.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = env_flag("SESSION_COOKIE_SECURE", False)
app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=env_int("SESSION_LIFETIME_HOURS", 12))

app.config["MAIL_SERVER"]         = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"]           = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USE_TLS"]        = env_flag("MAIL_USE_TLS", True)
app.config["MAIL_USE_SSL"]        = env_flag("MAIL_USE_SSL", False)
app.config["MAIL_USERNAME"]       = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"]       = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@schediq.edu")

db   = SQLAlchemy(app)
mail = Mail(app)

if app.secret_key == "schediq_v2_secret_change_in_prod":
    logger.warning("Using the default SECRET_KEY. Set SECRET_KEY in the environment for safer deployments.")
if app.config["SESSION_COOKIE_SECURE"]:
    logger.info("Secure session cookies enabled.")
else:
    logger.info("SESSION_COOKIE_SECURE is off. Enable it when serving over HTTPS.")

# ═════════════════════════════════════════════
# MODELS
# ═════════════════════════════════════════════

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    name          = db.Column(db.String(120), nullable=False)
    role          = db.Column(db.String(20), default="teacher")
    department    = db.Column(db.String(100), default="")
    phone         = db.Column(db.String(20), default="")
    first_login   = db.Column(db.Boolean, default=True)
    reset_token   = db.Column(db.String(64), nullable=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    timetables    = db.relationship("Timetable", backref="creator", lazy=True, foreign_keys="Timetable.creator_id")
    notifications = db.relationship("Notification", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "email": self.email,
                "name": self.name, "role": self.role, "department": self.department,
                "phone": self.phone, "first_login": self.first_login,
                "created_at": self.created_at.strftime("%d %b %Y")}


class Department(db.Model):
    __tablename__ = "departments"
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), unique=True, nullable=False)
    code     = db.Column(db.String(20), nullable=False)
    sections = db.Column(db.String(100), default="")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "code": self.code, "sections": self.sections}


class Teacher(db.Model):
    __tablename__ = "teachers"
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True)
    name         = db.Column(db.String(120), nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False)
    phone        = db.Column(db.String(20), default="")
    dept         = db.Column(db.String(100), default="")
    subjects     = db.Column(db.Text, default="")
    max_periods  = db.Column(db.Integer, default=6)   # 🆕 max periods per day
    user         = db.relationship("User", backref=db.backref("teacher_profile", uselist=False))

    def to_dict(self):
        return {"id": self.id, "user_id": self.user_id, "name": self.name,
                "email": self.email, "phone": self.phone, "dept": self.dept,
                "subjects": self.subjects, "max_periods": self.max_periods,
                "username": self.user.username if self.user else ""}


timetable_teachers = db.Table("timetable_teachers",
    db.Column("timetable_id", db.Integer, db.ForeignKey("timetables.id")),
    db.Column("teacher_id",   db.Integer, db.ForeignKey("teachers.id"))
)


class Timetable(db.Model):
    __tablename__ = "timetables"
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    department    = db.Column(db.String(100), default="")
    room          = db.Column(db.String(50), default="")
    year_sem      = db.Column(db.String(80), default="")
    academic_year = db.Column(db.String(20), default="")
    wef_date      = db.Column(db.String(20), default="")
    cells_json    = db.Column(db.Text, default="{}")
    creator_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_published  = db.Column(db.Boolean, default=True)   # 🆕 draft/publish toggle
    assigned_teachers = db.relationship("Teacher", secondary=timetable_teachers, lazy="subquery",
                                        backref=db.backref("timetables", lazy=True))

    def cells(self):
        try:
            return json.loads(self.cells_json or "{}")
        except (TypeError, json.JSONDecodeError):
            logger.warning("Timetable %s has invalid cells_json; returning empty cells.", self.id)
            return {}

    def to_dict(self, include_cells=False):
        d = {"id": self.id, "name": self.name, "department": self.department,
             "room": self.room, "year_sem": self.year_sem,
             "academic_year": self.academic_year, "wef_date": self.wef_date,
             "created_at": self.created_at.strftime("%d %b %Y"),
             "updated_at": self.updated_at.strftime("%d %b %Y %H:%M"),
             "is_published": self.is_published,
             "assigned": [t.id for t in self.assigned_teachers]}
        if include_cells:
            d["cells"] = self.cells()
        return d


class Notification(db.Model):
    __tablename__ = "notifications"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    message    = db.Column(db.Text, nullable=False)
    notif_type = db.Column(db.String(20), default="info")
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {"id": self.id, "message": self.message, "type": self.notif_type,
                "read": self.is_read, "time": self.created_at.strftime("%d %b %Y %H:%M")}


class EmailLog(db.Model):
    __tablename__ = "email_log"
    id         = db.Column(db.Integer, primary_key=True)
    recipient  = db.Column(db.String(255), nullable=False)
    subject    = db.Column(db.String(255), nullable=False)
    mail_type  = db.Column(db.String(40), default="general")
    status     = db.Column(db.String(20), nullable=False)  # sent | failed | skipped
    detail     = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "recipient": self.recipient,
            "subject": self.subject,
            "mail_type": self.mail_type,
            "status": self.status,
            "detail": self.detail,
            "time": self.created_at.strftime("%d %b %Y %H:%M"),
        }


class TimetableHistory(db.Model):
    """✅ GAP FIX 1 — Audit log for every timetable change."""
    __tablename__ = "timetable_history"
    id           = db.Column(db.Integer, primary_key=True)
    timetable_id = db.Column(db.Integer, db.ForeignKey("timetables.id", ondelete="CASCADE"))
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"))
    action       = db.Column(db.String(30), nullable=False)
    detail       = db.Column(db.Text, default="")
    snapshot     = db.Column(db.Text, default="{}")
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    timetable    = db.relationship("Timetable", backref=db.backref("history", lazy=True, cascade="all, delete-orphan"))
    user         = db.relationship("User")

    def to_dict(self):
        u = self.user
        return {"id": self.id, "timetable_id": self.timetable_id,
                "action": self.action, "detail": self.detail,
                "user": u.name if u else "System", "role": u.role if u else "",
                "time": self.created_at.strftime("%d %b %Y %H:%M"),
                "timestamp": self.created_at.isoformat()}


class Announcement(db.Model):
    """🆕 Admin posts announcements visible to all or specific dept."""
    __tablename__ = "announcements"
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    body        = db.Column(db.Text, nullable=False)
    dept_filter = db.Column(db.String(100), default="")   # blank = all
    priority    = db.Column(db.String(10), default="normal")  # normal | urgent
    author_id   = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    author      = db.relationship("User")

    def to_dict(self):
        return {"id": self.id, "title": self.title, "body": self.body,
                "dept_filter": self.dept_filter, "priority": self.priority,
                "author": self.author.name if self.author else "Admin",
                "time": self.created_at.strftime("%d %b %Y %H:%M")}


class TeacherLeave(db.Model):
    """🆕 Teacher marks themselves absent / on leave for a date."""
    __tablename__ = "teacher_leaves"
    id          = db.Column(db.Integer, primary_key=True)
    teacher_id  = db.Column(db.Integer, db.ForeignKey("teachers.id"))
    leave_date  = db.Column(db.String(12), nullable=False)   # YYYY-MM-DD
    reason      = db.Column(db.String(200), default="")
    approved    = db.Column(db.Boolean, default=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    teacher     = db.relationship("Teacher")

    def to_dict(self):
        return {"id": self.id, "teacher_id": self.teacher_id,
                "teacher_name": self.teacher.name if self.teacher else "",
                "leave_date": self.leave_date, "reason": self.reason,
                "approved": self.approved,
                "time": self.created_at.strftime("%d %b %Y")}


class ActivityLog(db.Model):
    """🆕 Tracks key admin/system events (logins, deletes, etc.)."""
    __tablename__ = "activity_log"
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"))
    action     = db.Column(db.String(80), nullable=False)
    detail     = db.Column(db.Text, default="")
    ip         = db.Column(db.String(45), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user       = db.relationship("User")

    def to_dict(self):
        return {"id": self.id, "user": self.user.name if self.user else "?",
                "action": self.action, "detail": self.detail,
                "ip": self.ip, "time": self.created_at.strftime("%d %b %Y %H:%M")}


# ═════════════════════════════════════════════
# CONSTANTS
# ═════════════════════════════════════════════

DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT"]

TIME_SLOTS = [
    {"id": "t1", "label": "9:40AM-10:40AM"},
    {"id": "t2", "label": "10:40AM-11:40AM"},
    {"id": "t3", "label": "11:40AM-12:40PM"},
    {"id": "t4", "label": "12:40PM-1:20PM", "isLunch": True},
    {"id": "t5", "label": "1:20PM-2:20PM"},
    {"id": "t6", "label": "2:20PM-3:20PM"},
    {"id": "t7", "label": "3:20PM-4:20PM"},
]

# ═════════════════════════════════════════════
# DECORATORS
# ═════════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "msg": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "msg": "Not authenticated"}), 401
        u = User.query.get(session["user_id"])
        if not u or u.role != "admin":
            return jsonify({"ok": False, "msg": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def current_user():
    return User.query.get(session.get("user_id"))

def gen_password(length=12):
    special = "!@#$%^&*"
    base_chars = string.ascii_letters + string.digits + special
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(special),
    ]
    password.extend(secrets.choice(base_chars) for _ in range(max(0, length - 4)))
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)

# ═════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════

def create_notification(user_id, message, notif_type="info"):
    n = Notification(user_id=user_id, message=message, notif_type=notif_type)
    db.session.add(n)
    db.session.commit()
    user = User.query.get(user_id)
    if user and user.email:
        send_notification_email(user.email, user.name or user.username, message, notif_type)


def format_slot_key(key):
    if not key or "|" not in key:
        return key
    day, slot_id = key.split("|", 1)
    slot_idx = next((idx for idx, slot in enumerate(TIME_SLOTS, start=1) if slot["id"] == slot_id), None)
    return f"{day} period {slot_idx}" if slot_idx else key


def notify_timetable_change(tt, message, notif_type="timetable_change"):
    notified = set()
    for teacher in tt.assigned_teachers:
        if teacher.user_id and teacher.user_id not in notified:
            create_notification(teacher.user_id, message, notif_type)
            notified.add(teacher.user_id)

def log_history(timetable_id, action, detail, snapshot_cells=None):
    """Record a timetable change. Must be called before db.session.commit()."""
    uid  = session.get("user_id")
    snap = json.dumps(snapshot_cells) if snapshot_cells is not None else "{}"
    db.session.add(TimetableHistory(
        timetable_id=timetable_id, user_id=uid,
        action=action, detail=detail, snapshot=snap))

def log_activity(action, detail=""):
    """Record an admin activity event."""
    uid = session.get("user_id")
    ip  = request.remote_addr or ""
    db.session.add(ActivityLog(user_id=uid, action=action, detail=detail, ip=ip))
    db.session.commit()


def mail_is_configured():
    return bool(app.config.get("MAIL_USERNAME") and app.config.get("MAIL_PASSWORD"))


def log_email_attempt(recipient, subject, mail_type, status, detail=""):
    try:
        db.session.add(EmailLog(
            recipient=recipient,
            subject=subject,
            mail_type=mail_type,
            status=status,
            detail=detail[:2000] if detail else "",
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("Email log error: %s", e)


def send_notification_email(user_email, user_name, message, notif_type="info"):
    subject_map = {
        "welcome": "SchediQ Welcome Notification",
        "announcement": "SchediQ Announcement",
        "broadcast": "SchediQ Broadcast Notification",
        "daily": "SchediQ Daily Notification",
        "info": "SchediQ Notification",
    }
    subject = subject_map.get(notif_type, "SchediQ Notification")
    if not mail_is_configured():
        detail = "MAIL_USERNAME or MAIL_PASSWORD is not configured."
        logger.warning("Notification email skipped: %s", detail)
        log_email_attempt(user_email, subject, "notification", "skipped", detail)
        return False
    try:
        msg = Message(
            subject=subject,
            recipients=[user_email],
            html=f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
              <div style="background:#1e3a5f;padding:20px;text-align:center">
                <h2 style="color:white;margin:0">SchediQ Notification</h2>
              </div>
              <div style="padding:24px">
                <p>Hello {user_name},</p>
                <p style="font-size:15px;line-height:1.6">{message}</p>
                <p style="color:#64748b;font-size:12px;margin-top:20px">Type: {notif_type}</p>
              </div>
            </div>""",
        )
        mail.send(msg)
        log_email_attempt(user_email, subject, "notification", "sent", f"Type: {notif_type}")
        return True
    except Exception as e:
        logger.exception("Notification email error: %s", e)
        log_email_attempt(user_email, subject, "notification", "failed", str(e))
        return False


APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")


def local_now():
    return datetime.now(ZoneInfo(APP_TIMEZONE))


def local_today():
    return local_now().date()


def load_export_fonts(ImageFont):
    font_candidates = [
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ),
        (
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ),
    ]
    for bold_path, regular_path in font_candidates:
        try:
            return (
                ImageFont.truetype(bold_path, 18),
                ImageFont.truetype(bold_path, 10),
                ImageFont.truetype(regular_path, 9),
                ImageFont.truetype(regular_path, 8),
            )
        except OSError:
            continue
    logger.warning("Falling back to default Pillow fonts for timetable image export.")
    fallback = ImageFont.load_default()
    return fallback, fallback, fallback, fallback


def validate_password_strength(password, username="", email="", name=""):
    password = password or ""
    lowered = password.lower()
    forbidden_bits = {
        "password", "admin", "teacher", "schediq", "123456", "qwerty",
        (username or "").strip().lower(),
        ((email or "").split("@")[0] if email else "").strip().lower(),
    }
    forbidden_bits.update(part.lower() for part in (name or "").split() if len(part) >= 3)
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not any(ch.isupper() for ch in password):
        return "Password must include at least one uppercase letter"
    if not any(ch.islower() for ch in password):
        return "Password must include at least one lowercase letter"
    if not any(ch.isdigit() for ch in password):
        return "Password must include at least one number"
    if not any(not ch.isalnum() for ch in password):
        return "Password must include at least one special character"
    for item in forbidden_bits:
        if item and len(item) >= 3 and item in lowered:
            return "Password is too easy to guess. Avoid names, usernames, and common words."
    return None


def user_can_access_timetable(user, tt):
    if not user or not tt:
        return False
    if user.role == "admin":
        return True
    teacher = Teacher.query.filter_by(user_id=user.id).first()
    return bool(teacher and tt in teacher.timetables)


def resolve_chat_timetable(user, timetable_id=None):
    if timetable_id:
        tt = Timetable.query.get(timetable_id)
        if not tt:
            return None, "Timetable not found."
        if not user_can_access_timetable(user, tt):
            return None, "You do not have access to that timetable."
        return tt, None
    if user.role == "admin":
        tt = Timetable.query.order_by(Timetable.updated_at.desc()).first()
        return tt, None if tt else "No timetable is available yet."
    teacher = Teacher.query.filter_by(user_id=user.id).first()
    if not teacher:
        return None, "No teacher profile is linked to this account."
    tt = next((item for item in teacher.timetables if item.is_published), None)
    if not tt and teacher.timetables:
        tt = teacher.timetables[0]
    return (tt, None) if tt else (None, "No assigned timetable is available.")


def detect_day_from_text(text_lower):
    day_words = {
        "monday": "MON", "mon": "MON",
        "tuesday": "TUE", "tue": "TUE", "tues": "TUE",
        "wednesday": "WED", "wed": "WED",
        "thursday": "THU", "thu": "THU", "thurs": "THU",
        "friday": "FRI", "fri": "FRI",
        "saturday": "SAT", "sat": "SAT",
    }
    if "today" in text_lower:
        wd = local_today().weekday()
        return DAYS[wd] if wd < len(DAYS) else None
    for word, code in day_words.items():
        if word in text_lower:
            return code
    return None


def detect_slot_from_text(text_lower):
    import re
    if "lunch" in text_lower:
        return 4
    match = re.search(r"(?:slot|period|class)\s*(\d+)", text_lower)
    if match:
        return int(match.group(1))
    ordinals = {
        "first": 1, "second": 2, "third": 3, "fourth": 4,
        "fifth": 5, "sixth": 6, "seventh": 7,
        "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
        "5th": 5, "6th": 6, "7th": 7,
    }
    for word, num in ordinals.items():
        if word in text_lower:
            return num
    return None


def format_chat_cell(cell, slot_label):
    if not cell or not cell.get("subject"):
        return f"{slot_label}: Free"
    teacher = cell.get("teacher", "").strip()
    suffix = f" by {teacher}" if teacher else ""
    return f"{slot_label}: {cell['subject']}{suffix}"

# ═════════════════════════════════════════════
# EMAIL HELPERS
# ═════════════════════════════════════════════

def send_credentials_email(teacher_email, teacher_name, username, password):
    subject = "Your SchediQ Login Credentials"
    if not mail_is_configured():
        detail = "MAIL_USERNAME or MAIL_PASSWORD is not configured."
        logger.warning("Credentials email skipped: %s", detail)
        log_email_attempt(teacher_email, subject, "credentials", "skipped", detail)
        return False
    try:
        msg = Message(subject=subject, recipients=[teacher_email],
            html=f"""
            <div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
              <div style="background:#1e3a5f;padding:24px;text-align:center">
                <h1 style="color:white;margin:0;font-size:24px">SchediQ</h1>
                <p style="color:#93c5fd;margin:8px 0 0">Institute Timetable Management</p>
              </div>
              <div style="padding:32px">
                <h2 style="color:#1e293b">Welcome, {teacher_name}! 👋</h2>
                <table style="width:100%;border-collapse:collapse;margin:20px 0">
                  <tr><td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;font-weight:bold;width:120px">Username</td>
                      <td style="padding:10px;border:1px solid #e2e8f0;font-family:monospace;background:#fff">{username}</td></tr>
                  <tr><td style="padding:10px;background:#f8fafc;border:1px solid #e2e8f0;font-weight:bold">Password</td>
                      <td style="padding:10px;border:1px solid #e2e8f0;font-family:monospace;background:#fff">{password}</td></tr>
                </table>
                <p style="color:#ef4444;font-size:13px">⚠️ Please change your password immediately after first login.</p>
              </div>
            </div>""")
        mail.send(msg)
        log_email_attempt(teacher_email, subject, "credentials", "sent", f"Teacher: {teacher_name}")
        return True
    except Exception as e:
        logger.exception("Credentials email error: %s", e)
        log_email_attempt(teacher_email, subject, "credentials", "failed", str(e))
        return False

def send_reset_email(user_email, user_name, token):
    subject = "SchediQ Reset Password"
    if not mail_is_configured():
        detail = "MAIL_USERNAME or MAIL_PASSWORD is not configured."
        logger.warning("Reset email skipped: %s", detail)
        log_email_attempt(user_email, subject, "reset", "skipped", detail)
        return False
    try:
        msg = Message(subject="SchediQ — Password Reset", recipients=[user_email],
            html=f"""<div style="font-family:Arial,sans-serif;max-width:500px;margin:auto">
              <h2>Password Reset Request</h2><p>Hi {user_name}, your reset token is:</p>
              <div style="background:#f1f5f9;padding:16px;border-radius:8px;font-family:monospace;font-size:20px;text-align:center;letter-spacing:4px">{token}</div>
              <p style="color:#64748b;font-size:13px">Valid for one use only.</p></div>""")
        subject = msg.subject
        mail.send(msg)
        log_email_attempt(user_email, subject, "reset", "sent", f"User: {user_name}")
        return True
    except Exception as e:
        logger.exception("Reset email error: %s", e)
        log_email_attempt(user_email, subject, "reset", "failed", str(e))
        return False

def send_daily_reminder_email(teacher_email, teacher_name, today_str, classes_info):
    subject = f"SchediQ Daily Schedule — {today_str}"
    if not mail_is_configured():
        detail = "MAIL_USERNAME or MAIL_PASSWORD is not configured."
        logger.warning("Daily reminder skipped: %s", detail)
        log_email_attempt(teacher_email, subject, "daily_reminder", "skipped", detail)
        return False
    try:
        if classes_info:
            rows = "".join(f"<tr><td style='padding:8px;border:1px solid #e2e8f0'>{c['time']}</td>"
                           f"<td style='padding:8px;border:1px solid #e2e8f0'>{c['subject']}</td>"
                           f"<td style='padding:8px;border:1px solid #e2e8f0'>{c['timetable']}</td></tr>"
                           for c in classes_info)
            body = f"""<h3 style='color:#1e3a5f'>📅 Your Classes Today ({today_str})</h3>
            <table style='border-collapse:collapse;width:100%'>
              <tr style='background:#1e3a5f;color:white'><th style='padding:8px'>Time</th><th style='padding:8px'>Subject</th><th style='padding:8px'>Timetable</th></tr>
              {rows}</table>"""
        else:
            body = f"<h3 style='color:#1e3a5f'>📭 No Classes Today ({today_str})</h3><p>Enjoy your day!</p>"
        msg = Message(subject=f"SchediQ Daily Schedule — {today_str}", recipients=[teacher_email],
            html=f"""<div style="font-family:Arial,sans-serif;max-width:500px;margin:auto;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden">
              <div style="background:#1e3a5f;padding:20px;text-align:center"><h2 style="color:white;margin:0">SchediQ Daily Reminder</h2></div>
              <div style="padding:24px"><p>Hello {teacher_name},</p>{body}
              <p style="color:#64748b;font-size:12px;margin-top:24px">— SchediQ Team</p></div></div>""")
        subject = msg.subject
        mail.send(msg)
        log_email_attempt(teacher_email, subject, "daily_reminder", "sent", f"Classes: {len(classes_info)}")
        return True
    except Exception as e:
        logger.exception("Daily email error: %s", e)
        log_email_attempt(teacher_email, subject, "daily_reminder", "failed", str(e))
        return False

def notify_all_teachers_daily():
    if not mail_is_configured():
        logger.warning("Daily notification job skipped: MAIL_USERNAME or MAIL_PASSWORD is not configured.")
        return
    """Send daily class notifications to all teachers — called by APScheduler."""
    with app.app_context():
        now = local_now()
        today_idx = now.weekday()
        if today_idx >= 6: return
        today     = DAYS[today_idx]
        today_str = now.strftime("%A, %d %b %Y")
        for teacher in Teacher.query.all():
            classes_info = []
            for tt in teacher.timetables:
                if not tt.is_published: continue
                cells = tt.cells()
                for slot in TIME_SLOTS:
                    if slot.get("isLunch"): continue
                    key = f"{today}|{slot['id']}"
                    c   = cells.get(key)
                    if c and c.get("subject"):
                        classes_info.append({"time": slot["label"], "subject": c["subject"], "timetable": tt.name})
            msg = (f"Today ({today_str}): {', '.join(c['subject'] for c in classes_info)}"
                   if classes_info else f"No classes today ({today_str}).")
            if teacher.user_id:
                create_notification(teacher.user_id, msg, "daily")
            send_daily_reminder_email(teacher.email, teacher.name, today_str, classes_info)

def send_weekly_summary_email():
    if not mail_is_configured():
        detail = "MAIL_USERNAME or MAIL_PASSWORD is not configured."
        logger.warning("Weekly summary skipped: %s", detail)
        sender = app.config.get("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME") or "admin"
        log_email_attempt(sender, "SchediQ Weekly Summary", "weekly_summary", "skipped", detail)
        return
    """🆕 Weekly summary for admin: timetable stats, pending leaves."""
    with app.app_context():
        admins = User.query.filter_by(role="admin").all()
        tt_count  = Timetable.query.count()
        t_count   = Teacher.query.count()
        pending   = TeacherLeave.query.filter_by(approved=False).count()
        ann_count = Announcement.query.count()
        for admin in admins:
            subject = f"SchediQ Weekly Summary {local_now().strftime('%d %b %Y')}"
            try:
                msg = Message(subject=f"SchediQ Weekly Summary — {local_now().strftime('%d %b %Y')}",
                    recipients=[admin.email],
                    html=f"""<div style="font-family:Arial;max-width:500px;margin:auto">
                      <h2 style="color:#1e3a5f">📊 Weekly Admin Summary</h2>
                      <ul>
                        <li>Total Timetables: <strong>{tt_count}</strong></li>
                        <li>Total Teachers: <strong>{t_count}</strong></li>
                        <li>Pending Leave Requests: <strong>{pending}</strong></li>
                        <li>Announcements Posted: <strong>{ann_count}</strong></li>
                      </ul>
                      <p style="color:#64748b;font-size:12px">— SchediQ Auto-Report</p></div>""")
                subject = msg.subject
                mail.send(msg)
                log_email_attempt(admin.email, subject, "weekly_summary", "sent", "Admin weekly summary")
            except Exception as e:
                logger.exception("Weekly summary error for %s: %s", admin.email, e)
                log_email_attempt(admin.email, subject, "weekly_summary", "failed", str(e))

# ═════════════════════════════════════════════
# NLP VOICE PARSER
# ═════════════════════════════════════════════

DAY_MAP = {"monday":"MON","tuesday":"TUE","wednesday":"WED","thursday":"THU","friday":"FRI","saturday":"SAT",
           "mon":"MON","tue":"TUE","wed":"WED","thu":"THU","fri":"FRI","sat":"SAT"}
ORDINAL_MAP = {"first":1,"second":2,"third":3,"fourth":4,"fifth":5,"sixth":6,"seventh":7,
               "1st":1,"2nd":2,"3rd":3,"4th":4,"5th":5,"6th":6,"7th":7}

def parse_voice_nlp(text):
    import re
    tl = text.lower().strip()
    if any(w in tl for w in ["add","schedule","put","set","assign"]): intent = "add"
    elif any(w in tl for w in ["clear","remove","delete","erase"]):   intent = "clear"
    elif any(w in tl for w in ["show","view","what","display"]):       intent = "query"
    elif any(w in tl for w in ["generate","create","make","build"]):   intent = "generate"
    elif any(w in tl for w in ["broadcast","notify"]):                 intent = "broadcast"
    elif any(w in tl for w in ["free slot","available","empty slot"]): intent = "free_slot"
    elif any(w in tl for w in ["export","download","pdf","save"]):     intent = "export"
    elif any(w in tl for w in ["clash","check","conflict"]):           intent = "clash_check"
    elif any(w in tl for w in ["autofill","auto fill","fill empty"]):  intent = "autofill"
    else: intent = "add"
    day = next((code for word, code in DAY_MAP.items() if word in tl), None)
    slot = None
    sm = re.search(r'(?:slot|period|at|number)?\s*(\d+)', tl)
    if sm: slot = int(sm.group(1))
    else:
        for word, num in ORDINAL_MAP.items():
            if word in tl: slot = num; break
    subject = None
    if intent == "add":
        doc = nlp(text)
        for chunk in doc.noun_chunks:
            cl = chunk.text.lower()
            if not any(d in cl for d in DAY_MAP) and not any(w in cl for w in ["slot","period","class"]):
                if len(chunk.text.strip()) > 2: subject = chunk.text.strip(); break
    if not subject and intent == "add":
        m = re.search(r'(?:add|schedule|put|set)\s+(.+?)\s+(?:on|for|at|to)', tl)
        if m: subject = m.group(1).strip().title()
        else:
            m2 = re.search(r'(?:add|schedule|put|set)\s+(.+?)(?:\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|mon|tue|wed|thu|fri|sat))', tl)
            if m2: subject = m2.group(1).strip().title()
    teacher = None
    t_match = re.search(r'(?:teacher|by|taught by|with)\s+([A-Za-z\s]+)', text, re.IGNORECASE)
    if t_match: teacher = t_match.group(1).strip()
    return {"intent": intent, "day": day, "slot": slot, "subject": subject, "teacher": teacher, "raw": text}

# ═════════════════════════════════════════════
# FRONTEND
# ═════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    db_ok = True
    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        logger.exception("Health check database probe failed: %s", exc)
    return jsonify({
        "ok": db_ok,
        "app": "SchediQ",
        "time": local_now().isoformat(),
        "timezone": APP_TIMEZONE,
        "database": "ok" if db_ok else "error",
        "mail_configured": mail_is_configured(),
        "scheduler_available": SCHEDULER_AVAILABLE,
    }), (200 if db_ok else 500)

# ═════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d = request.json or {}
    identifier = d.get("username", "").strip()
    password   = d.get("password", "")
    user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
    if not user or not user.check_password(password):
        return jsonify({"ok": False, "msg": "Invalid credentials"})
    session["user_id"] = user.id
    session["role"]    = user.role
    log_activity("login", f"{user.username} logged in")
    return jsonify({"ok": True, "user": user.to_dict()})

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    d = request.json or {}
    name, email, username = d.get("name","").strip(), d.get("email","").strip(), d.get("username","").strip()
    password, role, dept  = d.get("password",""), d.get("role","teacher"), d.get("department","").strip()
    if not all([name, email, username, password]):
        return jsonify({"ok": False, "msg": "All fields required"})
    pw_error = validate_password_strength(password, username=username, email=email, name=name)
    if pw_error:
        return jsonify({"ok": False, "msg": pw_error})
    if User.query.filter_by(username=username).first():
        return jsonify({"ok": False, "msg": "Username already taken"})
    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "msg": "Email already registered"})
    user = User(name=name, email=email, username=username, role=role, department=dept, first_login=True)
    user.set_password(password)
    db.session.add(user); db.session.commit()
    return jsonify({"ok": True, "msg": "Account created successfully"})

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    if "user_id" in session:
        log_activity("logout")
    session.clear()
    return jsonify({"ok": True})

@app.route("/api/auth/me")
@login_required
def api_me():
    return jsonify({"ok": True, "user": current_user().to_dict()})

@app.route("/api/auth/change-password", methods=["POST"])
@login_required
def api_change_password():
    d = request.json or {}
    user = current_user()
    if not user.check_password(d.get("old_password","")):
        return jsonify({"ok": False, "msg": "Current password is incorrect"})
    new_pw = d.get("new_password","")
    pw_error = validate_password_strength(new_pw, username=user.username, email=user.email, name=user.name)
    if pw_error:
        return jsonify({"ok": False, "msg": pw_error})
    user.set_password(new_pw)
    user.first_login = False
    db.session.commit()
    return jsonify({"ok": True, "msg": "Password changed successfully"})

@app.route("/api/auth/forgot-password", methods=["POST"])
def api_forgot_password():
    email = (request.json or {}).get("email","").strip()
    user  = User.query.filter_by(email=email).first()
    if not user: return jsonify({"ok": False, "msg": "Email not found"})
    token = secrets.token_urlsafe(16)
    user.reset_token = token
    db.session.commit()
    sent = send_reset_email(email, user.name, token)
    return jsonify({"ok": True,
                    "msg": f"Reset token sent to {email}. {'(Email delivered)' if sent else '(Demo: token below)'}",
                    "demo_token": token})

@app.route("/api/auth/reset-password", methods=["POST"])
def api_reset_password():
    d  = request.json or {}
    user = User.query.filter_by(reset_token=d.get("token","").strip()).first()
    if not user: return jsonify({"ok": False, "msg": "Invalid or expired token"})
    new_pw = d.get("new_password","").strip()
    pw_error = validate_password_strength(new_pw, username=user.username, email=user.email, name=user.name)
    if pw_error:
        return jsonify({"ok": False, "msg": pw_error})
    user.set_password(new_pw)
    user.reset_token = None
    user.first_login = False
    db.session.commit()
    return jsonify({"ok": True, "msg": "Password reset successfully. Please login."})

@app.route("/api/profile/update", methods=["POST"])
@login_required
def api_update_profile():
    d = request.json or {}
    user = current_user()
    if "name" in d and d["name"].strip(): user.name = d["name"].strip()
    if "phone" in d: user.phone = d["phone"].strip()
    if "department" in d: user.department = d["department"].strip()
    if user.teacher_profile:
        if "name" in d: user.teacher_profile.name = user.name
        if "phone" in d: user.teacher_profile.phone = user.phone
        if "department" in d: user.teacher_profile.dept = user.department
    db.session.commit()
    return jsonify({"ok": True, "user": user.to_dict()})

@app.route("/api/profile", methods=["GET"])
@login_required
def api_profile():
    user    = current_user()
    teacher = Teacher.query.filter_by(user_id=user.id).first()
    tts = (Timetable.query.filter_by(creator_id=user.id).all()
           if user.role == "admin"
           else (teacher.timetables if teacher else []))
    return jsonify({"ok": True, "user": user.to_dict(),
                    "timetable_count": len(tts),
                    "teacher": teacher.to_dict() if teacher else None})

# ═════════════════════════════════════════════
# DEPARTMENTS
# ═════════════════════════════════════════════

@app.route("/api/departments", methods=["GET"])
@login_required
def api_get_departments():
    return jsonify({"ok": True, "departments": [d.to_dict() for d in Department.query.all()]})

@app.route("/api/departments", methods=["POST"])
@admin_required
def api_add_department():
    d = request.json or {}
    name, code = d.get("name","").strip(), d.get("code","").strip()
    if not name or not code: return jsonify({"ok": False, "msg": "Name and code required"})
    if Department.query.filter_by(name=name).first():
        return jsonify({"ok": False, "msg": "Department already exists"})
    dept = Department(name=name, code=code, sections=d.get("sections","").strip())
    db.session.add(dept); db.session.commit()
    return jsonify({"ok": True, "department": dept.to_dict()})

@app.route("/api/departments/<int:dept_id>", methods=["DELETE"])
@admin_required
def api_delete_department(dept_id):
    dept = Department.query.get_or_404(dept_id)
    db.session.delete(dept); db.session.commit()
    return jsonify({"ok": True})

# ═════════════════════════════════════════════
# TEACHERS
# ═════════════════════════════════════════════

@app.route("/api/teachers", methods=["GET"])
@login_required
def api_get_teachers():
    return jsonify({"ok": True, "teachers": [t.to_dict() for t in Teacher.query.all()]})

@app.route("/api/teachers", methods=["POST"])
@admin_required
def api_add_teacher():
    import re
    d = request.json or {}
    name, email  = d.get("name","").strip(), d.get("email","").strip()
    dept, phone  = d.get("dept","").strip(), d.get("phone","").strip()
    subjects     = d.get("subjects","").strip()
    max_periods  = int(d.get("max_periods", 6))
    password     = d.get("password","").strip() or gen_password()
    if not name or not email: return jsonify({"ok": False, "msg": "Name and email required"})
    if phone and not re.fullmatch(r"\d{10}", phone):
        return jsonify({"ok": False, "msg": "Phone number must contain exactly 10 digits"})
    if Teacher.query.filter_by(email=email).first():
        return jsonify({"ok": False, "msg": "Teacher with this email already exists"})
    base_uname = email.split("@")[0].replace(".","_")
    username, suffix = base_uname, 1
    while User.query.filter_by(username=username).first():
        username = f"{base_uname}_{suffix}"; suffix += 1
    pw_error = validate_password_strength(password, username=username, email=email, name=name)
    if pw_error:
        return jsonify({"ok": False, "msg": pw_error})
    user = User(name=name, email=email, username=username, role="teacher",
                department=dept, phone=phone, first_login=True)
    user.set_password(password)
    db.session.add(user); db.session.flush()
    teacher = Teacher(user_id=user.id, name=name, email=email, phone=phone,
                      dept=dept, subjects=subjects, max_periods=max_periods)
    db.session.add(teacher); db.session.commit()
    email_sent = send_credentials_email(email, name, username, password)
    create_notification(user.id, f"Welcome to SchediQ! Username: {username}. Change your password.", "welcome")
    log_activity("add_teacher", f"Added teacher {name} ({email})")
    return jsonify({"ok": True, "teacher": teacher.to_dict(),
                    "credentials": {"username": username, "password": password},
                    "email_sent": email_sent,
                    "msg": ("Teacher added and credentials email sent."
                            if email_sent else
                            "Teacher added, but email was not sent. Check MAIL settings.")})

@app.route("/api/teachers/<int:tid>", methods=["PUT"])
@admin_required
def api_update_teacher(tid):
    teacher = Teacher.query.get_or_404(tid)
    d = request.json or {}
    teacher.name        = d.get("name", teacher.name)
    teacher.phone       = d.get("phone", teacher.phone)
    teacher.dept        = d.get("dept", teacher.dept)
    teacher.subjects    = d.get("subjects", teacher.subjects)
    teacher.max_periods = int(d.get("max_periods", teacher.max_periods))
    if teacher.user:
        teacher.user.name = teacher.name; teacher.user.phone = teacher.phone
        teacher.user.department = teacher.dept
    db.session.commit()
    return jsonify({"ok": True, "teacher": teacher.to_dict()})

@app.route("/api/teachers/<int:tid>", methods=["DELETE"])
@admin_required
def api_delete_teacher(tid):
    teacher = Teacher.query.get_or_404(tid)
    name = teacher.name
    if teacher.user: db.session.delete(teacher.user)
    db.session.delete(teacher); db.session.commit()
    log_activity("delete_teacher", f"Deleted teacher {name}")
    return jsonify({"ok": True})

# 🆕 Workload analytics per teacher
@app.route("/api/teachers/<int:tid>/workload", methods=["GET"])
@login_required
def api_teacher_workload(tid):
    teacher = Teacher.query.get_or_404(tid)
    workload = {}   # day → count of periods
    for tt in teacher.timetables:
        if not tt.is_published: continue
        cells = tt.cells()
        for key, c in cells.items():
            if c and c.get("teacher") == teacher.name and c.get("subject"):
                day = key.split("|")[0]
                workload[day] = workload.get(day, 0) + 1
    total = sum(workload.values())
    return jsonify({"ok": True, "teacher": teacher.name, "workload": workload,
                    "total_periods": total, "max_periods_per_day": teacher.max_periods,
                    "overloaded_days": [d for d, cnt in workload.items() if cnt > teacher.max_periods]})

# 🆕 All workloads summary
@app.route("/api/workload/summary", methods=["GET"])
@admin_required
def api_workload_summary():
    results = []
    for teacher in Teacher.query.all():
        workload = {}
        for tt in teacher.timetables:
            if not tt.is_published: continue
            for key, c in tt.cells().items():
                if c and c.get("teacher") == teacher.name and c.get("subject"):
                    day = key.split("|")[0]
                    workload[day] = workload.get(day, 0) + 1
        total = sum(workload.values())
        overloaded = [d for d, cnt in workload.items() if cnt > teacher.max_periods]
        results.append({"id": teacher.id, "name": teacher.name, "dept": teacher.dept,
                        "total": total, "workload": workload, "overloaded": overloaded,
                        "max_periods": teacher.max_periods})
    return jsonify({"ok": True, "summary": sorted(results, key=lambda x: -x["total"])})

# ═════════════════════════════════════════════
# TIMETABLES
# ═════════════════════════════════════════════

@app.route("/api/timetables", methods=["GET"])
@login_required
def api_get_timetables():
    user = current_user()
    if user.role == "admin":
        tts = Timetable.query.order_by(Timetable.updated_at.desc()).all()
    else:
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        tts = [tt for tt in (teacher.timetables if teacher else []) if tt.is_published]
    return jsonify({"ok": True, "timetables": [tt.to_dict() for tt in tts]})

@app.route("/api/timetables", methods=["POST"])
@admin_required
def api_create_timetable():
    d = request.json or {}
    name = d.get("name","").strip()
    if not name: return jsonify({"ok": False, "msg": "Name is required"})
    tt = Timetable(name=name, department=d.get("department",""),
                   room=d.get("room",""), year_sem=d.get("year_sem",""),
                   academic_year=d.get("academic_year",""), wef_date=d.get("wef_date",""),
                   cells_json="{}", creator_id=session["user_id"],
                   is_published=d.get("is_published", True))
    db.session.add(tt); db.session.commit()
    log_activity("create_timetable", f"Created timetable '{name}'")
    return jsonify({"ok": True, "timetable": tt.to_dict(include_cells=True)})

@app.route("/api/timetables/<int:tt_id>", methods=["GET"])
@login_required
def api_get_timetable(tt_id):
    tt   = Timetable.query.get_or_404(tt_id)
    user = current_user()
    if user.role != "admin":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher or tt not in teacher.timetables:
            return jsonify({"ok": False, "msg": "Access denied"}), 403
        # If not published, still allow access but note it
        if not tt.is_published:
            return jsonify({"ok": False, "msg": "This timetable has not been published yet"}), 403
    return jsonify({"ok": True, "timetable": tt.to_dict(include_cells=True)})

@app.route("/api/timetables/<int:tt_id>", methods=["PUT"])
@admin_required
def api_update_timetable(tt_id):
    tt = Timetable.query.get_or_404(tt_id)
    d  = request.json or {}
    changed = []
    for field in ["name","department","room","year_sem","academic_year","wef_date"]:
        if field in d:
            if getattr(tt, field) != d[field]: changed.append(field)
            setattr(tt, field, d[field])
    if "is_published" in d:
        was_published = tt.is_published
        tt.is_published = bool(d["is_published"])
        changed.append("publish_status")
        # Notify all assigned teachers when timetable is published
        if tt.is_published and not was_published:
            for t in tt.assigned_teachers:
                if t.user_id:
                    create_notification(
                        t.user_id,
                        f"📅 Timetable '{tt.name}' ({tt.department}) has been published — you can now view it.",
                        "assignment"
                    )
        elif was_published and not tt.is_published:
            notify_timetable_change(
                tt,
                f"🔕 Timetable '{tt.name}' has been moved to draft mode. It may be temporarily unavailable while updates are being made.",
                "timetable_change"
            )
    if "cells" in d:
        tt.cells_json = json.dumps(d["cells"])
        log_history(tt_id, "generate_applied",
                    f"Generated timetable applied ({len(d['cells'])} cells)", d["cells"])
        notify_timetable_change(
            tt,
            f"📋 Timetable '{tt.name}' was updated in bulk. Please review the latest schedule.",
            "timetable_change"
        )
    elif changed:
        log_history(tt_id, "settings", f"Settings updated: {', '.join(changed)}")
        notify_timetable_change(
            tt,
            f"✏️ Timetable '{tt.name}' settings were updated ({', '.join(changed)}). Check the latest details in SchediQ.",
            "timetable_change"
        )
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "timetable": tt.to_dict(include_cells=True)})

# 🆕 Duplicate/clone timetable
@app.route("/api/timetables/<int:tt_id>/clone", methods=["POST"])
@admin_required
def api_clone_timetable(tt_id):
    src  = Timetable.query.get_or_404(tt_id)
    d    = request.json or {}
    name = d.get("name", f"{src.name} (Copy)").strip()
    new_tt = Timetable(name=name, department=src.department, room=src.room,
                       year_sem=src.year_sem, academic_year=src.academic_year,
                       wef_date=src.wef_date, cells_json=src.cells_json,
                       creator_id=session["user_id"], is_published=False)
    db.session.add(new_tt); db.session.flush()
    # Copy assigned teachers
    for t in src.assigned_teachers:
        new_tt.assigned_teachers.append(t)
    log_history(new_tt.id, "settings", f"Cloned from timetable '{src.name}' (#{src.id})", src.cells())
    db.session.commit()
    log_activity("clone_timetable", f"Cloned '{src.name}' → '{name}'")
    return jsonify({"ok": True, "timetable": new_tt.to_dict(include_cells=True)})

@app.route("/api/timetables/<int:tt_id>/cells", methods=["POST"])
@admin_required
def api_set_cell(tt_id):
    tt = Timetable.query.get_or_404(tt_id)
    d  = request.json or {}
    key, subject, teacher, ctype = (d.get("key",""), d.get("subject","").strip(),
                                    d.get("teacher","").strip(), d.get("type","lecture"))
    cells = tt.cells()
    slot_label = format_slot_key(key)
    if subject:
        cells[key] = {"subject": subject, "teacher": teacher, "type": ctype}
        log_history(tt_id, "cell_set",
                    f"Set {key}: {subject}" + (f" ({teacher})" if teacher else ""), cells)
    elif key in cells:
        del cells[key]
        log_history(tt_id, "cell_clear", f"Cleared {key}", cells)
    tt.cells_json = json.dumps(cells)
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "cells": cells})

@app.route("/api/timetables/<int:tt_id>/cells/bulk", methods=["POST"])
@admin_required
def api_bulk_add(tt_id):
    tt = Timetable.query.get_or_404(tt_id)
    d  = request.json or {}
    entries, source = d.get("entries",[]), d.get("source","bulk")
    cells = tt.cells()
    for e in entries:
        key = e.get("key","")
        if key and e.get("subject"):
            cells[key] = {"subject": e["subject"], "teacher": e.get("teacher",""), "type": e.get("type","lecture")}
    action = "autofill" if source == "autofill" else "bulk_add"
    detail = (f"Auto-filled {len(entries)} empty slots" if source == "autofill"
              else f"Bulk added {len(entries)} entries")
    log_history(tt_id, action, detail, cells)
    tt.cells_json = json.dumps(cells)
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "count": len(entries), "cells": cells})

@app.route("/api/timetables/<int:tt_id>/cells/clear", methods=["POST"])
@admin_required
def api_clear_cells(tt_id):
    tt = Timetable.query.get_or_404(tt_id)
    filled = len(tt.cells())
    log_history(tt_id, "clear_all", f"Cleared all {filled} cells", {})
    tt.cells_json = "{}"
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/timetables/<int:tt_id>", methods=["DELETE"])
@admin_required
def api_delete_timetable(tt_id):
    tt = Timetable.query.get_or_404(tt_id)
    name = tt.name
    db.session.delete(tt); db.session.commit()
    log_activity("delete_timetable", f"Deleted timetable '{name}'")
    return jsonify({"ok": True})

@app.route("/api/timetables/<int:tt_id>/assign", methods=["POST"])
@admin_required
def api_assign_teacher(tt_id):
    tt  = Timetable.query.get_or_404(tt_id)
    tid = (request.json or {}).get("teacher_id")
    t   = Teacher.query.get(tid)
    if not t: return jsonify({"ok": False, "msg": "Teacher not found"})
    if t not in tt.assigned_teachers:
        tt.assigned_teachers.append(t)
        db.session.commit()
        if t.user_id:
            if tt.is_published:
                # Timetable is live — tell teacher they can view it right now
                create_notification(
                    t.user_id,
                    f"📅 You have been assigned to timetable '{tt.name}' ({tt.department}). Log in to view your schedule.",
                    "assignment"
                )
            else:
                # Timetable is still draft
                create_notification(
                    t.user_id,
                    f"🔔 You have been assigned to timetable '{tt.name}' ({tt.department}). It will be visible once published.",
                    "assignment"
                )
    return jsonify({"ok": True, "assigned": [t.id for t in tt.assigned_teachers]})

@app.route("/api/timetables/<int:tt_id>/unassign", methods=["POST"])
@admin_required
def api_unassign_teacher(tt_id):
    tt  = Timetable.query.get_or_404(tt_id)
    tid = (request.json or {}).get("teacher_id")
    t   = Teacher.query.get(tid)
    if t and t in tt.assigned_teachers:
        tt.assigned_teachers.remove(t); db.session.commit()
    return jsonify({"ok": True})

# ═════════════════════════════════════════════
# HISTORY (GAP FIX 1)
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/history", methods=["GET"])
@admin_required
def api_get_history(tt_id):
    Timetable.query.get_or_404(tt_id)
    limit  = min(int(request.args.get("limit",50)), 200)
    offset = int(request.args.get("offset",0))
    entries = (TimetableHistory.query.filter_by(timetable_id=tt_id)
               .order_by(TimetableHistory.created_at.desc())
               .offset(offset).limit(limit).all())
    total = TimetableHistory.query.filter_by(timetable_id=tt_id).count()
    return jsonify({"ok": True, "history": [e.to_dict() for e in entries],
                    "total": total, "offset": offset, "limit": limit})

@app.route("/api/timetables/<int:tt_id>/history/<int:entry_id>/restore", methods=["POST"])
@admin_required
def api_restore_snapshot(tt_id, entry_id):
    entry = TimetableHistory.query.filter_by(id=entry_id, timetable_id=tt_id).first_or_404()
    try:
        snap = json.loads(entry.snapshot or "{}")
    except (TypeError, json.JSONDecodeError):
        return jsonify({"ok": False, "msg": "Snapshot data is corrupt"}), 400
    tt = Timetable.query.get_or_404(tt_id)
    log_history(tt_id, "settings",
                f"Restored snapshot from {entry.created_at.strftime('%d %b %Y %H:%M')} (entry #{entry_id})", snap)
    tt.cells_json = json.dumps(snap)
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "timetable": tt.to_dict(include_cells=True)})

# ═════════════════════════════════════════════
# SMART AUTO-FILL (GAP FIX 2)
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/autofill", methods=["POST"])
@admin_required
def api_autofill(tt_id):
    import random
    tt = Timetable.query.get_or_404(tt_id)
    d  = request.json or {}
    strategy = d.get("strategy", "round_robin")
    teachers = tt.assigned_teachers or Teacher.query.all()
    if not teachers: return jsonify({"ok": False, "msg": "No teachers assigned to this timetable"})
    pairs = []
    for t in teachers:
        for subj in [s.strip() for s in (t.subjects or "").split(",") if s.strip()]:
            pairs.append({"subject": subj, "teacher": t.name})
    if not pairs: return jsonify({"ok": False, "msg": "Assigned teachers have no subjects. Edit teachers first."})
    if strategy == "random": random.shuffle(pairs)
    cells     = tt.cells()
    non_lunch = [s for s in TIME_SLOTS if not s.get("isLunch")]
    slot_used : dict = {}
    for key, c in cells.items():
        if c and c.get("teacher"):
            slot_used.setdefault(key, set()).add(c["teacher"])
    entries, pi = [], 0
    for day in DAYS:
        for slot in non_lunch:
            key = f"{day}|{slot['id']}"
            if cells.get(key,{}).get("subject"): continue
            placed = False
            for attempt in range(len(pairs)):
                pair = pairs[(pi + attempt) % len(pairs)]
                if pair["teacher"] not in slot_used.get(key, set()):
                    entries.append({"key": key, "subject": pair["subject"],
                                    "teacher": pair["teacher"], "type": "lecture"})
                    slot_used.setdefault(key, set()).add(pair["teacher"])
                    pi += 1; placed = True; break
            if not placed:
                pair = pairs[pi % len(pairs)]
                entries.append({"key": key, "subject": pair["subject"],
                                "teacher": pair["teacher"], "type": "lecture"})
                pi += 1
    if not entries:
        return jsonify({"ok": True, "count": 0, "msg": "All slots already filled", "cells": cells})
    for e in entries:
        cells[e["key"]] = {"subject": e["subject"], "teacher": e["teacher"], "type": e["type"]}
    log_history(tt_id, "autofill",
                f"Auto-filled {len(entries)} empty slots (strategy: {strategy})", cells)
    tt.cells_json = json.dumps(cells)
    tt.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "count": len(entries), "cells": cells,
                    "msg": f"Auto-filled {len(entries)} slot(s) clash-free"})

# ═════════════════════════════════════════════
# 🆕 CLASH DETECTOR
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/clashes", methods=["GET"])
@login_required
def api_detect_clashes(tt_id):
    """Scan a single timetable for repeated teacher in same slot."""
    tt    = Timetable.query.get_or_404(tt_id)
    cells = tt.cells()
    clashes = []
    slot_teachers: dict = {}
    for key, c in cells.items():
        if c and c.get("teacher") and c.get("subject"):
            if c["teacher"] in slot_teachers.get(key, set()):
                clashes.append({"slot": key, "teacher": c["teacher"], "subject": c["subject"]})
            slot_teachers.setdefault(key, set()).add(c["teacher"])

    # Compute free teachers per slot for suggestion (across all timetables)
    all_busy = {}
    for tt_all in Timetable.query.all():
        for key, c in tt_all.cells().items():
            if c and c.get("teacher") and c.get("subject"):
                all_busy.setdefault(key, set()).add(c["teacher"])

    all_teachers = [t.name for t in Teacher.query.all()]
    clash_with_suggestions = []
    for c in clashes:
        slot_key = c["slot"]
        free_teachers = [t for t in all_teachers if t not in all_busy.get(slot_key, set())]
        clash_with_suggestions.append({
            "slot": slot_key,
            "teacher": c["teacher"],
            "subject": c["subject"],
            "suggested_teachers": free_teachers[:5],
            "suggested_note": "Try assigning one of these free teachers for this slot, or clear the slot to resolve clash."
        })

    return jsonify({"ok": True, "clashes": clash_with_suggestions, "clash_count": len(clash_with_suggestions)})

@app.route("/api/clashes/cross", methods=["GET"])
@admin_required
def api_cross_timetable_clashes():
    """🆕 Find teacher double-booked across DIFFERENT timetables in same slot."""
    slot_map: dict = {}   # (slot_key, teacher) → list of timetable names
    for tt in Timetable.query.all():
        for key, c in tt.cells().items():
            if c and c.get("teacher") and c.get("subject"):
                k = (key, c["teacher"])
                slot_map.setdefault(k, []).append(tt.name)
    clashes = []
    for (slot_key, teacher), tts in slot_map.items():
        if len(tts) > 1:
            clashes.append({"slot": slot_key, "teacher": teacher, "timetables": tts})
    return jsonify({"ok": True, "clashes": clashes, "count": len(clashes)})

# ═════════════════════════════════════════════
# 🆕 SUBSTITUTE TEACHER
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/substitute", methods=["POST"])
@admin_required
def api_find_substitute(tt_id):
    """Given an absent teacher, find available teachers for each of their slots today."""
    tt      = Timetable.query.get_or_404(tt_id)
    d       = request.json or {}
    absent  = d.get("teacher_name","").strip()
    current_weekday = local_now().weekday()
    day     = d.get("day", DAYS[current_weekday] if current_weekday < 6 else "MON")
    if not absent: return jsonify({"ok": False, "msg": "teacher_name required"})
    cells     = tt.cells()
    all_tts   = Timetable.query.all()
    # Find which slots the absent teacher has today
    affected_slots = []
    for slot in TIME_SLOTS:
        if slot.get("isLunch"): continue
        key = f"{day}|{slot['id']}"
        c   = cells.get(key,{})
        if c.get("teacher") == absent and c.get("subject"):
            affected_slots.append({"slot": key, "time": slot["label"], "subject": c["subject"]})
    suggestions = []
    all_teachers = [t.name for t in Teacher.query.all() if t.name != absent]
    for s in affected_slots:
        busy_here = set()
        for other_tt in all_tts:
            oc = other_tt.cells().get(s["slot"],{})
            if oc and oc.get("teacher"): busy_here.add(oc["teacher"])
        available = [t for t in all_teachers if t not in busy_here]
        suggestions.append({"slot": s["slot"], "time": s["time"],
                             "subject": s["subject"], "available": available})
    return jsonify({"ok": True, "absent": absent, "day": day, "suggestions": suggestions})

# ═════════════════════════════════════════════
# 🆕 ANNOUNCEMENTS
# ═════════════════════════════════════════════

@app.route("/api/announcements", methods=["GET"])
@login_required
def api_get_announcements():
    user    = current_user()
    teacher = Teacher.query.filter_by(user_id=user.id).first() if user.role == "teacher" else None
    dept    = teacher.dept if teacher else ""
    anns    = Announcement.query.order_by(Announcement.created_at.desc()).limit(30).all()
    visible = [a for a in anns if not a.dept_filter or a.dept_filter == dept or user.role == "admin"]
    return jsonify({"ok": True, "announcements": [a.to_dict() for a in visible]})

@app.route("/api/announcements", methods=["POST"])
@admin_required
def api_post_announcement():
    d = request.json or {}
    title = d.get("title","").strip()
    body  = d.get("body","").strip()
    if not title or not body: return jsonify({"ok": False, "msg": "Title and body required"})
    ann = Announcement(title=title, body=body,
                       dept_filter=d.get("dept_filter","").strip(),
                       priority=d.get("priority","normal"),
                       author_id=session["user_id"])
    db.session.add(ann); db.session.commit()
    # Notify all teachers
    for u in User.query.filter_by(role="teacher").all():
        create_notification(u.id, f"📢 {title}", "announcement")
    log_activity("announcement", f"Posted: {title}")
    return jsonify({"ok": True, "announcement": ann.to_dict()})

@app.route("/api/announcements/<int:ann_id>", methods=["DELETE"])
@admin_required
def api_delete_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    db.session.delete(ann); db.session.commit()
    return jsonify({"ok": True})

# ═════════════════════════════════════════════
# 🆕 TEACHER LEAVE / AVAILABILITY
# ═════════════════════════════════════════════

@app.route("/api/leaves", methods=["GET"])
@login_required
def api_get_leaves():
    user = current_user()
    if user.role == "admin":
        leaves = TeacherLeave.query.order_by(TeacherLeave.leave_date.desc()).limit(60).all()
    else:
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        leaves  = TeacherLeave.query.filter_by(teacher_id=teacher.id).all() if teacher else []
    return jsonify({"ok": True, "leaves": [l.to_dict() for l in leaves]})

@app.route("/api/leaves", methods=["POST"])
@login_required
def api_apply_leave():
    d       = request.json or {}
    user    = current_user()
    teacher = Teacher.query.filter_by(user_id=user.id).first()
    if not teacher and user.role != "admin":
        return jsonify({"ok": False, "msg": "Teacher profile not found"})
    tid = d.get("teacher_id") if user.role == "admin" else (teacher.id if teacher else None)
    if not tid: return jsonify({"ok": False, "msg": "teacher_id required"})
    leave_date = d.get("leave_date","").strip()
    if not leave_date: return jsonify({"ok": False, "msg": "leave_date (YYYY-MM-DD) required"})
    lv = TeacherLeave(teacher_id=tid, leave_date=leave_date,
                      reason=d.get("reason","").strip(), approved=user.role == "admin")
    db.session.add(lv); db.session.commit()
    return jsonify({"ok": True, "leave": lv.to_dict()})

@app.route("/api/leaves/<int:lid>/approve", methods=["POST"])
@admin_required
def api_approve_leave(lid):
    lv = TeacherLeave.query.get_or_404(lid)
    lv.approved = True; db.session.commit()
    if lv.teacher and lv.teacher.user_id:
        create_notification(lv.teacher.user_id,
            f"Your leave request for {lv.leave_date} has been approved.", "info")
    return jsonify({"ok": True})

@app.route("/api/leaves/<int:lid>", methods=["DELETE"])
@login_required
def api_delete_leave(lid):
    lv   = TeacherLeave.query.get_or_404(lid)
    user = current_user()
    if user.role != "admin":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher or lv.teacher_id != teacher.id:
            return jsonify({"ok": False, "msg": "Not authorized"}), 403
    db.session.delete(lv); db.session.commit()
    return jsonify({"ok": True})

# ═════════════════════════════════════════════
# 🆕 ACTIVITY LOG
# ═════════════════════════════════════════════

@app.route("/api/activity", methods=["GET"])
@admin_required
def api_get_activity():
    limit  = min(int(request.args.get("limit",50)), 200)
    offset = int(request.args.get("offset",0))
    logs   = (ActivityLog.query.order_by(ActivityLog.created_at.desc())
              .offset(offset).limit(limit).all())
    total  = ActivityLog.query.count()
    return jsonify({"ok": True, "logs": [l.to_dict() for l in logs], "total": total})


@app.route("/api/ai/chat", methods=["POST"])
@login_required
def api_ai_chat():
    user = current_user()
    data = request.json or {}
    message = (data.get("message") or "").strip()
    timetable_id = data.get("timetable_id")
    if not message:
        return jsonify({"ok": False, "msg": "Please enter a message."})

    tt, err = resolve_chat_timetable(user, timetable_id)
    if err:
        return jsonify({"ok": False, "msg": err})

    text_lower = message.lower()
    cells = tt.cells() if tt else {}
    day_code = detect_day_from_text(text_lower)
    slot_number = detect_slot_from_text(text_lower)

    if any(word in text_lower for word in ["summary", "summarize", "overview"]):
        filled = sum(1 for c in cells.values() if c and c.get("subject"))
        teacher_counts = {}
        day_counts = {day: 0 for day in DAYS}
        for key, cell in cells.items():
            if cell and cell.get("subject"):
                day_key = key.split("|", 1)[0]
                day_counts[day_key] = day_counts.get(day_key, 0) + 1
                teacher = cell.get("teacher", "").strip()
                if teacher:
                    teacher_counts[teacher] = teacher_counts.get(teacher, 0) + 1
        busiest_day = max(day_counts, key=day_counts.get) if day_counts else None
        top_teacher = max(teacher_counts, key=teacher_counts.get) if teacher_counts else None
        reply = (
            f"{tt.name} is for {tt.department or 'the selected branch'} in room {tt.room or 'not set'}. "
            f"It has {filled} scheduled classes. "
            f"The busiest day is {busiest_day or 'not available'} with {day_counts.get(busiest_day, 0)} classes. "
            f"{'The highest load is for ' + top_teacher + ' with ' + str(teacher_counts[top_teacher]) + ' periods.' if top_teacher else 'No teacher load data is assigned yet.'}"
        )
        return jsonify({"ok": True, "reply": reply, "context": f"Using timetable: {tt.name}"})

    if any(word in text_lower for word in ["room", "branch", "year", "academic year"]):
        reply = (
            f"Timetable {tt.name} is for {tt.department or 'unknown branch'}, room {tt.room or 'not set'}, "
            f"{tt.year_sem or 'year/semester not set'}, academic year {tt.academic_year or 'not set'}."
        )
        return jsonify({"ok": True, "reply": reply, "context": f"Using timetable: {tt.name}"})

    if "who teaches the most" in text_lower or "highest load" in text_lower or "top teacher" in text_lower:
        teacher_counts = {}
        for cell in cells.values():
            if cell and cell.get("subject") and cell.get("teacher"):
                teacher = cell["teacher"].strip()
                teacher_counts[teacher] = teacher_counts.get(teacher, 0) + 1
        if not teacher_counts:
            return jsonify({"ok": True, "reply": "No teacher assignments are available in this timetable yet.", "context": f"Using timetable: {tt.name}"})
        teacher = max(teacher_counts, key=teacher_counts.get)
        return jsonify({"ok": True, "reply": f"{teacher} has the highest visible load in this timetable with {teacher_counts[teacher]} scheduled periods.", "context": f"Using timetable: {tt.name}"})

    if "clash" in text_lower:
        slot_map = {}
        clashes = []
        for other_tt in Timetable.query.all():
            for key, cell in other_tt.cells().items():
                if cell and cell.get("teacher") and cell.get("subject"):
                    map_key = (key, cell["teacher"].strip())
                    slot_map.setdefault(map_key, []).append(other_tt.name)
        for (slot_key, teacher), tt_names in slot_map.items():
            if len(tt_names) > 1 and tt.name in tt_names:
                clashes.append(f"{teacher} is double-booked at {slot_key} across {', '.join(sorted(set(tt_names)))}")
        if clashes:
            return jsonify({"ok": True, "reply": "Cross-timetable clashes found:\n" + "\n".join(clashes[:5]), "context": f"Using timetable: {tt.name}"})
        return jsonify({"ok": True, "reply": "I do not see any cross-timetable teacher clashes involving this timetable right now.", "context": f"Using timetable: {tt.name}"})

    if day_code and (slot_number is not None):
        if slot_number < 1 or slot_number > len(TIME_SLOTS):
            return jsonify({"ok": True, "reply": "Period numbers in this timetable go from 1 to 7.", "context": f"Using timetable: {tt.name}"})
        slot = TIME_SLOTS[slot_number - 1]
        if slot.get("isLunch"):
            return jsonify({"ok": True, "reply": f"{day_code} period {slot_number} is the lunch break.", "context": f"Using timetable: {tt.name}"})
        key = f"{day_code}|{slot['id']}"
        cell = cells.get(key, {})
        return jsonify({"ok": True, "reply": format_chat_cell(cell, f"{day_code} period {slot_number}"), "context": f"Using timetable: {tt.name}"})

    if day_code and any(word in text_lower for word in ["free", "available", "empty"]):
        free_slots = []
        for idx, slot in enumerate(TIME_SLOTS, start=1):
            if slot.get("isLunch"):
                continue
            key = f"{day_code}|{slot['id']}"
            cell = cells.get(key, {})
            if not cell or not cell.get("subject"):
                free_slots.append(f"Period {idx} ({slot['label']})")
        reply = f"Free periods on {day_code}: " + (", ".join(free_slots) if free_slots else "none")
        return jsonify({"ok": True, "reply": reply, "context": f"Using timetable: {tt.name}"})

    if day_code:
        lines = []
        for idx, slot in enumerate(TIME_SLOTS, start=1):
            if slot.get("isLunch"):
                lines.append(f"Period {idx}: Lunch break")
                continue
            key = f"{day_code}|{slot['id']}"
            lines.append(format_chat_cell(cells.get(key, {}), f"Period {idx}"))
        return jsonify({"ok": True, "reply": f"{day_code} schedule:\n" + "\n".join(lines), "context": f"Using timetable: {tt.name}"})

    if any(word in text_lower for word in ["today", "now"]):
        if local_today().weekday() >= len(DAYS):
            return jsonify({"ok": True, "reply": "Today is outside the Monday to Saturday timetable.", "context": f"Using timetable: {tt.name}"})
        today_code = DAYS[local_today().weekday()]
        lines = []
        for idx, slot in enumerate(TIME_SLOTS, start=1):
            if slot.get("isLunch"):
                continue
            key = f"{today_code}|{slot['id']}"
            cell = cells.get(key, {})
            if cell and cell.get("subject"):
                lines.append(format_chat_cell(cell, f"Period {idx}"))
        reply = f"Today's schedule ({today_code}):\n" + ("\n".join(lines) if lines else "No classes scheduled today.")
        return jsonify({"ok": True, "reply": reply, "context": f"Using timetable: {tt.name}"})

    subject_hits = []
    if any(word in text_lower for word in ["subject", "where is", "find", "when is"]):
        for key, cell in cells.items():
            if cell and cell.get("subject") and cell["subject"].lower() in text_lower:
                day_part, slot_id = key.split("|", 1)
                slot_index = next((idx for idx, slot in enumerate(TIME_SLOTS, start=1) if slot["id"] == slot_id), None)
                teacher = cell.get("teacher", "").strip()
                extra = f" by {teacher}" if teacher else ""
                subject_hits.append(f"{cell['subject']} is on {day_part} period {slot_index}{extra}")
        if subject_hits:
            return jsonify({"ok": True, "reply": "\n".join(subject_hits[:6]), "context": f"Using timetable: {tt.name}"})

    filled = sum(1 for c in cells.values() if c and c.get("subject"))
    reply = (
        f"I can help with {tt.name}. Try asking for a summary, a day schedule, free periods on a day, "
        f"a specific period like MON period 2, room details, clashes, or who teaches the most. "
        f"This timetable currently has {filled} scheduled classes."
    )
    return jsonify({"ok": True, "reply": reply, "context": f"Using timetable: {tt.name}"})

# ═════════════════════════════════════════════
# SMART GENERATION (clash-free)
# ═════════════════════════════════════════════

@app.route("/api/generate", methods=["POST"])
@admin_required
def api_generate():
    import random
    d = request.json or {}
    subjects = d.get("subjects",[])
    teachers = d.get("teachers",[])
    sections = int(d.get("sections",2))
    if not subjects: return jsonify({"ok": False, "msg": "At least one subject required"})
    results      = []
    non_lunch    = [s for s in TIME_SLOTS if not s.get("isLunch")]
    slot_used    = {}
    for sec in range(sections):
        cells    = {}
        subj_list= subjects[:]
        random.shuffle(subj_list)
        si = 0
        for day in DAYS:
            if day == "SAT": continue
            for slot in non_lunch:
                key  = f"{day}|{slot['id']}"
                subj = subj_list[si % len(subj_list)]
                assigned_teacher = ""
                if teachers:
                    for offset in range(len(teachers)):
                        cand = teachers[(si + offset) % len(teachers)]
                        if cand not in slot_used.get(key, set()):
                            assigned_teacher = cand
                            slot_used.setdefault(key, set()).add(cand)
                            break
                cells[key] = {"subject": subj, "teacher": assigned_teacher, "type": "lecture"}
                si += 1
        results.append({"name": f"Section {chr(65+sec)}", "cells": cells})
    return jsonify({"ok": True, "results": results})

# ═════════════════════════════════════════════
# VOICE NLP
# ═════════════════════════════════════════════

@app.route("/api/voice/parse", methods=["POST"])
@login_required
def api_voice_parse():
    text = (request.json or {}).get("text","").strip()
    if not text: return jsonify({"ok": False, "msg": "No text provided"})
    return jsonify({"ok": True, "parsed": parse_voice_nlp(text), "nlp_used": NLP_AVAILABLE})


@app.route("/api/voice/nlp-correct", methods=["POST"])
@login_required
def api_voice_nlp_correct():
    """
    NLP correction endpoint for the 4-step voice wizard.
    For each step, takes raw speech text and returns the best corrected value.

    Steps:
      1 = subject  → fuzzy-match against known subjects in all timetables
      2 = day      → fuzzy-match against day names
      3 = period   → extract number from words / digits
      4 = teacher  → fuzzy-match against teacher names in DB
    """
    import difflib, re

    d    = request.json or {}
    step = int(d.get("step", 1))
    raw  = d.get("text", "").strip()
    t    = raw.lower()

    # ── STEP 1: Subject fuzzy correction ─────────────────────
    if step == 1:
        # Collect all known subjects from timetables
        known = set()
        for tt in Timetable.query.all():
            for c in tt.cells().values():
                if c and c.get("subject"):
                    known.add(c["subject"].strip())
        # Also collect from teacher.subjects field
        for teacher in Teacher.query.all():
            for s in (teacher.subjects or "").split(","):
                s = s.strip()
                if s: known.add(s)

        if not known:
            # No known subjects — just title-case what was said
            corrected = raw.replace("/", " ").title().strip()
            return jsonify({"ok": True, "corrected": corrected, "confidence": "low",
                            "matched": False, "original": raw})

        # Try exact match first (case-insensitive)
        raw_lower = raw.lower()
        for k in known:
            if k.lower() == raw_lower:
                return jsonify({"ok": True, "corrected": k, "confidence": "exact",
                                "matched": True, "original": raw})

        # Fuzzy match
        matches = difflib.get_close_matches(raw, list(known), n=1, cutoff=0.5)
        if matches:
            return jsonify({"ok": True, "corrected": matches[0], "confidence": "high",
                            "matched": True, "original": raw})

        # Try word-level: "network security" → "Cryptography and Network Security"
        words = set(raw_lower.split())
        best_score = 0; best_match = None
        for k in known:
            k_words = set(k.lower().split())
            overlap  = len(words & k_words)
            score    = overlap / max(len(words), len(k_words), 1)
            if score > best_score: best_score = score; best_match = k
        if best_score >= 0.4 and best_match:
            return jsonify({"ok": True, "corrected": best_match, "confidence": "medium",
                            "matched": True, "original": raw})

        # No match — return title-cased original
        corrected = raw.title().strip()
        return jsonify({"ok": True, "corrected": corrected, "confidence": "low",
                        "matched": False, "original": raw})

    # ── STEP 2: Day fuzzy correction ─────────────────────────
    elif step == 2:
        day_map = {
            "monday":"MON","tuesday":"TUE","wednesday":"WED",
            "thursday":"THU","friday":"FRI","saturday":"SAT",
            "mon":"MON","tue":"TUE","wed":"WED",
            "thu":"THU","fri":"FRI","sat":"SAT",
            # Common mis-pronunciations / typos
            "munday":"MON","mondy":"MON","monda":"MON",
            "thuesday":"TUE","tues":"TUE",
            "wednes":"WED","wednessday":"WED","wendsday":"WED",
            "thurday":"THU","thurs":"THU","thrusday":"THU",
            "fridat":"FRI","fryday":"FRI",
            "saterday":"SAT","saturdy":"SAT","satur":"SAT",
        }
        # Direct lookup
        for word, code in day_map.items():
            if word in t:
                full = {"MON":"Monday","TUE":"Tuesday","WED":"Wednesday",
                        "THU":"Thursday","FRI":"Friday","SAT":"Saturday"}[code]
                return jsonify({"ok": True, "corrected": code, "display": full,
                                "confidence": "high", "matched": True, "original": raw})
        # Fuzzy on day names
        day_names = ["monday","tuesday","wednesday","thursday","friday","saturday"]
        matches   = difflib.get_close_matches(t, day_names, n=1, cutoff=0.6)
        if matches:
            code = day_map[matches[0]]
            full = {"MON":"Monday","TUE":"Tuesday","WED":"Wednesday",
                    "THU":"Thursday","FRI":"Friday","SAT":"Saturday"}[code]
            return jsonify({"ok": True, "corrected": code, "display": full,
                            "confidence": "medium", "matched": True, "original": raw})
        return jsonify({"ok": True, "corrected": None, "confidence": "none",
                        "matched": False, "original": raw,
                        "msg": "Day గుర్తించలేదు"})

    # ── STEP 3: Period number extraction ─────────────────────
    elif step == 3:
        ordinals = {
            "one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
            "first":1,"second":2,"third":3,"fourth":4,"fifth":5,"sixth":6,"seventh":7,
            "1st":1,"2nd":2,"3rd":3,"4th":4,"5th":5,"6th":6,"7th":7,
            # Telugu/Hinglish words
            "ek":1,"do":2,"dho":2,"teen":3,"char":4,"paanch":5,"chhe":6,"saat":7,
            "okati":1,"rendu":2,"moodu":3,"nalugu":4,"ayidu":5,"aaru":6,"edu":7,
        }
        # Digit
        m = re.search(r'\b([1-7])\b', t)
        if m:
            slot = int(m.group(1))
            return jsonify({"ok": True, "corrected": slot, "confidence": "exact",
                            "matched": True, "original": raw})
        # Word
        for word, num in ordinals.items():
            if word in t:
                return jsonify({"ok": True, "corrected": num, "confidence": "high",
                                "matched": True, "original": raw})
        # Any digit at all
        m2 = re.search(r'\d+', t)
        if m2:
            val = int(m2.group())
            if 1 <= val <= 7:
                return jsonify({"ok": True, "corrected": val, "confidence": "medium",
                                "matched": True, "original": raw})
        return jsonify({"ok": True, "corrected": None, "confidence": "none",
                        "matched": False, "original": raw,
                        "msg": "Period number గుర్తించలేదు"})

    # ── STEP 4: Teacher fuzzy match ───────────────────────────
    elif step == 4:
        skip_words = ["skip","none","no","empty","blank","nobody","no one","noone"]
        if any(w in t for w in skip_words):
            return jsonify({"ok": True, "corrected": "", "confidence": "skip",
                            "matched": True, "original": raw, "skipped": True})

        teachers = Teacher.query.all()
        if not teachers:
            return jsonify({"ok": True, "corrected": raw.title(), "confidence": "low",
                            "matched": False, "original": raw})

        teacher_names = [tc.name for tc in teachers]

        # Exact match (case-insensitive)
        for name in teacher_names:
            if name.lower() == t:
                return jsonify({"ok": True, "corrected": name, "confidence": "exact",
                                "matched": True, "original": raw})

        # Fuzzy full name
        matches = difflib.get_close_matches(raw.title(), teacher_names, n=1, cutoff=0.5)
        if matches:
            return jsonify({"ok": True, "corrected": matches[0], "confidence": "high",
                            "matched": True, "original": raw})

        # Try partial: last name / first name match
        raw_parts = set(raw.lower().split())
        best_score = 0; best_name = None
        for name in teacher_names:
            name_parts = set(name.lower().split())
            overlap    = len(raw_parts & name_parts)
            score      = overlap / max(len(raw_parts), 1)
            if score > best_score: best_score = score; best_name = name
        if best_score >= 0.4 and best_name:
            return jsonify({"ok": True, "corrected": best_name, "confidence": "medium",
                            "matched": True, "original": raw})

        # No match — return title-cased original
        return jsonify({"ok": True, "corrected": raw.title(), "confidence": "low",
                        "matched": False, "original": raw})

    return jsonify({"ok": False, "msg": "Invalid step"})



@app.route("/api/notifications", methods=["GET"])
@login_required
def api_get_notifications():
    user   = current_user()
    notifs = (Notification.query.filter_by(user_id=user.id)
              .order_by(Notification.created_at.desc()).limit(50).all())
    return jsonify({"ok": True, "notifications": [n.to_dict() for n in notifs],
                    "unread": sum(1 for n in notifs if not n.is_read)})

@app.route("/api/notifications/read", methods=["POST"])
@login_required
def api_mark_read():
    Notification.query.filter_by(user_id=session["user_id"], is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/api/notifications/broadcast", methods=["POST"])
@admin_required
def api_broadcast():
    message = (request.json or {}).get("message","").strip()
    if not message: return jsonify({"ok": False, "msg": "Message required"})
    users = User.query.filter_by(role="teacher").all()
    for u in users: create_notification(u.id, message, "broadcast")
    return jsonify({"ok": True, "sent": len(users)})

@app.route("/api/notifications/daily", methods=["POST"])
@admin_required
def api_daily_notify():
    notify_all_teachers_daily()
    return jsonify({"ok": True, "msg": "Daily notifications sent"})


# ═════════════════════════════════════════════
# STATS
# ═════════════════════════════════════════════

@app.route("/api/stats", methods=["GET"])
@admin_required
def api_stats():
    subjects = set()
    for tt in Timetable.query.all():
        for v in tt.cells().values():
            if v and v.get("subject"): subjects.add(v["subject"])
    pending_leaves = TeacherLeave.query.filter_by(approved=False).count()
    cross_clashes  = 0
    slot_map: dict = {}
    for tt in Timetable.query.all():
        for key, c in tt.cells().items():
            if c and c.get("teacher") and c.get("subject"):
                k = (key, c["teacher"])
                slot_map.setdefault(k, []).append(tt.name)
    cross_clashes = sum(1 for tts in slot_map.values() if len(tts) > 1)
    return jsonify({"ok": True,
                    "timetables": Timetable.query.count(),
                    "teachers": Teacher.query.count(),
                    "departments": Department.query.count(),
                    "subjects": len(subjects),
                    "pending_leaves": pending_leaves,
                    "cross_clashes": cross_clashes})

# ═════════════════════════════════════════════
# EXPORT — PDF
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/export/pdf", methods=["GET"])
@login_required
def api_export_pdf(tt_id):
    tt   = Timetable.query.get_or_404(tt_id)
    user = current_user()
    if user.role != "admin":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher or tt not in teacher.timetables:
            return jsonify({"ok": False}), 403
    cells = tt.cells()
    buf   = io.BytesIO()
    doc   = SimpleDocTemplate(buf, pagesize=landscape(A4),
                              leftMargin=0.4*inch, rightMargin=0.4*inch,
                              topMargin=0.5*inch, bottomMargin=0.4*inch)
    styles      = getSampleStyleSheet()
    title_style = ParagraphStyle("T", parent=styles["Title"], fontSize=14,
                                 textColor=colors.HexColor("#1e3a5f"), spaceAfter=4,
                                 fontName="Helvetica-Bold", alignment=1)
    sub_style   = ParagraphStyle("S", parent=styles["Normal"], fontSize=8,
                                 textColor=colors.HexColor("#666666"), spaceAfter=8, alignment=1)
    header_cell_style = ParagraphStyle(
        "TH", parent=styles["BodyText"], fontSize=7, leading=8, alignment=1,
        fontName="Helvetica-Bold", textColor=colors.white
    )
    body_cell_style = ParagraphStyle(
        "TC", parent=styles["BodyText"], fontSize=6.4, leading=8, alignment=1,
        fontName="Helvetica", textColor=colors.HexColor("#0f172a"), wordWrap="CJK"
    )
    lunch_cell_style = ParagraphStyle(
        "TL", parent=body_cell_style, textColor=colors.HexColor("#92400e"), fontName="Helvetica-Bold"
    )
    day_cell_style = ParagraphStyle(
        "TD", parent=header_cell_style, fontSize=8
    )
    elements = [
        Paragraph("B. TECH TIMETABLE", title_style),
        Paragraph(f"Branch: {tt.department}  |  Room: {tt.room}  |  {tt.year_sem}  |  W.E.F: {tt.wef_date}  |  A.Y: {tt.academic_year}", sub_style),
        Spacer(1, 4)
    ]
    header = [Paragraph("DAY / TIME", header_cell_style)]
    for slot in TIME_SLOTS:
        header.append(Paragraph(escape(slot["label"]).replace("-", "<br/>", 1), header_cell_style))
    rows   = [header]
    for day in DAYS:
        row = [Paragraph(day, day_cell_style)]
        for slot in TIME_SLOTS:
            key = f"{day}|{slot['id']}"
            if slot.get("isLunch"):
                row.append(Paragraph("LUNCH", lunch_cell_style))
            else:
                c = cells.get(key,{})
                if c.get("subject"):
                    subject = escape(c.get("subject", ""))
                    teacher = escape(c.get("teacher", ""))
                    html = f"<b>{subject}</b>"
                    if teacher:
                        html += f"<br/>{teacher}"
                    row.append(Paragraph(html, body_cell_style))
                else:
                    row.append(Paragraph("-", body_cell_style))
        rows.append(row)
    usable_width = landscape(A4)[0] - doc.leftMargin - doc.rightMargin
    day_width = 0.8 * inch
    slot_width = (usable_width - day_width) / len(TIME_SLOTS)
    tbl = Table(
        rows,
        colWidths=[day_width] + [slot_width] * len(TIME_SLOTS),
        repeatRows=1,
    )
    sty = TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  colors.HexColor("#1e3a5f")),
        ("TEXTCOLOR",     (0,0),(-1,0),  colors.white),
        ("BACKGROUND",    (0,0),(0,-1),  colors.HexColor("#2d4a6e")),
        ("TEXTCOLOR",     (0,1),(0,-1),  colors.white),
        ("FONTNAME",      (0,0),(-1,0),  "Helvetica-Bold"),
        ("FONTNAME",      (0,1),(0,-1),  "Helvetica-Bold"),
        ("ALIGN",         (0,0),(-1,-1), "CENTER"),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("GRID",          (0,0),(-1,-1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS",(1,1),(-1,-1), [colors.HexColor("#f0f6ff"), colors.white]),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(-1,-1), 4),
        ("RIGHTPADDING",  (0,0),(-1,-1), 4),
    ])
    lunch_col = next(i+1 for i,s in enumerate(TIME_SLOTS) if s.get("isLunch"))
    for r in range(1, len(DAYS)+1):
        sty.add("BACKGROUND",(lunch_col,r),(lunch_col,r),colors.HexColor("#fef3c7"))
        sty.add("TEXTCOLOR", (lunch_col,r),(lunch_col,r),colors.HexColor("#92400e"))
    tbl.setStyle(sty)
    elements.append(tbl)
    footer_style = ParagraphStyle("F", parent=styles["Normal"], fontSize=7,
                                  textColor=colors.grey, spaceBefore=8, alignment=2)
    elements += [Spacer(1,6),
                 Paragraph(f"Generated by SchediQ v2 on {datetime.now().strftime('%d %b %Y %H:%M')}", footer_style)]
    doc.build(elements)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"{tt.name.replace(' ','_')}_Timetable.pdf")

# ═════════════════════════════════════════════
# EXPORT — IMAGE
# ═════════════════════════════════════════════

@app.route("/api/timetables/<int:tt_id>/export/image", methods=["GET"])
@login_required
def api_export_image(tt_id):
    tt   = Timetable.query.get_or_404(tt_id)
    user = current_user()
    if user.role != "admin":
        teacher = Teacher.query.filter_by(user_id=user.id).first()
        if not teacher or tt not in teacher.timetables:
            return jsonify({"ok": False}), 403
    try: from PIL import Image, ImageDraw, ImageFont
    except ImportError: return jsonify({"ok": False, "msg": "Pillow not installed"}), 500
    cells = tt.cells()
    CW, CH = 160, 60; DCW = 70; HH = 50; TH = 80
    W = DCW + CW*len(TIME_SLOTS); H = TH + HH + CH*len(DAYS) + 30
    img  = Image.new("RGB",(W,H),"#ffffff")
    draw = ImageDraw.Draw(img)
    ft, fh, fc, fs = load_export_fonts(ImageFont)
    draw.rectangle([0,0,W,TH],fill="#1e3a5f")
    draw.text((W//2,20),"TIMETABLE",font=ft,fill="white",anchor="mm")
    draw.text((W//2,52),f"{tt.department} | Room:{tt.room} | {tt.year_sem} | {tt.academic_year}",font=fs,fill="#93c5fd",anchor="mm")
    y0 = TH
    draw.rectangle([0,y0,DCW,y0+HH],fill="#2d4a6e")
    draw.text((DCW//2,y0+HH//2),"DAY/TIME",font=fh,fill="white",anchor="mm")
    for i,slot in enumerate(TIME_SLOTS):
        x0 = DCW+i*CW
        bg,fg = ("#fef3c7","#92400e") if slot.get("isLunch") else ("#1e3a5f","white")
        draw.rectangle([x0,y0,x0+CW,y0+HH],fill=bg)
        draw.text((x0+CW//2,y0+HH//2),slot["label"],font=fh,fill=fg,anchor="mm")
    for ri,day in enumerate(DAYS):
        y0  = TH+HH+ri*CH
        rbg = "#f8fafc" if ri%2==0 else "#ffffff"
        draw.rectangle([0,y0,DCW,y0+CH],fill="#2d4a6e")
        draw.text((DCW//2,y0+CH//2),day,font=fh,fill="white",anchor="mm")
        for ci,slot in enumerate(TIME_SLOTS):
            x0 = DCW+ci*CW; key = f"{day}|{slot['id']}"
            if slot.get("isLunch"):
                draw.rectangle([x0,y0,x0+CW,y0+CH],fill="#fef3c7")
                draw.text((x0+CW//2,y0+CH//2),"LUNCH",font=fh,fill="#92400e",anchor="mm")
            else:
                c = cells.get(key,{})
                bg = "#dbeafe" if c.get("type")=="lab" else rbg
                draw.rectangle([x0,y0,x0+CW,y0+CH],fill=bg)
                if c.get("subject"):
                    draw.text((x0+CW//2,y0+20),c["subject"][:22],font=fc,fill="#1e293b",anchor="mm")
                    draw.text((x0+CW//2,y0+38),c.get("teacher","")[:22],font=fs,fill="#64748b",anchor="mm")
            draw.rectangle([x0,y0,x0+CW-1,y0+CH-1],outline="#cbd5e1",width=1)
        draw.rectangle([0,y0,DCW-1,y0+CH-1],outline="#1e3a5f",width=1)
    y_foot = TH+HH+len(DAYS)*CH+8
    draw.text((W//2,y_foot),f"SchediQ v2 — {datetime.now().strftime('%d %b %Y')}",font=fs,fill="#94a3b8",anchor="mm")
    buf = io.BytesIO(); img.save(buf,"PNG",optimize=True); buf.seek(0)
    return send_file(buf,mimetype="image/png",as_attachment=True,
                     download_name=f"{tt.name.replace(' ','_')}_Timetable.png")

# ═════════════════════════════════════════════

# ═════════════════════════════════════════════
# SEED DATA
# ═════════════════════════════════════════════

def seed_demo_data():
    if User.query.filter_by(username="admin").first(): return
    demo_admin_password = "Admin@SchediQ2026"
    demo_teacher_password = "Teach@SchediQ2026"
    admin = User(name="Administrator", email="admin@college.edu",
                 username="admin", role="admin", first_login=False)
    admin.set_password(demo_admin_password)
    db.session.add(admin)
    depts = [
        Department(name="Computer Science", code="CSE", sections="A, B, C"),
        Department(name="Electronics",      code="ECE", sections="A, B"),
        Department(name="Mechanical",       code="MECH",sections="A"),
    ]
    db.session.add_all(depts); db.session.flush()
    teacher_data = [
        ("Ch. Divya",                    "divya@college.edu",      "9866092733","CSE","Cryptography and Network Security, CNS"),
        ("M. Chinababu",                  "chinababu@college.edu",  "9963891727","CSE","Compiler Design, CD"),
        ("V. Venkata Ramanjaneyulu",      "venkata@college.edu",    "9603012398","CSE","Cloud Computing, CC"),
        ("PV. Rama Gopal Rao",            "ramagopal@college.edu",  "9441825884","CSE","Agile Methodology"),
        ("G. Dasharatha",                 "dasharatha@college.edu", "9989701816","EEE","Utilization of Electric Energy, UEE"),
    ]
    teachers = []
    for (name, email, phone, dept, subjects) in teacher_data:
        uname = email.split("@")[0]
        u = User(name=name, email=email, username=uname, role="teacher",
                 department=dept, phone=phone, first_login=False)
        u.set_password(demo_teacher_password); db.session.add(u); db.session.flush()
        t = Teacher(user_id=u.id, name=name, email=email, phone=phone,
                    dept=dept, subjects=subjects, max_periods=6)
        db.session.add(t); db.session.flush(); teachers.append(t)
        create_notification(u.id, f"Welcome to SchediQ v2! Login: {uname} / {demo_teacher_password}", "welcome")
    cells = {}
    sched = {
        "MON": [("TT/CC","V. Venkata Ramanjaneyulu"),("TT/Agile","PV. Rama Gopal Rao"),("TT/CNS","Ch. Divya"),None,("UEE","G. Dasharatha"),("CNS","Ch. Divya"),("CD","M. Chinababu")],
        "TUE": [("Agile","PV. Rama Gopal Rao"),("UEE","G. Dasharatha"),("CC","V. Venkata Ramanjaneyulu"),None,None,None,None],
        "WED": [("CD","M. Chinababu"),("Agile","PV. Rama Gopal Rao"),("CNS","Ch. Divya"),None,("AT/UEE","G. Dasharatha"),("AT/CC","V. Venkata Ramanjaneyulu"),("AT/CD","M. Chinababu")],
        "THU": [("CD","M. Chinababu"),("CC","V. Venkata Ramanjaneyulu"),("CNS","Ch. Divya"),None,("CD","M. Chinababu"),("Agile","PV. Rama Gopal Rao"),("UEE","G. Dasharatha")],
        "FRI": [("CNS","Ch. Divya"),("UEE","G. Dasharatha"),("CC","V. Venkata Ramanjaneyulu"),None,None,None,None],
        "SAT": [],
    }
    for day, slots in sched.items():
        for i, slot in enumerate(TIME_SLOTS):
            if slots and i < len(slots) and slots[i]:
                cells[f"{day}|{slot['id']}"] = {"subject": slots[i][0], "teacher": slots[i][1], "type": "lecture"}
    for key, subj, teacher in [("TUE|t5","CD LAB(305)","M. Chinababu"),("TUE|t6","CD LAB(305)","M. Chinababu"),
                                 ("TUE|t7","CD LAB(305)","M. Chinababu"),("FRI|t5","CNS LAB(305)","Ch. Divya"),
                                 ("FRI|t6","CNS LAB(305)","Ch. Divya"),("FRI|t7","CNS LAB(305)","Ch. Divya")]:
        cells[key] = {"subject": subj, "teacher": teacher, "type": "lab"}
    tt = Timetable(name="CSE-B IV Year I Sem", department="CSE-B", room="NB-201",
                   year_sem="IV Year I Sem", academic_year="2025-2026", wef_date="2025-06-09",
                   cells_json=json.dumps(cells), creator_id=admin.id, is_published=True)
    db.session.add(tt); db.session.flush()
    for t in teachers: tt.assigned_teachers.append(t)
    # Demo announcement
    db.session.add(Announcement(title="Welcome to SchediQ v2!",
        body="New features: clash detector, substitute finder, teacher leave management, announcements, audit log, clone timetable, CSV export and more.",
        priority="urgent", author_id=admin.id))
    db.session.commit()
    logger.info("SchediQ v2 demo data seeded. Admin: admin/%s | Teachers: <name>@college.edu / %s", demo_admin_password, demo_teacher_password)

# ═════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_demo_data()
    if SCHEDULER_AVAILABLE:
        scheduler = BackgroundScheduler(timezone=ZoneInfo(APP_TIMEZONE))
        scheduler.add_job(notify_all_teachers_daily, "cron", hour=7, minute=30)
        scheduler.add_job(send_weekly_summary_email, "cron", day_of_week="mon", hour=8, minute=0)
        scheduler.start()
        logger.info("Scheduler started: daily reminders 7:30 AM | weekly summary Monday 8:00 AM")
    else:
        logger.warning("APScheduler not installed - pip install apscheduler")
    if env_flag("AUTO_OPEN_BROWSER", True):
        import threading, webbrowser
        def open_browser():
            import time; time.sleep(1.5)
            webbrowser.open("http://localhost:5000")
        threading.Thread(target=open_browser, daemon=True).start()
    app.run(debug=False, port=5000)
