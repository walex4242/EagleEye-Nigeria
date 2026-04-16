# EagleEye-Nigeria — Architecture Overview

## System Design

EagleEye-Nigeria is a three-layer system: data ingestion from space, analysis on the server, and visualisation in the browser.

```
┌─────────────────────────────────────────────────────┐
│                   DATA SOURCES                       │
│  NASA FIRMS (Thermal)  │  Sentinel-2 (Optical)      │
│  ACLED (Conflict)      │  Google Earth Engine        │
└────────────┬────────────────────────┬────────────────┘
             │                        │
             ▼                        ▼
┌─────────────────────────────────────────────────────┐
│                 INGESTION LAYER                      │
│  ingestion/firms.py   — FIRMS API fetch & parse      │
│  ingestion/sentinel.py — Sentinel-2 image pull       │
│  ingestion/acled.py   — Conflict event fetch         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                 ANALYSIS LAYER                       │
│  analysis/change_detection.py  — diff between passes │
│  analysis/anomaly_score.py     — 0–100 threat score  │
│  analysis/region_classifier.py — state + tier tagging│
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                  ML LAYER (Phase 3)                  │
│  ml/preprocessor.py  — image patch preparation      │
│  ml/detector.py      — MobileNetV3 CNN classifier    │
│  ml/train.py         — training script               │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                   API LAYER                          │
│  api/main.py            — FastAPI app + CORS         │
│  api/routes/hotspots.py — /api/v1/hotspots endpoints │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│                 DASHBOARD LAYER                      │
│  dashboard/index.html  — Leaflet.js map              │
│  Real-time markers, red zone overlays, popups        │
└─────────────────────────────────────────────────────┘
```

---

## Folder Structure

```
eagleeye-nigeria/
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI entry point
│   └── routes/
│       ├── __init__.py
│       └── hotspots.py      # /api/v1/hotspots endpoints
├── ingestion/
│   ├── __init__.py
│   └── firms.py             # NASA FIRMS data fetcher
├── analysis/
│   ├── __init__.py
│   ├── change_detection.py  # Before/after snapshot comparison
│   ├── anomaly_score.py     # Threat priority scoring (0–100)
│   └── region_classifier.py # Nigerian state + threat tier mapping
├── ml/
│   ├── __init__.py
│   ├── preprocessor.py      # Image preprocessing pipeline
│   ├── detector.py          # CampDetector CNN model
│   ├── train.py             # Training script
│   ├── data/                # Training images (not committed to Git)
│   └── weights/             # Saved model weights (not committed to Git)
├── dashboard/
│   └── index.html           # Leaflet.js map dashboard
├── docs/
│   ├── setup.md             # Installation guide
│   ├── api_reference.md     # API endpoint docs
│   └── architecture.md      # This file
├── tests/
│   └── ...
├── .env                     # Your local secrets (never commit)
├── .env.example             # Template for contributors
├── .gitignore
├── requirements.txt
├── README.md
└── CONTRIBUTING.md
```

---

## Data Flow — Phase 1 (Current)

```
User opens browser
      ↓
dashboard/index.html loads
      ↓
JS fetches GET /api/v1/hotspots?days=1
      ↓
api/routes/hotspots.py calls ingestion/firms.py
      ↓
firms.py calls NASA FIRMS API (or returns mock data)
      ↓
CSV response parsed → GeoJSON FeatureCollection
      ↓
Returned to dashboard → Leaflet.js plots markers
      ↓
User clicks marker → popup shows brightness, FRP, zone
```

---

## Security Considerations

- All sensitive keys are in `.env` — never committed to Git
- The `.gitignore` excludes `.env`, `service_account.json`, model weights, and raw satellite data
- Public-facing data can be subject to a configurable time delay (`PUBLIC_DATA_DELAY_MINUTES` in `.env`)
- API access control (JWT / API key auth) is planned for Phase 2 before any public deployment
