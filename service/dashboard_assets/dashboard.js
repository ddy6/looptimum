const configElement = document.getElementById("dashboard-config");
const config = configElement ? JSON.parse(configElement.textContent || "{}") : {};
const currentCampaignId = config.currentCampaignId || document.body.dataset.currentCampaignId || "";

const serviceHealthState = document.getElementById("service-health-state");
const serviceHealthDetail = document.getElementById("service-health-detail");
const campaignListState = document.getElementById("campaign-list-state");
const campaignList = document.getElementById("campaign-list");
const campaignTitle = document.getElementById("campaign-title");
const campaignDetailState = document.getElementById("campaign-detail-state");
const campaignDetailGrid = document.getElementById("campaign-detail-grid");
const campaignMonitorGrid = document.getElementById("campaign-monitor-grid");
const trialLayout = document.getElementById("trial-layout");
const timeseriesState = document.getElementById("timeseries-state");
const timeseriesChart = document.getElementById("best-timeseries-chart");
const decisionTraceState = document.getElementById("decision-trace-state");
const decisionTraceList = document.getElementById("decision-trace-list");
const trialListState = document.getElementById("trial-list-state");
const trialList = document.getElementById("trial-list");
const trialDetailState = document.getElementById("trial-detail-state");
const trialDetailGrid = document.getElementById("trial-detail-grid");

let selectedTrialId = null;

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function setPre(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = JSON.stringify(value ?? {}, null, 2);
  }
}

function setHidden(element, hidden) {
  if (element) {
    element.hidden = hidden;
  }
}

function formatMaybeNumber(value) {
  if (value === null || value === undefined) {
    return "None";
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toFixed(3).replace(/\.?0+$/, "") : "None";
  }
  return String(value);
}

function formatTimestamp(value) {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) {
    return "None";
  }
  return new Date(value * 1000).toLocaleString();
}

function formatDuration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) {
    return "None";
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  if (seconds < 3600) {
    return `${(seconds / 60).toFixed(1).replace(/\.0$/, "")}m`;
  }
  if (seconds < 86400) {
    return `${(seconds / 3600).toFixed(1).replace(/\.0$/, "")}h`;
  }
  return `${(seconds / 86400).toFixed(1).replace(/\.0$/, "")}d`;
}

function formatBest(best) {
  if (!best || typeof best !== "object") {
    return "None";
  }
  const trialId = best.trial_id ?? "?";
  const objectiveValue = formatMaybeNumber(best.objective_value);
  return `Trial ${trialId} (${objectiveValue})`;
}

function formatStatusMix(byStatus) {
  if (!byStatus || typeof byStatus !== "object") {
    return "No status data";
  }
  const parts = Object.entries(byStatus)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([status, count]) => `${status}:${count}`);
  return parts.length > 0 ? parts.join(" | ") : "No status data";
}

function formatTraceSummary(entry) {
  const decision = entry?.decision || {};
  const strategy = decision.strategy || "unknown";
  const backend = decision.surrogate_backend || "none";
  const latency = decision.telemetry?.suggest_latency_seconds;
  const constraintStatus = decision.constraint_status || {};
  const constraintSummary =
    constraintStatus.enabled === true
      ? `feasible ${constraintStatus.accepted ?? 0}/${constraintStatus.requested ?? 0}`
      : "constraints off";
  const latencySummary =
    typeof latency === "number" && Number.isFinite(latency)
      ? `latency ${latency.toFixed(3).replace(/\.?0+$/, "")}s`
      : "latency n/a";
  return `${strategy} | backend ${backend} | ${constraintSummary} | ${latencySummary}`;
}

function createTimeseriesMarkup(points) {
  const values = points.map((point) => {
    const value = point.scalarized_objective ?? point.objective_value ?? 0;
    return typeof value === "number" && Number.isFinite(value) ? value : 0;
  });
  const width = 720;
  const height = 220;
  const paddingX = 34;
  const paddingY = 26;
  const plotWidth = width - paddingX * 2;
  const plotHeight = height - paddingY * 2;
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const range = maxValue - minValue || 1;
  const step = values.length > 1 ? plotWidth / (values.length - 1) : 0;

  const coords = values.map((value, index) => {
    const x = values.length === 1 ? width / 2 : paddingX + step * index;
    const y = paddingY + ((maxValue - value) / range) * plotHeight;
    return {
      x: Number(x.toFixed(3)),
      y: Number(y.toFixed(3)),
      value,
      trialId: points[index].trial_id,
    };
  });

  const polyline = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const gridValues = [maxValue, minValue + range / 2, minValue];
  const grid = gridValues
    .map((value) => {
      const y = paddingY + ((maxValue - value) / range) * plotHeight;
      return `<g>
        <line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(15,23,32,0.14)" stroke-dasharray="6 6" />
        <text x="${paddingX}" y="${y - 6}" fill="rgba(77,97,114,0.88)" font-size="11">${formatMaybeNumber(value)}</text>
      </g>`;
    })
    .join("");
  const dots = coords
    .map((point, index) => {
      const isImprovement = Boolean(points[index].is_improvement);
      const fill = isImprovement ? "#d36d3f" : "#13202b";
      const radius = isImprovement ? 5 : 4;
      return `<circle cx="${point.x}" cy="${point.y}" r="${radius}" fill="${fill}" />`;
    })
    .join("");
  const labels = coords
    .map(
      (point) =>
        `<text x="${point.x}" y="${height - 10}" text-anchor="middle" fill="rgba(77,97,114,0.88)" font-size="11">T${point.trialId}</text>`,
    )
    .join("");

  return `${grid}
    <polyline
      fill="none"
      stroke="#8f3f1f"
      stroke-width="3"
      stroke-linecap="round"
      stroke-linejoin="round"
      points="${polyline}"
    />
    ${dots}
    ${labels}`;
}

function setActionLink(id, href, enabled) {
  const element = document.getElementById(id);
  if (!element) {
    return;
  }
  if (enabled) {
    element.href = href;
    element.classList.remove("is-disabled");
    element.setAttribute("aria-disabled", "false");
    element.target = "_blank";
    element.rel = "noreferrer";
  } else {
    element.href = "#";
    element.classList.add("is-disabled");
    element.setAttribute("aria-disabled", "true");
    element.removeAttribute("target");
    element.removeAttribute("rel");
  }
}

function renderHealth(payload) {
  serviceHealthState.textContent = payload.ok ? "Healthy" : "Unavailable";
  serviceHealthState.dataset.state = payload.ok ? "healthy" : "error";
  serviceHealthDetail.textContent = `Registry: ${payload.registry_file} | campaigns: ${payload.campaign_count}`;
}

function renderCampaignList(campaigns) {
  campaignList.innerHTML = "";
  if (!Array.isArray(campaigns) || campaigns.length === 0) {
    campaignListState.hidden = false;
    campaignListState.textContent = "No campaigns registered in the preview service yet.";
    return;
  }
  campaignListState.hidden = true;
  for (const campaign of campaigns) {
    const link = document.createElement("a");
    link.href = `/dashboard/campaigns/${campaign.campaign_id}`;
    link.className = "campaign-link";
    if (campaign.campaign_id === currentCampaignId) {
      link.classList.add("is-active");
    }

    const title = document.createElement("div");
    title.className = "campaign-link__title";
    title.textContent = campaign.label || campaign.campaign_id;
    link.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "campaign-link__meta";
    meta.textContent = `${campaign.campaign_id} | ${campaign.root_path}`;
    link.appendChild(meta);
    campaignList.appendChild(link);
  }
}

function renderOverview(detail, alerts) {
  setHidden(campaignDetailGrid, false);
  setHidden(campaignMonitorGrid, false);
  setHidden(trialLayout, false);
  setHidden(campaignDetailState, true);

  const campaign = detail.campaign || {};
  const status = detail.status || {};
  campaignTitle.textContent = campaign.label || campaign.campaign_id || "Campaign Detail";
  setText("campaign-id-value", campaign.campaign_id || "None");
  setText("campaign-label-value", campaign.label || "None");
  setText("campaign-root-value", campaign.root_path || "None");
  setText("status-observations", String(status.observations ?? 0));
  setText("status-pending", String(status.pending ?? 0));
  setText("status-best-trial", formatBest(status.best));
  setText("status-next-trial", String(status.next_trial_id ?? "None"));
  setText("alerts-pending", String(alerts.pending_count ?? 0));
  setText("alerts-stale", String(alerts.stale_pending_count ?? 0));
  setText("alerts-oldest-age", formatDuration(alerts.oldest_pending_age_seconds));
  setText("alerts-max-age", formatDuration(alerts.max_pending_age_seconds));
  setText("alerts-leased", String(alerts.leased_pending_count ?? 0));
  setText(
    "alerts-decision-trace",
    alerts.decision_trace_available ? "Available" : "Not generated",
  );
}

function renderTimeseries(payload) {
  const points = Array.isArray(payload.points) ? payload.points : [];
  setText("timeseries-primary-objective", payload.objective_name || "None");
  setText("timeseries-best-objective", payload.best_objective_name || "None");
  setText("timeseries-scalarization", payload.scalarization_policy || "primary_only");
  setText("timeseries-point-count", String(points.length));
  setText("timeseries-ignored-count", String((payload.ignored_trial_ids || []).length));

  if (points.length === 0) {
    setText("timeseries-current-best", "No completed ok trials");
    setText(
      "timeseries-caption",
      "No completed ok trials are available yet, so the best-over-time chart is empty.",
    );
    setHidden(timeseriesChart, true);
    setHidden(timeseriesState, false);
    timeseriesState.textContent = "No best-over-time points available yet.";
    timeseriesChart.innerHTML = "";
    return;
  }

  const latestPoint = points[points.length - 1];
  setText(
    "timeseries-current-best",
    `Trial ${latestPoint.best_trial_id} (${formatMaybeNumber(latestPoint.best_objective_value)})`,
  );
  setText(
    "timeseries-caption",
    `Tracking ${points.length} completed ok trial(s) with ${points.filter((point) => point.is_improvement).length} improvement event(s).`,
  );
  timeseriesChart.innerHTML = createTimeseriesMarkup(points);
  setHidden(timeseriesChart, false);
  setHidden(timeseriesState, true);
}

function renderExportLinks(alerts) {
  if (!currentCampaignId) {
    setActionLink("export-report-json", "#", false);
    setActionLink("export-report-md", "#", false);
    setActionLink("export-decision-trace", "#", false);
    return;
  }
  setActionLink(
    "export-report-json",
    `/campaigns/${currentCampaignId}/exports/report.json`,
    Boolean(alerts.report_available),
  );
  setActionLink(
    "export-report-md",
    `/campaigns/${currentCampaignId}/exports/report.md`,
    Boolean(alerts.report_available),
  );
  setActionLink(
    "export-decision-trace",
    `/campaigns/${currentCampaignId}/exports/decision-trace.jsonl`,
    Boolean(alerts.decision_trace_available),
  );
}

function renderDecisionTrace(payload) {
  const entries = Array.isArray(payload.entries) ? payload.entries.slice(-5).reverse() : [];
  decisionTraceList.innerHTML = "";

  if (!payload.available || entries.length === 0) {
    decisionTraceState.textContent = "No decision trace has been generated for this campaign yet.";
    setHidden(decisionTraceState, false);
    setHidden(decisionTraceList, true);
    return;
  }

  for (const entry of entries) {
    const card = document.createElement("article");
    card.className = "trace-entry";

    const title = document.createElement("div");
    title.className = "trace-entry__title";
    title.textContent = `Trial ${entry.trial_id ?? "?"}`;
    card.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "trace-entry__meta";
    meta.textContent = `${formatTimestamp(entry.timestamp)} | ${formatTraceSummary(entry)}`;
    card.appendChild(meta);

    const detail = document.createElement("div");
    detail.className = "trace-entry__detail";
    detail.textContent = JSON.stringify(entry.decision || {}, null, 2);
    card.appendChild(detail);
    decisionTraceList.appendChild(card);
  }

  setHidden(decisionTraceState, true);
  setHidden(decisionTraceList, false);
}

function markActiveTrial() {
  const buttons = trialList.querySelectorAll(".trial-button");
  for (const button of buttons) {
    const matches = Number(button.dataset.trialId) === selectedTrialId;
    button.classList.toggle("is-active", matches);
  }
}

async function loadTrialDetail(trialId) {
  selectedTrialId = trialId;
  markActiveTrial();
  setHidden(trialDetailState, false);
  setText("trial-detail-title", `Trial ${trialId}`);
  trialDetailState.textContent = `Loading detail for trial ${trialId}.`;
  try {
    const payload = await fetchJson(`/campaigns/${currentCampaignId}/trials/${trialId}`);
    const trial = payload.trial || {};
    const decision = payload.decision || {};
    setText("trial-detail-title", `Trial ${trial.trial_id ?? trialId}`);
    setText("trial-status-value", String(trial.status ?? "None"));
    setText("trial-terminal-reason", String(trial.terminal_reason ?? "None"));
    setText(
      "trial-objective-value",
      `${trial.objective_name ?? "objective"}: ${formatMaybeNumber(trial.objective_value)}`,
    );
    setText("trial-scalarized-value", formatMaybeNumber(trial.scalarized_objective));
    setText("trial-suggested-at", formatTimestamp(trial.suggested_at));
    setText("trial-completed-at", formatTimestamp(trial.completed_at));
    setText("trial-heartbeats", String(trial.heartbeat_count ?? 0));
    setText("trial-lease-token", trial.lease_token || "None");
    setText("trial-manifest-path", trial.manifest_path || "None");
    setText("trial-artifact-path", trial.artifact_path || "None");
    setPre("trial-params-json", trial.params);
    setPre("trial-objectives-json", trial.objective_vector);
    setPre("trial-decision-json", decision);
    setHidden(trialDetailState, true);
    setHidden(trialDetailGrid, false);
  } catch (error) {
    setHidden(trialDetailGrid, true);
    setHidden(trialDetailState, false);
    trialDetailState.textContent =
      error instanceof Error ? error.message : "Unable to load trial detail.";
  }
}

function renderTrialList(payload) {
  const counts = payload.counts || {};
  const trials = Array.isArray(payload.trials) ? payload.trials : [];
  setText("trial-count-total", String(counts.total ?? trials.length));
  setText("trial-count-terminal", String(counts.terminal ?? 0));
  setText("trial-count-pending", String(counts.pending ?? 0));
  setText("trial-count-by-status", formatStatusMix(counts.by_status));
  setText("trial-status-mix", formatStatusMix(counts.by_status));

  trialList.innerHTML = "";
  if (trials.length === 0) {
    setHidden(trialListState, false);
    trialListState.textContent = "No trial history is available yet for this campaign.";
    setHidden(trialList, true);
    setHidden(trialDetailGrid, true);
    setHidden(trialDetailState, false);
    trialDetailState.textContent = "No trial detail is available yet because no suggestions have been issued.";
    return;
  }

  setHidden(trialListState, true);
  setHidden(trialList, false);
  for (const trial of trials) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "trial-button";
    button.dataset.trialId = String(trial.trial_id);

    const title = document.createElement("div");
    title.className = "trial-button__title";
    title.textContent = `Trial ${trial.trial_id} | ${trial.status ?? "unknown"}`;
    button.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "trial-button__meta";
    meta.textContent = `${trial.is_pending ? "pending" : "terminal"} | objective ${formatMaybeNumber(trial.objective_value)} | updated ${formatTimestamp(trial.completed_at || trial.suggested_at)}`;
    button.appendChild(meta);

    button.addEventListener("click", () => {
      void loadTrialDetail(Number(trial.trial_id));
    });
    trialList.appendChild(button);
  }

  const firstTrialId = Number(trials[0].trial_id);
  if (!Number.isInteger(selectedTrialId)) {
    selectedTrialId = firstTrialId;
  }
  void loadTrialDetail(selectedTrialId);
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { accept: "application/json" } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error?.message || `Request failed for ${path}`;
    throw new Error(message);
  }
  return payload;
}

async function loadDashboard() {
  try {
    const health = await fetchJson(config.healthPath || "/health");
    renderHealth(health);
  } catch (error) {
    serviceHealthState.textContent = "Error";
    serviceHealthState.dataset.state = "error";
    serviceHealthDetail.textContent = error instanceof Error ? error.message : "Service check failed.";
  }

  try {
    const campaignsPayload = await fetchJson(config.campaignsPath || "/campaigns");
    renderCampaignList(campaignsPayload.campaigns || []);
  } catch (error) {
    campaignListState.hidden = false;
    campaignListState.textContent = error instanceof Error ? error.message : "Unable to load campaigns.";
    return;
  }

  renderExportLinks({ report_available: false, decision_trace_available: false });

  if (!currentCampaignId) {
    return;
  }

  setHidden(campaignDetailState, false);
  campaignDetailState.textContent = "Loading campaign overview, timeseries, and trial detail.";

  try {
    const [detail, alerts, timeseries, trials, decisionTrace] = await Promise.all([
      fetchJson(`/campaigns/${currentCampaignId}/detail`),
      fetchJson(`/campaigns/${currentCampaignId}/alerts`),
      fetchJson(`/campaigns/${currentCampaignId}/timeseries/best`),
      fetchJson(`/campaigns/${currentCampaignId}/trials`),
      fetchJson(`/campaigns/${currentCampaignId}/decision-trace`),
    ]);
    renderOverview(detail, alerts);
    renderTimeseries(timeseries);
    renderExportLinks(alerts);
    renderDecisionTrace(decisionTrace);
    renderTrialList(trials);
  } catch (error) {
    setHidden(campaignDetailGrid, true);
    setHidden(campaignMonitorGrid, true);
    setHidden(trialLayout, true);
    setHidden(campaignDetailState, false);
    campaignDetailState.textContent =
      error instanceof Error ? error.message : "Unable to load campaign detail.";
  }
}

void loadDashboard();
