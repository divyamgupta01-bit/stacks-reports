from datetime import date, datetime, timedelta
from urllib.parse import quote, urlencode

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    OPEN_STATUSES,
    TASK_STATUSES,
    Attachment,
    Location,
    Report,
    Task,
    TaskActivity,
    User,
    db,
    active_followup_categories,
    active_severities,
    local_today,
    severity_weights,
)
from utils import save_photo

bp = Blueprint("tasks", __name__)


def _visible_task_ids_for(user):
    """Task ids this user is allowed to see, when they don't have full
    queue visibility (other_staff: only tasks that came from their own
    reports)."""
    return [
        r.task_id for r in
        Report.query.filter_by(reporter_id=user.id).filter(Report.task_id.isnot(None)).all()
    ]


def _apply_filters(query):
    status = request.args.get("status", "")
    location_id = request.args.get("location_id", "")
    category = request.args.get("category", "")
    severity = request.args.get("severity", "")

    if status:
        query = query.filter(Task.status == status)
    if location_id.isdigit():
        query = query.filter(Task.location_id == int(location_id))
    if category:
        query = query.filter(Task.category == category)
    if severity:
        query = query.filter(Task.severity == severity)
    if request.args.get("unassigned") == "1":
        query = query.filter(Task.owner_id.is_(None))
    if request.args.get("overdue") == "1":
        query = query.filter(Task.due_date.isnot(None), Task.due_date < local_today())
    return query


FILTER_PARAMS = ("status", "location_id", "category", "severity", "unassigned", "overdue", "show_all")


def _active_filter_chips(locations_by_id):
    """Human-readable (label, remove_url) pairs for every filter currently
    applied, so the queue page can show what's filtered and let it be
    cleared one piece at a time instead of forcing a full reset."""
    chips = []
    args = request.args.to_dict()
    for key, value in list(args.items()):
        if key not in FILTER_PARAMS or not value:
            continue
        if key == "location_id":
            loc = locations_by_id.get(int(value)) if value.isdigit() else None
            label = f"Location: {loc.display_name}" if loc else "Location"
        elif key == "unassigned":
            label = "Unassigned"
        elif key == "overdue":
            label = "Overdue"
        elif key == "show_all":
            label = "Including closed"
        else:
            label = f"{key.capitalize()}: {value}"
        remaining = {k: v for k, v in args.items() if k != key}
        chips.append((label, "?" + urlencode(remaining) if remaining else "?"))
    return chips


def _sort_by_urgency(tasks, weights, due_first=False):
    """Sort a list of Task objects most-urgent-first using the live
    Severity weights (a plain `.severity.desc()` string sort breaks as soon
    as admins add/rename severities, since it stops being alphabetical)."""
    def key(t):
        urgency = -weights.get(t.severity, 0)
        if due_first:
            return (urgency, t.due_date or date.max)
        return (urgency, -(t.created_at or datetime.min).timestamp())
    return sorted(tasks, key=key)


def _top_severity_label():
    """The most urgent configured severity's label — used both for the
    dashboard's "high severity" count and the queue's quick-filter chip, so
    it stays correct if an admin renames or reorders severities."""
    return max(severity_weights().items(), key=lambda kv: kv[1], default=(None, None))[0]


@bp.route("/queue")
@login_required
def queue():
    query = Task.query
    if not current_user.can_view_shared_queue():
        ids = _visible_task_ids_for(current_user)
        query = query.filter(Task.id.in_(ids)) if ids else query.filter(False)

    show_all = request.args.get("show_all") == "1"
    if not request.args.get("status") and not show_all:
        query = query.filter(Task.status.in_(OPEN_STATUSES))

    query = _apply_filters(query)
    tasks = query.order_by(Task.created_at.desc()).all()
    locations = Location.query.filter_by(active=True).order_by(Location.name.asc()).all()
    locations_by_id = {loc.id: loc for loc in locations}

    return render_template(
        "queue.html",
        heading="Open stack work" if not show_all else "All tasks",
        tasks=tasks,
        locations=locations,
        categories=active_followup_categories(),
        severities=active_severities(),
        statuses=TASK_STATUSES,
        show_all=show_all,
        mine_view=False,
        top_severity=_top_severity_label(),
        active_filters=_active_filter_chips(locations_by_id),
        back=quote(request.full_path, safe=""),
    )


@bp.route("/queue/mine")
@login_required
def my_assignments():
    tasks = (
        Task.query.filter_by(owner_id=current_user.id)
        .filter(Task.status.in_(OPEN_STATUSES))
        .all()
    )
    tasks = _sort_by_urgency(tasks, severity_weights(), due_first=True)
    return render_template(
        "queue.html",
        heading="My assignments",
        tasks=tasks,
        locations=[],
        categories=[],
        severities=[],
        statuses=[],
        show_all=False,
        mine_view=True,
        top_severity=None,
        active_filters=[],
        back=quote(request.full_path, safe=""),
    )


def _can_view_task(task):
    if current_user.can_view_shared_queue():
        return True
    return task.id in _visible_task_ids_for(current_user)


def _log(task, change_type, previous_value, new_value, comment=None):
    db.session.add(TaskActivity(
        task_id=task.id,
        actor_id=current_user.id,
        change_type=change_type,
        previous_value=str(previous_value) if previous_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        comment=comment,
    ))


@bp.route("/bulletin")
@login_required
def bulletin():
    """Shared, status-only view — no reporter names or internal notes.
    Visible to everyone, including roles that can't see the full queue."""
    weights = severity_weights()
    open_tasks = Task.query.filter(Task.status.in_(OPEN_STATUSES)).all()
    open_tasks = _sort_by_urgency(open_tasks, weights)

    two_weeks_ago = datetime.utcnow() - timedelta(days=14)
    recently_done = (
        Task.query.filter(Task.status.in_(["Resolved", "Closed"]))
        .filter(Task.updated_at >= two_weeks_ago)
        .order_by(Task.updated_at.desc()).limit(15).all()
    )
    return render_template("bulletin.html", open_tasks=open_tasks, recently_done=recently_done)


@bp.route("/dashboard")
@login_required
def supervisor_dashboard():
    if not current_user.can_manage_queue():
        abort(403)

    today = local_today()
    open_q = Task.query.filter(Task.status.in_(OPEN_STATUSES))

    open_count = open_q.count()
    high_severity_label = _top_severity_label()

    overdue_tasks = open_q.filter(Task.due_date.isnot(None), Task.due_date < today).all()
    high_tasks = open_q.filter(Task.severity == high_severity_label).all() if high_severity_label else []
    unassigned_tasks = open_q.filter(Task.owner_id.is_(None)).all()

    overdue_ids = {t.id for t in overdue_tasks}
    high_ids = {t.id for t in high_tasks}
    unassigned_ids = {t.id for t in unassigned_tasks}

    overdue_count = len(overdue_ids)
    high_open_count = len(high_ids)
    unassigned_count = len(unassigned_ids)

    week_ago = datetime.utcnow() - timedelta(days=7)
    resolved_this_week = (
        Task.query.filter(Task.status.in_(["Resolved", "Closed"]))
        .filter(Task.updated_at >= week_ago).count()
    )

    by_category = (
        db.session.query(Task.category, db.func.count(Task.id))
        .filter(Task.status.in_(OPEN_STATUSES)).group_by(Task.category)
        .order_by(db.func.count(Task.id).desc()).all()
    )
    by_location = (
        db.session.query(Location.name, db.func.count(Task.id))
        .join(Task, Task.location_id == Location.id)
        .filter(Task.status.in_(OPEN_STATUSES)).group_by(Location.name)
        .order_by(db.func.count(Task.id).desc()).all()
    )
    max_category_count = max([c for _, c in by_category], default=1)
    max_location_count = max([c for _, c in by_location], default=1)

    # Needs attention: overdue, high severity, or unassigned — deduped,
    # each row tagged with which of those apply so it's clear why it's
    # here, not just another undifferentiated task list.
    attention_ids = overdue_ids | high_ids | unassigned_ids
    attention_tasks = Task.query.filter(Task.id.in_(attention_ids)).all() if attention_ids else []
    attention_tasks = _sort_by_urgency(attention_tasks, severity_weights())[:10]
    attention_rows = []
    for t in attention_tasks:
        reasons = []
        if t.id in overdue_ids:
            reasons.append("Overdue")
        if t.id in high_ids:
            reasons.append("High severity")
        if t.id in unassigned_ids:
            reasons.append("Unassigned")
        attention_rows.append((t, reasons))

    return render_template(
        "dashboard.html",
        open_count=open_count,
        overdue_count=overdue_count,
        high_open_count=high_open_count,
        unassigned_count=unassigned_count,
        resolved_this_week=resolved_this_week,
        high_severity_label=high_severity_label,
        by_category=by_category,
        by_location=by_location,
        max_category_count=max_category_count,
        max_location_count=max_location_count,
        attention_rows=attention_rows,
        today=today,
    )


@bp.route("/tasks/<int:task_id>", methods=["GET", "POST"])
@login_required
def task_detail(task_id):
    task = Task.query.get_or_404(task_id)
    if not _can_view_task(task):
        abort(403)

    can_manage = current_user.can_manage_queue()
    severities = active_severities()

    # Flask already URL-decodes query args once, so back_param here is a
    # plain path like "/queue?severity=High" — usable directly as an href,
    # but it must be re-encoded as a single value when appended onto
    # another URL's query string (back_qs), or its own "?"/"&" would be
    # parsed as extra top-level params instead of part of this one's value.
    back_param = request.args.get("back", "")
    if back_param.startswith("/") and not back_param.startswith("//"):
        back_url = back_param
    else:
        back_url = url_for("tasks.queue")
    back_qs = f"?back={quote(back_param, safe='')}" if back_param else ""

    if request.method == "POST":
        if not can_manage and request.form.get("action") != "comment":
            abort(403)

        action = request.form.get("action")

        if action == "status":
            new_status = request.form.get("status")
            if new_status in TASK_STATUSES and new_status != task.status:
                _log(task, "status", task.status, new_status)
                task.status = new_status
                task.updated_at = datetime.utcnow()
                db.session.commit()
                flash(f"Status changed to {new_status}.", "success")

        elif action == "assign":
            owner_id = request.form.get("owner_id", "")
            new_owner = User.query.get(int(owner_id)) if owner_id.isdigit() else None
            old_name = task.owner.full_name if task.owner else "Unassigned"
            task.owner_id = new_owner.id if new_owner else None
            if task.status == "New" and new_owner:
                task.status = "Assigned"
                _log(task, "status", "New", "Assigned")
            _log(task, "assignment", old_name, new_owner.full_name if new_owner else "Unassigned")
            task.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Assignment updated.", "success")

        elif action == "severity":
            new_sev = request.form.get("severity")
            if new_sev in severities and new_sev != task.severity:
                _log(task, "priority", task.severity, new_sev)
                task.severity = new_sev
                task.updated_at = datetime.utcnow()
                db.session.commit()
                flash(f"Severity set to {new_sev}.", "success")

        elif action == "due_date":
            due = request.form.get("due_date", "")
            try:
                task.due_date = datetime.strptime(due, "%Y-%m-%d").date() if due else None
                task.updated_at = datetime.utcnow()
                _log(task, "due_date", None, due or "cleared")
                db.session.commit()
                flash("Due date updated.", "success")
            except ValueError:
                flash("That date didn't parse — use the date picker.", "error")

        elif action == "work_order":
            ref = request.form.get("work_order_ref", "").strip()
            task.work_order_ref = ref or None
            task.updated_at = datetime.utcnow()
            _log(task, "work_order", None, ref or "cleared")
            db.session.commit()
            flash("Work order reference updated.", "success")

        elif action == "resolve":
            resolution = request.form.get("resolution", "").strip()
            if not resolution:
                flash("Add a short resolution note.", "error")
            else:
                task.resolution = resolution
                _log(task, "status", task.status, "Resolved", comment=resolution)
                task.status = "Resolved"
                task.updated_at = datetime.utcnow()
                db.session.commit()
                flash("Marked resolved.", "success")

        elif action == "reopen":
            _log(task, "status", task.status, "In Progress", comment="Reopened.")
            task.status = "In Progress"
            task.updated_at = datetime.utcnow()
            db.session.commit()
            flash("Reopened.", "success")

        elif action == "merge":
            target_id = request.form.get("duplicate_of", "")
            target = Task.query.get(int(target_id)) if target_id.isdigit() else None
            if not target or target.id == task.id:
                flash("Pick a valid task to merge into.", "error")
            else:
                # Fold this task's reports and photos into the surviving
                # task so nothing reported gets lost from view.
                for r in task.reports:
                    r.task_id = target.id
                for a in task.attachments:
                    a.task_id = target.id

                task.duplicate_of_task_id = target.id
                _log(task, "status", task.status, "Cancelled",
                     comment=f"Merged as duplicate of {target.task_number}.")
                task.status = "Cancelled"
                task.updated_at = datetime.utcnow()

                _log(target, "merge", None, task.task_number,
                     comment=f"Absorbed reports from {task.task_number} (duplicate).")
                target.updated_at = datetime.utcnow()

                db.session.commit()
                flash(f"Merged into {target.task_number}.", "success")

        elif action == "comment":
            body = request.form.get("comment", "").strip()
            photo = request.files.get("photo")
            stored_name, original_or_error = save_photo(photo)

            if original_or_error == "error:upload":
                flash("The photo couldn't be uploaded. Try again.", "error")
            elif original_or_error == "error:type":
                flash("That photo type isn't supported — use JPG, PNG, GIF, or WebP.", "error")
            else:
                if body:
                    _log(task, "comment", None, None, comment=body)
                if stored_name:
                    db.session.add(Attachment(
                        task_id=task.id, filename=stored_name,
                        original_filename=original_or_error, uploaded_by_id=current_user.id,
                    ))
                    _log(task, "comment", None, None,
                         comment=None if body else "Added a photo.")
                if body or stored_name:
                    db.session.commit()
                    flash("Note added.", "success")

        return redirect(url_for("tasks.task_detail", task_id=task.id) + back_qs)

    staff = User.query.filter(
        (User.role == "stack_maintenance") | (User.is_admin == True)  # noqa: E712
    ).order_by(User.full_name.asc()).all()
    open_tasks_for_merge = (
        Task.query.filter(Task.id != task.id, Task.status.in_(OPEN_STATUSES))
        .order_by(Task.created_at.desc()).all()
    )

    return render_template(
        "task_detail.html",
        task=task,
        can_manage=can_manage,
        statuses=TASK_STATUSES,
        severities=severities,
        staff=staff,
        open_tasks_for_merge=open_tasks_for_merge,
        back_url=back_url,
        back_qs=back_qs,
    )
