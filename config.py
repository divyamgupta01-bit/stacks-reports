import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _database_uri():
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or f"sqlite:///{os.path.join(BASE_DIR, 'stacks.db')}"
    )
    # Neon/Vercel hand out postgres:// URLs; SQLAlchemy + psycopg 3 wants this form.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    # Supabase's pooler URLs can carry a non-libpq "supa=" parameter that psycopg rejects.
    if "supa=" in url:
        base, _, query = url.partition("?")
        kept = [q for q in query.split("&") if q and not q.startswith("supa=")]
        url = base + ("?" + "&".join(kept) if kept else "")
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")

    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Serverless instances come and go; recycle dead pooled connections.
    # prepare_threshold=None: Supabase's transaction pooler (pgbouncer) can't do
    # server-side prepared statements, which psycopg 3 would otherwise start using.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
        "connect_args": {"prepare_threshold": None} if not _database_uri().startswith("sqlite") else {},
    }

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    # Vercel functions reject request bodies over 4.5 MB.
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
