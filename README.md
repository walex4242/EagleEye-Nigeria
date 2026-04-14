# 🦅 EagleEye-Nigeria

### Open-Source Satellite Intelligence for National Security

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)
![Mission: Security](https://img.shields.io/badge/Mission-Security-red)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi&logoColor=white)
![PyTorch](https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white)
![NASA FIRMS](https://img.shields.io/badge/Data-NASA%20FIRMS-orange)
![Sentinel-2](https://img.shields.io/badge/Imagery-Sentinel--2-4CAF50)
![GEE](https://img.shields.io/badge/GIS-Google%20Earth%20Engine-34A853?logo=google&logoColor=white)
![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen)

**EagleEye-Nigeria** is an open-source initiative designed to provide **proactive** security monitoring across Nigeria using Satellite Intelligence (SATINT) and AI.

While traditional security apps rely on human reports — which can be slow or dangerous to send — EagleEye-Nigeria looks from above. We use multi-spectral satellite imagery and thermal data to detect bandit encampments, forest clearings, and movement corridors in near real-time.

---

## 🚀 The Core Difference

Most existing security tools in Nigeria are **reactive**. EagleEye-Nigeria is **proactive**:

| Feature | Traditional Tools | EagleEye-Nigeria |
|---|---|---|
| Data source | Human reports | Satellite imagery |
| Speed | Hours to days | Near real-time |
| Civilian risk | High (informant exposure) | Zero |
| Coverage | Urban-biased | Remote terrain capable |

- **Thermal Anomaly Detection** — Uses NASA FIRMS to spot illegal campfires and heat signatures in remote forests.
- **Vegetation Disturbance Analysis** — Uses Sentinel-2 to identify new, man-made clearings under dense canopy.
- **Zero Human Risk** — Intelligence gathered from orbit removes the risk of informant retaliation against civilians.

---

## 🛠️ Technology Stack

### Data Sources
| Source | Type | Use Case |
|---|---|---|
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | Thermal / Fire | Active fire & heat anomaly detection |
| [Sentinel-2 (ESA)](https://sentinel.esa.int/web/sentinel/missions/sentinel-2) | Optical / Infrared | Vegetation change & clearing detection |
| [ACLED](https://acleddata.com) | Conflict Data | Ground-truth event correlation |

### Backend & Geospatial
- **Runtime:** Python 3.10+
- **API Framework:** [FastAPI](https://fastapi.tiangolo.com/)
- **Geospatial:** [Google Earth Engine (GEE)](https://earthengine.google.com/), [GeoPandas](https://geopandas.org/), [Shapely](https://shapely.readthedocs.io/)
- **Visualisation:** [Leaflet.js](https://leafletjs.com/)

### AI / ML
- **Framework:** [PyTorch](https://pytorch.org/)
- **Computer Vision:** [OpenCV](https://opencv.org/)
- **Tasks:** Automated camp detection, change detection, anomaly classification

---

## 🗺️ Project Roadmap

### Phase 1 — The "Heat" Map *(Months 1–2)*
- [ ] Integrate NASA FIRMS API for daily thermal hotspot monitoring
- [ ] Build a dashboard to visualise hotspots in known red zones (Northwest / Northeast corridors)
- [ ] Establish baseline alert thresholds per region

### Phase 2 — Change Detection *(Months 3–4)*
- [ ] Automate difference imaging between weekly Sentinel-2 passes
- [ ] Flag new forest clearings and suspicious road-cutting activity
- [ ] Build a change-event log with timestamps and coordinates

### Phase 3 — AI Classification & OSINT *(Months 5–6)*
- [ ] Train a Computer Vision model to distinguish legal farming activity from illegal encampments
- [ ] Integrate OSINT feeds for ground-truth verification
- [ ] Publish a public threat-density heatmap (with strategic delay applied)

---

## 📁 Project Structure

```
eagleeye-nigeria/
├── api/                  # FastAPI backend
│   ├── routes/           # Endpoint definitions
│   └── models/           # Pydantic schemas
├── ingestion/            # Data pipeline (FIRMS, Sentinel-2, ACLED)
├── analysis/             # Change detection & anomaly logic
├── ml/                   # PyTorch model training & inference
├── dashboard/            # Leaflet.js frontend
├── tests/                # Unit and integration tests
└── docs/                 # Architecture diagrams & field guides
```

---

## 🤝 How to Contribute

We are looking for engineers and researchers to help secure the nation through code.

**Roles needed:**

- **GIS Engineers** — Refine satellite data processing pipelines and coordinate systems.
- **Fullstack Developers** — Build a robust, low-bandwidth dashboard optimised for field use.
- **AI Researchers** — Build and evaluate models that identify man-made structures in remote terrain.
- **OSINT Analysts** — Verify satellite "hits" against real-world incidents and open data feeds.

**Getting started:**

1. Fork this repository.
2. Open the `ISSUES` tab and filter by the `good-first-issue` label.
3. Read [`CONTRIBUTING.md`](CONTRIBUTING.md) for code style, branch naming, and PR guidelines.
4. Reach out via [LinkedIn / contact link] to join the core team.

---

## ⚙️ Local Development

```bash
# Clone the repo
git clone https://github.com/your-org/eagleeye-nigeria.git
cd eagleeye-nigeria

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment variables
cp .env.example .env

# Start the development server
uvicorn api.main:app --reload
```

> **Requirements:** Python 3.10+, a NASA FIRMS API key, and Google Earth Engine credentials. See [`docs/setup.md`](docs/setup.md) for the full guide.

---

## ⚖️ Ethics & Safety

EagleEye-Nigeria is built for **peacebuilding and national security**.

- **Access Control:** To prevent misuse by criminal elements, sensitive data outputs may be subject to a strategic time delay or role-based access restrictions.
- **No Targeting of Individuals:** The system detects patterns and anomalies at a structural level — it does not identify or track individuals.
- **Institutional Partnership:** This project is designed to support, not replace, the efforts of the Nigerian Armed Forces, DSS, and local security agencies.
- **Responsible Disclosure:** If you discover a vulnerability or misuse vector, please report it to [security contact] rather than opening a public issue.

---

## 📄 License

This project is licensed under the **MIT License** — see the [`LICENSE`](LICENSE) file for details.

---

*"The eye of the eagle sees what the ground-dweller cannot."*
