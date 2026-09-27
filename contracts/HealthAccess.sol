// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

/**
 * HealthAccess — on-chain audit/registration/consent trail for IoToDChain.
 *
 * Mirrors exactly the function/event/return-tuple shapes that
 * `blockchain.py` (the Python Web3.py client) already expects, so wiring
 * this in is additive: no changes needed to the read/poll side of the
 * pipeline (SQL Block table + web-visualizer), only to how the
 * block-info dicts get produced.
 *
 * Scope: this contract records WHO did WHAT and WHEN (data registration,
 * access-grant decisions, generic audit events) — it does not perform any
 * cryptography itself. The actual CxABE-PRE encrypt/re-encrypt/decrypt
 * happens off-chain (Fog server), exactly as described in the thesis —
 * the contract only formalizes and timestamps the decisions.
 */
contract HealthAccess {
    address public owner;
    mapping(address => bool) public fogNodes;

    struct Record {
        string hCT;
        string policyCommit;
        string ownerID;
        uint256 timestamp;
        address registeredBy;
        bool exists;
    }

    struct AuditEntry {
        string txType;
        string actor;
        string recordID;
        string detail;
        uint256 timestamp;
    }

    mapping(string => Record) private records;
    mapping(address => mapping(string => bool)) private accessGrants;
    AuditEntry[] private auditLog;

    event FogNodeAdded(address indexed node);
    event KeyIssued(address indexed specialist, uint256[] attrIds);
    event RecordRegistered(string indexed recordIdIndexed, string recordId, string ownerID, address registeredBy);
    event AccessGranted(address indexed specialist, string recordId);
    event AccessRevoked(address indexed specialist, string recordId);
    event AuditLogged(string txType, string actor, string recordId);

    modifier onlyOwner() {
        require(msg.sender == owner, "HealthAccess: not owner");
        _;
    }

    modifier onlyFogNode() {
        require(fogNodes[msg.sender], "HealthAccess: not an authorized fog node");
        _;
    }

    constructor() {
        owner = msg.sender;
        fogNodes[msg.sender] = true;
        emit FogNodeAdded(msg.sender);
    }

    // ── Setup (Algorithm 1) ────────────────────────────────────────────────
    function addFogNode(address node) external onlyOwner {
        fogNodes[node] = true;
        emit FogNodeAdded(node);
    }

    // ── KeyGen (Algorithm 2) ────────────────────────────────────────────────
    function logKeyIssuance(address specialist, uint256[] calldata attrIds) external onlyFogNode {
        emit KeyIssued(specialist, attrIds);
        _appendAudit("KEY_ISSUANCE", _toAsciiString(specialist), "", "context attribute set issued");
    }

    // ── Encrypt + register (Algorithm 3 / Process 1 steps 7-9) ─────────────
    function addRecord(
        string calldata recordId,
        string calldata hCT,
        string calldata policyCommit,
        string calldata ownerId,
        uint256[] calldata /* attrIds */
    ) external onlyFogNode {
        records[recordId] = Record({
            hCT: hCT,
            policyCommit: policyCommit,
            ownerID: ownerId,
            timestamp: block.timestamp,
            registeredBy: msg.sender,
            exists: true
        });
        emit RecordRegistered(recordId, recordId, ownerId, msg.sender);
        _appendAudit("DATA_REGISTRATION", ownerId, recordId, "hCT + policyCommit stored");
    }

    // ── Access decision (Process 2: "Validators decide PERMIT/DENY") ───────
    function requestAccess(address specialist, string calldata recordId) external onlyFogNode returns (bool) {
        accessGrants[specialist][recordId] = true;
        emit AccessGranted(specialist, recordId);
        _appendAudit("ACCESS_PERMIT", _toAsciiString(specialist), recordId, "granted");
        return true;
    }

    function revokeAccess(address specialist, string calldata recordId) external onlyFogNode {
        accessGrants[specialist][recordId] = false;
        emit AccessRevoked(specialist, recordId);
        _appendAudit("ACCESS_REVOKED", _toAsciiString(specialist), recordId, "revoked");
    }

    function canAccess(address specialist, string calldata recordId) external view returns (bool) {
        return accessGrants[specialist][recordId];
    }

    // ── Generic audit logger (covers request/approve/decline/revoke logs) ──
    function logEvent(
        string calldata txType,
        string calldata actor,
        string calldata recordId,
        string calldata detail
    ) external onlyFogNode {
        _appendAudit(txType, actor, recordId, detail);
    }

    // ── Reads ────────────────────────────────────────────────────────────
    function getRecord(string calldata recordId)
        external
        view
        returns (
            string memory hCT,
            string memory policyCommit,
            string memory ownerID,
            uint256 timestamp,
            address registeredBy
        )
    {
        Record storage r = records[recordId];
        require(r.exists, "HealthAccess: record not found");
        return (r.hCT, r.policyCommit, r.ownerID, r.timestamp, r.registeredBy);
    }

    function getAuditLogLength() external view returns (uint256) {
        return auditLog.length;
    }

    function getAuditEntry(uint256 index)
        external
        view
        returns (
            string memory txType,
            string memory actor,
            string memory recordID,
            string memory detail,
            uint256 timestamp
        )
    {
        AuditEntry storage e = auditLog[index];
        return (e.txType, e.actor, e.recordID, e.detail, e.timestamp);
    }

    // ── Internal helpers ────────────────────────────────────────────────
    function _appendAudit(
        string memory txType,
        string memory actor,
        string memory recordId,
        string memory detail
    ) internal {
        auditLog.push(
            AuditEntry({txType: txType, actor: actor, recordID: recordId, detail: detail, timestamp: block.timestamp})
        );
        emit AuditLogged(txType, actor, recordId);
    }

    function _toAsciiString(address x) internal pure returns (string memory) {
        bytes memory s = new bytes(42);
        s[0] = "0";
        s[1] = "x";
        for (uint256 i = 0; i < 20; i++) {
            bytes1 b = bytes1(uint8(uint256(uint160(x)) / (2 ** (8 * (19 - i)))));
            bytes1 hi = bytes1(uint8(b) / 16);
            bytes1 lo = bytes1(uint8(b) - 16 * uint8(hi));
            s[2 + 2 * i] = _char(hi);
            s[3 + 2 * i] = _char(lo);
        }
        return string(s);
    }

    function _char(bytes1 b) internal pure returns (bytes1 c) {
        if (uint8(b) < 10) {
            return bytes1(uint8(b) + 0x30);
        } else {
            return bytes1(uint8(b) + 0x57);
        }
    }
}
