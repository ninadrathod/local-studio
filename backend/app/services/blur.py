"""
Blur image-processing helpers.
"""

from PIL import Image, ImageFilter

# Gaussian radius — higher = softer blur
DEFAULT_BLUR_RADIUS = 12

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/x-ms-bmp",
    "image/heic",
    "image/heif",
}

ALLOWED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif",
)

# Shared 400 detail for uploads that fail `is_allowed_image`.
UNSUPPORTED_IMAGE_DETAIL = "File must be an image (JPEG, PNG, WEBP, GIF, BMP, TIFF, or HEIC)."


def is_allowed_image(content_type: str | None, filename: str | None) -> bool:
    """Return True if the upload looks like a supported image."""
    if content_type and content_type.lower() in ALLOWED_CONTENT_TYPES:
        return True
    if filename and filename.lower().endswith(ALLOWED_EXTENSIONS):
        return True
    return False


def apply_blur(image: Image.Image, radius: int = DEFAULT_BLUR_RADIUS) -> Image.Image:
    """Apply a Gaussian blur and return a new image (RGBA-safe)."""
    # Convert palette / exotic modes so blur + PNG export stay reliable
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    return image.filter(ImageFilter.GaussianBlur(radius=radius))
