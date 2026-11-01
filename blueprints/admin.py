import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import (
    ROLE_LABELS,
    ROLES,
    FollowupCategory,
    Location,
    QRCode,
    QuickReportType,
    Report,
    Severity,
    Task,
    User,
    db,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

PIN_PATTERN = re.compile(r"^\d{4}$")


def _require_admin():
    if not current_user.is_admin:
        abort(403)


def _move_item(model, item_id, direction, order_field="sort_order"):
    item = model.query.get_or_404(item_id)
    items = model.query.order_by(getattr(model, order_field)).all()
    idx = items.index(item)
    swap_idx = idx - 1 if direction == "up" else idx + 1 if direction == "down" else None
    if swap_idx is not None and 0 <= swap_idx < len(items):
        other = items[swap_idx]
        a, b = getattr(item, order_field), getattr(other, order_field)
        setattr(item, order_field, b)
        setattr(other, order_field, a)
        db.session.commit()


# ------------------------------------------------------------------ users ----

@bp.route("/users", methods=["GET", "POST"])
@login_required
def users():
    _require_admin()

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        pin = request.form.get("pin", "").strip()
        role = request.form.get("role", "")
        is_admin = bool(request.form.get("is_admin"))

        if not full_name or not pin:
            flash("Fill in a name and a PIN.", "error")
        elif not PIN_PATTERN.match(pin):
            flash("PIN must be exactly 4 digits.", "error")
        elif role not in ROLES:
            flash("Pick a valid role.", "error")
        else:
            user = User(full_name=full_name, role=role, is_admin=is_admin)
            user.set_pin(pin)
            db.session.add(user)
            db.session.commit()
            flash(f"Account created for {full_name}.", "success")

        return redirect(url_for("admin.users"))

    all_users = User.query.order_by(User.created_at.asc()).all()
    return render_template("admin_users.html", users=all_users, roles=ROLES, role_labels=ROLE_LABELS)


@bp.route("/users/<int:user_id>/reset-pin", methods=["POST"])
@login_required
def reset_pin(user_id):
    _require_admin()
    user = User.query.get_or_404(user_id)
    pin = request.form.get("pin", "").strip()

    if not PIN_PATTERN.match(pin):
        flash("PIN must be exactly 4 digits.", "error")
    else:
        user.set_pin(pin)
        user.register_successful_login()
        db.session.commit()
        flash(f"PIN reset for {user.full_name}.", "success")

    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    _require_admin()
    if user_id == current_user.id:
        flash("You can't remove your own account while signed in.", "error")
        return redirect(url_for("admin.users"))

    user = User.query.get_or_404(user_id)
    if Report.query.filter_by(reporter_id=user.id).first():
        flash(
            f"Can't remove {user.full_name} — they have reports on file. "
            "Consider this a permanent staff record instead.",
            "error",
        )
        return redirect(url_for("admin.users"))

    db.session.delete(user)
    db.session.commit()
    flash("Account removed.", "success")
    return redirect(url_for("admin.users"))


# -------------------------------------------------------------- locations ----

@bp.route("/locations", methods=["GET", "POST"])
@login_required
def locations():
    _require_admin()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        building = request.form.get("building", "").strip()
        floor = request.form.get("floor", "").strip()
        zone_description = request.form.get("zone_description", "").strip()

        if not name:
            flash("Give the location a name.", "error")
        else:
            db.session.add(Location(
                name=name, building=building or None, floor=floor or None,
                zone_description=zone_description or None,
            ))
            db.session.commit()
            flash(f"Location \"{name}\" added.", "success")

        return redirect(url_for("admin.locations"))

    all_locations = Location.query.order_by(Location.name.asc()).all()
    return render_template("admin_locations.html", locations=all_locations)


@bp.route("/locations/<int:location_id>/toggle", methods=["POST"])
@login_required
def toggle_location(location_id):
    _require_admin()
    loc = Location.query.get_or_404(location_id)
    loc.active = not loc.active
    db.session.commit()
    flash(f"{loc.name} is now {'active' if loc.active else 'inactive'}.", "success")
    return redirect(url_for("admin.locations"))


# --------------------------------------------------------------- qr codes ----

@bp.route("/locations/<int:location_id>/qrcodes", methods=["GET", "POST"])
@login_required
def qrcodes(location_id):
    _require_admin()
    location = Location.query.get_or_404(location_id)

    if request.method == "POST":
        label = request.form.get("label", "").strip() or location.name
        qr = QRCode(token=QRCode.generate_token(), location_id=location.id, label=label)
        db.session.add(qr)
        db.session.commit()
        flash("QR code generated.", "success")
        return redirect(url_for("admin.qrcodes", location_id=location.id))

    codes = QRCode.query.filter_by(location_id=location.id).order_by(QRCode.created_at.desc()).all()
    return render_template(
        "admin_qrcodes.html",
        location=location,
        codes=codes,
        report_base_url=url_for("reports.quick_report", _external=True),
    )


@bp.route("/qrcodes/<int:qr_id>/toggle", methods=["POST"])
@login_required
def toggle_qrcode(qr_id):
    _require_admin()
    qr = QRCode.query.get_or_404(qr_id)
    qr.active = not qr.active
    db.session.commit()
    flash(f"QR code is now {'active' if qr.active else 'inactive'}.", "success")
    return redirect(url_for("admin.qrcodes", location_id=qr.location_id))


# -------------------------------------------------------------- report options ----

@bp.route("/config")
@login_required
def config():
    _require_admin()
    return render_template(
        "admin_config.html",
        quick_types=QuickReportType.query.order_by(QuickReportType.sort_order).all(),
        categories=FollowupCategory.query.order_by(FollowupCategory.sort_order).all(),
        severities=Severity.query.order_by(Severity.weight).all(),
    )


@bp.route("/config/quick-types/add", methods=["POST"])
@login_required
def add_quick_type():
    _require_admin()
    label = request.form.get("label", "").strip()
    if not label:
        flash("Give it a label.", "error")
    elif QuickReportType.query.filter_by(label=label).first():
        flash("That report type already exists.", "error")
    else:
        max_order = db.session.query(db.func.max(QuickReportType.sort_order)).scalar()
        db.session.add(QuickReportType(label=label, sort_order=(max_order or 0) + 1))
        db.session.commit()
        flash("Quick report type added.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/quick-types/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_quick_type(item_id):
    _require_admin()
    item = QuickReportType.query.get_or_404(item_id)
    item.active = not item.active
    db.session.commit()
    flash(f"\"{item.label}\" is now {'active' if item.active else 'inactive'}.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/quick-types/<int:item_id>/move", methods=["POST"])
@login_required
def move_quick_type(item_id):
    _require_admin()
    _move_item(QuickReportType, item_id, request.form.get("direction"))
    return redirect(url_for("admin.config"))


@bp.route("/config/categories/add", methods=["POST"])
@login_required
def add_category():
    _require_admin()
    label = request.form.get("label", "").strip()
    if not label:
        flash("Give it a label.", "error")
    elif FollowupCategory.query.filter_by(label=label).first():
        flash("That category already exists.", "error")
    else:
        max_order = db.session.query(db.func.max(FollowupCategory.sort_order)).scalar()
        db.session.add(FollowupCategory(label=label, sort_order=(max_order or 0) + 1))
        db.session.commit()
        flash("Category added.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/categories/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_category(item_id):
    _require_admin()
    item = FollowupCategory.query.get_or_404(item_id)
    item.active = not item.active
    db.session.commit()
    flash(f"\"{item.label}\" is now {'active' if item.active else 'inactive'}.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/categories/<int:item_id>/move", methods=["POST"])
@login_required
def move_category(item_id):
    _require_admin()
    _move_item(FollowupCategory, item_id, request.form.get("direction"))
    return redirect(url_for("admin.config"))


@bp.route("/config/severities/add", methods=["POST"])
@login_required
def add_severity():
    _require_admin()
    label = request.form.get("label", "").strip()
    meaning = request.form.get("meaning", "").strip()
    if not label:
        flash("Give it a label.", "error")
    elif Severity.query.filter_by(label=label).first():
        flash("That severity already exists.", "error")
    else:
        max_weight = db.session.query(db.func.max(Severity.weight)).scalar()
        db.session.add(Severity(label=label, meaning=meaning or None, weight=(max_weight or 0) + 1))
        db.session.commit()
        flash("Severity added.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/severities/<int:item_id>/toggle", methods=["POST"])
@login_required
def toggle_severity(item_id):
    _require_admin()
    item = Severity.query.get_or_404(item_id)
    item.active = not item.active
    db.session.commit()
    flash(f"\"{item.label}\" is now {'active' if item.active else 'inactive'}.", "success")
    return redirect(url_for("admin.config"))


@bp.route("/config/severities/<int:item_id>/move", methods=["POST"])
@login_required
def move_severity(item_id):
    _require_admin()
    _move_item(Severity, item_id, request.form.get("direction"), order_field="weight")
    return redirect(url_for("admin.config"))
