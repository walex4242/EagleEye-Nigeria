"""
api/database/models.py
──────────────────────
SQLAlchemy models for users, roles, alerts, hotspot logs, and audit trail.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime,
    ForeignKey, Enum as SAEnum, JSON, Index,
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
    TOP_SECRET = "top_secret"      # Never public
    SECRET = "secret"              # Military only, never public
    CONFIDENTIAL = "confidential"  # Military + analysts, delayed public
    RESTRICTED = "restricted"      # Delayed public (72h default)
    UNCLASSIFIED = "unclassified"  # Immediately public


# ── Users ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default=UserRole.PUBLIC)
    rank = Column(String(100), nullable=True)          # Military rank
    unit = Column(String(255), nullable=True)          # Military unit/formation
    service_id = Column(String(100), nullable=True)    # Service number
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    audit_logs = relationship("AuditLog", back_populates="user")
    alerts_created = relationship("SavedAlert", back_populates="created_by_user")

    def is_military(self) -> bool:
        return self.role in UserRole.MILITARY_ONLY

    def is_privileged(self) -> bool:
        return self.role in UserRole.PRIVILEGED

    def can_access_classification(self, classification: str) -> bool:
        access_map = {
            DataClassification.TOP_SECRET: [UserRole.SUPERADMIN],
            DataClassification.SECRET: UserRole.MILITARY_ONLY,
            DataClassification.CONFIDENTIAL: UserRole.PRIVILEGED,
            DataClassification.RESTRICTED: UserRole.PRIVILEGED,
            DataClassification.UNCLASSIFIED: UserRole.ALL,
        }
        allowed = access_map.get(classification, [])
        return self.role in allowed


# ── Audit Log ─────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)         # login, view_hotspots, export, etc.
    resource = Column(String(255), nullable=True)        # /api/v1/hotspots
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    details = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("User", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "timestamp"),
    )


# ── Hotspot Archive ───────────────────────────────────────────

class HotspotRecord(Base):
    __tablename__ = "hotspot_records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    brightness = Column(Float, nullable=True)
    confidence = Column(String(5), nullable=True)
    frp = Column(Float, nullable=True)
    acq_date = Column(String(10), nullable=False, index=True)
    acq_time = Column(String(4), nullable=True)
    satellite = Column(String(50), nullable=True)
    daynight = Column(String(1), nullable=True)
    threat_score = Column(Float, nullable=True)
    priority = Column(String(20), nullable=True, index=True)
    state = Column(String(50), nullable=True, index=True)
    lga = Column(String(100), nullable=True)
    nearest_town = Column(String(100), nullable=True)
    red_zone = Column(String(50), nullable=True)
    classification = Column(
        String(20), default=DataClassification.RESTRICTED,
    )
    public_release_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_hotspot_coords", "latitude", "longitude"),
        Index("idx_hotspot_date_state", "acq_date", "state"),
        Index("idx_hotspot_public_release", "public_release_at"),
    )


# ── Vegetation Change Events ─────────────────────────────────

class VegetationEvent(Base):
    __tablename__ = "vegetation_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_id = Column(String(100), unique=True, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    date_before = Column(String(10), nullable=False)
    date_after = Column(String(10), nullable=False)
    index_used = Column(String(10), nullable=False)
    mean_change = Column(Float, nullable=False)
    max_change = Column(Float, nullable=False)
    area_hectares = Column(Float, nullable=False)
    area_pixels = Column(Integer, nullable=False)
    severity = Column(String(20), nullable=False, index=True)
    event_classification = Column(String(30), nullable=False)
    confidence = Column(Float, nullable=False)
    vegetation_zone = Column(String(50), nullable=True)
    state = Column(String(50), nullable=True, index=True)
    lga = Column(String(100), nullable=True)
    nearest_town = Column(String(100), nullable=True)
    classification = Column(
        String(20), default=DataClassification.CONFIDENTIAL,
    )
    public_release_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_veg_date", "date_after"),
        Index("idx_veg_severity", "severity"),
    )


# ── Saved Alerts ──────────────────────────────────────────────

class SavedAlert(Base):
    __tablename__ = "saved_alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    alert_type = Column(String(50), nullable=False)     # hotspot, vegetation, movement
    severity = Column(String(20), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    state = Column(String(50), nullable=True)
    data = Column(JSON, nullable=True)                   # Full alert payload
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(36), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    classification = Column(
        String(20), default=DataClassification.RESTRICTED,
    )
    public_release_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    created_by_user = relationship("User", back_populates="alerts_created")