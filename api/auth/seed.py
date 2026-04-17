"""
api/auth/seed.py
────────────────
Create the initial superadmin account on first startup.
Uses PostgreSQL native UUID.
"""

import os
from sqlalchemy.orm import Session
from sqlalchemy import func
from api.database.models import User, UserRole
from api.auth.security import hash_password


def seed_admin(db: Session):
    """Create default superadmin if no users exist in PostgreSQL."""
    try:
        user_count = db.query(func.count(User.id)).scalar()

        if user_count > 0:
            print(f"[AUTH] Database has {user_count} user(s) — skipping seed")
            return

        admin_email = os.getenv("FIRST_ADMIN_EMAIL", "admin@eagleeye.ng")
        admin_password = os.getenv(
            "FIRST_ADMIN_PASSWORD", "change-this-immediately",
        )

        # Truncate to bcrypt's 72-byte limit
        if len(admin_password.encode("utf-8")) > 72:
            print("[AUTH] ⚠ Admin password exceeds 72 bytes — truncating for bcrypt")
            admin_password = admin_password[:72]

        admin = User(
            email=admin_email,
            username="admin",
            hashed_password=hash_password(admin_password),
            full_name="System Administrator",
            role=UserRole.SUPERADMIN,
            is_active=True,
            is_verified=True,
        )

        db.add(admin)
        db.commit()

        print(f"[AUTH] ✓ Default superadmin created: {admin_email}")
        print("[AUTH] ⚠ CHANGE THE DEFAULT PASSWORD IMMEDIATELY!")

    except Exception as e:
        print(f"[AUTH] ✗ Failed to seed admin: {e}")
        db.rollback()
        raise