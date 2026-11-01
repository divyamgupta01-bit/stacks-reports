from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import User, db

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tasks.queue"))

    if request.method == "POST":
        user_id = request.form.get("user_id", "")
        pin = request.form.get("pin", "").strip()
        user = User.query.get(int(user_id)) if user_id.isdigit() else None

        if user and user.is_locked():
            flash(
                "This account is temporarily locked after too many wrong "
                "PIN attempts. Try again in a few minutes.",
                "error",
            )
        elif user and user.check_pin(pin):
            user.register_successful_login()
            db.session.commit()
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("tasks.queue"))
        else:
            if user:
                user.register_failed_attempt()
                db.session.commit()
            flash("That PIN isn't right.", "error")

    people = User.query.order_by(User.full_name.asc()).all()
    return render_template("login.html", people=people)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
