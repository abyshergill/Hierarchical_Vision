"""Upload and text sanitisation shared by every form in the project.

Images
------
* Only .jpg / .jpeg / .png are accepted, at most ``settings.MAX_IMAGE_UPLOAD_MB`` (default 20 MB).
* The extension and the browser-supplied MIME type are NEVER trusted: the bytes are decoded with Pillow and the
  detected format must be JPEG or PNG.
* Accepted pictures are re-encoded from their pixels, which drops EXIF/GPS data, ICC blobs, comments, appended
  payloads and polyglot tricks. The stored file gets a random name and the extension of its real format.
* Width/height and total-pixel caps protect the server from decompression bombs.
"""
import io
import os
import re
import unicodedata
import uuid

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = ["jpg", "jpeg", "png"]            # SVG, GIF, WebP, HTML ... are deliberately NOT allowed
IMAGE_ACCEPT = ".jpg,.jpeg,.png,image/jpeg,image/png"
MAX_IMAGE_SIDE = 8000                                # px per side
MAX_IMAGE_PIXELS = 50_000_000                        # total pixels (~50 MP) - bounds memory while decoding
_FORMATS = {"JPEG": ("jpg", "image/jpeg"), "PNG": ("png", "image/png")}
_BAD_IMAGE = "Upload a valid JPG, JPEG or PNG picture. The file is damaged or is not really an image."


def max_upload_mb():
    return getattr(settings, "MAX_IMAGE_UPLOAD_MB", 20)


def image_widget_attrs(**extra):
    """HTML attributes for file inputs: browser-side filter + hooks for static/js/app.js (previews, size check)."""
    attrs = {"accept": IMAGE_ACCEPT, "data-image-upload": "1", "data-max-mb": str(max_upload_mb())}
    attrs.update(extra)
    return attrs


def _is_new_upload(file):
    """Skip re-validating files that are already stored (no disk access on every save)."""
    return getattr(file, "_committed", None) is not True


# --------------------------------------------------------------------------- model-level validators
def validate_image_size(file):
    if not _is_new_upload(file):
        return
    limit = max_upload_mb() * 1024 * 1024
    if file.size > limit:
        raise ValidationError(f"Image is too large (max {max_upload_mb()} MB).")


def validate_image_dimensions(file):
    if not _is_new_upload(file):
        return
    from django.core.files.images import get_image_dimensions

    try:
        width, height = get_image_dimensions(file)
    except Exception:  # unreadable images are rejected by validate_image_content / the form field
        return
    if width and height and (max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS):
        raise ValidationError(f"Image dimensions are too large (max {MAX_IMAGE_SIDE}px per side).")


def validate_image_content(file):
    """Defence in depth for code paths that bypass SecureImageField (e.g. admin inlines): real format must be JPEG/PNG."""
    if not _is_new_upload(file):
        return
    try:
        file.seek(0)
        with Image.open(file) as img:
            fmt = img.format
    except Exception:
        raise ValidationError(_BAD_IMAGE)
    finally:
        try:
            file.seek(0)
        except Exception:
            pass
    if fmt not in _FORMATS:
        raise ValidationError("Only JPG, JPEG and PNG pictures are allowed.")


# --------------------------------------------------------------------------- the sanitiser
def secure_image(upload):
    """Validate + re-encode one uploaded picture. Returns a NEW in-memory file or raises ValidationError."""
    name = getattr(upload, "name", "") or ""
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Only .jpg, .jpeg and .png files are allowed.", code="invalid_extension")
    if upload.size > max_upload_mb() * 1024 * 1024:
        raise ValidationError(f"Image is too large (max {max_upload_mb()} MB).", code="too_large")
    try:
        upload.seek(0)
        img = Image.open(upload)
        fmt = img.format
        if fmt not in _FORMATS:
            raise ValidationError("Only JPG, JPEG and PNG pictures are allowed.", code="invalid_format")
        width, height = img.size
        if not width or not height or max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
            raise ValidationError(f"Image dimensions are too large (max {MAX_IMAGE_SIDE}px per side).", code="too_big")
        has_transparency = "transparency" in img.info
        img.load()
        img = ImageOps.exif_transpose(img)           # honour the camera's rotation before the EXIF is dropped
        out = io.BytesIO()
        if fmt == "JPEG":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(out, "JPEG", quality=92, optimize=True)
        else:
            if img.mode == "P":
                img = img.convert("RGBA" if has_transparency else "RGB")
            elif img.mode not in ("RGB", "RGBA", "L", "LA"):
                img = img.convert("RGBA" if "A" in img.mode else "RGB")
            img.save(out, "PNG", optimize=True)
    except ValidationError:
        raise
    except Exception:       # UnidentifiedImageError, truncated data, DecompressionBombError, OSError ...
        raise ValidationError(_BAD_IMAGE, code="invalid_image")
    safe_ext, content_type = _FORMATS[fmt]
    out.seek(0)
    return InMemoryUploadedFile(
        out, getattr(upload, "field_name", None), f"{uuid.uuid4().hex[:16]}.{safe_ext}", content_type,
        out.getbuffer().nbytes, None,
    )


class SecureImageField(forms.ImageField):
    """ImageField that only accepts JPG/JPEG/PNG up to MAX_IMAGE_UPLOAD_MB and hands back a re-encoded copy."""

    def __init__(self, *args, **kwargs):
        kwargs.pop("max_length", None)       # the stored name is replaced by a random one, so the length is irrelevant
        super().__init__(*args, **kwargs)

    def to_python(self, data):
        if data in self.empty_values:
            return None
        try:
            if not data.name:
                raise AttributeError
            size = data.size
        except AttributeError:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        if not size and not self.allow_empty_file:
            raise ValidationError(self.error_messages["empty"], code="empty")
        return secure_image(data)


# --------------------------------------------------------------------------- text
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c\ufeff]")   # text-direction spoofing + BOM


def clean_text(value, multiline=True):
    """Normalise user text: NFC, no control / bidi-override characters, tidy whitespace. (HTML is escaped on output.)"""
    value = unicodedata.normalize("NFC", str(value or ""))
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _BIDI.sub("", _CONTROL.sub("", value))
    if not multiline:
        return " ".join(value.split())
    lines = [line.rstrip() for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
