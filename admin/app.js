const API_BASE = window.location.origin + window.location.pathname.split("/admin")[0];

const token = localStorage.getItem("admin_token");
if (!token) {
  window.location.href = "login.html";
}

async function adminFetch(path, opts = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(opts.headers || {}),
    },
  });
  if (response.status === 401) {
    localStorage.removeItem("admin_token");
    window.location.href = "login.html";
    throw new Error("unauthorized");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.appendChild(child);
  return node;
}

function showModal(title, formHtml, onSubmit) {
  const backdrop = document.getElementById("modalBackdrop");
  const modal = document.getElementById("modal");
  modal.innerHTML = `
    <h3>${title}</h3>
    <form id="modalForm">${formHtml}</form>
    <div class="modal-actions">
      <button type="button" class="btn btn-secondary" id="modalCancel">Cancel</button>
      <button type="submit" form="modalForm" class="btn btn-primary">Save</button>
    </div>
    <p class="error-text" id="modalError"></p>
  `;
  backdrop.classList.remove("hidden");
  document.getElementById("modalCancel").addEventListener("click", () => backdrop.classList.add("hidden"));
  document.getElementById("modalForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    try {
      await onSubmit(Object.fromEntries(formData.entries()));
      backdrop.classList.add("hidden");
      loadView(currentView);
    } catch (err) {
      document.getElementById("modalError").textContent = err.message;
    }
  });
}

function hideAddButton() {
  const btn = document.getElementById("btnAddNew");
  btn.classList.add("hidden");
}

function showAddButton(label, onClick) {
  const btn = document.getElementById("btnAddNew");
  btn.textContent = label;
  btn.classList.remove("hidden");
  btn.onclick = onClick;
}

// ── Generic CRUD view for the 4 simple lookup entities ──────────────────────

const LOOKUP_CONFIGS = {
  hospitals: {
    title: "Hospitals",
    endpoint: "/api/admin/hospitals",
    columns: [{ key: "name", label: "Name" }, { key: "city", label: "City" }],
    fields: [
      { key: "name", label: "Name", type: "text" },
      { key: "city", label: "City", type: "text" },
    ],
  },
  specialities: {
    title: "Specialities",
    endpoint: "/api/admin/specialities",
    columns: [{ key: "name", label: "Name" }],
    fields: [{ key: "name", label: "Name", type: "text" }],
  },
  "job-titles": {
    title: "Job Titles",
    endpoint: "/api/admin/job-titles",
    columns: [{ key: "name", label: "Name" }],
    fields: [{ key: "name", label: "Name", type: "text" }],
  },
};

async function renderLookupView(key) {
  const config = LOOKUP_CONFIGS[key];
  const rows = await adminFetch(config.endpoint);
  const content = document.getElementById("content");

  if (rows.length === 0) {
    content.innerHTML = '<p class="empty-state">Nothing here yet.</p>';
  } else {
    const table = el("table");
    const thead = el("tr", {}, [
      ...config.columns.map((c) => el("th", { text: c.label })),
      el("th", { text: "Status" }),
      el("th", { text: "" }),
    ]);
    table.appendChild(el("thead", {}, [thead]));
    const tbody = el("tbody");
    rows.forEach((row) => {
      const tr = el("tr", {}, [
        ...config.columns.map((c) => el("td", { text: row[c.key] ?? "" })),
        el("td", {}, [el("span", { class: row.is_active ? "pill pill-active" : "pill pill-inactive", text: row.is_active ? "Active" : "Inactive" })]),
        el("td", { class: "row-actions" }, [
          el("button", {
            class: "btn btn-secondary",
            text: "Edit",
            onClick: () => openLookupForm(key, row),
          }),
          el("button", {
            class: "btn btn-danger",
            text: "Deactivate",
            onClick: async () => {
              if (!confirm(`Deactivate "${row.name}"?`)) return;
              await adminFetch(`${config.endpoint}/${row.id}`, { method: "DELETE" });
              loadView(key);
            },
          }),
          el("button", {
            class: "btn btn-danger",
            text: "Delete",
            onClick: async () => {
              if (!confirm(`Permanently delete "${row.name}"? This cannot be undone.`)) return;
              try {
                await adminFetch(`${config.endpoint}/${row.id}/permanent`, { method: "DELETE" });
                loadView(key);
              } catch (e) {
                alert(e.message);
              }
            },
          }),
        ]),
      ]);
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    content.innerHTML = "";
    content.appendChild(table);
  }

  showAddButton(`+ Add ${config.title.replace(/s$/, "")}`, () => openLookupForm(key, null));
}

function openLookupForm(key, existing) {
  const config = LOOKUP_CONFIGS[key];
  const formHtml = config.fields
    .map(
      (f) => `
    <div class="field">
      <label>${f.label}</label>
      <input name="${f.key}" type="text" value="${existing ? (existing[f.key] ?? "") : ""}" required />
    </div>`
    )
    .join("");

  showModal(existing ? `Edit ${config.title.replace(/s$/, "")}` : `Add ${config.title.replace(/s$/, "")}`, formHtml, async (values) => {
    const path = existing ? `${config.endpoint}/${existing.id}` : config.endpoint;
    await adminFetch(path, { method: existing ? "PUT" : "POST", body: JSON.stringify(values) });
  });
}

// ── Departments (needs a hospital dropdown) ──────────────────────────────────

async function renderDepartmentsView() {
  const [departments, hospitals] = await Promise.all([
    adminFetch("/api/admin/departments"),
    adminFetch("/api/admin/hospitals"),
  ]);
  const hospitalById = Object.fromEntries(hospitals.map((h) => [h.id, h]));
  const content = document.getElementById("content");

  if (departments.length === 0) {
    content.innerHTML = '<p class="empty-state">Nothing here yet.</p>';
  } else {
    const table = el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Name" }), el("th", { text: "Hospital" }), el("th", { text: "Status" }), el("th", { text: "" })])]),
    ]);
    const tbody = el("tbody");
    departments.forEach((d) => {
      const hospital = hospitalById[d.hospital_id];
      tbody.appendChild(
        el("tr", {}, [
          el("td", { text: d.name }),
          el("td", { text: hospital ? hospital.name : `#${d.hospital_id}` }),
          el("td", {}, [el("span", { class: d.is_active ? "pill pill-active" : "pill pill-inactive", text: d.is_active ? "Active" : "Inactive" })]),
          el("td", { class: "row-actions" }, [
            el("button", { class: "btn btn-secondary", text: "Edit", onClick: () => openDepartmentForm(d, hospitals) }),
            el("button", {
              class: "btn btn-danger",
              text: "Deactivate",
              onClick: async () => {
                if (!confirm(`Deactivate "${d.name}"?`)) return;
                await adminFetch(`/api/admin/departments/${d.id}`, { method: "DELETE" });
                loadView("departments");
              },
            }),
            el("button", {
              class: "btn btn-danger",
              text: "Delete",
              onClick: async () => {
                if (!confirm(`Permanently delete "${d.name}"? This cannot be undone.`)) return;
                try {
                  await adminFetch(`/api/admin/departments/${d.id}/permanent`, { method: "DELETE" });
                  loadView("departments");
                } catch (e) {
                  alert(e.message);
                }
              },
            }),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    content.innerHTML = "";
    content.appendChild(table);
  }

  showAddButton("+ Add Department", () => openDepartmentForm(null, hospitals));
}

function openDepartmentForm(existing, hospitals) {
  const options = hospitals
    .map((h) => `<option value="${h.id}" ${existing && existing.hospital_id === h.id ? "selected" : ""}>${h.name}</option>`)
    .join("");
  const formHtml = `
    <div class="field">
      <label>Hospital</label>
      <select name="hospital_id" required>${options}</select>
    </div>
    <div class="field">
      <label>Name</label>
      <input name="name" type="text" value="${existing ? existing.name : ""}" required />
    </div>`;

  showModal(existing ? "Edit Department" : "Add Department", formHtml, async (values) => {
    const path = existing ? `/api/admin/departments/${existing.id}` : "/api/admin/departments";
    await adminFetch(path, {
      method: existing ? "PUT" : "POST",
      body: JSON.stringify({ hospital_id: Number(values.hospital_id), name: values.name }),
    });
  });
}

// ── Attribute Types + Values (CxABE-PRE context "parameters") ───────────────

async function renderAttributeTypesView() {
  const types = await adminFetch("/api/admin/attribute-types");
  const content = document.getElementById("content");

  if (types.length === 0) {
    content.innerHTML = '<p class="empty-state">No attribute types yet — e.g. add "Network" or "Horaire".</p>';
  } else {
    const table = el("table", {}, [
      el("thead", {}, [el("tr", {}, [el("th", { text: "Code" }), el("th", { text: "Label" }), el("th", { text: "Status" }), el("th", { text: "" })])]),
    ]);
    const tbody = el("tbody");
    types.forEach((t) => {
      tbody.appendChild(
        el("tr", {}, [
          el("td", { text: t.code }),
          el("td", { text: t.label }),
          el("td", {}, [el("span", { class: t.is_active ? "pill pill-active" : "pill pill-inactive", text: t.is_active ? "Active" : "Inactive" })]),
          el("td", { class: "row-actions" }, [
            el("button", { class: "btn btn-secondary", text: "Values", onClick: () => renderAttributeValuesView(t) }),
            el("button", { class: "btn btn-secondary", text: "Edit", onClick: () => openAttributeTypeForm(t) }),
            el("button", {
              class: "btn btn-danger",
              text: "Deactivate",
              onClick: async () => {
                if (!confirm(`Deactivate "${t.label}"?`)) return;
                await adminFetch(`/api/admin/attribute-types/${t.id}`, { method: "DELETE" });
                loadView("attribute-types");
              },
            }),
            el("button", {
              class: "btn btn-danger",
              text: "Delete",
              onClick: async () => {
                if (!confirm(`Permanently delete "${t.label}" and all its values? This cannot be undone.`)) return;
                try {
                  await adminFetch(`/api/admin/attribute-types/${t.id}/permanent`, { method: "DELETE" });
                  loadView("attribute-types");
                } catch (e) {
                  alert(e.message);
                }
              },
            }),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    content.innerHTML = "";
    content.appendChild(table);
  }

  showAddButton("+ Add Attribute Type", () => openAttributeTypeForm(null));
}

function openAttributeTypeForm(existing) {
  const formHtml = `
    <div class="field">
      <label>Code (used as the attribute key, e.g. "Network")</label>
      <input name="code" type="text" value="${existing ? existing.code : ""}" required />
    </div>
    <div class="field">
      <label>Label (admin-facing name)</label>
      <input name="label" type="text" value="${existing ? existing.label : ""}" required />
    </div>`;

  showModal(existing ? "Edit Attribute Type" : "Add Attribute Type", formHtml, async (values) => {
    const path = existing ? `/api/admin/attribute-types/${existing.id}` : "/api/admin/attribute-types";
    await adminFetch(path, { method: existing ? "PUT" : "POST", body: JSON.stringify(values) });
  });
}

async function renderAttributeValuesView(type) {
  document.getElementById("viewTitle").textContent = `${type.label} — values`;
  const values = await adminFetch(`/api/admin/attribute-types/${type.id}/values`);
  const content = document.getElementById("content");

  const backBtn = el("button", { class: "btn btn-secondary", text: "← Back to Attribute Types", onClick: () => loadView("attribute-types") });
  content.innerHTML = "";
  content.appendChild(backBtn);
  content.appendChild(el("div", { style: "height: 14px" }));

  if (values.length === 0) {
    content.appendChild(el("p", { class: "empty-state", text: "No values yet for this attribute type." }));
  } else {
    const table = el("table", {}, [el("thead", {}, [el("tr", {}, [el("th", { text: "Value" }), el("th", { text: "Status" }), el("th", { text: "" })])])]);
    const tbody = el("tbody");
    values.forEach((v) => {
      tbody.appendChild(
        el("tr", {}, [
          el("td", { text: v.value }),
          el("td", {}, [el("span", { class: v.is_active ? "pill pill-active" : "pill pill-inactive", text: v.is_active ? "Active" : "Inactive" })]),
          el("td", { class: "row-actions" }, [
            el("button", {
              class: "btn btn-danger",
              text: "Deactivate",
              onClick: async () => {
                if (!confirm(`Deactivate "${v.value}"?`)) return;
                await adminFetch(`/api/admin/attribute-values/${v.id}`, { method: "DELETE" });
                renderAttributeValuesView(type);
              },
            }),
            el("button", {
              class: "btn btn-danger",
              text: "Delete",
              onClick: async () => {
                if (!confirm(`Permanently delete "${v.value}"? This cannot be undone.`)) return;
                await adminFetch(`/api/admin/attribute-values/${v.id}/permanent`, { method: "DELETE" });
                renderAttributeValuesView(type);
              },
            }),
          ]),
        ])
      );
    });
    table.appendChild(tbody);
    content.appendChild(table);
  }

  showAddButton("+ Add Value", () => {
    showModal(`Add value to ${type.label}`, '<div class="field"><label>Value</label><input name="value" type="text" required /></div>', async (values2) => {
      await adminFetch(`/api/admin/attribute-types/${type.id}/values`, { method: "POST", body: JSON.stringify(values2) });
      renderAttributeValuesView(type);
    });
  });
}

// ── Providers ─────────────────────────────────────────────────────────────

async function renderProvidersView() {
  const rows = await adminFetch("/api/admin/providers");
  const content = document.getElementById("content");
  hideAddButton();

  if (rows.length === 0) {
    content.innerHTML = '<p class="empty-state">No providers yet.</p>';
    return;
  }

  const table = el("table", {}, [
    el("thead", {}, [
      el("tr", {}, [
        el("th", { text: "Name" }), el("th", { text: "Role" }), el("th", { text: "Hospital" }),
        el("th", { text: "Department" }), el("th", { text: "Speciality" }), el("th", { text: "Job Title" }),
        el("th", { text: "City" }), el("th", { text: "Status" }), el("th", { text: "" }),
      ]),
    ]),
  ]);
  const tbody = el("tbody");
  rows.forEach((p) => {
    tbody.appendChild(
      el("tr", {}, [
        el("td", { text: p.full_name }),
        el("td", { text: p.role }),
        el("td", { text: p.hospital || "—" }),
        el("td", { text: p.department || "—" }),
        el("td", { text: p.speciality || "—" }),
        el("td", { text: p.job_title || "—" }),
        el("td", { text: p.city }),
        el("td", {}, [el("span", { class: p.blacklisted ? "pill pill-inactive" : "pill pill-active", text: p.blacklisted ? "Blacklisted" : "Active" })]),
        el("td", { class: "row-actions" }, [
          el("button", {
            class: "btn btn-danger",
            text: p.blacklisted ? "Blacklisted" : "Blacklist",
            ...(p.blacklisted ? { disabled: "disabled" } : {}),
            onClick: async () => {
              if (!confirm(`Blacklist ${p.full_name}? They will no longer be able to log in.`)) return;
              await adminFetch(`/api/admin/providers/${p.provider_id}`, { method: "DELETE" });
              loadView("providers");
            },
          }),
          el("button", {
            class: "btn btn-danger",
            text: "Delete",
            onClick: async () => {
              if (!confirm(`Permanently delete ${p.full_name}'s account? This cannot be undone.`)) return;
              try {
                await adminFetch(`/api/admin/providers/${p.provider_id}/permanent`, { method: "DELETE" });
                loadView("providers");
              } catch (e) {
                alert(e.message);
              }
            },
          }),
        ]),
      ])
    );
  });
  table.appendChild(tbody);
  content.innerHTML = "";
  content.appendChild(table);
}

// ── Patients ──────────────────────────────────────────────────────────────

async function renderPatientsView() {
  const rows = await adminFetch("/api/admin/patients");
  const content = document.getElementById("content");
  hideAddButton();

  if (rows.length === 0) {
    content.innerHTML = '<p class="empty-state">No patients yet.</p>';
    return;
  }

  const table = el("table", {}, [
    el("thead", {}, [el("tr", {}, [el("th", { text: "Name" }), el("th", { text: "Phone" }), el("th", { text: "Registered" }), el("th", { text: "Status" }), el("th", { text: "" })])]),
  ]);
  const tbody = el("tbody");
  rows.forEach((p) => {
    tbody.appendChild(
      el("tr", {}, [
        el("td", { text: p.display_name }),
        el("td", { text: p.phone_number || "—" }),
        el("td", { text: p.created_at ? p.created_at.split("T")[0] : "—" }),
        el("td", {}, [el("span", { class: p.blacklisted ? "pill pill-inactive" : "pill pill-active", text: p.blacklisted ? "Blacklisted" : "Active" })]),
        el("td", { class: "row-actions" }, [
          el("button", {
            class: "btn btn-danger",
            text: p.blacklisted ? "Blacklisted" : "Blacklist",
            ...(p.blacklisted ? { disabled: "disabled" } : {}),
            onClick: async () => {
              if (!confirm(`Blacklist ${p.display_name}? They will no longer be able to log in.`)) return;
              await adminFetch(`/api/admin/patients/${p.id}`, { method: "DELETE" });
              loadView("patients");
            },
          }),
          el("button", {
            class: "btn btn-danger",
            text: "Delete",
            onClick: async () => {
              if (!confirm(`Permanently delete ${p.display_name}'s account? This cannot be undone.`)) return;
              try {
                await adminFetch(`/api/admin/patients/${p.id}/permanent`, { method: "DELETE" });
                loadView("patients");
              } catch (e) {
                alert(e.message);
              }
            },
          }),
        ]),
      ])
    );
  });
  table.appendChild(tbody);
  content.innerHTML = "";
  content.appendChild(table);
}

// ── Change Password ──────────────────────────────────────────────────────

function renderChangePasswordView() {
  hideAddButton();
  const content = document.getElementById("content");
  content.innerHTML = "";

  const form = el("form", { style: "max-width: 360px;" });
  form.innerHTML = `
    <div class="field">
      <label>Current password</label>
      <input name="current_password" type="password" required autocomplete="current-password" />
    </div>
    <div class="field">
      <label>New password</label>
      <input name="new_password" type="password" required minlength="4" autocomplete="new-password" />
    </div>
    <button type="submit" class="btn btn-primary">Change Password</button>
    <p class="error-text" id="changePasswordMessage"></p>
  `;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(form);
    const messageEl = document.getElementById("changePasswordMessage");
    messageEl.textContent = "";
    messageEl.style.color = "";
    try {
      await adminFetch("/api/admin/change-password", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(formData.entries())),
      });
      messageEl.style.color = "var(--teal)";
      messageEl.textContent = "Password changed successfully.";
      form.reset();
    } catch (err) {
      messageEl.textContent = err.message;
    }
  });
  content.appendChild(form);
}

// ── Navigation ────────────────────────────────────────────────────────────

let currentView = "hospitals";

const VIEW_TITLES = {
  hospitals: "Hospitals",
  departments: "Departments",
  specialities: "Specialities",
  "job-titles": "Job Titles",
  "attribute-types": "Attribute Types",
  providers: "Providers",
  patients: "Patients",
  "change-password": "Change Password",
};

async function loadView(view) {
  currentView = view;
  document.getElementById("viewTitle").textContent = VIEW_TITLES[view] || "";
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  hideAddButton();
  document.getElementById("content").innerHTML = "";

  try {
    if (view in LOOKUP_CONFIGS) await renderLookupView(view);
    else if (view === "departments") await renderDepartmentsView();
    else if (view === "attribute-types") await renderAttributeTypesView();
    else if (view === "providers") await renderProvidersView();
    else if (view === "patients") await renderPatientsView();
    else if (view === "change-password") renderChangePasswordView();
  } catch (e) {
    document.getElementById("content").innerHTML = `<p class="empty-state">${e.message}</p>`;
  }
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    if (item.dataset.view === "logout") {
      localStorage.removeItem("admin_token");
      window.location.href = "login.html";
      return;
    }
    loadView(item.dataset.view);
  });
});

loadView("hospitals");
