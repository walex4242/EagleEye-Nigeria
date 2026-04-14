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
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount dashboard static files
app.mount("/static", StaticFiles(directory="dashboard"), name="static")

# Import and register routes
from api.routes.hotspots import router as hotspots_router
app.include_router(hotspots_router, prefix="/api/v1", tags=["Hotspots"])


@app.get("/", include_in_schema=False)
def serve_dashboard():
    return FileResponse("dashboard/index.html")


@app.get("/health")
def health_check():
    return {
        "status": "online",
        "project": "EagleEye-Nigeria",
        "version": "0.1.0"
    }