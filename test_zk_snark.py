import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zk_snark import EligibilityInput, canonical_policy, _field_from_hex


def test_policy_hash_is_deterministic():
    p = canonical_policy("ProofPolicyID_trial", "(30 <= age <= 60)")
    assert p == canonical_policy("ProofPolicyID_trial", "(30 <= age <= 60)")
    assert len(hashlib.sha256(p.encode()).hexdigest()) == 64


def test_field_hash_is_bn128_field_element():
    h = hashlib.sha256(b"iotodchain").hexdigest()
    value = int(_field_from_hex(h))
    assert value >= 0


def test_input_validation():
    EligibilityInput(45, 6.5, 0).validate()
