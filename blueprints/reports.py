from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    FOLLOWUP_TRIGGER,
    OPEN_STATUSES,
    Attachment,
    Location,
    QRCode,
    Report,
    Task,
    TaskActivity,
    db,
    active_followup_categories,
    active_quick_report_types,
    active_severities,
)
from utils import save_photo

bp = Blueprint("reports", __name__)


def _resolve_location():
    """Figure out the location for this /report visit from a QR token or a
    manually-chosen location id. Returns (location, qr_code) — either may
    be None if nothing valid was given."""
    token = request.values.get("qr")
    location_id = request.values.get("location_id")

    if token:
        qr = QRCode.query.filter_by(token=token, active=True).first()
        if qr and qr.location.active:
            qr.last_scanned_at = datetime.utcnow()
            db.session.commit()
            return qr.location, qr
        return None, None

    if location_id and location_id.isdigit():
        loc = Location.query.filter_by(id=int(location_id), active=True).first()
        return loc, None

    return None, None


@bp.route("/report", methods=["GET", "POST"])
@login_required
def quick_report():
    location, qr = _resolve_location()
    quick_types = active_quick_report_types()
    all_quick_options = quick_types + [FOLLOWUP_TRIGGER]

    if request.method == "POST":
        report_type = request.form.get("report_type", "")
        notes = request.form.get("notes", "").strip()
        quantity_estimate = request.form.get("quantity_estimate", "").strip()
        qr_token = request.form.get("qr_token", "")
        location_id = request.form.get("location_id", "")

        # Re-resolve from the submitted hidden fields rather than trusting
        # query params again, in case the form was open a while.
        if qr_token:
            qr = QRCode.query.filter_by(token=qr_token, active=True).first()
            location = qr.location if qr else None
        elif location_id.isdigit():
            location = Location.query.filter_by(id=int(location_id), active=True).first()
            qr = None

        if not location:
            flash("Pick a location before submitting.", "error")
        elif report_type not in all_quick_options:
            flash("Pick a report type.", "error")
        elif report_type == FOLLOWUP_TRIGGER:
            # Hand off to the full follow-up form; carry the location along.
            return redirect(
                url_for("reports.follow_up", location_id=location.id, qr=qr.token if qr else None)
            )
        else:
            report = Report(
                report_type=report_type,
                reporter_id=current_user.id,
                location_id=location.id,
                qr_code_id=qr.id if qr else None,
                notes=notes or None,
                quantity_estimate=quantity_estimate or None,
                outcome="completed",
            )
            db.session.add(report)
            db.session.flush()

            photo = request.files.get("photo")
            stored_name, original_or_error = save_photo(photo)
            if original_or_error == "error:upload":
                flash("The photo couldn't be uploaded. Try again.", "error")
            elif original_or_error == "error:type":
                flash("That photo type isn't supported — use JPG, PNG, GIF, or WebP.", "error")
            elif stored_name:
                db.session.add(Attachment(
                    report_id=report.id, filename=stored_name,
                    original_filename=original_or_error, uploaded_by_id=current_user.id,
                ))

            db.session.commit()
            flash(f"Logged: {report_type} at {location.display_name}.", "success")
            # Loop back to the same location so they can log the next item
            # without re-scanning.
            if qr:
                return redirect(url_for("reports.quick_report", qr=qr.token))
            return redirect(url_for("reports.quick_report", location_id=location.id))

    locations = Location.query.filter_by(active=True).order_by(Location.name.asc()).all()
    return render_template(
        "report_quick.html",
        location=location,
        qr=qr,
        locations=locations,
        quick_types=quick_types,
        followup_trigger=FOLLOWUP_TRIGGER,
    )


@bp.route("/report/follow-up", methods=["GET", "POST"])
@login_required
def follow_up():
    location, qr = _resolve_location()
    categories = active_followup_categories()
    severities = active_severities()
    default_severity = "Normal" if "Normal" in severities else (severities[0] if severities else "")

    if request.method == "POST":
        location_id = request.form.get("location_id", "")
        qr_token = request.form.get("qr_token", "")
        category = request.form.get("category", "").strip()
        description = request.form.get("description", "").strip()
        severity = request.form.get("severity", default_severity)
        quantity_estimate = request.form.get("quantity_estimate", "").strip()
        call_number_range = request.form.get("call_number_range", "").strip()
        work_order_ref = request.form.get("work_order_ref", "").strip()
        link_to_task_id = request.form.get("link_to_task_id", "")

        if qr_token:
            qr = QRCode.query.filter_by(token=qr_token, active=True).first()
            location = qr.location if qr else None
        elif location_id.isdigit():
            location = Location.query.filter_by(id=int(location_id), active=True).first()

        errors = []
        if not location:
            errors.append("Pick a location.")
        if category not in categories:
            errors.append("Pick a category.")
        if not description:
            errors.append("Add a brief description.")
        if severity not in severities:
            severity = default_severity

        if errors:
            for e in errors:
                flash(e, "error")
        else:
            full_notes = description
            if call_number_range:
                full_notes += f"\n\nRelated call numbers: {call_number_range}"
            if work_order_ref:
                full_notes += f"\nWork order already started: {work_order_ref}"

            existing_task = (
                Task.query.get(int(link_to_task_id))
                if link_to_task_id.isdigit() else None
            )

            if existing_task and existing_task.status in OPEN_STATUSES:
                # Link to the existing task instead of creating a duplicate.
                task = existing_task
                db.session.add(TaskActivity(
                    task_id=task.id, actor_id=current_user.id, change_type="comment",
                    comment=f"Additional report filed for this issue: {description}",
                ))
            else:
                task = Task(
                    title=f"{category} — {location.display_name}",
                    location_id=location.id,
                    category=category,
                    severity=severity,
                    status="New",
                    notes=full_notes,
                    work_order_ref=work_order_ref or None,
                )
                db.session.add(task)
                db.session.flush()
                db.session.add(TaskActivity(
                    task_id=task.id,
                    actor_id=current_user.id,
                    change_type="status",
                    previous_value=None,
                    new_value="New",
                    comment="Task created from a follow-up report.",
                ))

            report = Report(
                report_type=FOLLOWUP_TRIGGER,
                reporter_id=current_user.id,
                location_id=location.id,
                qr_code_id=qr.id if qr else None,
                notes=description,
                quantity_estimate=quantity_estimate or None,
                outcome="follow_up",
                task_id=task.id,
            )
            db.session.add(report)
            db.session.flush()

            photo = request.files.get("photo")
            stored_name, original_or_error = save_photo(photo)
            if original_or_error == "error:upload":
                flash("The photo couldn't be uploaded. Try again.", "error")
            elif original_or_error == "error:type":
                flash("That photo type isn't supported — use JPG, PNG, GIF, or WebP.", "error")
            elif stored_name:
                db.session.add(Attachment(
                    report_id=report.id, task_id=task.id, filename=stored_name,
                    original_filename=original_or_error, uploaded_by_id=current_user.id,
                ))

            db.session.commit()

            if existing_task and task.id == existing_task.id:
                flash(f"Linked to existing task {task.task_number}.", "success")
            else:
                flash(f"Follow-up filed as {task.task_number}.", "success")
            return redirect(url_for("tasks.task_detail", task_id=task.id))

    # Suggest a possible existing match: same location + category, still open.
    possible_matches = []
    if location:
        possible_matches = (
            Task.query.filter_by(location_id=location.id)
            .filter(Task.status.in_(OPEN_STATUSES))
            .order_by(Task.created_at.desc()).all()
        )

    return render_template(
        "report_followup.html",
        location=location,
        qr=qr,
        categories=categories,
        severities=severities,
        possible_matches=possible_matches,
        form=request.form if request.method == "POST" else {},
    )


@bp.route("/reports/log")
@login_required
def report_log():
    """Every Report ever filed, newest first — completed quick logs and the
    follow-ups that became tasks alike. This is the only place a photo
    attached to a *completed* quick report is visible: task_detail.html only
    shows photos attached directly to the task, and a completed report never
    has a task, so its photo had nowhere to surface before this page."""
    query = Report.query.order_by(Report.submitted_at.desc())
    if not current_user.can_view_shared_queue():
        # Other Library Staff: same restriction as the task queue — only
        # their own submissions, not everyone's.
        query = query.filter_by(reporter_id=current_user.id)
    reports = query.limit(200).all()
    return render_template("report_log.html", reports=reports)
