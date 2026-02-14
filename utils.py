import os
import re

UPLOAD_ROOT = "static/uploads"

def slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')

def get_gallery_path(client_id, gallery_title):
    gallery_slug = slugify(gallery_title)

    path = os.path.join(
        UPLOAD_ROOT,
        f"client_{client_id}",
        gallery_slug
    )

    os.makedirs(path, exist_ok=True)
    return path, gallery_slug
