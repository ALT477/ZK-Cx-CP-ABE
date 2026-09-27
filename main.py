import hashlib
import json
import psutil
import os as _os
import pathlib
import random
import secrets
import time
import traceback as _tb
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import jwt
from collections import deque
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from blockchain import get_blockchain, BlockchainClient
from crypto import CxABEEngine, MasterKey, PublicKey
from database import (
    get_db, seed_providers,
    Participant, Provider, AccessRequestRow, OtpChallenge, SmsOutbox,
    HealthRecord, Block, CriticalAlertRow,
    Hospital, Department, Speciality, JobTitle, Admin,
    PatientSharingPolicy, ZKEligibilityProfile, ZKProofLog,
    SessionLocal
)
from zk_snark import ZKSnarkEngine, EligibilityInput, ZKConfigurationError, ZKProofError

APP_DIR = pathlib.Path(__file__).resolve().parent
FRONTEND = APP_DIR / "frontend"
WEB_VISUALIZER = APP_DIR / "web-visualizer"
ADMIN_UI = APP_DIR / "admin"

_startup_error = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_error
    try:
        db = SessionLocal()
        seed_providers(db)
        db.close()
    except Exception:
        _startup_error = _tb.format_exc()
    yield


app = FastAPI(
    title="IoToDChain API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PERFORMANCE_STATS = {
    "total_requests": 0,
    "successful_requests": 0,
    "failed_requests": 0,
    "latencies_ms": deque(maxlen=200)  # Stores latencies of last 100 requests
}

def record_resource_utilization(duration_sec=1, interval=0.1):
    process = psutil.Process(os.getpid())
    cpu_readings = []
    mem_readings = []

    start_time = time.time()
    while time.time() - start_time < duration_sec:
        cpu_readings.append(process.cpu_percent(interval=interval))
        mem_readings.append(process.memory_info().rss / (1024 * 1024))  # RAM in MB

    return {
        "avg_cpu_percent": round(sum(cpu_readings) / len(cpu_readings), 2) if cpu_readings else 0.0,
        "peak_memory_mb": round(max(mem_readings), 2) if mem_readings else 0.0
    }
@app.get("/api/system/resources")
def get_resource_usage():
    return record_resource_utilization(duration_sec=1, interval=0.1)

@app.middleware("http")
async def add_latency_header(request: Request, call_next):
    auth_header = request.headers.get("Authorization")
    if auth_header:
        print(f"[SESSION TOKEN INCOMING] {auth_header}")

    start_time = time.perf_counter()
    try:
        response = await call_next(request)
        process_time_ms = (time.perf_counter() - start_time) * 1000

        if not request.url.path.endswith("/metrics"):
            PERFORMANCE_STATS["total_requests"] += 1
            if response.status_code < 400:
                PERFORMANCE_STATS["successful_requests"] += 1
            else:
                PERFORMANCE_STATS["failed_requests"] += 1
            PERFORMANCE_STATS["latencies_ms"].append(process_time_ms)

            # Print live timing to console alongside Uvicorn logs
            print(f"[METRIC] {request.method} {request.url.path} | Latency: {process_time_ms:.2f} ms")

        response.headers["X-Process-Time-Ms"] = f"{process_time_ms:.2f}"
        return response
    except Exception as e:
        process_time_ms = (time.perf_counter() - start_time) * 1000
        PERFORMANCE_STATS["total_requests"] += 1
        PERFORMANCE_STATS["failed_requests"] += 1
        PERFORMANCE_STATS["latencies_ms"].append(process_time_ms)
        raise e


@app.get("/api/system/metrics")
def get_performance_metrics():
    # 1. Real Latency Calculation
    latencies = list(PERFORMANCE_STATS["latencies_ms"])
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    min_latency = min(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0

    # 2. Real System Hardware Utilization via psutil
    process = psutil.Process(os.getpid())
    cpu_usage_pct = process.cpu_percent(interval=None)
    memory_usage_mb = process.memory_info().rss / (1024 * 1024)

    total = PERFORMANCE_STATS["total_requests"]
    success_rate = (PERFORMANCE_STATS["successful_requests"] / total * 100) if total > 0 else 100.0

    return {
        "requests": {
            "total": total,
            "success_rate_percent": round(success_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "min_latency_ms": round(min_latency, 2),
            "max_latency_ms": round(max_latency, 2)
        },
        "hardware": {
            "cpu_usage_percent": cpu_usage_pct,
            "memory_usage_mb": round(memory_usage_mb, 2)
        },
        "recent_latencies": [round(l, 2) for l in latencies[-20:]]
    }

if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

if WEB_VISUALIZER.exists():
    app.mount("/monitor", StaticFiles(directory=str(WEB_VISUALIZER), html=True), name="monitor")

if ADMIN_UI.exists():
    app.mount("/admin", StaticFiles(directory=str(ADMIN_UI), html=True), name="admin")


# ── Crypto state (server-side only) ──────────────────────────────────────────

class AppState:
    mk: Optional[MasterKey] = None
    pk: Optional[PublicKey] = None
    keys: dict = {}
    records: dict = {}


state = AppState()


def _ensure_setup():
    if state.mk is None:
        state.mk, state.pk = CxABEEngine.setup(256)


def _ensure_key(participant_id: str, role: str, attributes: list):
    if participant_id not in state.keys:
        _ensure_setup()
        state.keys[participant_id] = CxABEEngine.keygen(
            participant_id, role, attributes, state.mk
        )
    return state.keys[participant_id]


def _patient_attrs(city: str):
    return [f"Role=Patient", f"City={city}"]


def _provider_attrs(hospital: str, department: str, city: str, speciality: Optional[str]):
    role = speciality or "Provider"
    return [f"Role={role}", f"Hospital={hospital}", f"Dept={department}", f"City={city}"]


def _provider_matches_policy(provider: Provider, policy: Optional["PatientSharingPolicy"]) -> bool:
    if not policy or (policy.speciality_id is None and policy.hospital_id is None and policy.department_id is None):
        return False
    if policy.speciality_id is not None and provider.speciality_id != policy.speciality_id:
        return False
    if policy.hospital_id is not None and provider.hospital_id != policy.hospital_id:
        return False
    if policy.department_id is not None and provider.department_id != policy.department_id:
        return False
    return True


def _grant_access(bc: BlockchainClient, patient_id: str, provider_id: str) -> dict:
    bc.set_sim_authorized(provider_id, True)
    specialist_addr = bc.address_for(provider_id)
    record_ref = f"patient:{patient_id}"
    _granted, b = bc.request_access(specialist_addr, record_ref, provider_id)
    return b


# ── JWT session tokens & Auth Dependencies ────────────────────────────────────

def _load_or_create_jwt_secret() -> str:
    path = APP_DIR / ".jwt_secret"
    if path.exists():
        return path.read_text().strip()
    secret = secrets.token_hex(32)
    path.write_text(secret)
    return secret


JWT_SECRET = _load_or_create_jwt_secret()
JWT_ALG = "HS256"
PHONE_TOKEN_MINUTES = 15
SESSION_TOKEN_DAYS = 30


def create_phone_token(phone_number: str) -> str:
    payload = {
        "phone": phone_number,
        "purpose": "phone_verified",
        "exp": datetime.utcnow() + timedelta(minutes=PHONE_TOKEN_MINUTES),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def create_session_token(participant_id: str, role: str) -> str:
    payload = {
        "sub": participant_id,
        "role": role,
        "purpose": "session",
        "exp": datetime.utcnow() + timedelta(days=SESSION_TOKEN_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def _decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.split(" ", 1)[1]


def require_session(authorization: Optional[str] = Header(None)) -> dict:
    token = _bearer_token(authorization)
    payload = _decode_token(token) if token else None
    if not payload or payload.get("purpose") != "session":
        raise HTTPException(401, "Missing or invalid session token")
    return payload


# ── Admin auth ──────────────────────────────────────────────────────────────

def _load_or_create_admin_bootstrap_key() -> str:
    path = APP_DIR / ".admin_bootstrap_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(24)
    path.write_text(key)
    return key


ADMIN_BOOTSTRAP_KEY = _load_or_create_admin_bootstrap_key()


def create_admin_session_token(admin_id: int, username: str) -> str:
    payload = {
        "sub": str(admin_id),
        "username": username,
        "purpose": "admin_session",
        "exp": datetime.utcnow() + timedelta(days=SESSION_TOKEN_DAYS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def require_admin_session(authorization: Optional[str] = Header(None)) -> dict:
    token = _bearer_token(authorization)
    payload = _decode_token(token) if token else None
    if not payload or payload.get("purpose") != "admin_session":
        raise HTTPException(401, "Missing or invalid admin session token")
    return payload


def _consume_phone_token(token: str) -> str:
    payload = _decode_token(token)
    if not payload or payload.get("purpose") != "phone_verified":
        raise HTTPException(401, "Phone verification expired — verify your phone again")
    return payload["phone"]


# ── SMS sender (pluggable) ────────────────────────────────────────────────────

def _to_local_dz_number(phone: str) -> str:
    p = phone.strip().replace(" ", "")
    if p.startswith("+213"):
        return "0" + p[4:]
    if p.startswith("213") and len(p) == 12:
        return "0" + p[3:]
    return p


class SmsSender:
    def send(self, phone: str, message: str) -> None:
        raise NotImplementedError


class SimulationSmsSender(SmsSender):
    def send(self, phone: str, message: str) -> None:
        print(f"[SIMULATED SMS] -> {phone}: {message}")


class QueuedSmsSender(SmsSender):
    def send(self, phone: str, message: str) -> None:
        db = SessionLocal()
        try:
            db.add(SmsOutbox(phone_number=_to_local_dz_number(phone), message=message))
            db.commit()
        finally:
            db.close()


SMS_PROVIDER = _os.environ.get("SMS_PROVIDER", "simulation")
SMS_SIMULATION_MODE = SMS_PROVIDER == "simulation"


def get_sms_sender() -> SmsSender:
    if SMS_PROVIDER == "gateway_queue":
        return QueuedSmsSender()
    return SimulationSmsSender()


sms_sender = get_sms_sender()


def _load_or_create_gateway_key() -> str:
    path = APP_DIR / ".sms_gateway_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(24)
    path.write_text(key)
    return key


SMS_GATEWAY_KEY = _load_or_create_gateway_key()


def require_gateway_key(x_gateway_key: Optional[str] = Header(None)):
    if x_gateway_key != SMS_GATEWAY_KEY:
        raise HTTPException(401, "Invalid gateway key")


OTP_TTL_MINUTES = 5
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_ATTEMPTS = 5


def _hash_code(code: str, phone: str) -> str:
    return hashlib.sha256(f"{phone}:{code}:{JWT_SECRET}".encode()).hexdigest()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def _new_salt() -> str:
    return secrets.token_hex(16)


# ── Schemas ───────────────────────────────────────────────────────────────────

class OtpRequestBody(BaseModel):
    phone_number: str


class OtpVerifyBody(BaseModel):
    phone_number: str
    code: str


class RegisterPatientRequest(BaseModel):
    phone_token: str
    display_name: str
    password: str
    city: str = "Setif"


class RegisterProviderRequest(BaseModel):
    phone_token: str
    display_name: str
    password: str
    role: str  # "doctor" | "nurse"
    hospital_id: int
    department_id: int
    speciality_id: Optional[int] = None
    job_title_id: Optional[int] = None
    city: str = "Setif"


class LoginRequest(BaseModel):
    phone_number: str
    password: str


class AdminBootstrapRequest(BaseModel):
    username: str
    password: str


class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class HospitalReq(BaseModel):
    name: str
    city: str


class DepartmentReq(BaseModel):
    hospital_id: int
    name: str


class SpecialityReq(BaseModel):
    name: str


class JobTitleReq(BaseModel):
    name: str


class AttributeTypeReq(BaseModel):
    code: str
    label: str


class AttributeValueReq(BaseModel):
    value: str


class AdminProviderUpdateReq(BaseModel):
    full_name: Optional[str] = None
    hospital_id: Optional[int] = None
    department_id: Optional[int] = None
    speciality_id: Optional[int] = None
    job_title_id: Optional[int] = None
    city: Optional[str] = None


class AdminPatientUpdateReq(BaseModel):
    display_name: Optional[str] = None
    city: Optional[str] = None


class VitalsSubmitRequest(BaseModel):
    patient_id: str
    heart_rate: int
    systolic: int
    diastolic: int
    temperature: float
    spo2: int
    device_id: Optional[str] = "Android-App"


class CreateRequestBody(BaseModel):
    patient_id: str
    patient_name: Optional[str] = None
    provider_id: str


class RespondRequestBody(BaseModel):
    request_id: int
    provider_id: str
    approve: bool


class RevokeRequestBody(BaseModel):
    patient_id: str
    provider_id: str


class CreateNoteBody(BaseModel):
    patient_id: str
    provider_id: str
    text: str


class ZKEligibilityProfileRequest(BaseModel):
    age: int
    hba1c: float
    ckd: int


class ZKVerifyRequest(BaseModel):
    record_id: str
    proof_policy_id: str = "ProofPolicyID_trial"
    proof: dict
    public: list


# ── Helper Functions ──────────────────────────────────────────────────────────

def _save_block(db: Session, b: dict, tx_type: str):
    try:
        bn = b.get("blockNumber")
        if not bn:
            return
        tx_hash = b.get("txHash")
        existing = db.query(Block).filter_by(tx_hash=tx_hash).first() if tx_hash else None
        if not existing:
            db.add(Block(
                block_number=bn,
                block_hash=b.get("blockHash", ""),
                tx_hash=tx_hash,
                tx_type=tx_type,
                tx_data=json.dumps(b.get("txData", "")),
                verdict=b.get("verdict"),
                validator=b.get("validator", "FOG-NODE-01"),
                gas_used=b.get("gasUsed"),
            ))
            db.commit()
    except Exception:
        db.rollback()


def _describe_critical_reasons(req: VitalsSubmitRequest) -> str:
    reasons = []
    if req.heart_rate > 100: reasons.append(f"HR={req.heart_rate}bpm (>100)")
    if req.heart_rate < 50:  reasons.append(f"HR={req.heart_rate}bpm (<50)")
    if req.spo2 < 95:        reasons.append(f"SpO2={req.spo2}% (<95)")
    if req.temperature > 38.5: reasons.append(f"Temp={req.temperature}°C (>38.5)")
    if req.systolic > 140:   reasons.append(f"Systolic={req.systolic} (>140)")
    if req.systolic < 90:    reasons.append(f"Systolic={req.systolic} (<90)")
    return "; ".join(reasons) or "Vitals out of range"


def _raise_critical_alert(db: Session, bc: BlockchainClient, patient_id: str, reason: str):
    provider_ids = {
        r.provider_id for r in
        db.query(AccessRequestRow).filter_by(patient_id=patient_id, status="approved").all()
    }
    if not provider_ids:
        return

    patient = db.query(Participant).filter_by(id=patient_id).first()
    patient_name = patient.display_name if patient else None

    b = bc.log_critical_alert(patient_id, reason, len(provider_ids))
    _save_block(db, b, "CRITICAL_ALERT")

    for provider_id in provider_ids:
        db.add(CriticalAlertRow(
            patient_id=patient_id, patient_name=patient_name, provider_id=provider_id,
            reason=reason, tx_hash=b.get("txHash"), block_number=b.get("blockNumber"),
        ))
    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    fp = FRONTEND / "iotodchain.html"
    if fp.exists():
        return FileResponse(str(fp))
    return JSONResponse({"message": "IoToDChain API v3"})


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/api/blockchain/status")
def get_blockchain_status(bc: BlockchainClient = Depends(get_blockchain)):
    return {
        "status": "connected",
        "network": "Ganache Local",
        "chain_id": 5777,
        "is_simulated": getattr(bc, "simulated", True),
    }


@app.get("/api/debug/startup-error")
def debug_startup_error():
    return {"error": _startup_error or "none"}


@app.get("/api/debug/fix-db")
def fix_db():
    import sqlite3 as _sq
    from database import DB_PATH, Base, engine
    Base.metadata.create_all(bind=engine)
    try:
        conn = _sq.connect(DB_PATH)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
    except Exception as ex:
        tables = [str(ex)]
    return {
        "db_path": DB_PATH,
        "exists": _os.path.exists(DB_PATH),
        "tables": tables,
    }


# ── Phone + OTP authentication ────────────────────────────────────────────────

def _canonical_phone(raw: str) -> str:
    p = raw.strip().replace(" ", "").replace("-", "")
    if p.startswith("+213"):
        return p
    if p.startswith("00213"):
        return "+213" + p[5:]
    if p.startswith("213") and len(p) == 12:
        return "+213" + p[3:]
    if p.startswith("0") and len(p) == 10:
        return "+213" + p[1:]
    if len(p) == 9:
        return "+213" + p
    return p


@app.post("/api/auth/otp/request")
def otp_request(req: OtpRequestBody, db: Session = Depends(get_db)):
    phone = _canonical_phone(req.phone_number)
    if not phone:
        raise HTTPException(400, "Phone number required")

    recent = db.query(OtpChallenge).filter_by(phone_number=phone).order_by(
        OtpChallenge.created_at.desc()
    ).first()
    if recent:
        elapsed = (datetime.utcnow() - recent.created_at).total_seconds()
        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            wait = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(429, f"Please wait {wait}s before requesting another code")

    code = f"{random.randint(0, 999999):06d}"
    db.add(OtpChallenge(
        phone_number=phone,
        code_hash=_hash_code(code, phone),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    ))
    db.commit()

    sms_sender.send(phone, f"Hi, quick note from IoToDChain: {code}. Thanks for using our service today.")

    response = {"success": True, "message": "Code sent", "expires_in_seconds": OTP_TTL_MINUTES * 60}
    if SMS_SIMULATION_MODE:
        response["debug_otp"] = code
    return response


@app.post("/api/auth/otp/verify")
def otp_verify(req: OtpVerifyBody, db: Session = Depends(get_db)):
    phone = _canonical_phone(req.phone_number)
    challenge = db.query(OtpChallenge).filter_by(phone_number=phone, verified=False).order_by(
        OtpChallenge.created_at.desc()
    ).first()
    if not challenge:
        raise HTTPException(400, "No pending code for this number — request a new one")
    if datetime.utcnow() > challenge.expires_at:
        raise HTTPException(400, "Code expired — request a new one")
    if challenge.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, "Too many attempts — request a new code")

    challenge.attempts += 1
    if challenge.code_hash != _hash_code(req.code.strip(), phone):
        db.commit()
        raise HTTPException(400, "Incorrect code")

    challenge.verified = True
    db.commit()

    participant = db.query(Participant).filter_by(phone_number=phone).first()
    if participant:
        token = create_session_token(participant.id, participant.role)
        return {
            "success": True, "exists": True,
            "participant_id": participant.id, "role": participant.role,
            "token": token,
        }

    phone_token = create_phone_token(phone)
    return {"success": True, "exists": False, "token": phone_token}


@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    phone = _canonical_phone(req.phone_number)
    participant = db.query(Participant).filter_by(phone_number=phone).first()
    if not participant or not participant.password_hash or not participant.password_salt:
        raise HTTPException(401, "Incorrect phone number or password")
    if _hash_password(req.password, participant.password_salt) != participant.password_hash:
        raise HTTPException(401, "Incorrect phone number or password")

    token = create_session_token(participant.id, participant.role)
    return {
        "success": True,
        "participant_id": participant.id, "role": participant.role,
        "token": token,
    }


@app.post("/api/admin/bootstrap")
def admin_bootstrap(
        req: AdminBootstrapRequest,
        x_bootstrap_key: Optional[str] = Header(None),
        db: Session = Depends(get_db),
):
    if x_bootstrap_key != ADMIN_BOOTSTRAP_KEY:
        raise HTTPException(401, "Invalid bootstrap key")
    if db.query(Admin).count() > 0:
        raise HTTPException(403, "An admin account already exists")
    salt = _new_salt()
    db.add(Admin(
        username=req.username,
        password_hash=_hash_password(req.password, salt),
        password_salt=salt,
    ))
    db.commit()
    return {"success": True}


@app.post("/api/admin/login")
def admin_login(req: AdminLoginRequest, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter_by(username=req.username).first()
    if not admin or _hash_password(req.password, admin.password_salt) != admin.password_hash:
        raise HTTPException(401, "Incorrect username or password")
    return {
        "success": True,
        "admin_id": admin.id, "username": admin.username,
        "token": create_admin_session_token(admin.id, admin.username),
    }


@app.post("/api/admin/change-password")
def admin_change_password(
        req: AdminChangePasswordRequest,
        db: Session = Depends(get_db),
        admin_session: dict = Depends(require_admin_session),
):
    admin = db.query(Admin).filter_by(id=int(admin_session["sub"])).first()
    if not admin:
        raise HTTPException(404, "Admin account not found")
    if _hash_password(req.current_password, admin.password_salt) != admin.password_hash:
        raise HTTPException(401, "Current password is incorrect")
    if len(req.new_password) < 4:
        raise HTTPException(400, "New password must be at least 4 characters")
    salt = _new_salt()
    admin.password_hash = _hash_password(req.new_password, salt)
    admin.password_salt = salt
    db.commit()
    return {"success": True}


@app.post("/api/auth/register/patient")
def register_patient(req: RegisterPatientRequest, db: Session = Depends(get_db)):
    phone = _consume_phone_token(req.phone_token)
    if db.query(Participant).filter_by(phone_number=phone).first():
        raise HTTPException(409, "An account already exists for this phone number")

    if len(req.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    patient_id = f"PAT-{secrets.token_hex(4).upper()}"
    attrs = _patient_attrs(req.city)
    _ensure_key(patient_id, "patient", attrs)
    salt = _new_salt()
    db.add(Participant(
        id=patient_id, display_name=req.display_name, role="patient",
        phone_number=phone, attributes=json.dumps(attrs),
        password_salt=salt, password_hash=_hash_password(req.password, salt),
    ))
    db.commit()
    token = create_session_token(patient_id, "patient")
    return {"success": True, "participant_id": patient_id, "role": "patient", "token": token}


@app.post("/api/auth/register/provider")
def register_provider(req: RegisterProviderRequest, db: Session = Depends(get_db)):
    phone = _consume_phone_token(req.phone_token)
    if db.query(Participant).filter_by(phone_number=phone).first():
        raise HTTPException(409, "An account already exists for this phone number")
    if req.role not in ("doctor", "nurse"):
        raise HTTPException(400, "role must be 'doctor' or 'nurse'")
    if len(req.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    hospital = db.query(Hospital).filter_by(id=req.hospital_id, is_active=True).first()
    if not hospital:
        raise HTTPException(404, "Hospital not found")
    department = db.query(Department).filter_by(id=req.department_id, hospital_id=hospital.id, is_active=True).first()
    if not department:
        raise HTTPException(404, "Department not found for this hospital")
    speciality = None
    if req.speciality_id is not None:
        speciality = db.query(Speciality).filter_by(id=req.speciality_id, is_active=True).first()
        if not speciality:
            raise HTTPException(404, "Speciality not found")
    job_title = None
    if req.job_title_id is not None:
        job_title = db.query(JobTitle).filter_by(id=req.job_title_id, is_active=True).first()
        if not job_title:
            raise HTTPException(404, "Job title not found")

    prefix = "DR" if req.role == "doctor" else "NR"
    provider_id = f"{prefix}-{secrets.token_hex(4).upper()}"
    attrs = _provider_attrs(hospital.name, department.name, req.city, job_title.name if job_title else None)
    _ensure_key(provider_id, req.role, attrs)
    salt = _new_salt()

    db.add(Participant(
        id=provider_id, display_name=req.display_name, role=req.role,
        phone_number=phone, attributes=json.dumps(attrs),
        password_salt=salt, password_hash=_hash_password(req.password, salt),
    ))
    db.add(Provider(
        provider_id=provider_id, full_name=req.display_name, role=req.role,
        hospital=hospital.name, department=department.name,
        speciality=job_title.name if job_title else None, city=req.city, is_preseeded=False,
        hospital_id=hospital.id, department_id=department.id,
        speciality_id=speciality.id if speciality else None,
        job_title_id=job_title.id if job_title else None,
    ))
    db.commit()
    token = create_session_token(provider_id, req.role)
    return {"success": True, "participant_id": provider_id, "role": req.role, "token": token}


@app.get("/api/me")
def get_me(db: Session = Depends(get_db), session: dict = Depends(require_session)):
    participant = db.query(Participant).filter_by(id=session["sub"]).first()
    if not participant:
        raise HTTPException(404, "Account not found")

    city = "Setif"
    if participant.attributes:
        try:
            for a in json.loads(participant.attributes):
                if a.startswith("City="):
                    city = a.split("=", 1)[1]
        except Exception:
            pass

    result = {
        "success": True,
        "participant_id": participant.id,
        "display_name": participant.display_name,
        "phone_number": participant.phone_number,
        "role": participant.role,
        "city": city,
        "hospital": None,
        "department": None,
        "speciality": None,
        "hospital_id": None,
        "department_id": None,
        "speciality_id": None,
        "job_title_id": None,
    }
    if participant.role in ("doctor", "nurse"):
        provider = db.query(Provider).filter_by(provider_id=participant.id).first()
        if provider:
            result["hospital"] = provider.hospital
            result["department"] = provider.department
            result["speciality"] = provider.speciality
            result["city"] = provider.city
            result["hospital_id"] = provider.hospital_id
            result["department_id"] = provider.department_id
            result["speciality_id"] = provider.speciality_id
            result["job_title_id"] = provider.job_title_id
    return result


# ── Vitals & Approved Requests Routes ─────────────────────────────────────────

@app.get("/api/requests/approved/{patient_id}")
def get_approved_requests(
        patient_id: str,
        db: Session = Depends(get_db),
        session: dict = Depends(require_session)
):
    if session["sub"] != patient_id and session.get("role") != "patient":
        raise HTTPException(403, "Access denied for this resource")

    approved_rows = db.query(AccessRequestRow).filter_by(
        patient_id=patient_id,
        status="approved"
    ).all()

    results = []
    for row in approved_rows:
        provider = db.query(Provider).filter_by(provider_id=row.provider_id).first()
        results.append({
            "request_id": row.id,
            "provider_id": row.provider_id,
            "provider_name": provider.full_name if provider else row.provider_id,
            "hospital": provider.hospital if provider else None,
            "department": provider.department if provider else None,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None
        })

    return {"success": True, "approved_requests": results}


@app.post("/api/vitals/submit")
def submit_vitals(
        req: VitalsSubmitRequest,
        db: Session = Depends(get_db),
        bc: BlockchainClient = Depends(get_blockchain),
        session: dict = Depends(require_session)
):
    if session["sub"] != req.patient_id:
        raise HTTPException(403, "Cannot submit vitals for another patient")

    record_id = f"REC-{secrets.token_hex(4).upper()}"
    vitals_data = {
        "heart_rate": req.heart_rate,
        "systolic": req.systolic,
        "diastolic": req.diastolic,
        "temperature": req.temperature,
        "spo2": req.spo2,
        "device_id": req.device_id
    }

    _ensure_setup()

    # 1. Get the patient record to retrieve attributes and generate secret key
    patient = db.query(Participant).filter_by(id=req.patient_id).first()
    city = "Setif"
    if patient and patient.attributes:
        try:
            for a in json.loads(patient.attributes):
                if a.startswith("City="):
                    city = a.split("=", 1)[1]
        except Exception:
            pass

    attrs = _patient_attrs(city)
    sk_patient = _ensure_key(req.patient_id, "patient", attrs)

    policy_str = "Role=Patient"

    # 2. Pass patient_id and sk_patient as required by CxABEEngine.encrypt()
    enc_record = CxABEEngine.encrypt(
        plaintext=json.dumps(vitals_data),
        policy=policy_str,
        pk=state.pk,
        patient_id=req.patient_id,
        sk_patient=sk_patient
    )

    # 3. Instantiate HealthRecord using the exact columns from database.py
    db_record = HealthRecord(
        record_id=record_id,
        patient_id=req.patient_id,
        hEncM=enc_record.hEncM,
        ciphertext_b64=getattr(enc_record, "ciphertext_b64", getattr(enc_record, "ct_b64", "")),
        nonce_b64=getattr(enc_record, "nonce_b64", getattr(enc_record, "nonce", "")),
        policy_commit=getattr(enc_record, "policy_commit", getattr(enc_record, "commit", "")),
        policy=json.dumps(policy_str),
        C_b64=getattr(enc_record, "C_b64", None),
        device_id=req.device_id
    )
    db.add(db_record)

    b = bc.register_record(
        req.patient_id,
        record_id,
        enc_record.hEncM,
        req.patient_id,
        []
    )

    if (req.heart_rate > 100 or req.heart_rate < 50 or
            req.spo2 < 95 or req.temperature > 38.5 or
            req.systolic > 140 or req.systolic < 90):
        reason = _describe_critical_reasons(req)
        _raise_critical_alert(db, bc, req.patient_id, reason)

    db.commit()

    return {
        "success": True,
        "message": "Vitals submitted successfully",
        "record_id": record_id,
        "tx_hash": b.get("txHash"),
        "block_number": b.get("blockNumber")
    }

# ── Zero-knowledge eligibility (ZK-Cx-CP-ABE integration) ─────────────────────

ZK_PROOF_POLICY_ID = "ProofPolicyID_trial"
ZK_CONDITION = "(30 <= age <= 60) AND (HbA1c <= 69.0) AND (CKD = 0)"


def _zk_engine() -> ZKSnarkEngine:
    try:
        return ZKSnarkEngine()
    except ZKConfigurationError as exc:
        raise HTTPException(503, str(exc))


def _require_patient_session(session: dict, patient_id: str) -> None:
    if session["sub"] != patient_id:
        raise HTTPException(403, "Token does not match patient_id")
    if session.get("role") != "patient":
        raise HTTPException(403, "Only a patient account may manage this private profile")


@app.get("/api/zk/eligibility/profile")
def get_zk_profile(
        db: Session = Depends(get_db),
        session: dict = Depends(require_session),
):
    if session.get("role") != "patient":
        raise HTTPException(403, "Only patient accounts have an eligibility profile")
    row = db.query(ZKEligibilityProfile).filter_by(patient_id=session["sub"]).first()
    if not row:
        return {"success": True, "configured": False}
    return {
        "success": True,
        "configured": True,
        "patient_id": row.patient_id,
        "age": row.age,
        "hba1c": row.hba1c10 / 10.0,
        "ckd": row.ckd,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@app.put("/api/zk/eligibility/profile")
def update_zk_profile(
        req: ZKEligibilityProfileRequest,
        db: Session = Depends(get_db),
        session: dict = Depends(require_session),
):
    _require_patient_session(session, session["sub"])
    private_input = EligibilityInput(req.age, req.hba1c, req.ckd)
    try:
        private_input.validate()
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    row = db.query(ZKEligibilityProfile).filter_by(patient_id=session["sub"]).first()
    if row:
        row.age = req.age
        row.hba1c10 = round(req.hba1c * 10)
        row.ckd = req.ckd
        row.updated_at = datetime.utcnow()
    else:
        row = ZKEligibilityProfile(
            patient_id=session["sub"],
            age=req.age,
            hba1c10=round(req.hba1c * 10),
            ckd=req.ckd,
        )
        db.add(row)
    db.commit()
    return {"success": True, "message": "Private eligibility profile updated"}


@app.post("/api/zk/eligibility/prove")
def create_zk_eligibility_proof(
        record_id: str,
        proof_policy_id: str = ZK_PROOF_POLICY_ID,
        db: Session = Depends(get_db),
        bc: BlockchainClient = Depends(get_blockchain),
        session: dict = Depends(require_session),
):
    if session.get("role") != "patient":
        raise HTTPException(403, "Only the patient can create an eligibility proof")

    record = db.query(HealthRecord).filter_by(
        record_id=record_id, patient_id=session["sub"]
    ).first()
    if not record:
        raise HTTPException(404, "Health record not found for this patient")

    profile = db.query(ZKEligibilityProfile).filter_by(
        patient_id=session["sub"]
    ).first()
    if not profile:
        raise HTTPException(400, "Eligibility profile is not configured")

    try:
        engine = _zk_engine()
        result = engine.prove_and_verify(
            EligibilityInput(profile.age, profile.hba1c10 / 10.0, profile.ckd),
            proof_policy_id,
            record.hEncM,
            ZK_CONDITION,
        )
    except (ZKConfigurationError, ZKProofError, ValueError) as exc:
        raise HTTPException(500, str(exc))

    b = bc.log_zk_verification(
        session["sub"], record_id, proof_policy_id,
        result["ct_hash"], result["verified"]
    )
    _save_block(db, b, "ZK_VERIFICATION")

    db.add(ZKProofLog(
        patient_id=session["sub"],
        record_id=record_id,
        proof_policy_id=proof_policy_id,
        ct_hash=result["ct_hash"],
        policy_hash=result["policy_hash"],
        verified=result["verified"],
        tx_hash=b.get("txHash"),
        block_number=b.get("blockNumber"),
    ))
    db.commit()

    return {
        "success": True,
        "mode": "ZK_VERIFY",
        "verified": result["verified"],
        "proof_policy_id": proof_policy_id,
        "public": result["public"],
        "proof": result["proof"],
        "prove_ms": result["prove_ms"],
        "verify_ms": result["verify_ms"],
        "tx_hash": b.get("txHash"),
        "block_number": b.get("blockNumber"),
    }


@app.post("/api/zk/eligibility/verify")
def verify_zk_eligibility_proof(
        req: ZKVerifyRequest,
        db: Session = Depends(get_db),
        bc: BlockchainClient = Depends(get_blockchain),
        session: dict = Depends(require_session),
):
    record = db.query(HealthRecord).filter_by(record_id=req.record_id).first()
    if not record:
        raise HTTPException(404, "Health record not found")

    try:
        engine = _zk_engine()
        result = engine.verify_proof_payload(
            proof=req.proof,
            public=req.public,
            proof_policy_id=req.proof_policy_id,
            hEncM=record.hEncM,
            condition_str=ZK_CONDITION,
        )
    except (ZKConfigurationError, ZKProofError, ValueError) as exc:
        raise HTTPException(400, str(exc))

    b = bc.log_zk_verification(
        record.patient_id, req.record_id, req.proof_policy_id,
        result["ct_hash"], result["verified"]
    )
    _save_block(db, b, "ZK_VERIFICATION")

    db.add(ZKProofLog(
        patient_id=record.patient_id,
        record_id=req.record_id,
        proof_policy_id=req.proof_policy_id,
        ct_hash=result["ct_hash"],
        policy_hash=result["policy_hash"],
        verified=result["verified"],
        tx_hash=b.get("txHash"),
        block_number=b.get("blockNumber"),
    ))
    db.commit()

    return {
        "success": True,
        "verified": result["verified"],
        "tx_hash": b.get("txHash"),
        "block_number": b.get("blockNumber"),
    }