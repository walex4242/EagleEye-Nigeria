# EagleEye-Nigeria — API Reference

Base URL (development): `http://127.0.0.1:8000`

All endpoints return JSON. All hotspot data is GeoJSON-compliant.

---

## Health

### `GET /health`

Returns server status.

**Response:**

```json
{
  "status": "online",
  "project": "EagleEye-Nigeria",
  "version": "0.1.0"
}
```

---

## Hotspots

### `GET /api/v1/hotspots`

Returns a GeoJSON FeatureCollection of thermal detections for Nigeria.

**Query Parameters:**

| Parameter | Type    | Default | Description                         |
| --------- | ------- | ------- | ----------------------------------- |
| `days`    | integer | `1`     | Number of past days to query (1–10) |
| `country` | string  | `NGA`   | ISO 3166-1 alpha-3 country code     |

**Example Request:**

```
GET /api/v1/hotspots?days=3&country=NGA
```

**Example Response:**

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [8.5, 12.0]
      },
      "properties": {
        "brightness": 320.0,
        "confidence": "H",
        "acq_date": "2026-04-14",
        "acq_time": "0130",
        "frp": "25.4",
        "red_zone": "Northwest Corridor",
        "source": "VIIRS_SNPP_NRT"
      }
    }
  ],
  "metadata": {
    "count": 1,
    "source": "NASA FIRMS",
    "sensor": "VIIRS SNPP NRT"
  }
}
```

**Confidence values:**

- `H` — High confidence fire/heat detection
- `N` — Nominal (medium) confidence
- `L` — Low confidence

---

### `GET /api/v1/hotspots/summary`

Returns aggregate counts of hotspots by confidence tier.

**Query Parameters:**

| Parameter | Type    | Default | Description                |
| --------- | ------- | ------- | -------------------------- |
| `days`    | integer | `1`     | Number of past days (1–10) |

**Example Response:**

```json
{
  "total": 14,
  "high_confidence": 6,
  "medium_confidence": 5,
  "low_confidence": 3,
  "days_queried": 1
}
```

---

## Analysis Modules (Internal)

These are Python modules called internally by the API, not exposed as HTTP endpoints yet. They will be wired to routes in Phase 2.

### `analysis.change_detection.detect_changes(previous, current)`

Compares two GeoJSON snapshots and returns new, persistent, and resolved hotspots.

**Returns:**

```json
{
  "new": [...],
  "persistent": [...],
  "resolved": [...],
  "summary": {
    "new_count": 3,
    "persistent_count": 5,
    "resolved_count": 1,
    "high_confidence_new": 2,
    "risk_level": "HIGH"
  }
}
```

**Risk levels:** `LOW` → `ELEVATED` → `HIGH` → `CRITICAL`

---

### `analysis.anomaly_score.score_hotspots(geojson)`

Scores each hotspot on a 0–100 threat priority scale and adds `threat_score` and `priority` fields.

**Priority tiers:**

- `CRITICAL` — score ≥ 80
- `HIGH` — score ≥ 60
- `ELEVATED` — score ≥ 40
- `MONITOR` — score < 40

**Scoring factors:**

- Confidence level (up to 60 pts base)
- Fire Radiative Power / FRP (up to 20 pts)
- Brightness temperature (up to 10 pts)
- Night-time detection bonus (10 pts)
- Red zone multiplier (1.2×–1.4×)

---

### `analysis.region_classifier.enrich_with_regions(geojson)`

Adds Nigerian state name and threat tier to each hotspot feature.

**Threat tiers:**

- `Tier 1 — Active Conflict` (Zamfara, Borno, Yobe, Katsina, Sokoto)
- `Tier 2 — Elevated Risk`
- `Tier 3 — Monitored`
- `Tier 4 — Standard Monitoring`

---

## Interactive Docs

When the server is running, full interactive Swagger UI is available at:

```
http://127.0.0.1:8000/docs
```

ReDoc alternative:

```
http://127.0.0.1:8000/redoc
```
