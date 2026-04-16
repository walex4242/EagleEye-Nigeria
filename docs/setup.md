# EagleEye-Nigeria — Setup Guide

This guide walks you through getting EagleEye-Nigeria running from scratch.

---

## Prerequisites

- Python 3.10 or higher (3.13 recommended)
- Git
- A free NASA Earthdata account
- A free Google Earth Engine account (for Phase 2+)

---

## 1. Clone the Repository

```bash
git clone https://github.com/your-org/eagleeye-nigeria.git
cd eagleeye-nigeria
```

---

## 2. Create a Virtual Environment

```bash
python -m venv .venv

# Activate it:
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt --only-binary=:all:
```

If `torch` fails, install it separately first:

```bash
# CPU only (recommended for development)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Then install the rest
pip install -r requirements.txt --only-binary=:all:
```

---

## 4. Configure Environment Variables

```bash
copy .env.example .env     # Windows
cp .env.example .env       # macOS / Linux
```

Open `.env` and fill in your keys. See the sections below for how to get each one.

---

## 5. API Key Registration

### NASA FIRMS (Thermal Hotspot Data)

1. Go to [https://firms.modaps.eosdis.nasa.gov/api/area/](https://firms.modaps.eosdis.nasa.gov/api/area/)
2. Click **Get a FIRMS API Key**
3. Register with your NASA Earthdata account (free at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov))
4. Copy the key into `.env` as `NASA_FIRMS_API_KEY`

> **Note:** Without a FIRMS key the app still runs using built-in mock data. Add the key when you are ready for live satellite feeds.

### Google Earth Engine (Phase 2 — Vegetation Analysis)

1. Go to [https://earthengine.google.com/](https://earthengine.google.com/) and sign up
2. Once approved, go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
3. Create a project and enable the **Earth Engine API**
4. Create a **Service Account** and download the JSON key
5. Place the JSON key in the project root as `service_account.json`
6. Add the service account email to `.env` as `GEE_SERVICE_ACCOUNT`

### ACLED (Conflict Data)

1. Register at [https://acleddata.com/register/](https://acleddata.com/register/)
2. You will receive an API key by email
3. Add it to `.env` as `ACLED_API_KEY`

---

## 6. Create Required Folders

```bash
# Windows PowerShell
mkdir api, ingestion, analysis, ml, dashboard, docs, tests
New-Item api/__init__.py, api/routes/__init__.py, ingestion/__init__.py, analysis/__init__.py, ml/__init__.py -ItemType File

# macOS / Linux
mkdir -p api/routes ingestion analysis ml dashboard docs tests
touch api/__init__.py api/routes/__init__.py ingestion/__init__.py analysis/__init__.py ml/__init__.py
```

---

## 7. Run the Development Server

```bash
uvicorn api.main:app --reload
```

Then open your browser at:

```
http://127.0.0.1:8000
```

You should see the live dark-themed map dashboard with Nigeria's red zones marked.

---

## 8. API Endpoints

| Method | Endpoint                   | Description                       |
| ------ | -------------------------- | --------------------------------- |
| GET    | `/`                        | Serves the map dashboard          |
| GET    | `/health`                  | Server health check               |
| GET    | `/api/v1/hotspots`         | Fetch thermal hotspots (GeoJSON)  |
| GET    | `/api/v1/hotspots/summary` | Hotspot count by confidence tier  |
| GET    | `/docs`                    | Interactive API docs (Swagger UI) |

**Query parameters for `/api/v1/hotspots`:**

- `days` — number of past days to query (1–10, default 1)
- `country` — ISO 3166-1 alpha-3 country code (default `NGA`)

---

## 9. ML Model Setup (Phase 3)

To train the camp detector model you will need labelled satellite image patches:

```
ml/data/
    train/
        legal_activity/           ← images of farms, villages, cleared fields
        suspicious_encampment/    ← images of flagged encampment sites
    val/
        legal_activity/
        suspicious_encampment/
```

Once data is in place:

```bash
python -m ml.train
```

Trained weights are saved to `ml/weights/camp_detector_v1.pt` and automatically loaded on server start.

---

## 10. Running Tests

```bash
pytest tests/ -v
```

---

## Troubleshooting

| Problem                                                | Fix                                                                                |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `ModuleNotFoundError: No module named 'pkg_resources'` | Run `pip install --upgrade pip setuptools wheel`                                   |
| `shapely` build fails on Windows                       | Use `pip install --only-binary=:all: shapely`                                      |
| `torch` installation fails                             | Install from `https://download.pytorch.org/whl/cpu`                                |
| Dashboard shows no data                                | Check that `NASA_FIRMS_API_KEY` is set in `.env`; mock data shows if it is missing |
| `uvicorn` not found                                    | Make sure your virtual environment is activated                                    |
