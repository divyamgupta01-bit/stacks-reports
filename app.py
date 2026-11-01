import os
import secrets
from datetime import datetime

from flask import Flask, render_template
from flask_login import LoginManager

from config import Config
from models import User, db, ensure_default_config, to_local


def seed_demo_data(wipe=True):
    """Fill the database with fictional demo data only — made-up people and
    locations, safe to expose publicly. Returns [(label, pin), ...]."""
    from datetime import timedelta
    from models import Location, QRCode, Report, Task, TaskActivity, ROLE_SA, ROLE_MAINT, ROLE_OTHER

    if wipe:
        db.drop_all()
    db.create_all()
    ensure_default_config()

    def make_user(name, role, is_admin=False):
        pin = f"{secrets.randbelow(10000):04d}"
        u = User(full_name=name, role=role, is_admin=is_admin)
        u.set_pin(pin)
        db.session.add(u)
        db.session.flush()
        return u, pin

    people = []
    admin, admin_pin = make_user("Alex Rivera", ROLE_MAINT, is_admin=True)
    people.append(("Alex Rivera (admin)", admin_pin))
    maint, maint_pin = make_user("Jordan Lee", ROLE_MAINT)
    people.append(("Jordan Lee (stack maintenance)", maint_pin))
    sa1, sa1_pin = make_user("Sam Patel", ROLE_SA)
    people.append(("Sam Patel (student assistant)", sa1_pin))
    sa2, sa2_pin = make_user("Taylor Kim", ROLE_SA)
    people.append(("Taylor Kim (student assistant)", sa2_pin))
    other, other_pin = make_user("Morgan Diaz", ROLE_OTHER)
    people.append(("Morgan Diaz (other library staff)", other_pin))

    locations_data = [
        ("1st Floor — Periodicals", "Main Library", "1", "Current periodicals + newspapers"),
        ("2nd Floor — General Stacks (A–L)", "Main Library", "2", "Call numbers A–L"),
        ("3rd Floor — East Stacks (PR–PS)", "Main Library", "3", "Call numbers PR–PS"),
        ("Basement — Special Collections", "Main Library", "B1", "Restricted access area"),
    ]
    locations = []
    for name, building, floor, zone in locations_data:
        loc = Location(name=name, building=building, floor=floor, zone_description=zone)
        db.session.add(loc)
        db.session.flush()
        db.session.add(QRCode(token=QRCode.generate_token(), location_id=loc.id, label=name))
        locations.append(loc)
    db.session.flush()

    now = datetime.utcnow()

    db.session.add(Report(
        report_type="Book cleanup / loose books collected", reporter_id=sa1.id,
        location_id=locations[1].id, submitted_at=now - timedelta(days=1, hours=3),
        outcome="completed",
    ))
    db.session.add(Report(
        report_type="Shelving or shelf-reading correction completed", reporter_id=sa2.id,
        location_id=locations[2].id, submitted_at=now - timedelta(hours=6),
        outcome="completed",
    ))

    t1 = Task(
        title="Large shelf collapse — books on floor", location_id=locations[2].id,
        category="Physical damage in the stacks (shelving, signs, furniture, lighting, etc.)",
        severity="High", status="New",
        created_at=now - timedelta(hours=5), updated_at=now - timedelta(hours=5),
    )
    db.session.add(t1)
    db.session.flush()
    db.session.add(Report(
        report_type="Needs Stack Maintenance follow-up", reporter_id=sa2.id, location_id=locations[2].id,
        submitted_at=now - timedelta(hours=5),
        notes="Whole range on the end cap slid off, books everywhere.",
        outcome="follow_up", task_id=t1.id,
    ))
    db.session.add(TaskActivity(
        task_id=t1.id, actor_id=sa2.id, timestamp=now - timedelta(hours=5),
        change_type="status", previous_value=None, new_value="New", comment="Reported via QR code.",
    ))

    t2 = Task(
        title="Overflow cart needs reshelving", location_id=locations[1].id,
        category="Large-scale shelf disorder / collection disarray",
        severity="Normal", status="In Progress", owner_id=maint.id,
        created_at=now - timedelta(days=2), updated_at=now - timedelta(hours=1),
    )
    db.session.add(t2)
    db.session.flush()
    db.session.add(Report(
        report_type="Needs Stack Maintenance follow-up", reporter_id=sa1.id, location_id=locations[1].id,
        submitted_at=now - timedelta(days=2),
        notes="Two full carts sitting in the aisle since last week.",
        outcome="follow_up", task_id=t2.id,
    ))
    db.session.add(TaskActivity(
        task_id=t2.id, actor_id=maint.id, timestamp=now - timedelta(days=1, hours=20),
        change_type="assignment", previous_value=None, new_value="Jordan Lee", comment=None,
    ))
    db.session.add(TaskActivity(
        task_id=t2.id, actor_id=maint.id, timestamp=now - timedelta(hours=1),
        change_type="status", previous_value="Assigned", new_value="In Progress",
        comment="Started on the first cart.",
    ))

    t3 = Task(
        title="Damaged range sign", location_id=locations[0].id,
        category="Physical damage in the stacks (shelving, signs, furniture, lighting, etc.)",
        severity="Low", status="Closed", owner_id=maint.id,
        resolution="Sign reprinted and reattached.",
        created_at=now - timedelta(days=5), updated_at=now - timedelta(days=3),
    )
    db.session.add(t3)
    db.session.flush()
    db.session.add(Report(
        report_type="Needs Stack Maintenance follow-up", reporter_id=other.id, location_id=locations[0].id,
        submitted_at=now - timedelta(days=5), notes="Range sign for periodicals fell off.",
        outcome="follow_up", task_id=t3.id,
    ))
    for ts, ct, prev, new, comment in [
        (now - timedelta(days=4), "status", "New", "Assigned", None),
        (now - timedelta(days=3, hours=12), "status", "Assigned", "In Progress", None),
        (now - timedelta(days=3), "status", "In Progress", "Closed", "Sign reprinted and reattached."),
    ]:
        db.session.add(TaskActivity(
            task_id=t3.id, actor_id=maint.id, timestamp=ts,
            change_type=ct, previous_value=prev, new_value=new, comment=comment,
        ))

    t4 = Task(
        title="Flickering light over Special Collections entrance", location_id=locations[3].id,
        category="Facilities work order needed", severity="Normal", status="Waiting",
        owner_id=maint.id, work_order_ref="FAC-20265",
        created_at=now - timedelta(days=1, hours=2), updated_at=now - timedelta(hours=10),
    )
    db.session.add(t4)
    db.session.flush()
    db.session.add(Report(
        report_type="Needs Stack Maintenance follow-up", reporter_id=sa1.id, location_id=locations[3].id,
        submitted_at=now - timedelta(days=1, hours=2),
        notes="Light has been flickering for a few days.",
        outcome="follow_up", task_id=t4.id,
    ))
    db.session.add(TaskActivity(
        task_id=t4.id, actor_id=maint.id, timestamp=now - timedelta(hours=10),
        change_type="status", previous_value="Assigned", new_value="Waiting",
        comment="Filed facilities work order FAC-20265, waiting on electrician.",
    ))

    db.session.commit()

    print("Demo database created — fictional people and locations only.\n")
    print("Sign-in accounts:")
    for label, pin in people:
        print(f"  {label:38s} PIN: {pin}")
    print("\n4 locations with QR codes, 2 completed quick reports, 4 tasks")
    print("(New / In Progress / Waiting / Closed).")
    return people


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)

    with app.app_context():
        try:
            db.create_all()
            ensure_default_config()
        except Exception:
            # Concurrent cold starts can race to create tables; the winner's
            # tables are fine, so just reset this session and carry on.
            db.session.rollback()
        if os.environ.get("SEED_DEMO_ON_EMPTY") == "1":
            try:
                if User.query.count() == 0:
                    seed_demo_data(wipe=False)
            except Exception:
                db.session.rollback()

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Sign in to continue."
    login_manager.login_message_category = "error"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_globals():
        return {"current_year": datetime.utcnow().year}

    @app.template_filter("local_dt")
    def local_dt_filter(dt, fmt="%b %d, %I:%M %p"):
        """Stored timestamps are UTC; this renders them in the library's
        local timezone (America/Los_Angeles) instead of showing UTC as if
        it were local time."""
        converted = to_local(dt)
        return converted.strftime(fmt) if converted else "—"

    from blueprints.auth import bp as auth_bp
    from blueprints.reports import bp as reports_bp
    from blueprints.tasks import bp as tasks_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        from flask import redirect, url_for
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("tasks.queue"))
        return redirect(url_for("auth.login"))

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="You don't have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="That page doesn't exist."), 404

    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and, if none exist, a first admin account."""
        db.create_all()
        ensure_default_config()
        if User.query.count() == 0:
            starter_pin = f"{secrets.randbelow(10000):04d}"
            admin = User(full_name="Admin", role="stack_maintenance", is_admin=True)
            admin.set_pin(starter_pin)
            db.session.add(admin)
            db.session.commit()
            print("Database created.")
            print(f"First admin account -> name: Admin / PIN: {starter_pin}")
            print("Sign in, add Locations + QR codes and real accounts under Admin, then remove this one.")
        else:
            print("Database already has users — nothing to do.")

    @app.cli.command("seed-demo")
    def seed_demo_command():
        """Wipe the database and refill it with fictional demo data only."""
        seed_demo_data(wipe=True)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
