"""
The Local Studio API — FastAPI entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Allow the static frontend (any local origin) during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(blur_router, prefix="/api")
app.include_router(preset_router, prefix="/api")
app.include_router(preview_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(popular_router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
