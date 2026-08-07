"""
GA4 Dashboard Server

Local dev:  python server.py          (uses OAuth via client_secret.json)
Production: gunicorn server:app       (uses GOOGLE_SERVICE_ACCOUNT_JSON env var)
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import ga4_client

BASE_DIR   = Path(__file__).parent
TOKEN_FILE = BASE_DIR / "token.json"
CREDS_FILE = BASE_DIR / "client_secret.json"
SCOPES     = ["https://www.googleapis.com/auth/analytics.readonly"]

app = Flask(__name__, static_folder=str(BASE_DIR))


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_credentials():
    # Production option A: service account (requires GA4 admin access to grant)
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        return service_account.Credentials.from_service_account_info(
            json.loads(sa_json), scopes=SCOPES
        )

    # Production option B: pre-generated OAuth token from local token.json
    # Paste the contents of your token.json as the GOOGLE_OAUTH_TOKEN_JSON env var.
    # The refresh token inside is long-lived and will auto-renew the access token.
    oauth_json = os.environ.get("GOOGLE_OAUTH_TOKEN_JSON")
    if oauth_json:
        creds = Credentials.from_authorized_user_info(json.loads(oauth_json), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
        return creds

    # Local dev: OAuth browser flow
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS_FILE.exists():
                print("\n❌  client_secret.json not found in", BASE_DIR)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


# ── GA4 client (module-level so gunicorn workers share it) ────────────────────

_ga_client = None

def get_ga_client():
    global _ga_client
    if _ga_client is None:
        _ga_client = BetaAnalyticsDataClient(credentials=get_credentials())
    return _ga_client


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "dashboard.html")


@app.route("/api/data")
def api_data():
    default_end   = date.today().strftime("%Y-%m-%d")
    default_start = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")

    start_date = request.args.get("start", default_start)
    end_date   = request.args.get("end",   default_end)
    auth_only  = request.args.get("auth", "0") == "1"

    try:
        data = ga4_client.fetch_all(get_ga_client(), start_date, end_date, auth_only)
        data["meta"] = {"start": start_date, "end": end_date, "auth_only": auth_only}
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/export")
def export():
    start_date = request.args.get("start")
    end_date   = request.args.get("end")
    auth_only  = request.args.get("auth", "0") == "1"
    if not start_date or not end_date:
        return jsonify({"error": "start and end required"}), 400

    try:
        data = ga4_client.fetch_all(get_ga_client(), start_date, end_date, auth_only)
        data["meta"] = {"start": start_date, "end": end_date, "auth_only": auth_only}
        template = (BASE_DIR / "dashboard.html").read_text(encoding="utf-8")
        static_html = bake_static(template, data)
        suffix = "_authenticated" if auth_only else ""
        filename = f"sage_ga4_{start_date}_to_{end_date}{suffix}.html"
        return Response(
            static_html,
            mimetype="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def bake_static(template, data):
    shim = f"""<script>
(function() {{
  var _BAKED = {json.dumps(data, ensure_ascii=False)};
  var _realFetch = window.fetch;
  window.fetch = function(url) {{
    if (typeof url === 'string' && url.indexOf('/api/data') !== -1) {{
      var body = JSON.stringify(_BAKED);
      return Promise.resolve(new Response(body, {{
        status: 200,
        headers: {{'Content-Type': 'application/json'}}
      }}));
    }}
    return _realFetch.apply(this, arguments);
  }};
  document.addEventListener('DOMContentLoaded', function() {{
    var rb = document.getElementById('refresh-btn');
    var eb = document.getElementById('export-btn');
    if (rb) {{ rb.disabled = true; rb.title = 'Not available in exported file'; }}
    if (eb) {{ eb.style.display = 'none'; }}
    var sm = document.getElementById('status-msg');
    if (sm) {{ sm.textContent = 'Snapshot · {data["meta"]["start"]} → {data["meta"]["end"]}'; }}
  }});
}})();
</script>"""
    return template.replace("<script>", shim + "\n<script>", 1)


# ── Local dev entry point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n📊  GA4 Dashboard Server")
    print("🔑  Authenticating…")
    creds = get_credentials()
    _ga_client = BetaAnalyticsDataClient(credentials=creds)
    print("    ✓ Authenticated")

    default_end   = date.today().strftime("%Y-%m-%d")
    default_start = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
    print(f"\n🗺   Landing page diagnostic ({default_start} → {default_end}):")
    ga4_client.list_landing_pages_diagnostic(_ga_client, default_start, default_end)

    port = int(os.environ.get("PORT", 5000))
    print(f"🌐  Open http://localhost:{port} in your browser\n")
    app.run(host="0.0.0.0", port=port, debug=False)
