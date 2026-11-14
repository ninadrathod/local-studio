"""
POST /api/preview — return a small JPEG/PNG preview of an upload the browser
can't render itself (e.g. HEIC outside Safari, TIFF).
"""

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

from app.services.blur import UNSUPPORTED_IMAGE_DETAIL, is_allowed_image
from app.services.preset import PresetBusyError, preset_job_slot
from app.services.image_io import (
    ImageTooLargeError,
    encode_preview,
    load_image,
    read_upload_capped,
)

router = APIRouter(tags=["preview"])


@router.post("/preview")
async def preview_endpoint(file: UploadFile = File(...)):
    """Accept a multipart image upload and return a downscaled preview."""
    if not file.content_type or not is_allowed_image(file.content_type, file.filename):
        raise HTTPException(status_code=400, detail=UNSUPPORTED_IMAGE_DETAIL)

    # Shares the preset job slot: a full-size decode costs the same memory here.
    try:
        async with preset_job_slot():
            return await _preview_upload(file)
    except PresetBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _preview_upload(file: UploadFile) -> Response:
    try:
        raw = await read_upload_capped(file)
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        image = await asyncio.to_thread(load_image, raw)
        del raw
        body, media_type = await asyncio.to_thread(encode_preview, image)
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds maximum allowed pixel count.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not process image: {exc}") from exc

    return Response(content=body, media_type=media_type)
