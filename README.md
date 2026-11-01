# Stack Maintenance Reports

An internal tool for library stacks student assistants and staff to report
floor issues — unorganized shelves, damaged materials, safety concerns — by
scanning a QR code posted at each stack location, and for Stack Maintenance
staff to triage and track that work to resolution.

## What it does

- **QR-based reporting** — each location has its own non-guessable QR link that
  opens a pre-filled report form.
- **Two report flows** — a two-tap quick log for routine completed work, and a
  follow-up form (category, severity, description, photo) that creates a
  trackable task.
- **Task lifecycle** — New → Waiting → Assigned → In Progress → Resolved →
  Closed / Cancelled, with every change recorded in an activity timeline.
- **Duplicate handling** — new follow-ups at a location with an open task can
  be linked to it instead of creating a duplicate; tasks can be merged.
- **Roles** — student assistant, stack maintenance, other staff, plus admin,
  enforced server-side.
- **Views** — task queue with filters, "my assignments", report log, a public
  bulletin board (no reporter names), and a supervisor dashboard.
- **Admin** — manage people (name + 4-digit PIN sign-in), locations, QR codes,
  and the report option lists.
- **Mobile-first UI** — designed to be used one-handed on a phone in the stacks.

## Stack

Python 3.12 · Flask · Flask-SQLAlchemy · Flask-Login · PostgreSQL (SQLite
locally) · Vercel Blob for photos · deployed on Vercel.

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app seed-demo   # fictional demo data; prints sign-in PINs
flask --app app run
```

`seed-demo` creates **fictional** people and locations only. For a real
deployment use `flask --app app init-db` instead, which creates the tables and
a single bootstrap admin account.

## Configuration

All configuration comes from environment variables — nothing secret is stored
in this repository.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing key (required in production) |
| `DATABASE_URL` / `POSTGRES_URL` | Database connection; falls back to local SQLite |
| `BLOB_READ_WRITE_TOKEN` | Vercel Blob token for photo uploads; falls back to `static/uploads/` |
| `SESSION_COOKIE_SECURE` | Set to `1` when served over HTTPS |
| `SEED_DEMO_ON_EMPTY` | Seed demo data automatically on an empty database |

See [`ROADMAP.md`](ROADMAP.md) for what's built and what's planned.
