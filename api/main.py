"""
main.py
────────
EagleEye-Nigeria FastAPI application entry point (unified).
"""

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── App ───────────────────────────────────────────────────────
app = FastAPI(
    title="EagleEye-Nigeria",
    description="Satellite Intelligence for National Security",
    version="2.0.0",
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

# ── Database Admin Panel (like Prisma Studio) ─────────────────
from sqladmin import Admin, ModelView
from api.database.engine import engine
from api.database.models import (
    User,
    SavedAlert,
    HotspotRecord,
    AuditLog,
    DataSnapshot,
    MovementRecord,
    VegetationEvent,
)

admin = Admin(
    app,
    engine,
    title="EagleEye DB Admin",
    base_url="/admin",
)


class UserAdmin(ModelView, model=User):
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-user-shield"
    column_list = [
        "id", "username", "email", "full_name",
        "role", "is_active", "is_verified", "created_at",
    ]
    column_searchable_list = ["username", "email", "full_name"]
    column_sortable_list = ["created_at", "username", "role"]
    column_default_sort = ("created_at", True)
    can_create = True
    can_edit = True
    can_delete = False
    can_export = True
    page_size = 25


class SavedAlertAdmin(ModelView, model=SavedAlert):
    name = "Alert"
    name_plural = "Saved Alerts"
    icon = "fa-solid fa-bell"
    column_list = "__all__"
    can_create = True
    can_edit = True
    can_delete = True
    can_export = True
    page_size = 25


class HotspotRecordAdmin(ModelView, model=HotspotRecord):
    name = "Hotspot"
    name_plural = "Hotspot Records"
    icon = "fa-solid fa-fire"
    column_list = "__all__"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 50


class AuditLogAdmin(ModelView, model=AuditLog):
    name = "Audit Log"
    name_plural = "Audit Logs"
    icon = "fa-solid fa-clipboard-list"
    column_list = "__all__"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 50


class DataSnapshotAdmin(ModelView, model=DataSnapshot):
    name = "Snapshot"
    name_plural = "Data Snapshots"
    icon = "fa-solid fa-camera"
    column_list = "__all__"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 25


class MovementRecordAdmin(ModelView, model=MovementRecord):
    name = "Movement"
    name_plural = "Movement Records"
    icon = "fa-solid fa-route"
    column_list = "__all__"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 50


class VegetationEventAdmin(ModelView, model=VegetationEvent):
    name = "Vegetation Event"
    name_plural = "Vegetation Events"
    icon = "fa-solid fa-leaf"
    column_list = "__all__"
    can_create = False
    can_edit = False
    can_delete = False
    can_export = True
    page_size = 25


admin.add_view(UserAdmin)
admin.add_view(SavedAlertAdmin)
admin.add_view(HotspotRecordAdmin)
admin.add_view(AuditLogAdmin)
admin.add_view(DataSnapshotAdmin)
admin.add_view(MovementRecordAdmin)
admin.add_view(VegetationEventAdmin)

print("[INIT] ✓ Admin panel registered at /admin")

# ── Database & Auth Seed ──────────────────────────────────────
from api.database.engine import init_db, SessionLocal


@app.on_event("startup")
async def startup():
    init_db()

    from api.auth.seed import seed_admin
    db = SessionLocal()
    try:
        seed_admin(db)
    finally:
        db.close()

    print("[INIT] ✓ Database initialized & admin seeded")


# ── Auth Routes ───────────────────────────────────────────────
from api.auth.routes import router as auth_router
app.include_router(auth_router, tags=["Auth"])
print("[INIT] ✓ Auth routes registered.")

# ── Core Routes ───────────────────────────────────────────────
from api.routes.hotspots import router as hotspots_router
app.include_router(hotspots_router, prefix="/api/v1", tags=["Hotspots"])

from api.routes.acled import router as acled_router
app.include_router(acled_router, prefix="/api/v1", tags=["ACLED Conflicts"])

# Alerts router — paths already include "/api/" prefix internally
from api.routes.alerts import router as alerts_router
app.include_router(alerts_router, tags=["Intelligence Alerts"])
print("[INIT] ✓ Core routes registered (hotspots, acled, alerts).")

# ── Optional Routes ───────────────────────────────────────────
try:
    from api.routes.ml import router as ml_router
    app.include_router(ml_router, prefix="/api/v1", tags=["ML Inference"])
    print("[INIT] ✓ ML routes registered.")
except ImportError as e:
    print(f"[INIT] ML routes not available: {e}")

try:
    from api.routes.sentinel2 import router as sentinel2_router
    app.include_router(
        sentinel2_router, prefix="/api/v1", tags=["Sentinel-2 Vegetation"],
    )
    print("[INIT] ✓ Sentinel-2 routes registered.")
except ImportError as e:
    print(f"[INIT] Sentinel-2 routes not available: {e}")

# ── PWA / Dashboard Static Files ─────────────────────────────
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"

if dashboard_dir.exists():
    static_dir = dashboard_dir / "static"
    if static_dir.exists():
        app.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="static",
        )

    @app.get("/manifest.json", include_in_schema=False)
    async def manifest():
        return FileResponse(str(dashboard_dir / "manifest.json"))

    @app.get("/service-worker.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            str(dashboard_dir / "service-worker.js"),
            media_type="application/javascript",
        )

    @app.get("/offline.html", include_in_schema=False)
    async def offline():
        return FileResponse(str(dashboard_dir / "offline.html"))

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index = dashboard_dir / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return {
            "message": "EagleEye-Nigeria API is running. Dashboard index.html not found.",
        }
else:

    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "EagleEye-Nigeria API is running. Dashboard not deployed.",
        }

# ── Health Check ──────────────────────────────────────────────


@app.get("/health")
async def health_check():
    components = {
        "api": True,
        "auth": True,
        "admin_panel": True,
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

    components["acled"] = bool(os.getenv("ACLED_EMAIL", ""))
    components["sentinel2"] = bool(
        os.getenv("COPERNICUS_USER") and os.getenv("COPERNICUS_PASSWORD")
    )

    return {
        "status": "operational",
        "project": "EagleEye-Nigeria",
        "version": "2.0.0",
        "admin_url": "/admin",
        "components": components,
    }