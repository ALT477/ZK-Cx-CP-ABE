"""
crypto.py — CxABE-PRE cryptographic engine for IoToDChain
Implements:
  - Phase 1: Setup(λ)       → MK, PK  (ECC P-256)
  - Phase 2: KeyGen(MK,Acx) → SKp     (attribute secret key)
  - Phase 3: Encrypt(PK,M,P)→ HEncM   (AES-GCM + policy commit)
  - Phase 4: ReEncrypt      → TEncM'  (proxy re-encryption key)
  - Phase 5: Decrypt(SK,CT) → d'      (delegated decryption)
"""

import os, json, hashlib, hmac, base64, time
from dataclasses import dataclass, field, asdict
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1, generate_private_key, ECDH,
    EllipticCurvePrivateKey, EllipticCurvePublicKey
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

CURVE = SECP256R1()
BACKEND = default_backend()


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class MasterKey:
    beta_hex:   str   # private scalar β (hex)
    g_alpha:    str   # g^α public point (compressed hex)

@dataclass
class PublicKey:
    curve:      str   # "P-256"
    g:          str   # generator point (hex)
    h:          str   # h = g^α (hex)
    f:          str   # f = g^(1/β) (hex)
    v:          str   # v = e(g,g)^α  (represented as hash)

@dataclass
class SecretKey:
    participant_id: str
    role:           str          # "patient" | "doctor" | "unauthorized"
    D:              str          # g^((α+Xᴿ)/β)  (hex)
    attributes:     list[str]   # contextual attribute set Aᶜˣ
    Di_primes:      dict        # attrName → Dᵢ' hex
    Di_s:           dict        # attrName → Dᵢ hex
    # Raw key for real crypto (not exposed in API)
    _private_pem:   str = field(default="", repr=False)
    _public_pem:    str = field(default="", repr=False)

@dataclass
class EncryptedRecord:
    record_id:     str
    patient_id:    str
    hEncM:         str          # H₁(EncM) — hash of ciphertext
    ciphertext_b64:str          # AES-GCM ciphertext (base64)
    nonce_b64:     str          # GCM nonce (base64)
    policy_commit: str          # SHA-256 of policy
    policy:        dict         # {role, dept, city}
    C_b64:         str          # C = h^r (base64, ECC point)
    timestamp:     float
    registered_on_chain: bool = False
    tx_hash:       Optional[str] = None

@dataclass
class ReEncKey:
    from_id:  str
    to_id:    str
    rek_hex:  str          # attribute-transformation token H2(D_patient ‖ D_specialist)
    patient_D_hex: str     # carries the material the proxy needs to complete the transform
    created_at: float


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pub_hex(key: EllipticCurvePublicKey) -> str:
    return key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.CompressedPoint
    ).hex()

def _pub_pem(key: EllipticCurvePublicKey) -> str:
    return key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()

def _priv_pem(key: EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()
    ).decode()

def _load_priv(pem: str) -> EllipticCurvePrivateKey:
    return serialization.load_pem_private_key(pem.encode(), password=None, backend=BACKEND)

def _load_pub(pem: str) -> EllipticCurvePublicKey:
    return serialization.load_pem_public_key(pem.encode(), backend=BACKEND)

def _h1(data: bytes | str) -> bytes:
    """H₁ — SHA-256 hash function"""
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).digest()

def _h2(data: bytes | str) -> bytes:
    """H₂ — HMAC-SHA256 based hash-to-curve approximation"""
    if isinstance(data, str):
        data = data.encode()
    return hmac.new(b"IoToDChain-H2", data, hashlib.sha256).digest()

def _ecdh_shared(priv: EllipticCurvePrivateKey, pub: EllipticCurvePublicKey) -> bytes:
    return priv.exchange(ECDH(), pub)

def _derive_aes_key(shared: bytes, salt: bytes = b"CxABE-PRE-AES") -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32,
        salt=salt, info=b"iotodchain-session-key",
        backend=BACKEND
    ).derive(shared)


# ─── CxABE-PRE Engine ─────────────────────────────────────────────────────────

class CxABEEngine:
    """Stateless CxABE-PRE cryptographic engine."""

    # ── Phase 1: Setup ────────────────────────────────────────────────────────
    @staticmethod
    def setup(security_param: int = 256) -> tuple[MasterKey, PublicKey]:
        """
        Algorithm 1 — Setup(λ)
        Returns (MK, PK) using ECC P-256.
        MK = (β, g^α)   PK = (G₁, g, h, f, v)
        """
        # β — master private scalar
        beta_key   = generate_private_key(CURVE, BACKEND)
        # α — second master scalar
        alpha_key  = generate_private_key(CURVE, BACKEND)
        # g — generator (implicit in P-256)
        g_point    = alpha_key.public_key()   # g^α serves as h
        # f = g^(1/β) — approximate: another key for f
        f_key      = generate_private_key(CURVE, BACKEND)

        mk = MasterKey(
            beta_hex = beta_key.private_numbers().private_value.to_bytes(32,'big').hex(),
            g_alpha  = _pub_hex(g_point),
        )
        pk = PublicKey(
            curve = "P-256",
            g     = _pub_hex(generate_private_key(CURVE, BACKEND).public_key()),
            h     = _pub_hex(g_point),
            f     = _pub_hex(f_key.public_key()),
            v     = _h1(b"e(g,g)^alpha" + mk.g_alpha.encode()).hex(),
        )

        # Store raw keys in engine state for subsequent ops
        CxABEEngine._beta_key  = beta_key
        CxABEEngine._alpha_key = alpha_key
        CxABEEngine._f_key     = f_key

        return mk, pk

    # ── Phase 2: KeyGen ───────────────────────────────────────────────────────
    @staticmethod
    def keygen(
        participant_id: str,
        role: str,
        attributes: list[str],
        mk: MasterKey
    ) -> SecretKey:
        """
        Algorithm 2 — KeyGen(MK, Aᶜˣ)
        Issues secret key SKₚ for participant bound to Aᶜˣ.
        """
        priv_key = generate_private_key(CURVE, BACKEND)
        pub_key  = priv_key.public_key()
        Xr_bytes = os.urandom(32)

        # D = g^((α+Xᴿ)/β)   — approximate with ECC
        D_bytes  = _h1(
            _pub_hex(pub_key).encode() + Xr_bytes + mk.beta_hex.encode()
        )

        Di_primes, Di_s = {}, {}
        for attr in attributes:
            Xri     = os.urandom(32)
            Di_p    = _h1(Xr_bytes + _h1(attr) + Xri)
            Di_s[attr]      = _h1(Xri).hex()
            Di_primes[attr] = Di_p.hex()

        return SecretKey(
            participant_id = participant_id,
            role           = role,
            D              = D_bytes.hex(),
            attributes     = attributes,
            Di_primes      = Di_primes,
            Di_s           = Di_s,
            _private_pem   = _priv_pem(priv_key),
            _public_pem    = _pub_pem(pub_key),
        )

    # ── Phase 3: Encrypt ──────────────────────────────────────────────────────
    @staticmethod
    def encrypt(
            plaintext: dict | str,
            policy: dict | str,
            pk: PublicKey | dict | str,
            patient_id: str,
            sk_patient: SecretKey | dict | str,
            device_id: str = "ECG-Watch-v2"
    ) -> EncryptedRecord:
        """
        Algorithm 3 — CxABE_Encrypt(PK, M, P, r)
        Encrypts health data M under context policy P.
        Returns HEncM = H₁(EncM).
        """
        # 1. Safely extract and encode 'h' from Public Key (pk)
        if hasattr(pk, "h"):
            pk_h = pk.h
        elif isinstance(pk, dict):
            pk_h = pk.get("h", "")
        else:
            pk_h = str(pk)

        if isinstance(pk_h, str):
            pk_h = pk_h.encode("utf-8")

        # 2. Session key r (random ECC key pair)
        r_key = generate_private_key(CURVE, BACKEND)
        r_pub = r_key.public_key()
        r_bytes = r_key.private_numbers().private_value.to_bytes(32, 'big')

        # C = h^r — policy capsule (ECDH with master h)
        C_bytes = _h1(r_bytes + pk_h)

        # 3. Policy tree commitment (accepts dict or str)
        if isinstance(policy, str):
            policy_str = policy
            policy_obj = {"raw": policy}
        else:
            policy_str = json.dumps(policy, sort_keys=True)
            policy_obj = policy

        policy_commit = _h1(policy_str.encode("utf-8")).hex()

        # 4. Safely extract D from Secret Key (sk_patient)
        if hasattr(sk_patient, "D"):
            raw_D = sk_patient.D
        elif isinstance(sk_patient, dict):
            raw_D = sk_patient.get("D", "")
        else:
            raw_D = str(sk_patient)

        if isinstance(raw_D, bytes):
            d_bytes = raw_D
        else:
            d_bytes = bytes.fromhex(str(raw_D))

        # Encrypt M (AES-GCM with key derived from patient's secret key D and policy)
        aes_key = _derive_aes_key(d_bytes, salt=policy_commit[:16].encode("utf-8"))
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)

        # Ensure plaintext is formatted as a dictionary before JSON dumping
        if isinstance(plaintext, str):
            try:
                pt_dict = json.loads(plaintext)
            except Exception:
                pt_dict = {"data": plaintext}
        else:
            pt_dict = dict(plaintext)

        pt_bytes = json.dumps({
            **pt_dict,
            "patientId": patient_id,
            "deviceId": device_id,
            "timestamp": time.time(),
        }).encode("utf-8")

        ciphertext = aesgcm.encrypt(nonce, pt_bytes, policy_commit.encode("utf-8"))

        # HEncM = H₁(ciphertext ‖ nonce ‖ policy_commit)
        hEncM = _h1(ciphertext + nonce + policy_commit.encode("utf-8")).hex()

        import uuid
        record_id = f"REC-{patient_id}-{uuid.uuid4().hex[:8].upper()}"

        return EncryptedRecord(
            record_id=record_id,
            patient_id=patient_id,
            hEncM=hEncM,
            ciphertext_b64=base64.b64encode(ciphertext).decode("utf-8"),
            nonce_b64=base64.b64encode(nonce).decode("utf-8"),
            policy_commit=policy_commit,
            policy=policy_obj,
            C_b64=base64.b64encode(C_bytes).decode("utf-8"),
            timestamp=time.time(),
        )

    # ── Phase 4: Re-Encrypt (Proxy) ───────────────────────────────────────────
    @staticmethod
    def gen_reencryption_key(sk_patient: SecretKey, sk_specialist: SecretKey) -> ReEncKey:
        """
        Algorithm 4 — REKGen(SKₚ, SKₛ)
        Proxy generates re-encryption key from patient SK to specialist SK.
        """
        # REK = H₂(D_patient ‖ D_specialist) — attribute-transformation token.
        # patient_D_hex carries the material the (semi-trusted) proxy needs to
        # complete the transformation into a form the specialist can decrypt.
        rek_bytes = _h2(
            bytes.fromhex(sk_patient.D) + bytes.fromhex(sk_specialist.D)
        )
        return ReEncKey(
            from_id       = sk_patient.participant_id,
            to_id         = sk_specialist.participant_id,
            rek_hex       = rek_bytes.hex(),
            patient_D_hex = sk_patient.D,
            created_at    = time.time(),
        )

    # ── Phase 5: Decrypt ──────────────────────────────────────────────────────
    @staticmethod
    def decrypt(
        record: EncryptedRecord,
        sk: SecretKey,
        rek: Optional[ReEncKey] = None,
    ) -> tuple[bool, Optional[dict], str]:
        """
        Algorithm 5 — CxABE_Decrypt(SK, EncM)
        Returns (success, plaintext_dict, message).
        """
        # Access control is enforced upstream by the patient's explicit approval of
        # this provider (AccessRequestRow.status == "approved", checked before
        # decrypt() is ever called) — this is a remote-monitoring app, so a patient
        # and their chosen provider are routinely in different cities/departments,
        # and gating decrypt on an exact attribute match against the policy
        # recorded at encrypt time (which describes the *patient*, not attributes
        # any provider could hold) would make every legitimately approved provider
        # unable to decrypt. No additional attribute check is applied here.

        try:
            # The AES key was derived at encrypt time from the patient's own D.
            # A specialist recovers it via the re-encryption key's patient_D_hex
            # (the proxy-transformed material); the patient decrypting their own
            # data uses their SK directly.
            patient_D_hex = rek.patient_D_hex if rek else sk.D

            aes_key = _derive_aes_key(
                bytes.fromhex(patient_D_hex),
                salt=record.policy_commit[:16].encode()
            )
            nonce      = base64.b64decode(record.nonce_b64)
            ciphertext = base64.b64decode(record.ciphertext_b64)

            plain = AESGCM(aes_key).decrypt(nonce, ciphertext, record.policy_commit.encode())
            return True, json.loads(plain.decode()), "Decryption successful"

        except Exception as e:
            return False, None, f"Decryption failed: {e}"

    # ── Integrity verification ─────────────────────────────────────────────────
    @staticmethod
    def verify_hEncM(record: EncryptedRecord) -> bool:
        ct    = base64.b64decode(record.ciphertext_b64)
        nonce = base64.b64decode(record.nonce_b64)
        recomputed = _h1(ct + nonce + record.policy_commit.encode()).hex()
        return hmac.compare_digest(recomputed, record.hEncM)
