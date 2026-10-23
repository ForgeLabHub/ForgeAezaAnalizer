"use strict";

// ---------------------------------------------------------------- helpers
const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
};

const api = async (path, options) => {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
};

const eur = (v) => (v == null ? "—" : `€${v}`);
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));

const banner = (msg, kind = "error") => {
  const b = $("#banner");
  b.textContent = msg;
  b.className = `banner ${kind}`;
  if (kind === "ok") setTimeout(() => b.classList.add("hidden"), 4000);
};
const clearBanner = () => $("#banner").classList.add("hidden");

const pill = (level) => el("span", { class: `pill pill-${level}` }, level);

let HORIZON = 30;
let MODEL = { weights: {}, defaults: {}, factors: {} };

// ---------------------------------------------------------------- navigation
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    tab.classList.add("active");
    $(`#view-${tab.dataset.view}`).classList.add("active");
    if (tab.dataset.view === "data") loadDataTab();
    if (tab.dataset.view === "model") loadModelTab();
  });
});

// ---------------------------------------------------------------- dashboard
const bars = (container, entries, levelClass) => {
  container.replaceChildren();
  const max = Math.max(1, ...entries.map(([, v]) => v));
  for (const [label, value] of entries) {
    const cls = levelClass ? levelClass(label) : "fill-low";
    container.append(
      el("div", { class: "bar-row" },
        el("span", { class: "bar-label" }, label),
        el("div", { class: "bar-track" },
          el("div", { class: `bar-fill ${cls}`, style: `width:${(value / max) * 100}%` })),
        el("span", { class: "bar-value" }, num(value)))
    );
  }
};

const levelClass = (label) => `fill-${label}`;

async function loadDashboard() {
  const d = await api(`/api/dashboard?horizon_days=${HORIZON}`);
  const c = d.counts;

  $("#summary-cards").replaceChildren(
    card("Accounts", num(c.accounts), "imported customers"),
    card("Services", num(c.services), "all statuses"),
    card("Transactions", num(c.transactions), "order + prolong"),
    card("Revenue at risk", eur(d.revenue_at_risk_eur),
         `of ${eur(d.eligible_renewal_eur)} eligible (${HORIZON}d)`),
    card("High-risk customers", num(d.high_risk_customers), "score ≥ 65"),
  );

  const order = ["low", "medium", "high", "churned", "unknown"];
  bars($("#risk-bars"),
    order.map((k) => [k, d.risk_levels[k] || 0]).filter(([, v]) => v > 0),
    levelClass);

  bars($("#status-bars"), Object.entries(d.service_status).sort(), () => "fill-unknown");

  const top = await api(`/api/customers?horizon_days=${HORIZON}&sort=risk_score&order=desc`);
  const body = $("#top-customers tbody");
  body.replaceChildren();
  for (const cust of top.items.slice(0, 8)) {
    body.append(rowFor(cust));
  }
}

function card(label, value, sub) {
  return el("div", { class: "card" },
    el("div", { class: "label" }, label),
    el("div", { class: "value" }, value),
    sub ? el("div", { class: "sub" }, sub) : null);
}

function rowFor(cust) {
  return el("tr", { onclick: () => openCustomer(cust.account_id) },
    el("td", {}, `#${cust.account_id}`),
    el("td", {}, cust.email),
    el("td", { class: "score-cell" }, cust.risk_score.toFixed(1)),
    el("td", {}, pill(cust.risk_level)),
    el("td", { class: "mono" }, eur(cust.revenue_at_risk_eur)),
    el("td", { class: "mono" }, eur(cust.eligible_renewal_eur)));
}

// ---------------------------------------------------------------- customers
async function loadCustomers() {
  const params = new URLSearchParams({
    horizon_days: HORIZON,
    sort: $("#sort").value,
    order: $("#order").value,
  });
  const search = $("#search").value.trim();
  const level = $("#filter-level").value;
  if (search) params.set("search", search);
  if (level) params.set("level", level);

  const data = await api(`/api/customers?${params}`);
  $("#customer-count").textContent = `${data.total} customer(s)`;
  const body = $("#customers-table tbody");
  body.replaceChildren();
  for (const cust of data.items) {
    body.append(el("tr", { onclick: () => openCustomer(cust.account_id) },
      el("td", {}, `#${cust.account_id}`),
      el("td", {}, cust.email),
      el("td", { class: "score-cell" }, cust.risk_score.toFixed(1)),
      el("td", {}, pill(cust.risk_level)),
      el("td", { class: "mono" }, `${cust.live_service_count} / ${cust.service_count}`),
      el("td", { class: "mono" }, eur(cust.balance_eur)),
      el("td", { class: "mono" }, eur(cust.revenue_at_risk_eur))));
  }
}

["#search", "#filter-level", "#sort", "#order"].forEach((sel) =>
  $(sel).addEventListener("input", loadCustomers));

// ---------------------------------------------------------------- services
async function loadServices() {
  const params = new URLSearchParams({ horizon_days: HORIZON });
  const status = $("#filter-status").value;
  if (status) params.set("status", status);
  const data = await api(`/api/services?${params}`);
  $("#service-count").textContent = `${data.total} service(s)`;
  const body = $("#services-table tbody");
  body.replaceChildren();
  for (const s of data.items) {
    body.append(el("tr", {},
      el("td", {}, s.service_name),
      el("td", {}, el("span", { class: `pill pill-${s.status === "deleted" ? "churned" : "unknown"}` }, s.status)),
      el("td", {}, s.paymentTerm),
      el("td", {}, s.autoProlong ? "on" : "off"),
      el("td", { class: "mono" }, eur(s.price_eur)),
      el("td", { class: "mono" }, s.expires_at.slice(0, 10)),
      el("td", { class: "score-cell" }, s.level === "unknown" ? "—" : s.score.toFixed(1))));
  }
}

$("#filter-status").addEventListener("input", loadServices);

// ---------------------------------------------------------------- model
async function loadModelTab() {
  MODEL = await api("/api/weights");
  const form = $("#weight-form");
  form.replaceChildren();
  for (const [key, value] of Object.entries(MODEL.weights)) {
    form.append(el("div", { class: "weight-row" },
      el("span", { class: "factor-name" }, key),
      el("input", { type: "number", step: "0.1", min: "0", value, "data-key": key }),
      el("span", { class: "factor-desc" }, MODEL.factors[key] || "")));
  }
  const bands = await api(`/api/dashboard?horizon_days=${HORIZON}`);
  $("#risk-bands").replaceChildren(...bands.risk_bands.map((b) =>
    el("div", { class: "band" },
      el("div", { class: "band-name" }, b.level),
      el("div", { class: "band-range" }, `${b.min}–${b.max}`))));
}

$("#save-weights").addEventListener("click", async () => {
  const weights = {};
  document.querySelectorAll("#weight-form input").forEach((i) => {
    weights[i.dataset.key] = Number(i.value);
  });
  try {
    await api("/api/weights", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ weights }),
    });
    banner("Weights saved — analytics recalculated.", "ok");
    await loadDashboard();
  } catch (e) { banner(`Could not save weights: ${e.message}`); }
});

$("#reset-weights").addEventListener("click", async () => {
  await api("/api/weights/reset", { method: "POST" });
  banner("Weights reset to defaults.", "ok");
  await loadModelTab();
  await loadDashboard();
});

// ---------------------------------------------------------------- data tab
async function loadDataTab() {
  const meta = await api("/api/meta");
  $("#meta-json").textContent = JSON.stringify(meta, null, 2);
  const audit = await api("/api/audit");
  $("#audit-json").textContent = JSON.stringify(audit, null, 2);
}

$("#run-import").addEventListener("click", async () => {
  const btn = $("#run-import");
  btn.disabled = true;
  btn.textContent = "Importing…";
  try {
    const res = await api("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ horizon_days: HORIZON }),
    });
    banner(
      `Imported ${res.accounts} accounts, ${res.services} services, ` +
      `${res.transactions} transactions (${res.rejected.length} rejected).`, "ok");
    await loadDataTab();
    await loadDashboard();
    await refreshMetaLine();
  } catch (e) {
    banner(`Import failed: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-import organiser dataset";
  }
});

// ---------------------------------------------------------------- drawer
async function openCustomer(accountId) {
  const c = await api(`/api/customers/${accountId}?horizon_days=${HORIZON}`);
  const body = $("#drawer-body");
  body.replaceChildren(
    el("h2", {},
      el("span", {}, c.email),
      " ",
      el("span", { class: `pill pill-${c.risk_level}` }, c.risk_level)),
    el("div", { class: "kv" },
      el("dt", {}, "Account"), el("dd", {}, `#${c.account_id}`),
      el("dt", {}, "Risk score"), el("dd", { class: "score-cell" }, `${c.risk_score.toFixed(1)} / 100`),
      el("dt", {}, "Confidence"), el("dd", {}, `${(c.confidence * 100).toFixed(0)}%`),
      el("dt", {}, "Balance"), el("dd", { class: "mono" }, eur(c.balance_eur)),
      el("dt", {}, "Withdrawable"), el("dd", { class: "mono" }, eur(c.withdraw_balance_eur)),
      el("dt", {}, "Bonus"), el("dd", { class: "mono" }, `${eur(c.bonus_balance_eur)} (${c.bonus_state})`),
      el("dt", {}, "Total replenished"), el("dd", { class: "mono" }, eur(c.total_replenished_eur)),
      el("dt", {}, "Eligible renewals"), el("dd", { class: "mono" }, eur(c.eligible_renewal_eur)),
      el("dt", {}, "Revenue at risk"), el("dd", { class: "mono" }, eur(c.revenue_at_risk_eur)),
    ),
    el("h3", { class: "section" }, "Why this risk"),
    el("ul", { class: "reasons" }, ...c.reasons.map((r) => el("li", {}, r))),
    el("h3", { class: "section" }, `Services (${c.services.length})`),
    ...c.services.map(serviceCard),
  );
  $("#drawer").classList.remove("hidden");
}

function serviceCard(s) {
  return el("div", { class: "service-card" },
    el("div", { class: "service-head" },
      el("h3", {}, s.service_name),
      el("span", { class: `pill pill-${s.status === "deleted" ? "churned" : "unknown"}` }, s.status),
      el("span", { class: "spacer" }),
      el("span", { class: "score-cell" }, s.level === "unknown" ? "unknown" : `${s.score.toFixed(1)} / 100`)),
    el("div", { class: "kv" },
      el("dt", {}, "Price"), el("dd", { class: "mono" }, eur(s.price_eur)),
      el("dt", {}, "Expires"), el("dd", {}, s.expires_at.slice(0, 19).replace("T", " ") + " UTC")),
    el("div", { class: "factor-list" },
      ...s.factors.map((f) =>
        el("div", { class: `factor${f.unknown ? " unknown" : ""}` },
          el("span", {}, f.title),
          el("span", { class: "mono" }, f.unknown ? "unknown" : f.value.toFixed(2)),
          el("span", { class: "mono" }, `w=${f.weight}`),
          el("span", { class: "f-detail" }, f.detail)))));
}

$("#drawer-close").addEventListener("click", () => $("#drawer").classList.add("hidden"));
$("#drawer").addEventListener("click", (e) => {
  if (e.target.id === "drawer") $("#drawer").classList.add("hidden");
});

// ---------------------------------------------------------------- meta line
async function refreshMetaLine() {
  const meta = await api("/api/meta");
  const li = meta.last_import;
  $("#meta-line").textContent = li
    ? `snapshot ${meta.reference_at.slice(0, 16).replace("T", " ")} UTC · ` +
      `source ${meta.source_sha256.slice(0, 12)}… · ` +
      `${li.accounts}/${li.services}/${li.transactions} rows`
    : "no data imported yet";
}

// ---------------------------------------------------------------- init
$("#refresh-dashboard").addEventListener("click", async () => {
  HORIZON = Math.max(1, Math.min(365, Number($("#horizon").value) || 30));
  await loadDashboard();
});

(async function init() {
  try {
    await refreshMetaLine();
    await loadDashboard();
    await loadCustomers();
    await loadServices();
  } catch (e) {
    banner(`Failed to load: ${e.message}. Import the dataset from the Data tab.`);
  }
})();
