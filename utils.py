import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from flask import current_app
from werkzeug.utils import secure_filename

from models import ALLOWED_PHOTO_EXTENSIONS

BLOB_API = "https://blob.vercel-storage.com"
CONTENT_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp",
}


def _upload_to_blob(token, stored_name, ext, data):
    req = urllib.request.Request(
        f"{BLOB_API}/uploads/{urllib.parse.quote(stored_name)}",
        data=data, method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-version": "7",
            "x-content-type": CONTENT_TYPES[ext],
            "x-add-random-suffix": "0",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())["url"]


def save_photo(file_storage):
    """Store an uploaded photo and return (stored_ref, original_name).
    stored_ref is a public Blob URL on Vercel, or a filename under
    static/uploads/ when running locally without a Blob token. Returns
    (None, None) for no file and (None, "error:type" / "error:upload") on failure."""
    if not file_storage or not file_storage.filename:
        return None, None

    original = file_storage.filename
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_PHOTO_EXTENSIONS:
        return None, "error:type"

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    token = current_app.config.get("BLOB_READ_WRITE_TOKEN")

    if token:
        try:
            url = _upload_to_blob(token, stored_name, ext, file_storage.read())
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            return None, "error:upload"
        return url, secure_filename(original)

    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    file_storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name))
    return stored_name, secure_filename(original)
