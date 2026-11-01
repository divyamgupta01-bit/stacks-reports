import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# Every timestamp is stored in UTC (datetime.utcnow()) so ordering and
# comparisons in the DB stay unambiguous. APP_TZ is only for converting to
# a human-readable time at display time (via the `local_dt` template filter
# in app.py) and for "today" in date-boundary checks like overdue tasks —
# using UTC there would put the boundary at 5pm Pacific instead of midnight.
APP_TZ = ZoneInfo("America/Los_Angeles")


def to_local(dt):
    """Convert a naive UTC datetime (as stored) to an aware Pacific one."""
    if dt is None:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(APP_TZ)


def local_today():
    return datetime.now(APP_TZ).date()

# ---------------------------------------------------------------- roles ----

ROLE_SA = "student_assistant"
ROLE_MAINT = "stack_maintenance"
ROLE_OTHER = "other_staff"
ROLES = [ROLE_SA, ROLE_MAINT, ROLE_OTHER]
ROLE_LABELS = {
    ROLE_SA: "Student Assistant",
    ROLE_MAINT: "Stack Maintenance",
    ROLE_OTHER: "Other Library Staff",
}

# ------------------------------------------------------------ categories ----

# These are admin-configurable now (QuickReportType / FollowupCategory /
# Severity below). The lists here are only the starting defaults, used once
# to seed an empty database — after that, admins manage the live lists under
# Admin -> Report options.

FOLLOWUP_TRIGGER = "Needs Stack Maintenance follow-up"

DEFAULT_QUICK_REPORT_TYPES = [
    "Book cleanup / loose books collected",
    "Shelving or shelf-reading correction completed",
    "Cart or pile addressed",
    "General stack tidying completed",
    "Other completed task",
]

DEFAULT_FOLLOWUP_CATEGORIES = [
    "Large-scale shelf disorder / collection disarray",
    "Books or materials requiring cleanup",
    "Physical damage in the stacks (shelving, signs, furniture, lighting, etc.)",
    "Safety or access concern",
    "Collection issue (overflow, incorrect area, missing signage)",
    "Facilities work order needed",
    "Other",
]

# (label, meaning, weight) — weight ranks urgency; higher sorts as more urgent.
DEFAULT_SEVERITIES = [
    ("Low", "Can be handled during normal stack work", 1),
    ("Normal", "Needs attention soon, but does not prevent use", 2),
    ("High", "Substantial disruption, collection risk, or a time-sensitive issue", 3),
]

TASK_STATUSES = [
    "New", "Waiting", "Assigned", "In Progress", "Resolved", "Closed", "Cancelled",
]
OPEN_STATUSES = ["New", "Waiting", "Assigned", "In Progress"]

LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    pin_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default=ROLE_SA, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    reports = db.relationship("Report", backref="reporter", foreign_keys="Report.reporter_id")
    owned_tasks = db.relationship("Task", backref="owner", foreign_keys="Task.owner_id")
    activities = db.relationship("TaskActivity", backref="actor")

    def set_pin(self, pin):
        self.pin_hash = generate_password_hash(pin)

    def check_pin(self, pin):
        return check_password_hash(self.pin_hash, pin)

    def is_locked(self):
        return bool(self.locked_until and self.locked_until > datetime.utcnow())

    def register_failed_attempt(self):
        self.failed_attempts += 1
        if self.failed_attempts >= LOCKOUT_THRESHOLD:
            self.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)

    def register_successful_login(self):
        self.failed_attempts = 0
        self.locked_until = None

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    # Permissions -----------------------------------------------------

    def can_manage_queue(self):
        """Assign, reassign, change status, merge, close. Stack Maintenance + admins."""
        return self.is_admin or self.role == ROLE_MAINT

    def can_view_shared_queue(self):
        """See everyone's open work, not just their own. SA + Stack Maintenance + admins."""
        return self.is_admin or self.role in (ROLE_SA, ROLE_MAINT)


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)          # e.g. "3rd Floor — East Stacks"
    building = db.Column(db.String(120), nullable=True)
    floor = db.Column(db.String(50), nullable=True)
    zone_description = db.Column(db.String(200), nullable=True)  # e.g. "PR–PS call numbers"
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    qr_codes = db.relationship("QRCode", backref="location", cascade="all, delete-orphan")
    reports = db.relationship("Report", backref="location")

    @property
    def display_name(self):
        return self.name


class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    label = db.Column(db.String(120), nullable=True)   # printed label text, defaults to location name
    active = db.Column(db.Boolean, default=True, nullable=False)
    last_scanned_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reports = db.relationship("Report", backref="qr_code")

    @staticmethod
    def generate_token():
        # URL-safe, non-sequential — a token doesn't reveal how many codes exist
        # or let someone guess a neighboring one.
        return secrets.token_urlsafe(8)


class QuickReportType(db.Model):
    """Admin-configurable options for the fast 'completed task' report."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(150), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class FollowupCategory(db.Model):
    """Admin-configurable categories for the follow-up (task-creating) report."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(150), unique=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


class Severity(db.Model):
    """Admin-configurable severities. `weight` ranks urgency (higher = more
    urgent) and drives queue/bulletin sort order, since the label text itself
    can no longer be trusted to sort correctly once it's admin-editable."""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(30), unique=True, nullable=False)
    meaning = db.Column(db.String(200), nullable=True)
    weight = db.Column(db.Integer, default=0, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)


def ensure_default_config():
    """Populate QuickReportType / FollowupCategory / Severity from the
    original hardcoded lists, but only the first time each table is empty —
    never overwrites admin edits on later app starts.

    Runs once per worker process at startup (each gunicorn worker calls
    create_app() independently), so two workers can race to seed an empty
    table at the same time. If that happens the loser just hits a UNIQUE
    violation on labels the winner already inserted — harmless, so it's
    caught and rolled back rather than crashing the worker."""
    from sqlalchemy.exc import IntegrityError

    try:
        if QuickReportType.query.count() == 0:
            for i, label in enumerate(DEFAULT_QUICK_REPORT_TYPES):
                db.session.add(QuickReportType(label=label, sort_order=i))
        if FollowupCategory.query.count() == 0:
            for i, label in enumerate(DEFAULT_FOLLOWUP_CATEGORIES):
                db.session.add(FollowupCategory(label=label, sort_order=i))
        if Severity.query.count() == 0:
            for label, meaning, weight in DEFAULT_SEVERITIES:
                db.session.add(Severity(label=label, meaning=meaning, weight=weight))
        db.session.commit()
    except IntegrityError:
        db.session.rollback()


def active_quick_report_types():
    return [c.label for c in QuickReportType.query.filter_by(active=True).order_by(QuickReportType.sort_order).all()]


def active_followup_categories():
    return [c.label for c in FollowupCategory.query.filter_by(active=True).order_by(FollowupCategory.sort_order).all()]


def active_severities():
    """Ordered least to most urgent — natural order for a form dropdown."""
    return [s.label for s in Severity.query.filter_by(active=True).order_by(Severity.weight.asc()).all()]


def severity_weights():
    """label -> weight, including inactive ones, so historical tasks with a
    since-deactivated severity still sort sensibly instead of falling to 0."""
    return {s.label: s.weight for s in Severity.query.all()}


class Report(db.Model):
    """A single submission — either a completed quick-task log, or the
    submission that originated a follow-up Task."""
    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(120), nullable=False)
    reporter_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    qr_code_id = db.Column(db.Integer, db.ForeignKey("qr_code.id"), nullable=True)  # null = manual /report entry
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=True)
    quantity_estimate = db.Column(db.String(120), nullable=True)
    outcome = db.Column(db.String(20), nullable=False)  # "completed" | "follow_up"

    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    category = db.Column(db.String(120), nullable=False)
    severity = db.Column(db.String(20), default="Normal", nullable=False)
    status = db.Column(db.String(20), default="New", nullable=False)

    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    resolution = db.Column(db.Text, nullable=True)
    work_order_ref = db.Column(db.String(120), nullable=True)

    duplicate_of_task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    location = db.relationship("Location", foreign_keys=[location_id])
    reports = db.relationship("Report", backref="task", foreign_keys="Report.task_id")
    activity = db.relationship(
        "TaskActivity", backref="task", cascade="all, delete-orphan",
        order_by="TaskActivity.timestamp", foreign_keys="TaskActivity.task_id",
    )
    merged_children = db.relationship(
        "Task", backref=db.backref("duplicate_of", remote_side=[id]),
        foreign_keys=[duplicate_of_task_id],
    )

    @property
    def task_number(self):
        year = self.created_at.year if self.created_at else datetime.utcnow().year
        return f"TSK-{year}-{self.id:04d}"

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES


class TaskActivity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    change_type = db.Column(db.String(30), nullable=False)  # status, assignment, priority, comment, merge
    previous_value = db.Column(db.String(200), nullable=True)
    new_value = db.Column(db.String(200), nullable=True)
    comment = db.Column(db.Text, nullable=True)


ALLOWED_PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("report.id"), nullable=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=True)
    filename = db.Column(db.String(600), nullable=False)  # stored filename, on disk under uploads/
    original_filename = db.Column(db.String(255), nullable=True)
    caption = db.Column(db.String(300), nullable=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    report = db.relationship("Report", backref="attachments")
    task = db.relationship("Task", backref="attachments")
    uploaded_by = db.relationship("User")

    @property
    def url(self):
        # Blob uploads store a full URL; local dev stores a bare filename.
        if self.filename.startswith(("http://", "https://")):
            return self.filename
        return f"/static/uploads/{self.filename}"
