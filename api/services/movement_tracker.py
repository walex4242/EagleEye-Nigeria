"""
movement_tracker.py
───────────────────
Tracks temporal patterns in hotspot clusters to detect
movement corridors used by bandits/terrorists.

Analyzes:
  - Hotspot migration over time (fires moving = camp relocation)
  - Recurring patterns (same area, regular intervals)
  - Corridor detection (chain of hotspots along a route)
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Callable
from dataclasses import dataclass, field, asdict

ALERTS_DIR = Path(__file__).parent.parent.parent / "data" / "alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class MovementVector:
    """Represents detected movement between two time periods."""

    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    origin_state: str
    destination_state: str
    distance_km: float
    bearing_degrees: float
    time_delta_hours: float
    speed_kmh: float
    hotspot_count_origin: int
    hotspot_count_destination: int
    confidence: float
    detection_time: str
    classification: str  # "camp_relocation", "corridor", "rapid_relocation"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ThreatAlert:
    """An actionable alert for military/security notification."""

    alert_id: str
    priority: str  # "critical", "high", "medium", "low"
    title: str
    description: str
    latitude: float
    longitude: float
    state: str
    zone: str
    evidence: list[str] = field(default_factory=list)
    recommended_action: str = ""
    movement_vectors: list[MovementVector] = field(default_factory=list)
    timestamp: str = ""
    expires: str = ""
    notified: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate distance between two points in kilometers."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def bearing_degrees(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Calculate bearing from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)

    x = math.sin(dl) * math.cos(phi2)
    y = (
        math.cos(phi1) * math.sin(phi2)
        - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    )
    theta = math.atan2(x, y)
    return (math.degrees(theta) + 360) % 360


class MovementTracker:
    """
    Analyzes hotspot data over time to detect movement patterns.

    Strategy:
      1. Compare clusters at T-1 vs T (e.g., yesterday vs today)
      2. Find clusters that appeared/disappeared
      3. Match disappeared → appeared clusters by proximity
      4. Calculate movement vectors
      5. Generate alerts for significant patterns
    """

    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.alerts: list[ThreatAlert] = []

    def analyze_movement(
        self,
        clusters_before: list[dict[str, Any]],
        clusters_after: list[dict[str, Any]],
        time_before: str,
        time_after: str,
        get_state_fn: Optional[Callable[[float, float], str]] = None,
    ) -> list[MovementVector]:
        """
        Compare two snapshots of cluster data to detect movement.

        Args:
            clusters_before: Cluster data from earlier time
            clusters_after: Cluster data from later time
            time_before: ISO timestamp of earlier snapshot
            time_after: ISO timestamp of later snapshot
            get_state_fn: Function to resolve (lat, lon) → state name
        """
        movements: list[MovementVector] = []

        # Parse times
        try:
            t_before = datetime.fromisoformat(time_before)
            t_after = datetime.fromisoformat(time_after)
            delta_hours = (t_after - t_before).total_seconds() / 3600
        except ValueError:
            delta_hours = 24.0

        if delta_hours <= 0:
            return movements

        # Find new/grown clusters near disappeared/shrunk clusters
        for c_after in clusters_after:
            lat_a = float(
                c_after.get("lat", c_after.get("latitude", 0))
            )
            lon_a = float(
                c_after.get("lon", c_after.get("longitude", 0))
            )
            count_a = int(
                c_after.get("count", c_after.get("hotspot_count", 1))
            )

            best_match: Optional[dict[str, Any]] = None
            best_distance = float("inf")

            for c_before in clusters_before:
                lat_b = float(
                    c_before.get("lat", c_before.get("latitude", 0))
                )
                lon_b = float(
                    c_before.get("lon", c_before.get("longitude", 0))
                )

                dist = haversine_km(lat_b, lon_b, lat_a, lon_a)

                # Movement detection: 5–200 km in the time window
                if 5.0 < dist < 200.0 and dist < best_distance:
                    best_match = c_before
                    best_distance = dist

            if best_match is not None:
                lat_b = float(
                    best_match.get("lat", best_match.get("latitude", 0))
                )
                lon_b = float(
                    best_match.get("lon", best_match.get("longitude", 0))
                )
                count_b = int(
                    best_match.get(
                        "count", best_match.get("hotspot_count", 1)
                    )
                )

                speed = best_distance / delta_hours
                brng = bearing_degrees(lat_b, lon_b, lat_a, lon_a)

                # Classify the movement
                if speed > 10:
                    classification = "rapid_relocation"
                elif best_distance > 50:
                    classification = "corridor"
                else:
                    classification = "camp_relocation"

                # Confidence based on cluster sizes and distance
                confidence = min(
                    1.0,
                    (count_a + count_b)
                    / 20.0
                    * (1.0 - best_distance / 200.0),
                )

                origin_state = ""
                dest_state = ""
                if get_state_fn is not None:
                    origin_state = get_state_fn(lat_b, lon_b)
                    dest_state = get_state_fn(lat_a, lon_a)

                movement = MovementVector(
                    origin_lat=lat_b,
                    origin_lon=lon_b,
                    destination_lat=lat_a,
                    destination_lon=lon_a,
                    origin_state=origin_state,
                    destination_state=dest_state,
                    distance_km=round(best_distance, 2),
                    bearing_degrees=round(brng, 1),
                    time_delta_hours=round(delta_hours, 1),
                    speed_kmh=round(speed, 2),
                    hotspot_count_origin=count_b,
                    hotspot_count_destination=count_a,
                    confidence=round(confidence, 3),
                    detection_time=datetime.utcnow().isoformat(),
                    classification=classification,
                )
                movements.append(movement)

        return movements

    def generate_alerts(
        self,
        movements: list[MovementVector],
        current_clusters: list[dict[str, Any]],
    ) -> list[ThreatAlert]:
        """Generate actionable alerts from detected movements."""
        alerts: list[ThreatAlert] = []
        now = datetime.utcnow()

        for mv in movements:
            # Determine priority
            if (
                mv.classification == "rapid_relocation"
                and mv.confidence > 0.5
            ):
                priority = "critical"
            elif (
                mv.distance_km > 50
                and mv.hotspot_count_destination > 5
            ):
                priority = "high"
            elif mv.confidence > 0.3:
                priority = "medium"
            else:
                priority = "low"

            direction = _bearing_to_direction(mv.bearing_degrees)

            title = (
                f"{mv.classification.replace('_', ' ').title()} "
                f"Detected — "
                f"{mv.destination_state or 'Unknown Area'}"
            )

            description = (
                f"Hotspot cluster movement detected: "
                f"{mv.distance_km:.1f} km {direction} "
                f"from {mv.origin_state or 'origin'} to "
                f"{mv.destination_state or 'destination'} "
                f"over {mv.time_delta_hours:.0f} hours "
                f"({mv.speed_kmh:.1f} km/h). "
                f"Origin: {mv.hotspot_count_origin} hotspots, "
                f"Destination: {mv.hotspot_count_destination} hotspots."
            )

            evidence = [
                f"Thermal migration: {mv.distance_km:.1f} km",
                f"Direction: {direction} ({mv.bearing_degrees:.0f}°)",
                f"Speed: {mv.speed_kmh:.1f} km/h",
                f"Confidence: {mv.confidence:.0%}",
            ]

            recommended_action = _recommend_action(mv, priority)

            alert = ThreatAlert(
                alert_id=(
                    f"MVT-{now.strftime('%Y%m%d%H%M%S')}"
                    f"-{len(alerts):03d}"
                ),
                priority=priority,
                title=title,
                description=description,
                latitude=mv.destination_lat,
                longitude=mv.destination_lon,
                state=mv.destination_state,
                zone=_get_zone_name(
                    mv.destination_lat, mv.destination_lon
                ),
                evidence=evidence,
                recommended_action=recommended_action,
                movement_vectors=[mv],
                timestamp=now.isoformat(),
                expires=(now + timedelta(hours=12)).isoformat(),
            )
            alerts.append(alert)

        # Save alerts
        _save_alerts(alerts)
        self.alerts.extend(alerts)

        return alerts


# ── Module-level helper functions ─────────────────────────────


def _save_alerts(alerts: list[ThreatAlert]) -> None:
    """Persist alerts to disk."""
    if not alerts:
        return

    alerts_file = ALERTS_DIR / "active_alerts.json"
    existing: list[dict[str, Any]] = []

    if alerts_file.exists():
        try:
            with open(alerts_file) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = []

    for alert in alerts:
        existing.append(alert.to_dict())

    # Keep only last 500 alerts
    existing = existing[-500:]

    with open(alerts_file, "w") as f:
        json.dump(existing, f, indent=2)


def _bearing_to_direction(bearing: float) -> str:
    """Convert bearing to compass direction."""
    directions = [
        "North", "North-Northeast", "Northeast", "East-Northeast",
        "East", "East-Southeast", "Southeast", "South-Southeast",
        "South", "South-Southwest", "Southwest", "West-Southwest",
        "West", "West-Northwest", "Northwest", "North-Northwest",
    ]
    idx = round(bearing / 22.5) % 16
    return directions[idx]


def _recommend_action(mv: MovementVector, priority: str) -> str:
    """Generate recommended military action based on movement."""
    if priority == "critical":
        return (
            f"URGENT: Rapid group relocation detected toward "
            f"{mv.destination_state}. Recommend immediate aerial "
            f"reconnaissance of coordinates "
            f"({mv.destination_lat:.4f}, {mv.destination_lon:.4f}) "
            f"and observation posts along the "
            f"{_bearing_to_direction(mv.bearing_degrees)} corridor."
        )
    if priority == "high":
        return (
            f"Deploy surveillance to monitor area around "
            f"({mv.destination_lat:.4f}, {mv.destination_lon:.4f}). "
            f"Pattern suggests possible camp relocation. "
            f"Coordinate with ground units in "
            f"{mv.destination_state}."
        )
    if priority == "medium":
        return (
            f"Increase monitoring frequency for "
            f"{mv.destination_state} area. "
            f"Track pattern over next 48 hours to confirm."
        )
    return (
        f"Log for pattern analysis. "
        f"Continue routine monitoring of {mv.destination_state}."
    )


def _get_zone_name(lat: float, lon: float) -> str:
    """Map coordinates to a monitoring zone."""
    zones: dict[str, dict[str, float]] = {
        "Northwest Corridor": {
            "west": 4.0, "east": 7.5,
            "south": 10.0, "north": 14.0,
        },
        "Northeast Corridor": {
            "west": 10.0, "east": 15.0,
            "south": 10.0, "north": 14.0,
        },
        "North Central": {
            "west": 6.0, "east": 10.0,
            "south": 7.0, "north": 10.5,
        },
        "Niger Delta": {
            "west": 4.5, "east": 8.0,
            "south": 4.0, "north": 6.5,
        },
        "Southeast": {
            "west": 6.5, "east": 9.0,
            "south": 4.5, "north": 7.0,
        },
    }

    for zone_name, bounds in zones.items():
        if (
            bounds["south"] <= lat <= bounds["north"]
            and bounds["west"] <= lon <= bounds["east"]
        ):
            return zone_name

    return "Outside Monitored Zones"