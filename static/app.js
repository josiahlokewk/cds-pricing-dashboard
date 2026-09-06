const PALETTE = {
  bg: "#0b0f17", panel: "#131a26", grid: "#233046",
  text: "#e6edf7", muted: "#8ea0bd",
  teal: "#4dd6a8", blue: "#7aa2ff", coral: "#ff6b6b", gold: "#f6c453", lavender: "#c792ea",
};

const PLOTLY_CONFIG = { responsive: true, displayModeBar: false };

// Custom-built calendar picker for the trade date (replacing the browser's
// native type="date" popup, which is always light-themed regardless of page
// theme). Deliberately not a library: Pikaday was tried first, but it always
// renders the month/year pickers as native <select> elements, whose OPEN
// dropdown list is drawn by the OS/browser and can't be reliably re-themed
// with CSS alone -- confirmed by checking Pikaday's own source, not guessed.
// Everything below is plain divs/buttons, so there's no native control left
// to fight.
const pad2 = (n) => String(n).padStart(2, "0");
const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];

const dateInput = document.getElementById("std-trade-date");
const datePopup = document.getElementById("date-picker-popup");
let dpViewYear, dpViewMonth, dpSelected;

function parseInputDate(s) {
  const [y, m, d] = s.split("-").map((v) => parseInt(v, 10));
  return new Date(y, m - 1, d);
}
function formatDate(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

let dpView = "days"; // "days" | "months" | "years" -- click the month/year title to drill into the other two
let dpYearsPageStart; // first year shown in the "years" grid view

function dpOn(id, fn) {
  // Every internal click must stop propagation -- without this, the click
  // bubbles up to the document-level "close if clicked outside" listener
  // below, which (since renderDatePopup() just replaced the clicked button
  // with a new element) sees a target no longer inside the popup and
  // immediately closes it again -- same click, opens then instantly closes.
  // That was the actual bug: the buttons worked, but got undone in the same
  // event before anything became visible.
  document.getElementById(id).addEventListener("click", (e) => { e.stopPropagation(); fn(); });
}

function renderDatePopup() {
  if (dpView === "months") return renderMonthView();
  if (dpView === "years") return renderYearView();

  const today = new Date();
  const firstOfMonth = new Date(dpViewYear, dpViewMonth, 1);
  const daysInMonth = new Date(dpViewYear, dpViewMonth + 1, 0).getDate();
  const leadingBlanks = firstOfMonth.getDay(); // 0=Sun

  let dayCells = "";
  for (let i = 0; i < leadingBlanks; i++) dayCells += `<button class="dp-day dp-empty" disabled></button>`;
  for (let d = 1; d <= daysInMonth; d++) {
    const isToday = today.getFullYear() === dpViewYear && today.getMonth() === dpViewMonth && today.getDate() === d;
    const isSelected = dpSelected && dpSelected.getFullYear() === dpViewYear &&
      dpSelected.getMonth() === dpViewMonth && dpSelected.getDate() === d;
    const cls = ["dp-day", isToday ? "dp-today" : "", isSelected ? "dp-selected" : ""].join(" ").trim();
    dayCells += `<button type="button" class="${cls}" data-day="${d}">${d}</button>`;
  }

  datePopup.innerHTML = `
    <div class="dp-header">
      <button type="button" id="dp-prev-year" title="Previous year">&laquo;</button>
      <button type="button" id="dp-prev-month" title="Previous month">&lsaquo;</button>
      <span class="dp-title">
        <button type="button" class="dp-title-btn" id="dp-pick-month">${MONTH_NAMES[dpViewMonth]}</button>
        <button type="button" class="dp-title-btn" id="dp-pick-year">${dpViewYear}</button>
      </span>
      <button type="button" id="dp-next-month" title="Next month">&rsaquo;</button>
      <button type="button" id="dp-next-year" title="Next year">&raquo;</button>
    </div>
    <div class="dp-grid">
      ${["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => `<div class="dp-dow">${d}</div>`).join("")}
      ${dayCells}
    </div>`;

  dpOn("dp-prev-year", () => { dpViewYear--; renderDatePopup(); });
  dpOn("dp-next-year", () => { dpViewYear++; renderDatePopup(); });
  dpOn("dp-prev-month", () => { dpViewMonth--; if (dpViewMonth < 0) { dpViewMonth = 11; dpViewYear--; } renderDatePopup(); });
  dpOn("dp-next-month", () => { dpViewMonth++; if (dpViewMonth > 11) { dpViewMonth = 0; dpViewYear++; } renderDatePopup(); });
  dpOn("dp-pick-month", () => { dpView = "months"; renderDatePopup(); });
  dpOn("dp-pick-year", () => { dpYearsPageStart = dpViewYear - 5; dpView = "years"; renderDatePopup(); });
  datePopup.querySelectorAll("button[data-day]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      dpSelected = new Date(dpViewYear, dpViewMonth, parseInt(btn.dataset.day, 10));
      dateInput.value = formatDate(dpSelected);
      datePopup.classList.remove("open");
    });
  });
}

function renderMonthView() {
  datePopup.innerHTML = `
    <div class="dp-header">
      <span class="dp-title">${dpViewYear}</span>
    </div>
    <div class="dp-grid dp-grid-3col">
      ${MONTH_NAMES.map((name, i) => `<button type="button" class="dp-cell${i === dpViewMonth ? " dp-selected" : ""}"
        data-month="${i}">${name.slice(0, 3)}</button>`).join("")}
    </div>`;
  datePopup.querySelectorAll("button[data-month]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      dpViewMonth = parseInt(btn.dataset.month, 10);
      dpView = "days";
      renderDatePopup();
    });
  });
}

function renderYearView() {
  const years = Array.from({ length: 12 }, (_, i) => dpYearsPageStart + i);
  datePopup.innerHTML = `
    <div class="dp-header">
      <button type="button" id="dp-years-prev" title="Earlier years">&laquo;</button>
      <span class="dp-title">${years[0]} &ndash; ${years[years.length - 1]}</span>
      <button type="button" id="dp-years-next" title="Later years">&raquo;</button>
    </div>
    <div class="dp-grid dp-grid-3col">
      ${years.map((y) => `<button type="button" class="dp-cell${y === dpViewYear ? " dp-selected" : ""}"
        data-year="${y}">${y}</button>`).join("")}
    </div>`;
  dpOn("dp-years-prev", () => { dpYearsPageStart -= 12; renderDatePopup(); });
  dpOn("dp-years-next", () => { dpYearsPageStart += 12; renderDatePopup(); });
  datePopup.querySelectorAll("button[data-year]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      dpViewYear = parseInt(btn.dataset.year, 10);
      dpView = "days";
      renderDatePopup();
    });
  });
}

dateInput.addEventListener("click", (e) => {
  e.stopPropagation();
  dpSelected = parseInputDate(dateInput.value);
  dpViewYear = dpSelected.getFullYear();
  dpViewMonth = dpSelected.getMonth();
  dpView = "days";
  renderDatePopup();
  datePopup.classList.add("open");
});
document.addEventListener("click", (e) => {
  if (!datePopup.contains(e.target) && e.target !== dateInput) datePopup.classList.remove("open");
});

function darkLayout(extra) {
  return Object.assign({
    paper_bgcolor: PALETTE.panel,
    plot_bgcolor: PALETTE.panel,
    font: { color: PALETTE.text, family: "Segoe UI, Inter, system-ui, sans-serif", size: 11 },
    margin: { l: 48, r: 16, t: 8, b: 36 },
    xaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid, title: "Years" , automargin: true },
    yaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid },
    showlegend: false,
  }, extra || {});
}

let state = {
  result: null,       // last /api/price response
  stepIndex: 0,        // which hazard node is "current" in the survival/hazard stepper
  playTimer: null,
  discountStepIndex: 0,  // which OIS node is "current" in the discount curve's own, separate stepper
  discountPlayTimer: null,
  scheduleData: null,   // last /api/price response, for the schedule table specifically
  schedulePage: 0,       // current page in the schedule table pagination
  playSpeedMs: 1000,      // ms per node, shared by both curves' auto-play
};

const SPEED_SLIDER_MIN = 200;
const SPEED_SLIDER_MAX = 2000;
document.getElementById("speed-slider").addEventListener("input", (e) => {
  // The slider's own raw value just runs left-to-right (200->2000) like any
  // normal slider, so the browser's native fill grows naturally from the
  // left -- inverted here into the actual ms-per-node figure, so the left
  // (low raw value) end means "slow" (high ms) and the right end means "fast"
  // (low ms), matching the Slow/Fast labels either side of the track.
  const raw = parseInt(e.target.value, 10);
  state.playSpeedMs = SPEED_SLIDER_MIN + SPEED_SLIDER_MAX - raw;
  document.getElementById("speed-label").textContent = `${state.playSpeedMs}ms / node`;
  // Restart whichever animation is currently running so the new speed takes
  // effect immediately, instead of only on the next time Play is pressed.
  if (state.playTimer) { stopPlay(); startPlay(); }
  if (state.discountPlayTimer) { stopDiscountPlay(); startDiscountPlay(); }
});

// ------------------------------------------------------------- math drawer -
function setMathDrawerOpen(open) {
  const toggle = document.getElementById("math-toggle");
  document.getElementById("math-drawer").classList.toggle("open", open);
  toggle.classList.toggle("open", open);
  toggle.innerHTML = open ? "&#10095;" : "&#10094;";
  toggle.title = open ? "Hide the math" : "Show the math";
  document.body.classList.toggle("math-open", open);
  // The layout shifting (margin-right) doesn't fire a resize event on its
  // own, same issue as the sidebar collapse -- nudge Plotly explicitly once
  // the 0.2s transition finishes.
  setTimeout(() => {
    ["spread-input-chart", "hazard-chart", "survival-chart", "discount-chart"].forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.data) Plotly.Plots.resize(el);
    });
  }, 220);
}

document.getElementById("math-toggle").addEventListener("click", () => {
  setMathDrawerOpen(!document.getElementById("math-drawer").classList.contains("open"));
});

// Full substituted arithmetic for this segment's O'Kane-Turnbull protection-leg
// value -- exact whenever this segment isn't itself split by an intervening
// OIS node (true for every default/placeholder dataset in this project, where
// the CDS and OIS curves share the same node years; flagged below otherwise).
function renderHazardMath(node) {
  const recovery = state.result.calibration_recovery;
  const dt = node.t - node.t_prev;
  const lam = node.h;
  const r = node.r;
  const Zprev = node.discount_factor_prev, Zcurr = node.discount_factor;
  const Qprev = node.Q_prev, Qcurr = node.Q;
  const ratio = lam / (lam + r);
  const termPrev = Zprev * Qprev;
  const termCurr = Zcurr * Qcurr;
  const diff = termPrev - termCurr;
  const segmentValue = ratio * diff;
  const protLegSegment = (1 - recovery) * segmentValue;
  const QcurrCheck = Qprev * Math.exp(-lam * dt);
  const lastIter = node.iterations[node.iterations.length - 1];

  document.getElementById("hazard-math-current").innerHTML = `
    <strong>${node.tenor}</strong> segment: t = ${node.t_prev.toFixed(3)}y &rarr; ${node.t.toFixed(3)}y
    (&Delta;t = ${dt.toFixed(3)})<br><br>
    Forward discount rate: r = ${r.toFixed(6)}<br>
    Z(${node.t_prev.toFixed(3)}) = ${Zprev.toFixed(6)}, Z(${node.t.toFixed(3)}) = ${Zcurr.toFixed(6)}<br>
    Calibrated hazard rate (S = ${node.spread_bp.toFixed(3)}bp, ${node.iterations.length} Newton-Raphson
    iterations, residual = ${lastIter.residual.toExponential(3)}): &lambda; = ${lam.toFixed(6)}<br>
    Q(${node.t_prev.toFixed(3)}) = ${Qprev.toFixed(6)} (already known)<br>
    Q(${node.t.toFixed(3)}) = Q(${node.t_prev.toFixed(3)}) &times; e<sup>&minus;&lambda;&Delta;t</sup>
    = ${Qprev.toFixed(6)} &times; e<sup>&minus;${lam.toFixed(6)}&times;${dt.toFixed(3)}</sup> = ${QcurrCheck.toFixed(6)}<br><br>
    <strong>O'Kane-Turnbull segment value:</strong><br>
    &lambda;/(&lambda;+r) &times; [Z(${node.t_prev.toFixed(3)})Q(${node.t_prev.toFixed(3)})
    &minus; Z(${node.t.toFixed(3)})Q(${node.t.toFixed(3)})]<br>
    = ${lam.toFixed(6)}/(${lam.toFixed(6)}+${r.toFixed(6)}) &times;
    [${Zprev.toFixed(6)}&times;${Qprev.toFixed(6)} &minus; ${Zcurr.toFixed(6)}&times;${Qcurr.toFixed(6)}]<br>
    = ${ratio.toFixed(6)} &times; [${termPrev.toFixed(6)} &minus; ${termCurr.toFixed(6)}]
    = ${ratio.toFixed(6)} &times; ${diff.toFixed(6)} = ${segmentValue.toFixed(8)}<br><br>
    Protection leg segment PV = (1&minus;R) &times; ${segmentValue.toFixed(8)}
    = (1&minus;${recovery}) &times; ${segmentValue.toFixed(8)} =
    <strong>${protLegSegment.toFixed(8)}</strong> (per unit notional)`;
}

// Full substituted arithmetic for the OIS par condition, matching
// bootstrap_ois_curve's own documented derivation exactly:
//   Z(T) = (1 - C*annuity_so_far) / (1 + C*delta), annuity_so_far over STRICTLY
//   earlier nodes only.
function renderDiscountMath(years, rates, discounts, idx) {
  const T = years[idx];
  const C = rates[idx];

  let terms = [];
  let annuitySoFar = 0;
  let prevT = 0;
  for (let i = 0; i < idx; i++) {
    const delta = years[i] - prevT;
    const term = delta * discounts[i];
    terms.push(`&delta;&times;Z(${years[i]}) = ${delta.toFixed(3)}&times;${discounts[i].toFixed(6)} = ${term.toFixed(6)}`);
    annuitySoFar += term;
    prevT = years[i];
  }
  const delta = T - prevT;
  const numerator = 1 - C * annuitySoFar;
  const denominator = 1 + C * delta;
  const ZT = numerator / denominator;

  const priorTermsHtml = terms.length
    ? `Annuity so far (strictly earlier nodes):<br>${terms.join("<br>")}<br>Sum = ${annuitySoFar.toFixed(6)}<br><br>`
    : `Annuity so far = 0 (this is the shortest node, no earlier terms)<br><br>`;

  document.getElementById("discount-math-current").innerHTML = `
    <strong>${T}Y</strong> node, quoted par rate C = ${(C * 100).toFixed(4)}%, &delta; (this node) = ${delta.toFixed(3)}<br><br>
    ${priorTermsHtml}
    Z(T) = (1 &minus; C&times;annuity) / (1 + C&times;&delta;)<br>
    = (1 &minus; ${C.toFixed(6)}&times;${annuitySoFar.toFixed(6)}) / (1 + ${C.toFixed(6)}&times;${delta.toFixed(3)})<br>
    = ${numerator.toFixed(6)} / ${denominator.toFixed(6)} = <strong>${ZT.toFixed(6)}</strong>`;
}

// ------------------------------------------------------------ sidebar ------
document.getElementById("sidebar-toggle").addEventListener("click", (e) => {
  const layout = document.querySelector(".layout");
  const collapsed = layout.classList.toggle("sidebar-collapsed");
  e.target.innerHTML = collapsed ? "&#10095;" : "&#10094;";
  e.target.title = collapsed ? "Expand panel" : "Collapse panel";
  // CSS grid-template-columns changing doesn't fire a window resize event, so
  // Plotly's responsive:true won't pick up the new container width on its own.
  setTimeout(() => {
    ["spread-input-chart", "hazard-chart", "survival-chart", "discount-chart"].forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.data) Plotly.Plots.resize(el);
    });
  }, 200); // after the 0.15s CSS transition finishes
});

// ------------------------------------------------------- market data panel -
const marketDataBody = document.getElementById("market-data-body");
const marketDataChevron = document.getElementById("market-data-chevron");

function setMarketDataExpanded(expanded) {
  marketDataBody.classList.toggle("collapsed", !expanded);
  marketDataChevron.classList.toggle("expanded", expanded);
}

document.getElementById("market-data-header").addEventListener("click", () => {
  setMarketDataExpanded(marketDataBody.classList.contains("collapsed"));
});

function showMarketDataTab(which) {
  document.querySelectorAll("#market-data-toggle button").forEach((b) =>
    b.classList.toggle("active", b.dataset.table === which));
  document.getElementById("ois-table-wrap").classList.toggle("hidden", which !== "ois");
  document.getElementById("cds-table-wrap").classList.toggle("hidden", which !== "cds");
}

document.querySelectorAll("#market-data-toggle button").forEach((btn) => {
  btn.addEventListener("click", () => showMarketDataTab(btn.dataset.table));
});

// Event delegation for row deletion -- covers rows added later (via
// "+ Add row"), not just the ones present at page load.
document.querySelector("#ois-table tbody").addEventListener("click", (e) => {
  if (e.target.classList.contains("row-delete")) e.target.closest("tr").remove();
});
document.querySelector("#cds-table tbody").addEventListener("click", (e) => {
  if (e.target.classList.contains("row-delete")) e.target.closest("tr").remove();
});

document.getElementById("ois-add-row").addEventListener("click", () => {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="number" step="0.01" class="ois-years" value=""></td>
                   <td><input type="number" step="0.0001" class="ois-rate" value=""></td>
                   <td><button type="button" class="row-delete">&times;</button></td>`;
  document.querySelector("#ois-table tbody").appendChild(tr);
});
document.getElementById("cds-add-row").addEventListener("click", () => {
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="text" class="cds-tenor" value=""></td>
                   <td><input type="number" step="0.5" class="cds-years" value=""></td>
                   <td><input type="number" step="0.01" class="cds-spread" value=""></td>
                   <td><button type="button" class="row-delete">&times;</button></td>`;
  document.querySelector("#cds-table tbody").appendChild(tr);
});

// ------------------------------------------------------------- gather ------
function gatherOisCurve() {
  const years = [...document.querySelectorAll(".ois-years")].map((el) => parseFloat(el.value));
  const rates = [...document.querySelectorAll(".ois-rate")].map((el) => parseFloat(el.value));
  return years.map((y, i) => ({ years: y, rate: rates[i] }));
}

function gatherCdsCurve() {
  const tenors = [...document.querySelectorAll(".cds-tenor")].map((el) => el.value);
  const years = [...document.querySelectorAll(".cds-years")].map((el) => parseFloat(el.value));
  const spreads = [...document.querySelectorAll(".cds-spread")].map((el) => parseFloat(el.value));
  return tenors.map((t, i) => ({ tenor: t, years: years[i], spread_bp: spreads[i] }));
}

function gatherPayload() {
  const calibrationRecovery = parseFloat(document.getElementById("calibration-recovery").value);
  return {
    contract_type: "standard",
    ois_curve: gatherOisCurve(),
    cds_curve: gatherCdsCurve(),
    calibration_recovery: calibrationRecovery,
    trade_date: document.getElementById("std-trade-date").value,
    tenor_years: parseFloat(document.getElementById("std-tenor-years").value),
    coupon_bp: parseFloat(document.getElementById("std-coupon-bp").value),
    recovery: parseFloat(document.getElementById("std-recovery").value),
    notional: parseFloat(document.getElementById("std-notional").value),
  };
}

// -------------------------------------------------------------- pricing ----
document.getElementById("price-btn").addEventListener("click", async () => {
  const btn = document.getElementById("price-btn");
  btn.disabled = true;
  btn.textContent = "Pricing...";
  try {
    const resp = await fetch("/api/price", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(gatherPayload()),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Pricing failed.");
    state.result = data;
    state.stepIndex = 0;  // reset to the first node so each new price starts the node-by-node build fresh
    state.discountStepIndex = 0;
    renderKpis(data);
    renderDiscountChart(data);
    renderStepCharts();
    renderSchedule(data);
    stopPlay();          // in case a previous run's auto-play is still ticking
    stopDiscountPlay();
    setMathDrawerOpen(true);  // so the math is actually visible while the curves build, not hidden
    startPlay();         // auto-build both curves node-by-node right after pricing
    startDiscountPlay();
  } catch (err) {
    alert(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Price";
  }
});

// -------------------------------------------------------------- KPIs -------
function fmtMoney(x) { return "$" + x.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }

function renderPriceTooltip(data) {
  const notional = parseFloat(document.getElementById("std-notional").value);
  const coupon = data.coupon_bp / 10000;
  const rpv01 = coupon > 0 ? data.mtm.premium_leg / (coupon * notional) : 0;
  const mtmClass = data.mtm.full_mtm >= 0 ? "positive" : "negative";

  return `
    <div class="row"><span class="muted">Protection leg PV</span><span>${fmtMoney(data.mtm.protection_leg)}</span></div>
    <div class="row"><span class="muted">&minus; Premium leg PV</span><span>${fmtMoney(data.mtm.premium_leg)}</span></div>
    <div class="row muted" style="font-size:11px;">(coupon ${data.coupon_bp.toFixed(1)}bp &times; RPV01 ${rpv01.toFixed(6)} &times; notional)</div>
    <hr>
    <div class="row"><span>Full MTM (trade value)</span><span class="result ${mtmClass}">${fmtMoney(data.mtm.full_mtm)}</span></div>
    <hr>
    <div class="row"><span class="muted">Par spread = Protection/RPV01</span><span>${data.par_spread_bp.toFixed(2)} bp</span></div>
    <div class="row"><span class="muted">Points upfront = MTM / Notional</span><span>${data.points_upfront.toFixed(4)}%</span></div>
    <div class="row"><span class="muted">Cash settlement (T+3)</span><span>${fmtMoney(data.cash_settlement_amount)}</span></div>`;
}

function renderAccruedTooltip(data) {
  return `
    <div class="row"><span class="muted">Accrual start (last IMM date)</span><span>${data.accrued_start_date}</span></div>
    <div class="row"><span class="muted">Accrual end (trade date)</span><span>${data.accrued_end_date}</span></div>
    <div class="row"><span class="muted">Days (Act/360)</span><span>${data.accrued_days}</span></div>
    <hr>
    <div class="row muted" style="font-size:11px;">coupon ${data.coupon_bp.toFixed(1)}bp &times; ${data.accrued_days}/360 &times; notional</div>
    <div class="row"><span>Accrued interest</span><span class="result">${fmtMoney(data.mtm.accrued_interest)}</span></div>`;
}

function renderKpis(data) {
  const cards = [];
  const mtmClass = data.mtm.full_mtm >= 0 ? "positive" : "negative";
  cards.push(["Trade MTM", fmtMoney(data.mtm.full_mtm), mtmClass, renderPriceTooltip(data)]);
  cards.push(["Par / Breakeven Spread", data.par_spread_bp.toFixed(2) + " bp", ""]);
  cards.push(["Points Upfront", data.points_upfront.toFixed(4) + " %", data.points_upfront >= 0 ? "positive" : "negative"]);
  // Bloomberg/Big-Bang bond-price convention: Price = 100 - Points Upfront.
  // Pure re-expression of points_upfront, not an independent calculation --
  // lets our output be compared field-for-field against a Bloomberg CDSW screen.
  cards.push(["Price", (100 - data.points_upfront).toFixed(4), ""]);
  cards.push(["Cash Settlement", fmtMoney(data.cash_settlement_amount), ""]);
  cards.push(["Protection Leg PV", fmtMoney(data.mtm.protection_leg), ""]);
  cards.push(["Premium Leg PV", fmtMoney(data.mtm.premium_leg), ""]);
  cards.push(["Full MTM", fmtMoney(data.mtm.full_mtm), mtmClass]);
  cards.push(["Accrued Interest", fmtMoney(data.mtm.accrued_interest), "",
    data.accrued_days !== undefined ? renderAccruedTooltip(data) : null]);
  cards.push(["Clean MTM", fmtMoney(data.mtm.clean_mtm), ""]);

  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = "";
  cards.forEach(([label, value, cls, tooltip]) => {
    const div = document.createElement("div");
    div.className = tooltip ? "kpi-card price-card" : "kpi-card";
    const labelHtml = tooltip ? `${label} <span class="hint-icon">?</span>` : label;
    div.innerHTML = `<div class="label">${labelHtml}</div><div class="value ${cls}">${value}</div>` +
      (tooltip ? `<div class="kpi-tooltip">${tooltip}</div>` : "");
    grid.appendChild(div);
  });
}

// ---------------------------------------------------------- discount chart -
// The OIS bootstrap is genuinely sequential too -- each new node's discount
// factor depends on every shorter one already being solved, same order-
// dependence as the hazard curve -- it just doesn't need Newton-Raphson
// *within* a single node (no iterations table to show), because Z appears
// linearly in the swap's par condition instead of inside an exponential. So
// this gets its own node-by-node reveal, on its own stepper (its node tenors
// are a different list from the CDS/hazard curve's, calibrated off different
// instruments), just without a convergence table.
function renderDiscountChart(data) {
  const years = data.curve_fig.ois_node_years;
  const discounts = data.curve_fig.ois_node_discounts;
  const rates = data.curve_fig.ois_node_rates;
  const idx = state.discountStepIndex;
  const cutoffT = years[idx];
  renderDiscountMath(years, rates, discounts, idx);

  const fineT = data.curve_fig.t.filter((t) => t <= cutoffT + 1e-9);
  const fineZ = data.curve_fig.discount.slice(0, fineT.length);
  fineT.push(cutoffT);
  fineZ.push(discounts[idx]);

  const lineTrace = {
    x: fineT, y: fineZ, type: "scatter", mode: "lines",
    line: { color: PALETTE.blue, width: 2 }, name: "Z(t)",
  };

  const revealed = years.slice(0, idx + 1);
  const markerTrace = {
    x: revealed, y: discounts.slice(0, idx + 1),
    type: "scatter", mode: "markers+text",
    text: revealed.map((t) => `${t}Y`),
    textposition: "top center",
    textfont: { color: PALETTE.muted, size: 10 },
    marker: {
      size: revealed.map((_, i) => (i === idx ? 14 : 11)),
      color: revealed.map((_, i) => (i === idx ? PALETTE.coral : PALETTE.blue)),
      line: { color: PALETTE.coral, width: revealed.map((_, i) => (i === idx ? 3 : 0)) },
    },
    hovertemplate: revealed.map((t, i) => `T=${t}y<br>Z=${discounts[i].toFixed(6)}<extra></extra>`),
    name: "OIS input nodes",
  };

  const maxT = years[years.length - 1];
  Plotly.react("discount-chart", [lineTrace, markerTrace],
    darkLayout({
      xaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid, title: "Years", range: [0, maxT * 1.02] , automargin: true },
      // Fixed like the survival chart's y-axis -- otherwise Plotly auto-scales
      // to whatever tiny range the currently-revealed points span (e.g. just
      // 0.99985-1.0 at step 1), making a genuinely tiny change look like a
      // dramatic plunge, with the dot sitting awkwardly at the plot's edge.
      // Headroom goes up to 1.12 (not just 1.02) so tenor labels on the
      // earliest nodes -- which sit very close to Z=1 -- have room to render
      // without being clipped by the plot's own top edge.
      yaxis: { gridcolor: PALETTE.grid, title: "Discount factor", range: [0, 1.12] , automargin: true },
      margin: { l: 48, r: 16, t: 28, b: 36 },
    }),
    PLOTLY_CONFIG);

  document.getElementById("dstep-label").textContent = `${years[idx]}Y  (${idx + 1} / ${years.length})`;
  document.getElementById("dstep-prev").disabled = idx === 0;
  document.getElementById("dstep-next").disabled = idx === years.length - 1;
  document.getElementById("dstep-play").disabled = idx === years.length - 1;
  document.getElementById("dstep-replay").disabled = !!state.discountPlayTimer || idx !== years.length - 1;
}

function stopDiscountPlay() {
  if (state.discountPlayTimer) { clearInterval(state.discountPlayTimer); state.discountPlayTimer = null; }
  document.getElementById("dstep-play").textContent = "▶ Play";
  const atEnd = state.result && state.discountStepIndex >= state.result.curve_fig.ois_node_years.length - 1;
  document.getElementById("dstep-play").disabled = atEnd;
  document.getElementById("dstep-replay").disabled = !atEnd;
}
function startDiscountPlay() {
  document.getElementById("dstep-play").textContent = "⏸ Pause";
  document.getElementById("dstep-replay").disabled = true;
  state.discountPlayTimer = setInterval(() => {
    const years = state.result.curve_fig.ois_node_years;
    if (state.discountStepIndex >= years.length - 1) { stopDiscountPlay(); return; }
    state.discountStepIndex++;
    renderDiscountChart(state.result);
  }, state.playSpeedMs);
}
document.getElementById("dstep-prev").addEventListener("click", () => {
  if (!state.result) return;
  stopDiscountPlay();
  if (state.discountStepIndex > 0) { state.discountStepIndex--; renderDiscountChart(state.result); }
});
document.getElementById("dstep-next").addEventListener("click", () => {
  if (!state.result) return;
  stopDiscountPlay();
  if (state.discountStepIndex < state.result.curve_fig.ois_node_years.length - 1) {
    state.discountStepIndex++; renderDiscountChart(state.result);
  }
});
document.getElementById("dstep-play").addEventListener("click", () => {
  if (!state.result) return;
  if (state.discountPlayTimer) { stopDiscountPlay(); return; }
  startDiscountPlay();
});
document.getElementById("dstep-reset").addEventListener("click", () => {
  if (!state.result) return;
  stopDiscountPlay();
  state.discountStepIndex = 0;
  renderDiscountChart(state.result);
});
document.getElementById("dstep-replay").addEventListener("click", () => {
  if (!state.result) return;
  state.discountStepIndex = 0;
  renderDiscountChart(state.result);
  startDiscountPlay();
});

// ------------------------------------------------------- step charts (all 3) -
function renderStepCharts() {
  renderSpreadInputChart();
  renderHazardChart();
  renderSurvivalChart();
}

// ------------------------------------------------------- spread input chart -
function renderSpreadInputChart() {
  const nodes = state.result.hazard_nodes;
  const idx = state.stepIndex;
  const revealed = nodes.slice(0, idx + 1);
  const maxT = nodes[nodes.length - 1].t;
  const maxSpread = Math.max(...nodes.map((n) => n.spread_bp));

  const lineTrace = {
    x: revealed.map((n) => n.t), y: revealed.map((n) => n.spread_bp),
    type: "scatter", mode: "lines+markers+text",
    text: revealed.map((n) => n.tenor),
    textposition: "top center",
    textfont: { color: PALETTE.muted, size: 10 },
    line: { color: PALETTE.lavender, width: 2 },
    marker: {
      size: revealed.map((_, i) => (i === idx ? 14 : 11)),
      color: revealed.map((_, i) => (i === idx ? PALETTE.coral : PALETTE.lavender)),
      line: { color: PALETTE.coral, width: revealed.map((_, i) => (i === idx ? 3 : 0)) },
    },
    hovertemplate: revealed.map((n) => `${n.tenor}<br>spread=${n.spread_bp.toFixed(3)}bp<extra></extra>`),
    name: "Market quote",
  };

  Plotly.react("spread-input-chart", [lineTrace],
    darkLayout({
      xaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid, title: "", range: [0, maxT * 1.02],
                showticklabels: false , automargin: true },
      // Extra (1.25x, not 1.15x) headroom above the max spread so the tenor
      // label above the highest node has room to render without being
      // clipped by the plot's own top edge.
      yaxis: { gridcolor: PALETTE.grid, title: "Par spread (bp)", range: [0, maxSpread * 1.25] , automargin: true },
      margin: { l: 48, r: 16, t: 28, b: 4 },
      title: { text: "Market par CDS spread quotes (input)", font: { size: 11, color: PALETTE.muted } },
    }),
    PLOTLY_CONFIG);
}

// -------------------------------------------------------------- hazard chart -
function renderHazardChart() {
  const nodes = state.result.hazard_nodes;
  const idx = state.stepIndex;
  const maxT = nodes[nodes.length - 1].t;
  const maxH = Math.max(...nodes.map((n) => n.h));

  // Piecewise-constant hazard rate as an explicit step function: segment i
  // runs from the previous node's time (or 0, for the first) to node i's own
  // time, at a flat height of node i's hazard rate. Each segment contributes
  // its two endpoints at the SAME height, so consecutive segments only ever
  // connect via a vertical jump, never a slope.
  const stepX = [];
  const stepY = [];
  let prevT = 0;
  for (let i = 0; i <= idx; i++) {
    stepX.push(prevT); stepY.push(nodes[i].h);
    stepX.push(nodes[i].t); stepY.push(nodes[i].h);
    prevT = nodes[i].t;
  }

  const stepTrace = {
    x: stepX, y: stepY, type: "scatter", mode: "lines",
    line: { color: PALETTE.gold, width: 2, shape: "linear" }, name: "λ(t)",
  };
  const revealed = nodes.slice(0, idx + 1);
  const markerTrace = {
    x: revealed.map((n) => n.t), y: revealed.map((n) => n.h),
    type: "scatter", mode: "markers+text",
    text: revealed.map((n) => n.tenor),
    textposition: "top center",
    textfont: { color: PALETTE.muted, size: 10 },
    marker: {
      size: revealed.map((_, i) => (i === idx ? 14 : 11)),
      color: revealed.map((_, i) => (i === idx ? PALETTE.coral : PALETTE.gold)),
      line: { color: PALETTE.coral, width: revealed.map((_, i) => (i === idx ? 3 : 0)) },
    },
    hovertemplate: revealed.map((n) => `${n.tenor}<br>h=${n.h.toFixed(6)}<extra></extra>`),
    name: "Calibrated hazard rate",
  };

  Plotly.react("hazard-chart", [stepTrace, markerTrace],
    darkLayout({
      xaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid, title: "", range: [0, maxT * 1.02],
                showticklabels: false , automargin: true },
      // Extra (1.25x, not 1.15x) headroom above the max hazard rate so the
      // tenor label above the highest node has room to render without being
      // clipped by the plot's own top edge.
      yaxis: { gridcolor: PALETTE.grid, title: "Hazard rate λ(t)", range: [0, maxH * 1.25] , automargin: true },
      margin: { l: 48, r: 16, t: 28, b: 4 },
      title: { text: "Piecewise-constant hazard rate (calibrated)", font: { size: 11, color: PALETTE.muted } },
    }),
    PLOTLY_CONFIG);
}

// ---------------------------------------------------------- survival chart -
function renderSurvivalChart() {
  const data = state.result;
  const nodes = data.hazard_nodes;
  const idx = state.stepIndex;
  const cutoffT = nodes[idx].t;

  const fineT = data.curve_fig.t.filter((t) => t <= cutoffT + 1e-9);
  const fineQ = data.curve_fig.survival.slice(0, fineT.length);
  // The fine grid is coarse (300 evenly-spaced points) and almost never lands
  // exactly on the node's own time, which left a visible gap between where the
  // line stopped and the highlighted dot. Append the node's exact (t, Q) so
  // the line always reaches the dot precisely.
  fineT.push(cutoffT);
  fineQ.push(nodes[idx].Q);

  const lineTrace = {
    x: fineT, y: fineQ, type: "scatter", mode: "lines",
    line: { color: PALETTE.teal, width: 2 }, name: "Q(t)",
  };

  const revealed = nodes.slice(0, idx + 1);
  const markerTrace = {
    x: revealed.map((n) => n.t), y: revealed.map((n) => n.Q),
    type: "scatter", mode: "markers+text",
    text: revealed.map((n) => n.tenor),
    textposition: "top center",
    textfont: { color: PALETTE.muted, size: 10 },
    marker: {
      size: revealed.map((_, i) => (i === idx ? 16 : 12)),
      color: revealed.map((_, i) => (i === idx ? PALETTE.coral : PALETTE.teal)),
      line: { color: PALETTE.coral, width: revealed.map((_, i) => (i === idx ? 3 : 0)) },
    },
    hovertemplate: revealed.map((n) =>
      `${n.tenor}<br>T=%{x:.3f}y<br>Q=%{y:.6f}<br>h=${n.h.toFixed(6)}<extra></extra>`),
    name: "Calibrated nodes",
  };

  // Fixed axis ranges spanning the FULL final curve, not just what's revealed
  // so far -- otherwise Plotly auto-fits to only the visible data each step,
  // making the plot visibly "zoom" in/out as nodes are revealed.
  const maxT = nodes[nodes.length - 1].t;
  Plotly.react("survival-chart", [lineTrace, markerTrace],
    darkLayout({
      xaxis: { gridcolor: PALETTE.grid, zerolinecolor: PALETTE.grid, title: "Years", range: [0, maxT * 1.02] , automargin: true },
      // Extra headroom above 1.0 (not just 1.02) so tenor labels on the
      // earliest nodes -- which sit very close to Q=1 -- have room to render
      // without being clipped by the plot's own top edge.
      yaxis: { gridcolor: PALETTE.grid, title: "Survival probability", range: [0, 1.12] , automargin: true },
      margin: { l: 48, r: 16, t: 28, b: 36 },
    }),
    PLOTLY_CONFIG);

  document.getElementById("step-label").textContent =
    `${nodes[idx].tenor}  (${idx + 1} / ${nodes.length})`;
  document.getElementById("step-prev").disabled = idx === 0;
  document.getElementById("step-next").disabled = idx === nodes.length - 1;
  // Nothing left to play forward once the last node is reached -- Play stays
  // disabled there regardless of play/pause state (Replay is the way back in).
  document.getElementById("step-play").disabled = idx === nodes.length - 1;
  // Replay only makes sense once the build has actually reached the end, and
  // not while it's still actively animating.
  document.getElementById("step-replay").disabled = !!state.playTimer || idx !== nodes.length - 1;

  renderNodeInfo(nodes[idx]);
  renderHazardMath(nodes[idx]);
}

function renderNodeInfo(node) {
  const rows = node.iterations.map((it) => `
    <tr class="${it.iter === node.iterations.length - 1 ? "current-iter" : ""}">
      <td>${it.iter}</td><td>${it.x.toFixed(6)}</td>
      <td>${it.residual.toExponential(3)}</td><td>${it.derivative.toExponential(3)}</td>
    </tr>`).join("");
  document.getElementById("node-info").innerHTML = `
    <strong>${node.tenor}</strong> &mdash; T=${node.t.toFixed(3)}y,
    h=${node.h.toFixed(6)}, Q(T)=${node.Q.toFixed(6)}, Z(T)=${node.discount_factor.toFixed(6)}
    <table>
      <thead><tr><th>iter</th><th>trial h</th><th>residual</th><th>derivative</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

document.getElementById("step-prev").addEventListener("click", () => {
  if (!state.result) return;
  stopPlay();
  if (state.stepIndex > 0) { state.stepIndex--; renderStepCharts(); }
});
document.getElementById("step-next").addEventListener("click", () => {
  if (!state.result) return;
  stopPlay();
  if (state.stepIndex < state.result.hazard_nodes.length - 1) { state.stepIndex++; renderStepCharts(); }
});
document.getElementById("step-play").addEventListener("click", () => {
  if (!state.result) return;
  if (state.playTimer) { stopPlay(); return; }
  startPlay();
});
function startPlay() {
  document.getElementById("step-play").textContent = "⏸ Pause";
  document.getElementById("step-replay").disabled = true;  // can't replay while it's still running
  state.playTimer = setInterval(() => {
    if (state.stepIndex >= state.result.hazard_nodes.length - 1) { stopPlay(); return; }
    state.stepIndex++;
    renderStepCharts();
  }, state.playSpeedMs);
}
function stopPlay() {
  if (state.playTimer) { clearInterval(state.playTimer); state.playTimer = null; }
  document.getElementById("step-play").textContent = "▶ Play";
  // Replay becomes available exactly when playback has stopped AND the build
  // has actually reached the last node (whether that's because the animation
  // finished naturally, or the user stepped/played their way to the end).
  const atEnd = state.result && state.stepIndex >= state.result.hazard_nodes.length - 1;
  document.getElementById("step-play").disabled = atEnd;
  document.getElementById("step-replay").disabled = !atEnd;
}

document.getElementById("step-reset").addEventListener("click", () => {
  if (!state.result) return;
  stopPlay();
  state.stepIndex = 0;
  renderStepCharts();
});

document.getElementById("step-replay").addEventListener("click", () => {
  if (!state.result) return;
  state.stepIndex = 0;
  renderStepCharts();
  startPlay();
});

// -------------------------------------------------------------- schedule ---
const SCHEDULE_PAGE_SIZE = 15;

function renderSchedule(data) {
  state.scheduleData = data;
  state.schedulePage = 0;
  renderSchedulePage();
}

function renderSchedulePage() {
  const data = state.scheduleData;
  const head = document.getElementById("schedule-head");
  const body = document.getElementById("schedule-body");

  head.innerHTML = "<th>#</th><th>Unadjusted date</th><th>Adjusted date</th><th>Accrual Δ (Act/360)</th>" +
    "<th>Discount time (Act/365F)</th><th>Discount factor</th><th>Survival probability</th>";

  const totalRows = data.schedule.length;
  const totalPages = Math.max(1, Math.ceil(totalRows / SCHEDULE_PAGE_SIZE));
  const page = state.schedulePage;
  const start = page * SCHEDULE_PAGE_SIZE;
  const pageRows = data.schedule.slice(start, start + SCHEDULE_PAGE_SIZE);

  body.innerHTML = pageRows.map((row) => `<tr data-discount-time="${row.discount_time}">
        <td>${row.period}</td><td>${row.unadjusted}</td><td>${row.adjusted}</td>
        <td>${row.accrual_delta.toFixed(6)}</td><td>${row.discount_time.toFixed(6)}</td>
        <td>${row.discount_factor.toFixed(6)}</td><td>${row.survival_probability.toFixed(6)}</td>
      </tr>`).join("");

  document.getElementById("schedule-page-label").textContent = `Page ${page + 1} / ${totalPages}`;
  document.getElementById("schedule-first").disabled = page === 0;
  document.getElementById("schedule-prev").disabled = page === 0;
  document.getElementById("schedule-next").disabled = page >= totalPages - 1;
  document.getElementById("schedule-last").disabled = page >= totalPages - 1;
}

function goToSchedulePage(page) {
  if (!state.scheduleData) return;
  const totalPages = Math.max(1, Math.ceil(state.scheduleData.schedule.length / SCHEDULE_PAGE_SIZE));
  state.schedulePage = Math.max(0, Math.min(page, totalPages - 1));
  renderSchedulePage();
}

document.getElementById("schedule-first").addEventListener("click", () => goToSchedulePage(0));
document.getElementById("schedule-prev").addEventListener("click", () => goToSchedulePage(state.schedulePage - 1));
document.getElementById("schedule-next").addEventListener("click", () => goToSchedulePage(state.schedulePage + 1));
document.getElementById("schedule-last").addEventListener("click", () =>
  goToSchedulePage(Math.ceil(state.scheduleData.schedule.length / SCHEDULE_PAGE_SIZE) - 1));

// ------------------------------------------- schedule row <-> curve linking -
// Hovering a payment row highlights whichever calibration segment its own
// discount_time falls into -- the SAME segment on the hazard-rate and
// survival charts (they share the same calibration nodes), and the
// bracketing segment on the discount chart (a different node grid, the OIS
// curve's own tenors). Implemented as a Plotly shape overlaid via relayout,
// not a full re-render, so it never disturbs whichever stepper position the
// curves are currently showing.
function findBracketingSegment(t, nodeTimes) {
  let prev = 0;
  for (const nodeT of nodeTimes) {
    if (t <= nodeT + 1e-9) return [prev, nodeT];
    prev = nodeT;
  }
  return [prev, nodeTimes[nodeTimes.length - 1]];
}

function highlightSegment(chartId, x0, x1) {
  Plotly.relayout(chartId, {
    shapes: [{
      type: "rect", xref: "x", yref: "paper",
      x0, x1, y0: 0, y1: 1,
      fillcolor: PALETTE.coral, opacity: 0.18, line: { width: 0 },
    }],
  });
}

function clearSegmentHighlights() {
  ["hazard-chart", "survival-chart", "discount-chart"].forEach((id) => Plotly.relayout(id, { shapes: [] }));
}

document.getElementById("schedule-body").addEventListener("mouseover", (e) => {
  const tr = e.target.closest("tr");
  if (!tr || !tr.dataset.discountTime || !state.result) return;
  const t = parseFloat(tr.dataset.discountTime);

  const [hStart, hEnd] = findBracketingSegment(t, state.result.hazard_nodes.map((n) => n.t));
  highlightSegment("hazard-chart", hStart, hEnd);
  highlightSegment("survival-chart", hStart, hEnd);

  const [dStart, dEnd] = findBracketingSegment(t, state.result.curve_fig.ois_node_years);
  highlightSegment("discount-chart", dStart, dEnd);
});
document.getElementById("schedule-body").addEventListener("mouseout", (e) => {
  if (!e.target.closest("tr")) return;
  clearSegmentHighlights();
});
