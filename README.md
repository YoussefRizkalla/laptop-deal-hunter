# Gaming Laptop Deal Hunter

Automated 24/7 gaming laptop deal monitor built for **GitHub Actions + Discord + GitHub Pages**.

Tracks high-end gaming laptops (**RTX 5070 / 4080 / 5070 Ti / 5080 / 4090 / 5090**, **32GB+ RAM**, **1TB+ SSD**) across curated deal feeds and retailer APIs, alerts your Discord server only when a deal beats your target price / hits a steep discount / sets a new tracked low, and publishes a live interactive dashboard with Chart.js price history.

## Architecture

- **Sources**:
  - `Slickdeals` (Popular + live Forum RSS search feeds — catches flash sales fast)
  - `DealNews` (Official curated US Laptops RSS feed)
  - `r/LaptopDeals` (Reddit OAuth2 when `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` are set, with automatic public JSON + Atom RSS fallback)
  - `Best Buy Products & Open-Box API` *(optional — auto-activates when `BESTBUY_API_KEY` is configured)*
  - `GamingLaptop.deals` *(optional provider in registry, disabled by default due to Cloudflare bot protection on datacenter IPs)*
- **Strict Discord Alerts vs. Forgiving Dashboard**:
  - **Discord alerts** fire only on confirmed **≥ 32GB RAM & ≥ 1TB SSD** matches that beat your per-GPU target price (10% stricter for Open-Box / Refurbished), hit a ≥ 25% steep discount, or set a new tracked historical low — plus optional extreme outliers when a terse deal title omits RAM/SSD (tagged `[VERIFY SPECS]`).
  - **Near Misses & Upgradeable** deals (e.g., 16GB RAM / 512GB SSD configs that you could upgrade yourself) stay out of Discord and appear in a dedicated tab on the GitHub Pages dashboard.
- **Clean Git Persistence**:
  - Runtime price history lives on an isolated orphan `data` branch (`data/state.json`) and only commits when deals or prices change, keeping `main` conflict-free.

## 5-Minute GitHub Setup

1. **Create a public GitHub repository** (public repos get unlimited free GitHub Actions minutes and free GitHub Pages) and push this repo:
   ```bash
   git remote add origin https://github.com/<your-username>/laptop-deal-hunter.git
   git push -u origin main
   ```
2. **Create a Discord Webhook**:
   - In Discord: **Server Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
3. **Add GitHub Secrets** (**Settings → Secrets and variables → Actions → New repository secret**):
   - `DISCORD_WEBHOOK_URL` *(required for alerts)*: your Discord webhook URL.
   - `BESTBUY_API_KEY` *(optional)*: free API key from [developer.bestbuy.com](https://developer.bestbuy.com/) to include Best Buy live inventory & Open-Box deals.
   - `REDDIT_CLIENT_ID` & `REDDIT_CLIENT_SECRET` *(optional)*: free script app credentials from [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) so `r/LaptopDeals` works reliably from GitHub Actions IPs without rate limits.
4. **Enable GitHub Pages**:
   - Go to **Settings → Pages → Build and deployment → Source** and select **GitHub Actions**.
5. **Run it once manually**:
   - Go to **Actions → Laptop Deal Monitor → Run workflow**.
   - After that, it runs automatically every **20 minutes**, alerts Discord on killer deals, and updates your dashboard at `https://<your-username>.github.io/laptop-deal-hunter/`.

## Customizing Target Prices & Rules

Edit [`config.yaml`](config.yaml) on `main` and push — the workflow automatically picks up your new thresholds and refreshes the dashboard:

- `specs.gpu_targets`: per-GPU target prices in USD (edit anytime as market prices move).
- `specs.min_ram_gb` / `specs.min_ssd_gb`: strict Discord minimums (`32` / `1000`).
- `conditions.non_new_price_multiplier`: extra discount required for Open-Box / Refurbished (`0.90` = 10% below New target).
- `alerts.min_redrop_usd` / `alerts.min_redrop_pct`: anti-spam re-alert thresholds.

## Local Development & Dry-Run

```bash
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Run unit tests
pytest -v

# Dry-run against live feeds (builds site/index.html locally without pinging Discord)
$env:PYTHONPATH="src"
python -m laptop_hunter --dry-run
```

Then open `site/index.html` in your browser to preview the dashboard locally.
