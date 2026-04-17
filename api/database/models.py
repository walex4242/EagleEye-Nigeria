"""
api/database/models.py
──────────────────────
SQLAlchemy models for PostgreSQL.
Uses native UUID, JSONB, DOUBLE_PRECISION, ARRAY, and BRIN indexes.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Boolean, Text, DateTime,
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
)
from sqlalchemy.dialects.postgresql import (
    UUID, JSONB, ARRAY, DOUBLE_PRECISION,
)
from sqlalchemy.orm import relationship
from api.database.engine import Base


# ── Enums ─────────────────────────────────────────────────────

class UserRole:
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    MILITARY = "military"
    ANALYST = "analyst"
    PUBLIC = "public"

    ALL = [SUPERADMIN, ADMIN, MILITARY, ANALYST, PUBLIC]
    PRIVILEGED = [SUPERADMIN, ADMIN, MILITARY, ANALYST]
    MILITARY_ONLY = [SUPERADMIN, ADMIN, MILITARY]


class DataClassification:
    TOP_SECRET = "top_secret"
    SECRET = "secret"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    UNCLASSIFIED = "unclassified"


# ── Users ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    email = Column(String(255), unique=True, nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.PUBLIC)
    rank = Column(String(100), nullable=True)
    unit = Column(String(255), nullable=True)
    service_id = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    last_login = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    audit_logs = relationship(
        "AuditLog", back_populates="user", lazy="dynamic",
    )
    alerts_created = relationship(
        "SavedAlert", back_populates="created_by_user", lazy="dynamic",
    )

    __table_args__ = (
        Index("idx_users_email", "email"),
        Index("idx_users_username", "username"),
        Index("idx_users_role", "role"),
        Index("idx_users_active", "is_active"),
        CheckConstraint(
            "role IN ('superadmin','admin','military','analyst','public')",
            name="ck_users_role",
        ),
    )

    def is_military_user(self) -> bool:
        return self.role in UserRole.MILITARY_ONLY

    def is_privileged_user(self) -> bool:
        return self.role in UserRole.PRIVILEGED

    def can_access_classification(self, classification: str) -> bool:
        access_map = {
            DataClassification.TOP_SECRET: [UserRole.SUPERADMIN],
            DataClassification.SECRET: UserRole.MILITARY_ONLY,
            DataClassification.CONFIDENTIAL: UserRole.PRIVILEGED,
            DataClassification.RESTRICTED: UserRole.PRIVILEGED,
            DataClassification.UNCLASSIFIED: UserRole.ALL,
        }
        return self.role in access_map.get(classification, [])


# ── Audit Log ─────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = Column(String(100), nullable=False)
    resource = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    details = Column(JSONB, nullable=True)
    timestamp = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    user = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "timestamp"),
        Index("idx_audit_action", "action"),
        Index(
            "idx_audit_timestamp_brin", "timestamp",
            postgresql_using="brin",
        ),
    )


# ── Hotspot Archive ───────────────────────────────────────────

class HotspotRecord(Base):
    __tablename__ = "hotspot_records"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    latitude = Column(DOUBLE_PRECISION, nullable=False)
    longitude = Column(DOUBLE_PRECISION, nullable=False)
    brightness = Column(DOUBLE_PRECISION, nullable=True)
    confidence = Column(String(5), nullable=True)
    frp = Column(DOUBLE_PRECISION, nullable=True)
    acq_date = Column(String(10), nullable=False)
    acq_time = Column(String(4), nullable=True)
    satellite = Column(String(50), nullable=True)
    daynight = Column(String(1), nullable=True)

    # Scoring
    threat_score = Column(DOUBLE_PRECISION, nullable=True)
    priority = Column(String(20), nullable=True)
    threat_tier = Column(String(50), nullable=True)

    # Location (from geocoding)
    state = Column(String(50), nullable=True)
    lga = Column(String(100), nullable=True)
    nearest_town = Column(String(100), nullable=True)
    red_zone = Column(String(50), nullable=True)
    geo_zone = Column(String(50), nullable=True)
    location_data = Column(JSONB, nullable=True)

    # Security classification
    classification = Column(
        String(20), default=DataClassification.RESTRICTED, nullable=False,
    )
    public_release_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_hotspot_coords", "latitude", "longitude"),
        Index("idx_hotspot_date", "acq_date"),
        Index("idx_hotspot_state", "state"),
        Index("idx_hotspot_priority", "priority"),
        Index("idx_hotspot_date_state", "acq_date", "state"),
        Index("idx_hotspot_score", "threat_score"),
        Index("idx_hotspot_public_release", "public_release_at"),
        Index(
            "idx_hotspot_created_brin", "created_at",
            postgresql_using="brin",
        ),
    )


# ── Vegetation Change Events ─────────────────────────────────

class VegetationEvent(Base):
    __tablename__ = "vegetation_events"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    event_id = Column(String(100), unique=True, nullable=False)
    latitude = Column(DOUBLE_PRECISION, nullable=False)
    longitude = Column(DOUBLE_PRECISION, nullable=False)
    bbox = Column(ARRAY(DOUBLE_PRECISION), nullable=True)
    date_before = Column(String(10), nullable=False)
    date_after = Column(String(10), nullable=False)
    index_used = Column(String(10), nullable=False)
    mean_change = Column(DOUBLE_PRECISION, nullable=False)
    max_change = Column(DOUBLE_PRECISION, nullable=False)
    area_hectares = Column(DOUBLE_PRECISION, nullable=False)
    area_pixels = Column(Integer, nullable=False)
    severity = Column(String(20), nullable=False)
    event_classification = Column(String(30), nullable=False)
    confidence = Column(DOUBLE_PRECISION, nullable=False)
    vegetation_zone = Column(String(50), nullable=True)

    # Location
    state = Column(String(50), nullable=True)
    lga = Column(String(100), nullable=True)
    nearest_town = Column(String(100), nullable=True)
    location_data = Column(JSONB, nullable=True)

    # Correlations
    nearby_hotspots = Column(Integer, default=0)
    nearby_conflicts = Column(Integer, default=0)
    correlation_data = Column(JSONB, nullable=True)

    # Security classification
    classification = Column(
        String(20), default=DataClassification.CONFIDENTIAL, nullable=False,
    )
    public_release_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_veg_event_id", "event_id"),
        Index("idx_veg_date", "date_after"),
        Index("idx_veg_severity", "severity"),
        Index("idx_veg_state", "state"),
        Index("idx_veg_classification", "event_classification"),
        Index("idx_veg_coords", "latitude", "longitude"),
    )


# ── Saved Alerts ──────────────────────────────────────────────

class SavedAlert(Base):
    __tablename__ = "saved_alerts"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    latitude = Column(DOUBLE_PRECISION, nullable=True)
    longitude = Column(DOUBLE_PRECISION, nullable=True)
    state = Column(String(50), nullable=True)
    lga = Column(String(100), nullable=True)
    data = Column(JSONB, nullable=True)

    is_acknowledged = Column(Boolean, default=False, nullable=False)
    acknowledged_by = Column(UUID(as_uuid=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    classification = Column(
        String(20), default=DataClassification.RESTRICTED, nullable=False,
    )
    public_release_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    created_by_user = relationship("User", back_populates="alerts_created")

    __table_args__ = (
        Index("idx_alert_type", "alert_type"),
        Index("idx_alert_severity", "severity"),
        Index("idx_alert_state", "state"),
        Index("idx_alert_created", "created_at"),
        Index("idx_alert_ack", "is_acknowledged"),
    )


# ── Movement Records ─────────────────────────────────────────

class MovementRecord(Base):
    __tablename__ = "movement_records"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    origin_lat = Column(DOUBLE_PRECISION, nullable=False)
    origin_lon = Column(DOUBLE_PRECISION, nullable=False)
    destination_lat = Column(DOUBLE_PRECISION, nullable=False)
    destination_lon = Column(DOUBLE_PRECISION, nullable=False)
    distance_km = Column(DOUBLE_PRECISION, nullable=False)
    bearing_degrees = Column(DOUBLE_PRECISION, nullable=True)
    speed_kmh = Column(DOUBLE_PRECISION, nullable=True)
    time_delta_hours = Column(DOUBLE_PRECISION, nullable=True)
    movement_classification = Column(String(50), nullable=True)
    confidence = Column(DOUBLE_PRECISION, nullable=True)

    origin_state = Column(String(50), nullable=True)
    destination_state = Column(String(50), nullable=True)
    origin_nearest_town = Column(String(100), nullable=True)
    destination_nearest_town = Column(String(100), nullable=True)

    classification = Column(
        String(20), default=DataClassification.RESTRICTED, nullable=False,
    )
    public_release_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_movement_origin_state", "origin_state"),
        Index("idx_movement_dest_state", "destination_state"),
        Index("idx_movement_created", "created_at"),
    )


# ── Data Snapshots (for public delayed release) ──────────────

class DataSnapshot(Base):
    __tablename__ = "data_snapshots"

    id = Column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    snapshot_type = Column(String(50), nullable=False)
    snapshot_date = Column(DateTime(timezone=True), nullable=False)
    data = Column(JSONB, nullable=False)
    feature_count = Column(Integer, default=0)
    metadata_info = Column(JSONB, nullable=True)
    classification = Column(
        String(20), default=DataClassification.RESTRICTED, nullable=False,
    )
    public_release_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False,
    )

    __table_args__ = (
        Index("idx_snapshot_type_date", "snapshot_type", "snapshot_date"),
        Index("idx_snapshot_release", "public_release_at"),
        UniqueConstraint(
            "snapshot_type", "snapshot_date",
            name="uq_snapshot_type_date",
        ),
    )