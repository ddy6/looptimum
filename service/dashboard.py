from __future__ import annotations

import json
from pathlib import Path

ASSETS_DIR = Path(__file__).with_name("dashboard_assets")


def render_dashboard_shell(*, current_campaign_id: str | None = None) -> str:
    config = {
        "currentCampaignId": current_campaign_id,
        "healthPath": "/health",
        "campaignsPath": "/campaigns",
    }
    config_json = json.dumps(config, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Looptimum Dashboard Preview</title>
    <link rel="stylesheet" href="/dashboard/assets/dashboard.css">
  </head>
  <body data-current-campaign-id="{current_campaign_id or ""}">
    <div class="dashboard-shell">
      <header class="hero">
        <div class="hero__eyebrow">Service UI Preview</div>
        <div class="hero__row">
          <div>
            <h1>Looptimum Dashboard Preview</h1>
            <p class="hero__copy">
              Read-only operator shell over the preview API. Campaign roots remain file-backed and authoritative.
            </p>
          </div>
          <div class="hero__status" id="service-health-card" aria-live="polite">
            <div class="card-label">Service Health</div>
            <div class="metric-value" id="service-health-state">Loading</div>
            <p id="service-health-detail">Checking preview service status.</p>
          </div>
        </div>
      </header>

      <main class="workspace">
        <aside class="panel panel--rail" id="campaign-list-panel">
          <div class="panel__header">
            <div>
              <div class="card-label">Registered Campaigns</div>
              <h2>Campaign List</h2>
            </div>
            <a class="panel-link" href="/dashboard">Reset View</a>
          </div>
          <div class="state-message" id="campaign-list-state">Loading campaigns.</div>
          <nav class="campaign-list" id="campaign-list" aria-label="Registered campaigns"></nav>
        </aside>

        <section class="panel panel--detail" id="campaign-detail-panel">
          <div class="panel__header">
            <div>
              <div class="card-label">Campaign Overview</div>
              <h2 id="campaign-title">Select a campaign</h2>
            </div>
            <div class="preview-chip">Preview Only</div>
          </div>
          <div class="state-message" id="campaign-detail-state">
            Choose a campaign to inspect its current status and alert headline.
          </div>

          <div class="detail-grid" id="campaign-detail-grid" hidden>
            <article class="summary-card">
              <div class="card-label">Identity</div>
              <dl class="kv-grid">
                <div><dt>Campaign ID</dt><dd id="campaign-id-value">-</dd></div>
                <div><dt>Label</dt><dd id="campaign-label-value">-</dd></div>
                <div><dt>Root Path</dt><dd id="campaign-root-value">-</dd></div>
              </dl>
            </article>

            <article class="summary-card">
              <div class="card-label">Status Headline</div>
              <dl class="kv-grid">
                <div><dt>Observations</dt><dd id="status-observations">-</dd></div>
                <div><dt>Pending</dt><dd id="status-pending">-</dd></div>
                <div><dt>Best Trial</dt><dd id="status-best-trial">-</dd></div>
                <div><dt>Next Trial ID</dt><dd id="status-next-trial">-</dd></div>
              </dl>
            </article>

            <article class="summary-card summary-card--wide">
              <div class="card-label">Alert Headline</div>
              <dl class="kv-grid">
                <div><dt>Pending Trials</dt><dd id="alerts-pending">-</dd></div>
                <div><dt>Stale Pending</dt><dd id="alerts-stale">-</dd></div>
                <div><dt>Oldest Pending Age</dt><dd id="alerts-oldest-age">-</dd></div>
                <div><dt>Decision Trace</dt><dd id="alerts-decision-trace">-</dd></div>
              </dl>
            </article>
          </div>
        </section>
      </main>
    </div>

    <script id="dashboard-config" type="application/json">{config_json}</script>
    <script type="module" src="/dashboard/assets/dashboard.js"></script>
  </body>
</html>
"""
