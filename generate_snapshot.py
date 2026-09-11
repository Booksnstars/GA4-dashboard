"""Generates self-contained static HTML snapshots of the GA4 dashboard.

Produces three pages (30 days, 90 days, 1 year) with a range switcher bar,
deployed to output/ for GitHub Pages.
"""

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "ga4_dashboard"))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient

import ga4_client

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

RANGES = [
    (30,  "30 days",  "30d.html"),
    (90,  "90 days",  "90d.html"),
    (365, "1 year",   "index.html"),
]

# ── Credentials ───────────────────────────────────────────────────────────────

oauth_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
if not oauth_json:
    sys.exit("GOOGLE_OAUTH_TOKEN_JSON environment variable is not set.")

creds = Credentials.from_authorized_user_info(json.loads(oauth_json), SCOPES)
if not creds.valid and creds.refresh_token:
    creds.refresh(Request())

client = BetaAnalyticsDataClient(credentials=creds)

# ── Generate one page per range ───────────────────────────────────────────────

template = (Path(__file__).parent / "ga4_dashboard" / "dashboard.html").read_text(encoding="utf-8")
out = Path(__file__).parent / "output"
out.mkdir(exist_ok=True)

for days, range_label, filename in RANGES:
    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    print(f"Fetching {range_label}: {start_date} → {end_date} …")
    data = ga4_client.fetch_all(client, start_date, end_date, auth_only=False)
    data["meta"] = {"start": start_date, "end": end_date, "auth_only": False}
    print(f"  Done.")

    # Build the range-switcher bar injected at the top of the page
    switcher_items = []
    for _, lbl, fn in RANGES:
        if fn == filename:
            style = ("color:#fff;text-decoration:none;padding:5px 14px;"
                     "font-weight:700;border-bottom:2px solid rgba(255,255,255,.8);")
        else:
            style = "color:rgba(255,255,255,.75);text-decoration:none;padding:5px 14px;"
        switcher_items.append(f'<a href="{fn}" style="{style}">{lbl}</a>')

    switcher_html = (
        '<div id="range-switcher" style="background:#1e4d1e;padding:4px 16px 0;'
        'display:flex;align-items:center;gap:2px;font-size:.82rem;font-family:system-ui,sans-serif;">'
        '<span style="color:rgba(255,255,255,.55);margin-right:10px;font-size:.78rem;">Date range</span>'
        + "".join(switcher_items)
        + "</div>"
    )

    shim = f"""<script>
(function() {{
  var _BAKED = {json.dumps(data, ensure_ascii=False)};
  var _realFetch = window.fetch;
  window.fetch = function(url) {{
    if (typeof url === 'string' && url.indexOf('/api/data') !== -1) {{
      return Promise.resolve(new Response(JSON.stringify(_BAKED), {{
        status: 200,
        headers: {{'Content-Type': 'application/json'}}
      }}));
    }}
    return _realFetch.apply(this, arguments);
  }};
  document.addEventListener('DOMContentLoaded', function() {{
    // Inject range switcher above the existing header
    var bar = document.createElement('div');
    bar.innerHTML = {json.dumps(switcher_html)};
    document.body.insertBefore(bar.firstChild, document.body.firstChild);
    // Disable controls that require a live server
    var rb = document.getElementById('refresh-btn');
    if (rb) {{ rb.disabled = true; rb.title = 'Not available in snapshot'; }}
    var eb = document.getElementById('export-btn');
    if (eb) {{ eb.style.display = 'none'; }}
    // Hide auth toggle — snapshot is all-users only
    var at = document.querySelector('.auth-toggle-wrap');
    if (at) at.style.display = 'none';
    // Disable date inputs — date range is fixed in this snapshot
    document.querySelectorAll('input[type="date"]').forEach(function(el) {{
      el.disabled = true;
      el.title = 'Date range is fixed in this snapshot';
    }});
    // Update status line
    var sm = document.getElementById('status-msg');
    if (sm) {{ sm.textContent = 'Snapshot · {start_date} → {end_date}'; }}
  }});
}})();
</script>"""

    static_html = re.sub(r'<script\b', shim + '\n<script', template, count=1)
    (out / filename).write_text(static_html, encoding="utf-8")
    print(f"  Written: output/{filename}")

print("All snapshots complete.")
