"""
POST /api/blur — accept an image upload and return it blurred (JPEG in → JPEG out, else PNG).
"""

import asyncio

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

from app.services.blur import apply_blur, is_allowed_image
from app.services.preset import PresetBusyError, preset_job_slot
from app.services.image_io import (
    ImageTooLargeError,
    encode_result,
    load_image_with_format,
    read_upload_capped,
)

router = APIRouter(tags=["blur"])


@router.post("/blur")
async def blur_endpoint(file: UploadFile = File(...)):
    """
    Accept a multipart image upload, blur it, and return JPEG or PNG bytes.
    """
    if not file.content_type or not is_allowed_image(file.content_type, file.filename):
        raise HTTPException(
            status_code=400,
            detail="File must be an image (JPEG, PNG, WEBP, GIF, BMP, or TIFF).",
        )

    # Shares the preset job slot: a DSLR-size decode costs the same memory here.
    try:
        async with preset_job_slot():
            return await _blur_upload(file)
    except PresetBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _blur_upload(file: UploadFile) -> Response:
    try:
        raw = await read_upload_capped(file)
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        # Decode / encode off the event loop: a DSLR-size file takes a second or more.
        image, source_format = await asyncio.to_thread(load_image_with_format, raw)
        del raw
        blurred = await asyncio.to_thread(apply_blur, image)
        body, media_type = await asyncio.to_thread(encode_result, blurred, source_format)
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
