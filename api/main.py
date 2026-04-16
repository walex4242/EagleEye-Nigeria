"""
main.py
────────
EagleEye-Nigeria FastAPI application entry point.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(
    title="EagleEye-Nigeria",
    description="Open-Source Satellite Intelligence for National Security",
    version="0.4.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount dashboard static files
dashboard_dir = os.path.join(
    os.path.dirname(__file__), "..", "dashboard",
)
if os.path.isdir(dashboard_dir):
    app.mount(
        "/static",
        StaticFiles(directory=dashboard_dir),
        name="static",
    )

# ── Register routes ──────────────────────────────────────────
from api.routes.hotspots import router as hotspots_router
app.include_router(
    hotspots_router, prefix="/api/v1", tags=["Hotspots"],
)

from api.routes.acled import router as acled_router
app.include_router(
    acled_router, prefix="/api/v1", tags=["ACLED Conflicts"],
)

try:
    from api.routes.ml import router as ml_router
    app.include_router(
        ml_router, prefix="/api/v1", tags=["ML Inference"],
    )
    print("[INIT] ✓ ML routes registered.")
except ImportError as e:
    print(f"[INIT] ML routes not available: {e}")

try:
    from api.routes.sentinel2 import router as sentinel2_router
    app.include_router(
        sentinel2_router,
        prefix="/api/v1",
        tags=["Sentinel-2 Vegetation"],
    )
    print("[INIT] ✓ Sentinel-2 vegetation change detection routes registered.")
except ImportError as e:
    print(f"[INIT] Sentinel-2 routes not available: {e}")


@app.get("/", include_in_schema=False)
def serve_dashboard():
    index_path = os.path.join(
        os.path.dirname(__file__), "..", "dashboard", "index.html",
    )
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {
        "message": (
            "EagleEye-Nigeria API is running. "
            "Dashboard not found."
        ),
    }


@app.get("/health")
def health_check():
    components = {
        "api": True,
        "firms_data": True,
        "analysis": True,
        "ml_detector": False,
        "acled": False,
        "sentinel2": False,
    }

    try:
        from ml.detector import TORCH_AVAILABLE
        components["ml_detector"] = TORCH_AVAILABLE
    except ImportError:
        pass

    try:
        components["acled"] = bool(os.getenv("ACLED_EMAIL", ""))
    except Exception:
        pass

    try:
        copernicus_user = os.getenv("COPERNICUS_USER", "")
        copernicus_pass = os.getenv("COPERNICUS_PASSWORD", "")
        components["sentinel2"] = bool(
            copernicus_user and copernicus_pass
        )
    except Exception:
        pass

    return {
        "status": "online",
        "project": "EagleEye-Nigeria",
        "version": "0.4.0",
        "components": components,
    }