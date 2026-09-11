"""Generates a self-contained static HTML snapshot of the GA4 dashboard.

Called by the GitHub Actions workflow; reads GOOGLE_OAUTH_TOKEN_JSON from the
environment, fetches the last 365 days from all properties, and writes
output/index.html ready for GitHub Pages deployment.
"""

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow importing ga4_client from the subdirectory
sys.path.insert(0, str(Path(__file__).parent / "ga4_dashboard"))

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient

import ga4_client

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# ── Credentials ───────────────────────────────────────────────────────────────

oauth_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
if not oauth_json:
    sys.exit("GOOGLE_OAUTH_TOKEN_JSON environment variable is not set.")

creds = Credentials.from_authorized_user_info(json.loads(oauth_json), SCOPES)
if not creds.valid and creds.refresh_token:
    creds.refresh(Request())

# ── Fetch data ────────────────────────────────────────────────────────────────

end_date   = date.today().strftime("%Y-%m-%d")
start_date = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")

print(f"Fetching {start_date} → {end_date} …")
client = BetaAnalyticsDataClient(credentials=creds)
data   = ga4_client.fetch_all(client, start_date, end_date, auth_only=False)
data["meta"] = {"start": start_date, "end": end_date, "auth_only": False}
print("Fetch complete.")

# ── Bake into static HTML ─────────────────────────────────────────────────────

template = (Path(__file__).parent / "ga4_dashboard" / "dashboard.html").read_text(encoding="utf-8")

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
    // Disable controls that require a live server
    var rb = document.getElementById('refresh-btn');
    if (rb) {{ rb.disabled = true; rb.title = 'Not available in snapshot'; }}
    var eb = document.getElementById('export-btn');
    if (eb) {{ eb.style.display = 'none'; }}
    // Hide auth toggle — snapshot is all-users only
    var at = document.querySelector('.auth-toggle-wrap');
    if (at) at.style.display = 'none';
    // Update status line
    var sm = document.getElementById('status-msg');
    if (sm) {{ sm.textContent = 'Snapshot · {data["meta"]["start"]} → {data["meta"]["end"]}'; }}
  }});
}})();
</script>"""

static_html = re.sub(r'<script\b', shim + '\n<script', template, count=1)

out = Path(__file__).parent / "output"
out.mkdir(exist_ok=True)
(out / "index.html").write_text(static_html, encoding="utf-8")
print(f"Written: output/index.html")
