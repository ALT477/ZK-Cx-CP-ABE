// Same-origin by default (works whether this is served from the domain root
// or a sub-path like /iotodchain/monitor/, since this bundle is mounted at
// "<app-root>/monitor" by the FastAPI backend itself).
const API_BASE = window.location.origin + window.location.pathname.split("/monitor")[0];

const BLOCKS_POLL_MS = 3000;
const REQUESTS_POLL_MS = 3000;
const STATUS_POLL_MS = 5000;
const PULSE_STEP_MS = 220;
const PULSE_DURATION_MS = 900;

let seenBlockKeys = new Set();
let firstBlocksPoll = true;
let seenRequestKeys = new Set();
let blockFeedCount = 0;
let requestLogCount = 0;

document.getElementById("apiBaseLabel").textContent = API_BASE;

// Ties each on-chain tx type back to the exact thesis terminology/algorithm
// the jury sees in the slides.
const THESIS_LABELS = {
  CA_SETUP: "Algorithm 1: Setup (CA registers fog node)",
  KEY_ISSUANCE: "Algorithm 2: KeyGen (attribute-bound key issued)",
  DATA_REGISTRATION: "Algorithm 3: Encrypt — Process 1, steps 7-9 (hCT + policy commit on-chain)",
  ACCESS_INTENT: "Process 2, step 1-3: Access request logged",
  ACCESS_PERMIT: "Process 2: Validator decision — PERMIT",
  ACCESS_DENY: "Process 2: Validator decision — DENY",
  ACCESS_REVOKED: "Access revoked by patient",
  REVOCATION: "Access revoked by patient",
  CRITICAL_ALERT: "🚨 Critical vitals detected — providers notified",
};

function thesisLabel(txType) {
  return THESIS_LABELS[txType] || txType || "Transaction";
}

async function fetchJson(path) {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function setPollingIndicator(ok) {
  const el = document.getElementById("pollingIndicator");
  el.className = ok ? "badge badge-live" : "badge badge-neutral";
  el.textContent = ok ? "● live" : "● offline";
}

function shortHash(hash) {
  if (!hash) return "—";
  return hash.length > 18 ? `${hash.slice(0, 10)}…${hash.slice(-6)}` : hash;
}

function formatTime(isoString) {
  if (!isoString) return "";
  try {
    return new Date(isoString).toLocaleTimeString();
  } catch (e) {
    return isoString;
  }
}

function nodeForValidator(validator) {
  if (!validator) return "cloud";
  return validator.toUpperCase().startsWith("FOG") ? "fog" : "cloud";
}

function pulseNode(node, statusClass) {
  const el = document.querySelector(`.flow-node[data-node="${node}"]`);
  if (!el) return;
  el.classList.add(statusClass);
  setTimeout(() => el.classList.remove(statusClass), PULSE_DURATION_MS);
}

function pulseArrow(arrow) {
  const el = document.querySelector(`.flow-arrow[data-arrow="${arrow}"]`);
  if (!el) return;
  el.classList.add("active");
  setTimeout(() => el.classList.remove("active"), PULSE_DURATION_MS);
}

function pulseSequence(sequence, statusClass) {
  sequence.forEach((step, index) => {
    setTimeout(() => {
      if (step.type === "node") pulseNode(step.id, statusClass);
      else pulseArrow(step.id);
    }, index * PULSE_STEP_MS);
  });
}

function pulseFlowForBlock(validator, denied, alert = false) {
  const statusClass = alert ? "alert" : denied ? "denied" : "active";

  const sequence = [
    { type: "node", id: "patient" },
    { type: "arrow", id: "patient-proxy" },
    { type: "node", id: "proxy" },
    { type: "arrow", id: "proxy-fog" },
    { type: "node", id: "fog" },
    { type: "arrow", id: "fog-chain" },
    { type: "node", id: "chain" },
    { type: "arrow", id: "chain-cloud" },
    { type: "node", id: "cloud" },
    { type: "arrow", id: "cloud-doctor" },
    { type: "node", id: "doctor" },
  ];

  pulseSequence(sequence, statusClass);
}

function renderBlockFeedItem(block) {
  const feed = document.getElementById("blockFeed");
  const empty = feed.querySelector(".empty-state");
  if (empty) empty.remove();

  const isAlert = block.txType === "CRITICAL_ALERT";
  const denied = !isAlert && (block.verdict === false || block.verdict === "REJECT" || block.verdict === "DENY");
  const statusClass = isAlert ? "status-alert" : denied ? "status-denied" : "status-success";
  const pillText = isAlert ? "ALERT" : denied ? "DENY" : "OK";

  const item = document.createElement("div");
  item.className = `feed-item ${statusClass}`;
  item.innerHTML = `
    <div class="feed-item-top">
      <span>Block #${block.blockNumber ?? "—"} · ${block.txType ?? "TX"}</span>
      <span class="status-pill">${pillText}</span>
    </div>
    <div class="feed-item-thesis">${thesisLabel(block.txType)}</div>
    <div class="feed-item-meta">
      validator: ${block.validator ?? "—"} · gas: <span class="gas-value">${block.gasUsed ?? "—"}</span> · ${formatTime(block.timestamp)}<br/>
      hash: ${shortHash(block.blockHash)}
    </div>
  `;
  feed.prepend(item);

  while (feed.children.length > 40) {
    feed.removeChild(feed.lastChild);
  }

  blockFeedCount += 1;
  document.getElementById("blockCount").textContent = blockFeedCount;
}

function pick(obj, keys) {
  for (const key of keys) {
    if (obj[key] !== undefined && obj[key] !== null) return obj[key];
  }
  return null;
}

function renderAccessLogItem(request) {
  const log = document.getElementById("accessLog");
  const empty = log.querySelector(".empty-state");
  if (empty) empty.remove();

  const status = String(pick(request, ["status"]) ?? "pending").toLowerCase();
  const statusClass = status.includes("approve") || status.includes("grant")
    ? "status-success"
    : status.includes("declin") || status.includes("deny") || status.includes("reject")
      ? "status-denied"
      : "status-pending";

  const patientId = pick(request, ["patient_id", "patientId"]) ?? "—";
  const doctorId = pick(request, ["doctor_id", "doctorId"]) ?? "—";
  const requestedAt = pick(request, ["requested_at", "requestedAt", "timestamp"]);

  const item = document.createElement("div");
  item.className = `log-item ${statusClass}`;
  item.innerHTML = `
    <div class="log-item-top">
      <span>${patientId} → ${doctorId}</span>
      <span class="status-pill">${status.toUpperCase()}</span>
    </div>
    <div class="log-item-meta">${formatTime(requestedAt)}</div>
  `;
  log.prepend(item);

  while (log.children.length > 40) {
    log.removeChild(log.lastChild);
  }

  requestLogCount += 1;
  document.getElementById("requestCount").textContent = requestLogCount;

  if (statusClass === "status-denied") {
    pulseSequence(
      [
        { type: "node", id: "proxy" },
        { type: "arrow", id: "proxy-fog" },
        { type: "node", id: "fog" },
      ],
      "denied"
    );
  }
}

async function pollBlocks() {
  try {
    const blocks = await fetchJson("/api/internal/blocks");
    setPollingIndicator(true);
    if (!Array.isArray(blocks) || blocks.length === 0) return;

    // Backend returns newest-first. blockNumber is NOT a reliable ordering
    // key here — it resets to 1 on any fresh chain (simulated or a newly
    // (re)deployed live one) — so track new blocks by tx/block hash identity.
    let newBlocks = [];
    for (const block of blocks) {
      const key = block.txHash || block.blockHash;
      if (!key || seenBlockKeys.has(key)) break;
      seenBlockKeys.add(key);
      newBlocks.push(block);
    }

    if (firstBlocksPoll) {
      // Don't animate the entire history on first load — just the last few.
      newBlocks = newBlocks.slice(0, 5);
      firstBlocksPoll = false;
    }

    newBlocks.reverse().forEach((block, index) => {
      setTimeout(() => {
        renderBlockFeedItem(block);
        const isAlert = block.txType === "CRITICAL_ALERT";
        const denied = !isAlert && (block.verdict === false || block.verdict === "REJECT" || block.verdict === "DENY");
        pulseFlowForBlock(block.validator, denied, isAlert);
        document.getElementById("fogNodeName").textContent =
          nodeForValidator(block.validator) === "fog" ? block.validator : "—";
        document.getElementById("cloudNodeName").textContent =
          nodeForValidator(block.validator) === "cloud" ? block.validator : "—";
        document.getElementById("chainBlockNumber").textContent = `block #${block.blockNumber}`;
      }, index * 400);
    });
  } catch (e) {
    setPollingIndicator(false);
  }
}

async function pollRequests() {
  try {
    const requests = await fetchJson("/api/internal/requests");
    if (!Array.isArray(requests)) return;

    requests.forEach((request) => {
      const key = JSON.stringify(pick(request, ["id", "request_id", "requestId"]) ?? request);
      if (seenRequestKeys.has(key)) return;
      seenRequestKeys.add(key);
      renderAccessLogItem(request);
    });
  } catch (e) {
    // Non-fatal — access log simply won't update this cycle.
  }
}

let lastContractAddress = null;

async function pollStatus() {
  const badge = document.getElementById("chainModeBadge");
  const chainIdEl = document.getElementById("chainIdValue");
  const blockEl = document.getElementById("chainBlockValue");
  const addressEl = document.getElementById("contractAddressValue");

  try {
    const status = await fetchJson("/api/internal/blockchain/status");
    const isLive = status.connected && status.mode !== "simulation";

    if (isLive) {
      badge.textContent = "🟢 LIVE — Ganache";
      badge.className = "chain-mode-badge mode-live";
      chainIdEl.textContent = status.chainId ?? "—";
      blockEl.textContent = status.blockNumber != null ? `#${status.blockNumber}` : "—";
      lastContractAddress = status.contract ?? null;
      addressEl.textContent = lastContractAddress ? shortHash(lastContractAddress) : "—";
    } else {
      badge.textContent = "🔴 SIMULATED (fallback)";
      badge.className = "chain-mode-badge mode-sim";
      chainIdEl.textContent = "—";
      blockEl.textContent = status.blocks != null ? `${status.blocks} sim blocks` : "—";
      lastContractAddress = null;
      addressEl.textContent = "—";
    }
  } catch (e) {
    badge.textContent = "Status unavailable";
    badge.className = "chain-mode-badge badge-neutral";
    chainIdEl.textContent = "—";
    blockEl.textContent = "—";
    lastContractAddress = null;
    addressEl.textContent = "—";
  }
}

document.getElementById("contractAddressBtn").addEventListener("click", async () => {
  if (!lastContractAddress) return;
  const btn = document.getElementById("contractAddressBtn");
  try {
    await navigator.clipboard.writeText(lastContractAddress);
    btn.classList.add("copied");
    setTimeout(() => btn.classList.remove("copied"), 1200);
  } catch (e) {
    // Clipboard API unavailable — non-fatal, address is still shown on screen.
  }
});

pollBlocks();
pollRequests();
pollStatus();

setInterval(pollBlocks, BLOCKS_POLL_MS);
setInterval(pollRequests, REQUESTS_POLL_MS);
setInterval(pollStatus, STATUS_POLL_MS);
