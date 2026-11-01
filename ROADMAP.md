# Stack Maintenance Reporting App — Build Roadmap

Based on `stack-maintenance-reporting-app-brief.md`. The brief describes a
full system; this splits it into phases so it's actually buildable and
testable in stages, rather than one enormous unverified rewrite.

**Foundation decision:** keep Flask + SQLite and the deployment already in
place (systemd + gunicorn on the server), rather than starting over on a
different stack. The brief says the database technology is flexible, and
there's no real production data on the server yet to migrate (just a
bootstrap admin account) — so this is a clean point to redesign the schema
without any data-loss risk.

## Phase 1 — Foundation (building now)

The core loop: report something → it becomes a task → it gets tracked to
resolution. Without this working end to end, nothing else in the brief
matters.

- New data model: `Location`, `QRCode`, `Report`, `Task`, `TaskActivity`,
  `User` (with role: student assistant / stack maintenance / other staff,
  plus an admin flag)
- Workflow A: scan a QR code (or use a manual `/report` bookmark) → quick
  report form → either logged as completed, or routed into a follow-up
  form
- Workflow B: follow-up form → creates a trackable Task
- Workflow C (basic): a task queue with the brief's full status set (New
  → Waiting → Assigned → In Progress → Resolved → Closed →
  Cancelled/Duplicate), an automatic activity log on every change, and two
  simple filtered views ("My assignments", "Open stack work")
- Admin: manage Locations and QR codes (generate the report links/tokens),
  in addition to the existing user management
- Login stays PIN-based for now (see Phase 3 note on SSO)

**Deliberately left out of Phase 1:** photo attachments, merging duplicate
reports into one task, the public bulletin board view, the supervisor
analytics dashboard, and admin-configurable categories (categories/severity
levels are fixed lists for now, same pattern as the current app's floor
list). These are all additive on top of the Phase 1 schema — nothing here
should need to be rebuilt to add them later.

## Phase 2 — Depth

**Done and tested:**
- Photo attachments on reports and tasks (stored in `static/uploads/`,
  shown as thumbnails on the task page)
- Merging duplicate reports: filing a follow-up now checks for an
  existing open task at the same location and offers to link to it
  instead of creating a new one; merging one task into another now
  properly moves all of its reports and photos onto the surviving task,
  rather than just marking it cancelled
- Public bulletin board (`/bulletin`) — status-only view (category,
  location, severity, status), no reporter names or notes, visible to
  every role including Other Library Staff who can't see the full queue
- Supervisor dashboard (`/dashboard`) — open/overdue/high-severity/
  unassigned counts, resolved-this-week, breakdowns by category and
  location, oldest-open-tasks list with overdue dates flagged;
  restricted to Stack Maintenance and admin roles

**Now done (2026-09-28):**
- Admin-configurable quick report types, follow-up categories, and
  severities — new `QuickReportType` / `FollowupCategory` / `Severity`
  tables in `models.py`, managed at Admin -> Report options
  (`blueprints/admin.py`, `templates/admin_config.html`). Add, deactivate
  (never hard-deletes, so historical tasks/reports keep their label), and
  reorder. Severity now carries an explicit `weight` for urgency ranking,
  since the label text can no longer be trusted to sort alphabetically
  once it's admin-editable — queue/bulletin sorting was updated to use it.
  Defaults seed automatically on first startup (`ensure_default_config()`
  in `models.py`, called from `create_app()`), so this didn't need a
  manual migration step.
- Notification recipient lists are still not applicable — there's no
  email sending yet (Phase 3), so nothing to configure recipients for.
- **Fixed a real bug (2026-09-28):** a photo attached to a *completed*
  quick report (not a follow-up) was uploaded and saved correctly, but
  never appeared anywhere in the UI. Cause: `Attachment` rows from
  `quick_report()` only ever set `report_id`, never `task_id`, and
  `task_detail.html` only renders `task.attachments` — a completed quick
  report has no task, so its photo had nowhere to surface. Added a
  `/reports/log` page (nav: "Report log") listing every Report, newest
  first, with photo thumbnails and a link to the task if one exists.
  Visibility follows the same rule as the task queue: Student Assistants,
  Stack Maintenance and admins see everyone's; Other Library Staff see
  only their own.
- **Fixed a second bug (2026-09-28): all displayed times were 7 hours off.**
  Every timestamp is stored as UTC (`datetime.utcnow()`, correct practice
  for a DB), but every template rendered it with a raw `.strftime()` — so a
  6pm Pacific report showed as "1am" in the UI. Added `APP_TZ` (hardcoded
  to `America/Los_Angeles`, since that's the library) and a `to_local()`
  helper in `models.py`, wired up as a `local_dt` Jinja filter in `app.py`,
  and swapped every template's `.strftime()` call to go through it. Also
  fixed a related correctness bug this uncovered: the "overdue" check on
  the supervisor dashboard computed "today" from UTC, which for several
  hours every evening (Pacific) was actually already "tomorrow" in UTC —
  due dates near the boundary could misreport as/not-as overdue. Now uses
  `local_today()` instead.

**Still not done:**
- Printable QR sign sheets (PDF export with location name + QR + fallback
  URL) — for now, the admin QR page gives you the raw URL to turn into a
  QR image with any external generator

## Visual redesign (2026-09-29)

Replaced the whole look and feel, driven by a design brief Divyam gave in
chat (a general "clean modern ticketing system" spec) — adapted, not
copied wholesale, since this app is smaller in scope than a full helpdesk
(no customers/knowledge-base/bulk actions/reporting-exports).

**What changed:**
- `static/css/style.css` — full rewrite. Neutral white/light-gray surfaces,
  one primary accent (`--green`, now a teal `#0f6e5c`) reserved for brand
  and actions only. Introduced a strict 5-color semantic system used
  nowhere except status/severity badges: blue = open/active, amber =
  pending, green = resolved, gray = closed/inactive, red = urgent/overdue
  only. Same CSS variable *names* kept throughout so templates didn't all
  need touching — only the values and component-level rules changed.
  Dropped the serif display font in favor of one consistent sans (Inter)
  per the brief's "consistent typography, minimal visual noise" principle.
- Dashboard: stat tiles are now links to the underlying filtered task list
  (brief: "every metric clickable"). Replaced "Oldest open tasks" with a
  "Needs attention" table — overdue, high-severity, and unassigned tasks,
  deduped, each tagged with *why* it's there.
- Queue: added quick-filter chips (Open / Unassigned / High severity /
  Overdue) and a removable active-filter chip row, so filters stay visible
  and easy to clear one at a time instead of an all-or-nothing reset
  (`_apply_filters` in `blueprints/tasks.py` gained `unassigned=1` and
  `overdue=1` query flags to back this).
- Task detail: "Back to queue" now returns to the exact filtered/sorted
  view you came from (a `back` query param threaded through, validated as
  a local path only — never an open redirect) instead of always resetting
  to the plain unfiltered queue.
- Stylesheet is now cache-busted (`?v=2` on the `<link>`) since a plain
  CSS-file swap was getting silently served stale by the browser.

**Deliberately not done** (bigger functional features than a visual
pass, and not all applicable to this app's smaller scope): bulk actions
on the queue, saved/named views beyond the existing quick filters,
scheduled/exported reports, a Knowledge Base section, customer accounts.
Flag to Divyam if any of these turn out to be wanted.

## Phase 3 — Integrations (need answers from your boss / library IT first)

These depend on systems Stacks Reports doesn't control, so they can't
really be built until you have specifics:

- **SSO login**, replacing the PIN system — needs to know what identity
  system the library actually uses (Google Workspace? Shibboleth/CAS?
  something SJSU-wide?) and how to register an app against it
- **Email notifications** — needs a library-controlled sending
  account/service identity (the brief is explicit this shouldn't send from
  a personal account)
- **Retention/export policy** for reports, photos, and notification logs —
  a policy decision, not a technical one; worth pinning down before
  attachments pile up
- **Facilities work-order integration** — depends on whether there's an
  existing system to link to, or if it's just a free-text reference field

## Where things stand

**Phase 1 is built and tested end to end**, in a fresh project structure
(organized into Flask blueprints — `auth`, `reports`, `tasks`, `admin` —
since the app is meaningfully bigger than the single-file version).
Confirmed working via direct testing of every flow:

- QR scan → location auto-fills on the report form
- Quick "completed" report types save correctly
- Choosing "needs follow-up" hands off into the full follow-up form, which
  creates a Task and links back to the originating Report
- Task management: status changes, assignment, severity, due dates, work
  order references, resolving, reopening, and merging duplicates — each
  action correctly writes to the activity log
- Role permissions: Student Assistants see the shared queue read-only
  (no management controls, blocked with a 403 if they try to force a
  status change directly, but can still add comments); Other Library
  Staff only see tasks tied to their own submissions; Stack Maintenance
  staff and admins get full queue management
- Admin: creating Locations, generating QR codes for a Location, and
  creating/managing user accounts with roles all work

**Not yet done:** deploying this to the actual server (see
`DEPLOYMENT-NOTES.md` for what that involves, since this replaces the
schema of what's already running at `/var/www/project`), and Phase 2/3
features.
