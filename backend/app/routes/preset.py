"""
POST /api/apply-preset — apply a DB-named preset to an uploaded image.
"""

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image

from app.services.blur import is_allowed_image
from app.services.image_io import (
    ImageTooLargeError,
    encode_result,
    load_image_with_format,
    read_upload_capped,
)
from app.services.preset import (
    PresetAspectRatioError,
    PresetBusyError,
    PresetFileMissingError,
    PresetNotFoundError,
    PresetPathUnsafeError,
    PresetTextError,
    apply_named_preset,
    preset_job_slot,
)

router = APIRouter(tags=["preset"])


@router.post("/apply-preset")
async def apply_preset_endpoint(
    preset_name: str = Form(...),
    file: UploadFile = File(...),
    text: str | None = Form(None, max_length=200),
):
    """
    Accept a preset name (presets.preset_name), image upload, and optional
    `text` (used only when the preset JSON has text_input=yes); return JPEG bytes
    for a JPEG upload (opaque result), else PNG.
    """
    name = (preset_name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="preset_name is required.")

    if not file.content_type or not is_allowed_image(file.content_type, file.filename):
        raise HTTPException(
            status_code=400,
            detail="File must be an image (JPEG, PNG, WEBP, GIF, BMP, or TIFF).",
        )

    # Take the job slot before reading the upload into memory, and hold it
    # through encode: a busy server answers 503 without buffering or decoding
    # (Starlette has already spooled the body to a temp file).
    try:
        async with preset_job_slot():
            return await _apply_preset_upload(file, name, text)
    except PresetBusyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _apply_preset_upload(file: UploadFile, name: str, text: str | None) -> Response:
    try:
        raw = await read_upload_capped(file)
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        # Decode / filters / encode off the event loop: a DSLR-size file takes seconds.
        image, source_format = await asyncio.to_thread(load_image_with_format, raw)
        del raw  # up to 100 MiB; not needed once decoded
        result = await asyncio.to_thread(apply_named_preset, image, name, text=text)
        body, media_type = await asyncio.to_thread(encode_result, result, source_format)
    except PresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PresetFileMissingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PresetPathUnsafeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PresetAspectRatioError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PresetTextError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds maximum allowed pixel count.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not apply preset: {exc}",
        ) from exc

    return Response(content=body, media_type=media_type)
