"""
The Local Studio API — FastAPI entry point.
"""

from fastapi import FastAPI

from app.routes.blur import router as blur_router
from app.routes.popular import router as popular_router
from app.routes.preset import router as preset_router
from app.routes.preview import router as preview_router
from app.routes.search import router as search_router

app = FastAPI(
    title="The Local Studio API",
    description="Upload an image for blur or named-preset edits.",
    version="0.1.0",
)

# No CORS middleware: the browser only ever calls the API same-origin, through the
# frontend container's nginx proxy, and the backend has no port of its own.

app.include_router(blur_router, prefix="/api")
app.include_router(preset_router, prefix="/api")
app.include_router(preview_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(popular_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
