"""Zero-build static GitHub Pages dashboard generator."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from laptop_hunter.config import AppConfig
from laptop_hunter.storage import StateStore, utc_now


def build_dashboard_payload(
    store: StateStore,
    config: AppConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble serializable dashboard payload from StateStore and AppConfig."""
    now_dt = now or utc_now()
    active = store.active_deals(stale_days=config.storage.stale_deal_days, now=now_dt)

    matches = [d for d in active if d.get("category") == "match"]
    near_misses = [d for d in active if d.get("category") == "near_miss"]

    gpu_summary: list[dict[str, Any]] = []
    for gpu_name, target in sorted(
        config.specs.gpu_targets.items(),
        key=lambda kv: (kv[1].tier, kv[1].target_price_usd),
    ):
        gpu_matches = [d for d in matches if (d.get("specs") or {}).get("gpu") == gpu_name]
        active_low = (
            min(float(d["current_price_usd"]) for d in gpu_matches)
            if gpu_matches
            else None
        )
        tracked_low, samples = store.get_gpu_tier_low(gpu_name, condition="new")
        gpu_summary.append(
            {
                "gpu": gpu_name,
                "tier": target.tier,
                "target_price_usd": target.target_price_usd,
                "active_match_count": len(gpu_matches),
                "active_low_usd": active_low,
                "tracked_low_usd": tracked_low,
                "samples": samples,
            }
        )

    return {
        "generated_at": now_dt.isoformat(),
        "title": config.dashboard.title,
        "subtitle": config.dashboard.subtitle,
        "min_ram_gb": config.specs.min_ram_gb,
        "min_ssd_gb": config.specs.min_ssd_gb,
        "last_run_at": store.data.get("last_run_at"),
        "runs_count": store.data.get("runs_count", 0),
        "providers": store.data.get("last_provider_results", []),
        "gpu_summary": gpu_summary,
        "gpu_history": store.data.get("gpu_history", {}),
        "matches": matches,
        "near_misses": near_misses,
    }


def _safe_inline_json(payload: dict[str, Any]) -> str:
    """Serialize JSON safe to embed inside an HTML <script> tag."""
    return json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>__TITLE__</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0b0f17;
      --surface: #131a26;
      --surface-2: #1a2334;
      --border: #253147;
      --text: #e6edf7;
      --muted: #8ea0bc;
      --emerald: #10b981;
      --amber: #f59e0b;
      --orange: #f97316;
      --blue: #3b82f6;
      --purple: #a855f7;
      --red: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
      background: radial-gradient(circle at top right, #132038 0%, var(--bg) 45%);
      color: var(--text);
      line-height: 1.5;
    }
    .container { max-width: 1280px; margin: 0 auto; padding: 24px 18px 64px; }
    header {
      display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end;
      gap: 16px; padding-bottom: 20px; border-bottom: 1px solid var(--border);
    }
    h1 { margin: 0; font-size: 1.75rem; letter-spacing: -0.02em; }
    .subtitle { color: var(--muted); margin: 4px 0 0; font-size: 0.95rem; }
    .meta-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 0.82rem; color: var(--muted); }
    .pill {
      display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px;
      border-radius: 999px; font-size: 0.78rem; font-weight: 600;
      background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
    }
    .pill.ok { border-color: rgba(16,185,129,0.4); color: #6ee7b7; }
    .pill.skipped { border-color: rgba(142,160,188,0.3); color: var(--muted); }
    .pill.error { border-color: rgba(239,68,68,0.4); color: #fca5a5; }
    .kpi-grid {
      display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 14px; margin: 20px 0;
    }
    .kpi-card {
      background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
      padding: 16px 18px;
    }
    .kpi-label { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); }
    .kpi-value { font-size: 1.7rem; font-weight: 700; margin-top: 6px; }
    .section-card {
      background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
      padding: 18px 20px; margin-bottom: 20px;
    }
    .section-header {
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
      margin-bottom: 14px;
    }
    .section-title { margin: 0; font-size: 1.08rem; font-weight: 650; }
    .gpu-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(185px, 1fr)); gap: 10px;
    }
    .gpu-tile {
      background: var(--surface-2); border: 1px solid var(--border); border-radius: 10px;
      padding: 12px;
    }
    .gpu-name { font-weight: 700; font-size: 0.95rem; }
    .gpu-row { display: flex; justify-content: space-between; font-size: 0.82rem; color: var(--muted); margin-top: 4px; }
    .gpu-row strong { color: var(--text); }
    .gpu-row strong.good { color: var(--emerald); }
    .chart-wrap { position: relative; height: 290px; width: 100%; }
    .empty-state {
      text-align: center; padding: 40px 16px; color: var(--muted);
      border: 1px dashed var(--border); border-radius: 12px;
    }
    .tabs { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
    .tab-btn {
      background: var(--surface-2); color: var(--muted); border: 1px solid var(--border);
      padding: 9px 16px; border-radius: 10px; font-weight: 600; cursor: pointer; font-size: 0.9rem;
    }
    .tab-btn.active {
      background: rgba(59,130,246,0.18); color: #93c5fd; border-color: rgba(59,130,246,0.5);
    }
    .filters {
      display: grid; grid-template-columns: 2fr repeat(4, 1fr); gap: 10px; margin-bottom: 16px;
    }
    @media (max-width: 860px) { .filters { grid-template-columns: 1fr 1fr; } }
    input, select {
      background: var(--surface-2); border: 1px solid var(--border); color: var(--text);
      padding: 9px 12px; border-radius: 8px; font-size: 0.88rem; width: 100%;
    }
    .checkbox-label {
      display: inline-flex; align-items: center; gap: 8px; font-size: 0.86rem;
      color: var(--muted); cursor: pointer; margin-bottom: 14px;
    }
    .checkbox-label input { width: auto; }
    .deals-grid {
      display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px;
    }
    .deal-card {
      background: var(--surface-2); border: 1px solid var(--border); border-radius: 12px;
      padding: 16px; display: flex; flex-direction: column; justify-content: space-between; gap: 12px;
      transition: border-color 0.15s ease, transform 0.15s ease;
    }
    .deal-card:hover { border-color: #3b5075; transform: translateY(-1px); }
    .deal-card.killer { border-color: rgba(16,185,129,0.55); box-shadow: 0 0 0 1px rgba(16,185,129,0.15); }
    .deal-card.histlow { border-color: rgba(245,158,11,0.65); box-shadow: 0 0 0 1px rgba(245,158,11,0.18); }
    .badges { display: flex; flex-wrap: wrap; gap: 6px; }
    .badge {
      font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 6px;
      text-transform: uppercase; letter-spacing: 0.03em;
    }
    .badge.target { background: rgba(16,185,129,0.2); color: #6ee7b7; }
    .badge.hist { background: rgba(245,158,11,0.22); color: #fcd34d; }
    .badge.discount { background: rgba(59,130,246,0.2); color: #93c5fd; }
    .badge.warn { background: rgba(249,115,22,0.22); color: #fdba74; }
    .badge.cond { background: rgba(148,163,184,0.16); color: #cbd5e1; }
    .deal-title {
      font-weight: 650; font-size: 0.96rem; color: var(--text); text-decoration: none;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .deal-title:hover { color: #93c5fd; }
    .price-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
    .price-now { font-size: 1.5rem; font-weight: 800; color: #ffffff; }
    .price-msrp { font-size: 0.9rem; color: var(--muted); text-decoration: line-through; }
    .price-diff { font-size: 0.82rem; font-weight: 650; }
    .price-diff.under { color: var(--emerald); }
    .price-diff.over { color: var(--muted); }
    .spec-pills { display: flex; flex-wrap: wrap; gap: 6px; }
    .spec-pill {
      font-size: 0.78rem; padding: 3px 8px; border-radius: 6px;
      background: rgba(11,15,23,0.65); border: 1px solid var(--border); color: #d5e0f2;
    }
    .near-miss-note {
      font-size: 0.8rem; color: #fdba74; background: rgba(249,115,22,0.1);
      border: 1px solid rgba(249,115,22,0.25); border-radius: 8px; padding: 6px 10px;
    }
    .card-footer {
      display: flex; justify-content: space-between; align-items: center; gap: 10px;
      padding-top: 10px; border-top: 1px solid rgba(37,49,71,0.7); font-size: 0.8rem; color: var(--muted);
    }
    .btn-link {
      background: #2563eb; color: #fff; text-decoration: none; font-weight: 650;
      padding: 7px 12px; border-radius: 8px; font-size: 0.82rem; white-space: nowrap;
    }
    .btn-link:hover { background: #1d4ed8; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1 id="dash-title">__TITLE__</h1>
        <p class="subtitle" id="dash-subtitle">__SUBTITLE__</p>
      </div>
      <div class="meta-bar" id="meta-bar"></div>
    </header>

    <div class="kpi-grid" id="kpi-grid"></div>

    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">GPU Target Prices &amp; Tracked Lows (32GB+ / 1TB+ New)</h2>
      </div>
      <div class="gpu-grid" id="gpu-grid"></div>
    </section>

    <section class="section-card">
      <div class="section-header">
        <h2 class="section-title">Tracked Price History by GPU Tier</h2>
        <span style="font-size:0.82rem;color:var(--muted)">Daily lowest brand-new matching price</span>
      </div>
      <div class="chart-wrap" id="chart-container">
        <canvas id="priceChart"></canvas>
      </div>
    </section>

    <section class="section-card">
      <div class="tabs">
        <button class="tab-btn active" id="tab-matches" onclick="setTab('matches')">Matched Deals</button>
        <button class="tab-btn" id="tab-near" onclick="setTab('near_misses')">Near Misses &amp; Upgradeable</button>
      </div>

      <div class="filters">
        <input type="text" id="filter-search" placeholder="Search brand, model, CPU, OLED, store..." oninput="renderDeals()" />
        <select id="filter-gpu" onchange="renderDeals()"><option value="">All GPUs</option></select>
        <select id="filter-condition" onchange="renderDeals()">
          <option value="">All Conditions</option>
          <option value="new">New</option>
          <option value="open_box">Open-Box</option>
          <option value="refurbished">Refurbished</option>
        </select>
        <select id="filter-store" onchange="renderDeals()"><option value="">All Stores</option></select>
        <select id="filter-sort" onchange="renderDeals()">
          <option value="priority">Sort: Hottest First</option>
          <option value="price_asc">Sort: Price Low → High</option>
          <option value="discount_desc">Sort: Biggest % Off</option>
          <option value="newest">Sort: Most Recently Seen</option>
        </select>
      </div>

      <label class="checkbox-label">
        <input type="checkbox" id="filter-killer-only" onchange="renderDeals()" />
        Only show triggered "Can't Be Beat" deals (beats target / steep discount / historical low)
      </label>

      <div class="deals-grid" id="deals-grid"></div>
    </section>
  </div>

  <script id="dashboard-data" type="application/json">__DATA_JSON__</script>
  <script>
    const DATA = JSON.parse(document.getElementById("dashboard-data").textContent);
    let currentTab = "matches";

    const fmtMoney = (n) => n == null ? "—" : "$" + Number(n).toLocaleString(undefined, { maximumFractionDigits: n % 1 ? 2 : 0 });
    const fmtSsd = (gb) => !gb ? null : (gb >= 1000 && gb % 1000 === 0 ? `${gb/1000}TB SSD` : `${gb}GB SSD`);
    const condLabel = (c) => ({ new: "New", open_box: "Open-Box", refurbished: "Refurbished", used: "Used" }[c] || c);
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, m => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[m]));

    function init() {
      const updated = DATA.last_run_at ? new Date(DATA.last_run_at).toLocaleString() : "Never";
      const meta = document.getElementById("meta-bar");
      const provPills = (DATA.providers || []).map(p =>
        `<span class="pill ${esc(p.status)}" title="${esc(p.message)}">${esc(p.provider)}: ${p.listing_count}</span>`
      ).join("");
      meta.innerHTML = `<span>Updated: <strong>${esc(updated)}</strong> (Run #${DATA.runs_count || 0})</span>${provPills}`;

      const killerCount = (DATA.matches || []).filter(d => (d.triggers || []).length > 0).length;
      const lowestMatch = (DATA.matches || []).length
        ? Math.min(...DATA.matches.map(d => d.current_price_usd))
        : null;

      document.getElementById("kpi-grid").innerHTML = `
        <div class="kpi-card"><div class="kpi-label">Active Matches (${DATA.min_ram_gb}GB+ / ${DATA.min_ssd_gb >= 1000 ? (DATA.min_ssd_gb/1000)+'TB+' : DATA.min_ssd_gb+'GB+'})</div><div class="kpi-value">${(DATA.matches || []).length}</div></div>
        <div class="kpi-card"><div class="kpi-label">Triggered Killer Deals</div><div class="kpi-value" style="color:var(--emerald)">${killerCount}</div></div>
        <div class="kpi-card"><div class="kpi-label">Near Misses / Upgradeable</div><div class="kpi-value" style="color:var(--amber)">${(DATA.near_misses || []).length}</div></div>
        <div class="kpi-card"><div class="kpi-label">Lowest Active Match</div><div class="kpi-value">${fmtMoney(lowestMatch)}</div></div>
      `;

      document.getElementById("tab-matches").textContent = `Matched Deals (${(DATA.matches || []).length})`;
      document.getElementById("tab-near").textContent = `Near Misses & Upgradeable (${(DATA.near_misses || []).length})`;

      document.getElementById("gpu-grid").innerHTML = (DATA.gpu_summary || []).map(g => {
        const beats = g.active_low_usd != null && g.active_low_usd <= g.target_price_usd;
        return `
          <div class="gpu-tile">
            <div class="gpu-name">${esc(g.gpu)}</div>
            <div class="gpu-row"><span>Target</span><strong>${fmtMoney(g.target_price_usd)}</strong></div>
            <div class="gpu-row"><span>Active Low</span><strong class="${beats ? 'good' : ''}">${fmtMoney(g.active_low_usd)}</strong></div>
            <div class="gpu-row"><span>All-Time Low</span><strong>${fmtMoney(g.tracked_low_usd)}</strong></div>
            <div class="gpu-row"><span>Active Deals</span><strong>${g.active_match_count}</strong></div>
          </div>
        `;
      }).join("");

      const allDeals = [...(DATA.matches || []), ...(DATA.near_misses || [])];
      const gpus = [...new Set(allDeals.map(d => d.specs?.gpu).filter(Boolean))].sort();
      const stores = [...new Set(allDeals.map(d => d.store).filter(Boolean))].sort();

      const gpuSel = document.getElementById("filter-gpu");
      gpus.forEach(g => gpuSel.insertAdjacentHTML("beforeend", `<option value="${esc(g)}">${esc(g)}</option>`));
      const storeSel = document.getElementById("filter-store");
      stores.forEach(s => storeSel.insertAdjacentHTML("beforeend", `<option value="${esc(s)}">${esc(s)}</option>`));

      renderChart();
      renderDeals();
    }

    function renderChart() {
      const history = DATA.gpu_history || {};
      const allDates = [...new Set(Object.values(history).flat().map(pt => pt.date))].sort();
      if (!allDates.length || typeof Chart === "undefined") {
        document.getElementById("chart-container").innerHTML =
          '<div class="empty-state">Price history chart will populate automatically once matched deals are recorded across runs.</div>';
        return;
      }
      const palette = ["#10b981", "#3b82f6", "#f59e0b", "#a855f7", "#ec4899", "#06b6d4", "#f97316", "#84cc16"];
      const datasets = Object.entries(history).map(([gpu, pts], idx) => {
        const byDate = Object.fromEntries(pts.map(p => [p.date, p.min_price_usd]));
        const color = palette[idx % palette.length];
        return {
          label: gpu,
          data: allDates.map(d => byDate[d] ?? null),
          borderColor: color,
          backgroundColor: color,
          spanGaps: true,
          tension: 0.25,
          borderWidth: 2,
          pointRadius: 3,
        };
      });

      new Chart(document.getElementById("priceChart"), {
        type: "line",
        data: { labels: allDates, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: "index", intersect: false },
          plugins: {
            legend: { labels: { color: "#cbd5e1" } },
            tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtMoney(ctx.parsed.y)}` } }
          },
          scales: {
            x: { ticks: { color: "#8ea0bc" }, grid: { color: "rgba(37,49,71,0.5)" } },
            y: {
              ticks: { color: "#8ea0bc", callback: v => "$" + v },
              grid: { color: "rgba(37,49,71,0.5)" }
            }
          }
        }
      });
    }

    function setTab(tab) {
      currentTab = tab;
      document.getElementById("tab-matches").classList.toggle("active", tab === "matches");
      document.getElementById("tab-near").classList.toggle("active", tab === "near_misses");
      renderDeals();
    }

    function renderDeals() {
      const q = document.getElementById("filter-search").value.trim().toLowerCase();
      const gpu = document.getElementById("filter-gpu").value;
      const cond = document.getElementById("filter-condition").value;
      const store = document.getElementById("filter-store").value;
      const sort = document.getElementById("filter-sort").value;
      const killerOnly = document.getElementById("filter-killer-only").checked;

      let list = [...(DATA[currentTab] || [])];
      list = list.filter(d => {
        const s = d.specs || {};
        if (gpu && s.gpu !== gpu) return false;
        if (cond && s.condition !== cond) return false;
        if (store && d.store !== store) return false;
        if (killerOnly && !(d.triggers && d.triggers.length)) return false;
        if (q) {
          const blob = `${d.title} ${d.store} ${s.gpu} ${s.cpu} ${s.brand} ${s.panel_type} ${s.resolution}`.toLowerCase();
          if (!blob.includes(q)) return false;
        }
        return true;
      });

      list.sort((a, b) => {
        if (sort === "price_asc") return (a.current_price_usd ?? 9e9) - (b.current_price_usd ?? 9e9);
        if (sort === "discount_desc") return (b.specs?.discount_pct ?? 0) - (a.specs?.discount_pct ?? 0);
        if (sort === "newest") return String(b.last_seen_at || "").localeCompare(String(a.last_seen_at || ""));
        return (b.alert_priority ?? 0) - (a.alert_priority ?? 0) || (a.current_price_usd ?? 9e9) - (b.current_price_usd ?? 9e9);
      });

      const grid = document.getElementById("deals-grid");
      if (!list.length) {
        grid.innerHTML = '<div class="empty-state" style="grid-column:1/-1">No deals match your current filters yet.</div>';
        return;
      }

      grid.innerHTML = list.map(d => {
        const s = d.specs || {};
        const triggers = d.triggers || [];
        const isHist = triggers.includes("HISTORICAL_LOW_TIER") || triggers.includes("HISTORICAL_LOW_MODEL");
        const isKiller = triggers.includes("BEATS_TARGET") || triggers.includes("STEEP_DISCOUNT");
        const cardClass = isHist ? "histlow" : (isKiller ? "killer" : "");

        const badges = [];
        if (isHist) badges.push('<span class="badge hist">All-Time Low</span>');
        if (triggers.includes("BEATS_TARGET")) badges.push('<span class="badge target">Beats Target</span>');
        if (triggers.includes("STEEP_DISCOUNT")) badges.push('<span class="badge discount">Steep Discount</span>');
        if (triggers.includes("EXTREME_UNCONFIRMED")) badges.push('<span class="badge warn">Verify Specs</span>');
        badges.push(`<span class="badge cond">${esc(condLabel(s.condition || "new"))}</span>`);

        const diff = d.effective_target_usd != null ? (d.current_price_usd - d.effective_target_usd) : null;
        const diffHtml = diff != null
          ? `<span class="price-diff ${diff <= 0 ? 'under' : 'over'}">${diff <= 0 ? '-' : '+'}${fmtMoney(Math.abs(diff))} vs target</span>`
          : "";

        const pills = [
          s.gpu,
          s.ram_gb ? `${s.ram_gb}GB RAM` : null,
          fmtSsd(s.ssd_gb),
          s.cpu,
          [s.screen_inches ? `${s.screen_inches}"` : null, s.resolution, s.panel_type, s.refresh_hz ? `${s.refresh_hz}Hz` : null].filter(Boolean).join(" ") || null
        ].filter(Boolean).map(p => `<span class="spec-pill">${esc(p)}</span>`).join("");

        const nearNote = (d.near_miss_reasons && d.near_miss_reasons.length)
          ? `<div class="near-miss-note">Near miss: ${esc(d.near_miss_reasons.join(" • "))}</div>`
          : "";

        const seenTime = d.last_seen_at ? new Date(d.last_seen_at).toLocaleDateString() : "";

        return `
          <article class="deal-card ${cardClass}">
            <div style="display:flex;flex-direction:column;gap:10px">
              <div class="badges">${badges.join("")}</div>
              <a class="deal-title" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">${esc(d.title)}</a>
              <div class="price-row">
                <span class="price-now">${fmtMoney(d.current_price_usd)}</span>
                ${s.msrp_usd ? `<span class="price-msrp">${fmtMoney(s.msrp_usd)}</span>` : ""}
                ${s.discount_pct ? `<span class="badge discount">-${s.discount_pct}%</span>` : ""}
                ${diffHtml}
              </div>
              <div class="spec-pills">${pills}</div>
              ${nearNote}
            </div>
            <div class="card-footer">
              <span>${esc(d.store || "Store")} · ${esc(d.provider)} · ${esc(seenTime)}</span>
              <a class="btn-link" href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">View Deal ↗</a>
            </div>
          </article>
        `;
      }).join("");
    }

    init();
  </script>
</body>
</html>
"""


def generate_dashboard(
    store: StateStore,
    config: AppConfig,
    output_dir: str | Path,
    now: datetime | None = None,
) -> Path:
    """Write static GitHub Pages dashboard files (index.html + data.json)."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    payload = build_dashboard_payload(store, config, now=now)
    (out_path / "data.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    html = (
        _HTML_TEMPLATE.replace("__TITLE__", config.dashboard.title)
        .replace("__SUBTITLE__", config.dashboard.subtitle)
        .replace("__DATA_JSON__", _safe_inline_json(payload))
    )
    index_file = out_path / "index.html"
    index_file.write_text(html, encoding="utf-8")
    return index_file
