"""
database.py — IoToDChain with SQLite
No credentials needed — file-based database, works on any hosting with Python.
v3: phone/OTP identity, unified Provider (doctor+nurse) directory, clinical notes.
"""

from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Text, Boolean,
    Integer, DateTime, JSON, Enum as SAEnum, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import enum
import os

# SQLite — stored as a file, zero configuration needed
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iotodchain.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class ParticipantRole(str, enum.Enum):
    patient      = "patient"
    doctor       = "doctor"
    nurse        = "nurse"
    specialist   = "specialist"
    fog_node     = "fog_node"
    proxy        = "proxy"
    unauthorized = "unauthorized"

class AccessVerdict(str, enum.Enum):
    permit = "PERMIT"
    deny   = "DENY"
    intent = "INTENT"

class RequestStatus(str, enum.Enum):
    pending  = "pending"
    approved = "approved"
    declined = "declined"
    revoked  = "revoked"

class BlockTxType(str, enum.Enum):
    setup         = "CA_SETUP"
    key_issue     = "KEY_ISSUANCE"
    data_reg      = "DATA_REGISTRATION"
    access_intent = "ACCESS_INTENT"
    access_permit = "ACCESS_PERMIT"
    access_deny   = "ACCESS_DENY"
    revocation    = "REVOCATION"
    critical_alert = "CRITICAL_ALERT"


class Participant(Base):
    __tablename__ = "participants"
    id              = Column(String(64),  primary_key=True)
    display_name    = Column(String(128), nullable=False)
    role            = Column(String(32),  nullable=False)
    phone_number    = Column(String(32),  nullable=True, unique=True, index=True)
    password_hash   = Column(String(128), nullable=True)
    password_salt   = Column(String(32),  nullable=True)
    eth_address     = Column(String(42),  nullable=True)
    public_key_pem  = Column(Text,        nullable=True)
    attributes      = Column(Text,        nullable=True)  # JSON as text for SQLite
    secret_key_D    = Column(String(256), nullable=True)
    credit_score    = Column(Integer,     default=100)
    blacklisted     = Column(Boolean,     default=False)
    created_at      = Column(DateTime,    default=datetime.utcnow)
    updated_at      = Column(DateTime,    default=datetime.utcnow)


class Provider(Base):
    """Unified directory for both doctors and nurses — same request/approve/monitor flow."""
    __tablename__ = "providers"
    provider_id   = Column(String(64),  primary_key=True)
    full_name     = Column(String(128), nullable=False)
    role          = Column(String(16),  nullable=False, default="doctor")  # "doctor" | "nurse"
    hospital      = Column(String(128), nullable=False)
    department    = Column(String(128), nullable=False)
    speciality    = Column(String(128), nullable=True)
    city          = Column(String(64),  nullable=False)
    photo_url     = Column(String(512), nullable=True)
    is_preseeded  = Column(Boolean,     default=False)
    created_at    = Column(DateTime,    default=datetime.utcnow)
    # Admin-managed taxonomy FKs — nullable until migrate_providers.py backfills
    # them from the free-text columns above (which then become deprecated but
    # are left in place rather than dropped, to avoid a second migration).
    hospital_id    = Column(Integer, ForeignKey("hospitals.id"),    nullable=True)
    department_id  = Column(Integer, ForeignKey("departments.id"),  nullable=True)
    speciality_id  = Column(Integer, ForeignKey("specialities.id"), nullable=True)
    job_title_id   = Column(Integer, ForeignKey("job_titles.id"),   nullable=True)


class Hospital(Base):
    __tablename__ = "hospitals"
    id         = Column(Integer,     primary_key=True, autoincrement=True)
    name       = Column(String(128), nullable=False, unique=True)
    city       = Column(String(64),  nullable=False)
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


class Department(Base):
    __tablename__ = "departments"
    id          = Column(Integer,     primary_key=True, autoincrement=True)
    hospital_id = Column(Integer,     ForeignKey("hospitals.id"), nullable=False, index=True)
    name        = Column(String(128), nullable=False)
    is_active   = Column(Boolean,     default=True)
    created_at  = Column(DateTime,    default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("hospital_id", "name", name="uq_dept_hospital_name"),)


class Speciality(Base):
    __tablename__ = "specialities"
    id         = Column(Integer,     primary_key=True, autoincrement=True)
    name       = Column(String(128), nullable=False, unique=True)
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


class JobTitle(Base):
    __tablename__ = "job_titles"
    id         = Column(Integer,     primary_key=True, autoincrement=True)
    name       = Column(String(128), nullable=False, unique=True)
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


class AttributeType(Base):
    """The vocabulary of CxABE-PRE context-attribute kinds an admin can
    define beyond the directory ones above — e.g. Network, Horaire — each
    with its own admin-managed list of possible values (AttributeValue)."""
    __tablename__ = "attribute_types"
    id         = Column(Integer,     primary_key=True, autoincrement=True)
    code       = Column(String(64),  nullable=False, unique=True)   # e.g. "Network", "Horaire"
    label      = Column(String(128), nullable=False)
    is_active  = Column(Boolean,     default=True)
    created_at = Column(DateTime,    default=datetime.utcnow)


class AttributeValue(Base):
    __tablename__ = "attribute_values"
    id                = Column(Integer,     primary_key=True, autoincrement=True)
    attribute_type_id = Column(Integer,     ForeignKey("attribute_types.id"), nullable=False, index=True)
    value             = Column(String(128), nullable=False)
    is_active         = Column(Boolean,     default=True)
    created_at        = Column(DateTime,    default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("attribute_type_id", "value", name="uq_attrval_type_value"),)


class Admin(Base):
    __tablename__ = "admins"
    id            = Column(Integer,     primary_key=True, autoincrement=True)
    username      = Column(String(64),  nullable=False, unique=True, index=True)
    password_hash = Column(String(128), nullable=False)
    password_salt = Column(String(32),  nullable=False)
    display_name  = Column(String(128), nullable=True)
    created_at    = Column(DateTime,    default=datetime.utcnow)


class AccessRequestRow(Base):
    __tablename__ = "access_requests"
    id            = Column(Integer,     primary_key=True, autoincrement=True)
    patient_id    = Column(String(64),  nullable=False)
    patient_name  = Column(String(128), nullable=True)
    provider_id   = Column(String(64),  nullable=False)
    status        = Column(String(16),  default="pending")
    tx_hash       = Column(String(256), nullable=True)
    block_number  = Column(Integer,     nullable=True)
    requested_at  = Column(DateTime,    default=datetime.utcnow)
    responded_at  = Column(DateTime,    nullable=True)
    revoked_at    = Column(DateTime,    nullable=True)


class PatientSharingPolicy(Base):
    """A patient's attribute-based auto-share constraints — any provider whose
    attributes satisfy every set field here gets auto-approved on request,
    bypassing the manual approve step. No row (or all-null fields) means no
    active policy: falls back to today's manual approve/decline flow."""
    __tablename__ = "patient_sharing_policies"
    id             = Column(Integer,     primary_key=True, autoincrement=True)
    patient_id     = Column(String(64),  nullable=False, unique=True, index=True)
    speciality_id  = Column(Integer,     ForeignKey("specialities.id"), nullable=True)
    hospital_id    = Column(Integer,     ForeignKey("hospitals.id"),    nullable=True)
    department_id  = Column(Integer,     ForeignKey("departments.id"),  nullable=True)
    updated_at     = Column(DateTime,    default=datetime.utcnow)


class CriticalAlertRow(Base):
    __tablename__ = "critical_alerts"
    id              = Column(Integer,     primary_key=True, autoincrement=True)
    patient_id      = Column(String(64),  nullable=False, index=True)
    patient_name    = Column(String(128), nullable=True)
    provider_id     = Column(String(64),  nullable=False, index=True)
    reason          = Column(String(256), nullable=False)
    tx_hash         = Column(String(256), nullable=True)
    block_number    = Column(Integer,     nullable=True)
    acknowledged    = Column(Boolean,     default=False)
    acknowledged_at = Column(DateTime,    nullable=True)
    created_at      = Column(DateTime,    default=datetime.utcnow)


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    id            = Column(Integer,     primary_key=True, autoincrement=True)
    phone_number  = Column(String(32),  nullable=False, index=True)
    code_hash     = Column(String(128), nullable=False)
    purpose       = Column(String(16),  default="login")
    attempts      = Column(Integer,     default=0)
    verified      = Column(Boolean,     default=False)
    expires_at    = Column(DateTime,    nullable=False)
    created_at    = Column(DateTime,    default=datetime.utcnow)


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"
    id            = Column(Integer,     primary_key=True, autoincrement=True)
    patient_id    = Column(String(64),  nullable=False, index=True)
    provider_id   = Column(String(64),  nullable=False)
    provider_name = Column(String(128), nullable=True)
    text          = Column(Text,        nullable=False)
    created_at    = Column(DateTime,    default=datetime.utcnow)


class SmsOutbox(Base):
    """Queue of OTP SMS messages waiting to be sent by the phone-based gateway app."""
    __tablename__ = "sms_outbox"
    id            = Column(Integer,     primary_key=True, autoincrement=True)
    phone_number  = Column(String(32),  nullable=False)
    message       = Column(Text,        nullable=False)
    status        = Column(String(16),  default="pending")  # pending | sent | failed
    created_at    = Column(DateTime,    default=datetime.utcnow)
    sent_at       = Column(DateTime,    nullable=True)


class HealthRecord(Base):
    __tablename__ = "health_records"
    record_id           = Column(String(64),  primary_key=True)
    patient_id          = Column(String(64),  nullable=False)
    hEncM               = Column(String(256), nullable=False)
    ciphertext_b64      = Column(Text,        nullable=False)
    nonce_b64           = Column(String(64),  nullable=False)
    policy_commit       = Column(String(256), nullable=False)
    policy              = Column(Text,        nullable=False)  # JSON as text
    C_b64               = Column(String(256), nullable=True)
    device_id           = Column(String(64),  nullable=True)
    fog_node_id         = Column(String(64),  nullable=True)
    tx_hash             = Column(String(256), nullable=True)
    block_number        = Column(Integer,     nullable=True)
    registered_on_chain = Column(Boolean,     default=False)
    created_at          = Column(DateTime,    default=datetime.utcnow)


class AccessLog(Base):
    __tablename__ = "access_logs"
    id               = Column(Integer,     primary_key=True, autoincrement=True)
    record_id        = Column(String(64),  nullable=False)
    requester_id     = Column(String(64),  nullable=False)
    requester_eth    = Column(String(42),  nullable=True)
    verdict          = Column(String(16),  nullable=False)
    reason           = Column(String(512), nullable=True)
    tx_hash          = Column(String(256), nullable=True)
    block_number     = Column(Integer,     nullable=True)
    gas_used         = Column(Integer,     nullable=True)
    session_key_hash = Column(String(256), nullable=True)
    decrypted_hash   = Column(String(256), nullable=True)
    created_at       = Column(DateTime,    default=datetime.utcnow)


class Block(Base):
    __tablename__ = "blocks"
    # id is the row's own identity (insertion order) — block_number is NOT
    # unique across sources: the old simulated chain and any real chain both
    # number their blocks starting from 1, so block_number can't be the key.
    id           = Column(Integer,     primary_key=True, autoincrement=True)
    block_number = Column(Integer,     nullable=False, index=True)
    block_hash   = Column(String(256), nullable=False, unique=True)
    parent_hash  = Column(String(256), nullable=True)
    tx_hash      = Column(String(256), nullable=True)
    tx_type      = Column(String(32),  nullable=False)
    tx_data      = Column(Text,        nullable=True)
    verdict      = Column(String(16),  nullable=True)
    validator    = Column(String(64),  nullable=False)
    gas_used     = Column(Integer,     nullable=True)
    timestamp    = Column(DateTime,    default=datetime.utcnow)


class AuditEntry(Base):
    __tablename__ = "audit_entries"
    id           = Column(Integer,     primary_key=True, autoincrement=True)
    tx_type      = Column(String(32),  nullable=False)
    actor_id     = Column(String(64),  nullable=True)
    actor_eth    = Column(String(42),  nullable=True)
    record_id    = Column(String(64),  nullable=True)
    detail       = Column(Text,        nullable=True)
    tx_hash      = Column(String(256), nullable=True)
    block_number = Column(Integer,     nullable=True)
    timestamp    = Column(DateTime,    default=datetime.utcnow)



class ZKEligibilityProfile(Base):
    """Private patient inputs used only as a witness for the eligibility circuit.
    Values are never written to the blockchain."""
    __tablename__ = "zk_eligibility_profiles"
    patient_id  = Column(String(64), primary_key=True)
    age         = Column(Integer, nullable=False)
    hba1c10     = Column(Integer, nullable=False)  # HbA1c × 10
    ckd         = Column(Integer, nullable=False)  # 0 or 1
    updated_at  = Column(DateTime, default=datetime.utcnow)

class ZKProofLog(Base):
    """Audit metadata for ZK verification; private witness values are excluded."""
    __tablename__ = "zk_proof_logs"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    patient_id      = Column(String(64), nullable=False, index=True)
    record_id       = Column(String(64), nullable=True)
    proof_policy_id = Column(String(128), nullable=False)
    ct_hash         = Column(String(256), nullable=False)
    policy_hash     = Column(String(256), nullable=False)
    verified        = Column(Boolean, nullable=False)
    tx_hash         = Column(String(256), nullable=True)
    block_number    = Column(Integer, nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)


def create_tables():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


import json

def seed_taxonomy(db):
    """Pre-seed the admin-managed taxonomy (hospitals/departments/specialities/
    job titles) if empty — matches seed_providers()'s demo data so a fresh
    database (no migration ever run) comes up correct too."""
    if db.query(Hospital).count() > 0:
        return

    hospitals = {
        "El-Markazi Hospital": "Setif",
        "Ibn Sina Clinic": "Setif",
        "Algiers Central": "Algiers",
        "Oran Medical Center": "Oran",
    }
    hospital_rows = {}
    for name, city in hospitals.items():
        h = Hospital(name=name, city=city)
        db.add(h)
        db.flush()
        hospital_rows[name] = h

    departments = [
        ("El-Markazi Hospital", "Cardiology"),
        ("Ibn Sina Clinic", "ICU"),
        ("Ibn Sina Clinic", "General"),
        ("Algiers Central", "Cardiology"),
        ("Oran Medical Center", "Diabetic"),
    ]
    for hospital_name, dept_name in departments:
        db.add(Department(hospital_id=hospital_rows[hospital_name].id, name=dept_name))

    for name in ["Cardiology", "Intensive Care", "General Medicine", "Endocrinology"]:
        db.add(Speciality(name=name))

    for name in ["Cardiologist", "Heart Specialist", "Intensivist", "General Practitioner", "Endocrinologist"]:
        db.add(JobTitle(name=name))

    db.commit()


def seed_providers(db):
    """Pre-seed provider directory (doctors) if empty."""
    if db.query(Provider).count() > 0:
        return

    seed_taxonomy(db)

    # (provider_id, name, hospital, department, speciality, job_title, city)
    seed_data = [
        ("DR-SEED-001", "Dr. Ahmed Benali",   "El-Markazi Hospital", "Cardiology", "Cardiology",       "Cardiologist",         "Setif"),
        ("DR-SEED-002", "Dr. Yasmine Cherif",  "El-Markazi Hospital", "Cardiology", "Cardiology",       "Heart Specialist",     "Setif"),
        ("DR-SEED-003", "Dr. Karim Boudiaf",   "Ibn Sina Clinic",     "ICU",        "Intensive Care",   "Intensivist",          "Setif"),
        ("DR-SEED-004", "Dr. Amina Saadi",     "Ibn Sina Clinic",     "General",    "General Medicine", "General Practitioner", "Setif"),
        ("DR-SEED-005", "Dr. Walid Meziane",   "Algiers Central",     "Cardiology", "Cardiology",       "Cardiologist",         "Algiers"),
        ("DR-SEED-006", "Dr. Sara Khelifi",    "Oran Medical Center", "Diabetic",   "Endocrinology",    "Endocrinologist",      "Oran"),
    ]
    for prov_id, name, hospital, dept, spec, job_title, city in seed_data:
        hospital_row = db.query(Hospital).filter_by(name=hospital).first()
        dept_row = db.query(Department).filter_by(hospital_id=hospital_row.id, name=dept).first()
        spec_row = db.query(Speciality).filter_by(name=spec).first()
        title_row = db.query(JobTitle).filter_by(name=job_title).first()

        db.add(Provider(
            provider_id=prov_id, full_name=name, role="doctor", hospital=hospital,
            department=dept, speciality=job_title, city=city, is_preseeded=True,
            hospital_id=hospital_row.id, department_id=dept_row.id,
            speciality_id=spec_row.id if spec_row else None,
            job_title_id=title_row.id if title_row else None,
        ))
        if not db.query(Participant).filter_by(id=prov_id).first():
            db.add(Participant(
                id=prov_id, display_name=name, role="doctor",
                attributes=json.dumps([f"Role={job_title}", f"Dept={dept}", f"City={city}"]),
                credit_score=100,
            ))
    db.commit()

# Auto-create tables on import
create_tables()
