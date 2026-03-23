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

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
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

function formatBest(best) {
  if (!best || typeof best !== "object") {
    return "None";
  }
  const trialId = best.trial_id ?? "?";
  const objectiveValue = formatMaybeNumber(best.objective_value);
  return `Trial ${trialId} (${objectiveValue})`;
}

function renderHealth(payload) {
  serviceHealthState.textContent = payload.ok ? "Healthy" : "Unavailable";
  serviceHealthState.className = "metric-value";
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

function renderDetail(detail, alerts) {
  campaignDetailGrid.hidden = false;
  campaignDetailState.hidden = true;

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
  setText("alerts-oldest-age", formatMaybeNumber(alerts.oldest_pending_age_seconds));
  setText(
    "alerts-decision-trace",
    alerts.decision_trace_available ? "Available" : "Not generated",
  );
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

  if (!currentCampaignId) {
    return;
  }

  campaignDetailState.hidden = false;
  campaignDetailState.textContent = "Loading campaign overview.";

  try {
    const [detail, alerts] = await Promise.all([
      fetchJson(`/campaigns/${currentCampaignId}/detail`),
      fetchJson(`/campaigns/${currentCampaignId}/alerts`),
    ]);
    renderDetail(detail, alerts);
  } catch (error) {
    campaignDetailGrid.hidden = true;
    campaignDetailState.hidden = false;
    campaignDetailState.textContent =
      error instanceof Error ? error.message : "Unable to load campaign detail.";
  }
}

void loadDashboard();
