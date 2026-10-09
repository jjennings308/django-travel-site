"""HEIC/HEIF uploads (iPhone photos) are converted to JPEG before they are stored:
most browsers can't display HEIC. Conversion applies the EXIF orientation and drops
the metadata, which also removes GPS location."""
import io
import os

from django.core.files.base import ContentFile
from django.db import models
from PIL import Image, ImageOps

HEIC_EXTENSIONS = {".heic", ".heif"}
JPEG_QUALITY = 88


def is_heic_name(name):
    return os.path.splitext(name or "")[1].lower() in HEIC_EXTENSIONS


def heic_to_jpeg(file):
    """JPEG bytes for a HEIC file-like object."""
    file.seek(0)
    with Image.open(file) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


def convert_heic_uploads(instance):
    """Replace each not-yet-stored HEIC file on ``instance`` with a JPEG copy
    (same base name, .jpg). Stored files are left alone. Returns the converted
    field names."""
    converted = []
    for field in instance._meta.concrete_fields:
        if not isinstance(field, models.FileField):
            continue
        value = getattr(instance, field.attname)
        if not value or getattr(value, "_committed", True) or not is_heic_name(value.name):
            continue
        base = os.path.splitext(os.path.basename(value.name))[0]
        setattr(instance, field.attname, ContentFile(heic_to_jpeg(value.file), name=f"{base}.jpg"))
        converted.append(field.name)
    return converted


def shrink_image(file, max_side):
    """A ContentFile of ``file`` scaled so its longest side is at most ``max_side``
    (upright, metadata dropped; PNG/GIF/WebP keep their format, everything else
    becomes JPEG), or None when it is already small enough."""
    file.seek(0)
    with Image.open(file) as image:
        if max(image.size) <= max_side:
            file.seek(0)
            return None
        fmt = image.format if image.format in ("PNG", "GIF", "WEBP") else "JPEG"
        image = ImageOps.exif_transpose(image)
        image.thumbnail((max_side, max_side))
        if fmt == "JPEG":
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format=fmt, **({"quality": JPEG_QUALITY, "optimize": True} if fmt == "JPEG" else {}))
    base = os.path.splitext(os.path.basename(file.name or "picture"))[0]
    ext = {"JPEG": "jpg", "PNG": "png", "GIF": "gif", "WEBP": "webp"}[fmt]
    return ContentFile(out.getvalue(), name=f"{base}.{ext}")
