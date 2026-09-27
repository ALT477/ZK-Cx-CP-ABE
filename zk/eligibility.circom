pragma circom 2.1.6;

include "node_modules/circomlib/circuits/comparators.circom";

template Eligibility() {
    // Private witness values
    signal input age;
    signal input hba1c10;
    signal input ckd;

    // Public values used to bind the proof to a policy and ciphertext.
    signal input policyHash;
    signal input ctHash;

    signal output eligible;

    component age_ge_30 = LessEqThan(8);
    component age_le_60 = LessEqThan(8);
    component hba1c_le_690 = LessEqThan(16);

    signal t1;
    signal t2;

    // 30 <= age
    age_ge_30.in[0] <== 30;
    age_ge_30.in[1] <== age;

    // age <= 60
    age_le_60.in[0] <== age;
    age_le_60.in[1] <== 60;

    // HbA1c <= 69.0, represented as HbA1c*10 <= 690.
    hba1c_le_690.in[0] <== hba1c10;
    hba1c_le_690.in[1] <== 690;

    // CKD must be binary.
    ckd * (ckd - 1) === 0;

    // Keep multiplication quadratic.
    t1 <== age_ge_30.out * age_le_60.out;
    t2 <== t1 * hba1c_le_690.out;
    eligible <== t2 * (1 - ckd);

    // Proof is generated only for eligible witnesses.
    eligible === 1;
}

component main {public [policyHash, ctHash]} = Eligibility();
