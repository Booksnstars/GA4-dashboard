"""
GA4 Dashboard Generator
Pulls channel group and search-behaviour data from GA4, outputs an HTML dashboard.

Usage:
    python fetch_ga4.py

First run: opens browser for Google OAuth sign-in.
Subsequent runs: uses saved token (token.json).
"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    FilterExpression,
    Filter,
    RunReportRequest,
)
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ── Config ────────────────────────────────────────────────────────────────────

PROPERTY_ID = "258026800"
TOKEN_FILE = Path(__file__).parent / "token.json"
CREDENTIALS_FILE = Path(__file__).parent / "client_secret.json"
OUTPUT_FILE = Path(__file__).parent / "dashboard.html"

# Date range: last 90 days
END_DATE = date.today().strftime("%Y-%m-%d")
START_DATE = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# Channel grouping logic
EXTERNAL_DISCOVERY_CHANNELS = {
    "Organic Search",
    "Organic Social",
    "Referral",
    "Organic Video",
    "Organic Shopping",
    "Display",
    "Paid Search",
    "Paid Social",
    "Paid Video",
    "Paid Other",
    "Affiliates",
    "Audio",
    "Cross-network",
    # Common AI/LLM referral labels GA4 may surface
    "Organic AI",
    "AI Search",
}

DIRECT_CHANNELS = {"Direct"}

# ── Auth ──────────────────────────────────────────────────────────────────────

def get_credentials():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                print(
                    "\n❌  client_secret.json not found.\n"
                    "    Follow the setup instructions in README.txt, then re-run.\n"
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


# ── GA4 queries ───────────────────────────────────────────────────────────────

def fetch_channel_data(client):
    """Returns list of (channel_group, sessions)."""
    request = RunReportRequest(
        property=f"properties/{PROPERTY_ID}",
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=START_DATE, end_date=END_DATE)],
        limit=50,
    )
    response = client.run_report(request)
    rows = []
    for row in response.rows:
        channel = row.dimension_values[0].value
        sessions = int(row.metric_values[0].value)
        rows.append((channel, sessions))
    return rows


def fetch_search_data(client):
    """
    Returns (search_sessions, no_search_sessions).
    Uses the 'search' event as the signal for search interactions.
    We run two queries:
      1. Total sessions
      2. Sessions that fired at least one 'search' event
    """
    base_request = dict(
        property=f"properties/{PROPERTY_ID}",
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=START_DATE, end_date=END_DATE)],
    )

    # Total sessions
    total_resp = client.run_report(RunReportRequest(**base_request))
    total_sessions = int(total_resp.rows[0].metric_values[0].value) if total_resp.rows else 0

    # Sessions with a 'search' event
    search_resp = client.run_report(
        RunReportRequest(
            **base_request,
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    string_filter=Filter.StringFilter(
                        value="search",
                        match_type=Filter.StringFilter.MatchType.EXACT,
                    ),
                )
            ),
        )
    )
    # The metric here is "sessions that had a search event"
    search_sessions = int(search_resp.rows[0].metric_values[0].value) if search_resp.rows else 0
    no_search_sessions = max(0, total_sessions - search_sessions)

    return search_sessions, no_search_sessions, total_sessions


# ── Data processing ───────────────────────────────────────────────────────────

def categorise_channels(rows):
    """
    Groups raw channel rows into:
      - External Discovery
      - Direct
      - Other
    Returns dict with totals and breakdown list.
    """
    external = 0
    direct = 0
    other = 0
    breakdown = []

    for channel, sessions in rows:
        breakdown.append({"channel": channel, "sessions": sessions})
        if channel in EXTERNAL_DISCOVERY_CHANNELS:
            external += sessions
        elif channel in DIRECT_CHANNELS:
            direct += sessions
        else:
            other += sessions

    total = external + direct + other
    return {
        "external": external,
        "direct": direct,
        "other": other,
        "total": total,
        "breakdown": sorted(breakdown, key=lambda x: -x["sessions"]),
    }


def pct(part, total):
    if total == 0:
        return 0.0
    return round(part / total * 100, 1)


# ── HTML generation ───────────────────────────────────────────────────────────

def build_html(channel_data, search_sessions, no_search_sessions, total_sessions):
    cd = channel_data
    ext_pct = pct(cd["external"], cd["total"])
    dir_pct = pct(cd["direct"], cd["total"])
    oth_pct = pct(cd["other"], cd["total"])
    srch_pct = pct(search_sessions, total_sessions)
    no_srch_pct = pct(no_search_sessions, total_sessions)

    breakdown_rows = "".join(
        f'<tr><td>{r["channel"]}</td>'
        f'<td class="num">{r["sessions"]:,}</td>'
        f'<td class="num">{pct(r["sessions"], cd["total"])}%</td></tr>'
        for r in cd["breakdown"]
    )

    today = date.today().strftime("%-d %B %Y") if sys.platform != "win32" else date.today().strftime("%d %B %Y")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GA4 Dashboard — SAGE Publishing</title>
<style>
  :root {{
    --sage: #2e7d32;
    --sage-light: #e8f5e9;
    --ext: #1565c0;
    --ext-light: #e3f2fd;
    --dir: #ef6c00;
    --dir-light: #fff3e0;
    --oth: #6a1b9a;
    --oth-light: #f3e5f5;
    --srch: #00838f;
    --srch-light: #e0f7fa;
    --nosrch: #558b2f;
    --nosrch-light: #f1f8e9;
    --text: #1a1a1a;
    --muted: #555;
    --border: #e0e0e0;
    --bg: #f8f9fa;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; background: var(--bg); color: var(--text); }}
  header {{ background: var(--sage); color: white; padding: 24px 40px; }}
  header h1 {{ font-size: 1.6rem; font-weight: 600; }}
  header p {{ font-size: 0.9rem; opacity: .8; margin-top: 4px; }}
  .container {{ max-width: 1100px; margin: 32px auto; padding: 0 24px; }}
  .section-title {{ font-size: 1.15rem; font-weight: 600; color: var(--sage); margin-bottom: 16px; padding-bottom: 8px; border-bottom: 2px solid var(--sage-light); }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: white; border-radius: 8px; padding: 20px 24px; border: 1px solid var(--border); }}
  .card .label {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin-bottom: 8px; }}
  .card .value {{ font-size: 2.2rem; font-weight: 700; line-height: 1; }}
  .card .sub {{ font-size: 0.85rem; color: var(--muted); margin-top: 6px; }}
  .card.ext {{ border-top: 4px solid var(--ext); }} .card.ext .value {{ color: var(--ext); }}
  .card.dir {{ border-top: 4px solid var(--dir); }} .card.dir .value {{ color: var(--dir); }}
  .card.oth {{ border-top: 4px solid var(--oth); }} .card.oth .value {{ color: var(--oth); }}
  .card.srch {{ border-top: 4px solid var(--srch); }} .card.srch .value {{ color: var(--srch); }}
  .card.nosrch {{ border-top: 4px solid var(--nosrch); }} .card.nosrch .value {{ color: var(--nosrch); }}
  .card.total {{ border-top: 4px solid var(--sage); }} .card.total .value {{ color: var(--sage); }}
  .bar-wrap {{ background: white; border-radius: 8px; border: 1px solid var(--border); padding: 24px; margin-bottom: 32px; }}
  .bar-label {{ font-size: 0.85rem; margin-bottom: 6px; display: flex; justify-content: space-between; }}
  .bar {{ height: 36px; border-radius: 4px; display: flex; overflow: hidden; margin-bottom: 12px; }}
  .seg {{ display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 600; color: white; transition: width .4s; }}
  .seg.ext {{ background: var(--ext); }}
  .seg.dir {{ background: var(--dir); }}
  .seg.oth {{ background: var(--oth); }}
  .seg.srch {{ background: var(--srch); }}
  .seg.nosrch {{ background: var(--nosrch); }}
  .legend {{ display: flex; gap: 20px; flex-wrap: wrap; margin-top: 12px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.85rem; }}
  .dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; border: 1px solid var(--border); margin-bottom: 40px; }}
  th {{ background: var(--sage-light); color: var(--sage); font-size: 0.8rem; text-transform: uppercase; padding: 12px 16px; text-align: left; }}
  td {{ padding: 11px 16px; border-bottom: 1px solid var(--border); font-size: 0.9rem; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #fafafa; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  footer {{ text-align: center; padding: 24px; font-size: 0.8rem; color: var(--muted); }}
  .section {{ margin-bottom: 40px; }}
</style>
</head>
<body>
<header>
  <h1>GA4 Session Analytics — SAGE Publishing</h1>
  <p>Property {PROPERTY_ID} &nbsp;·&nbsp; {START_DATE} to {END_DATE} &nbsp;·&nbsp; Generated {today}</p>
</header>
<div class="container">

  <!-- ── Section 1: Channel Groups ── -->
  <div class="section">
    <div class="section-title">1 · Session Origin: External Discovery vs Direct</div>
    <div class="cards">
      <div class="card total">
        <div class="label">Total Sessions</div>
        <div class="value">{cd["total"]:,}</div>
      </div>
      <div class="card ext">
        <div class="label">External Discovery</div>
        <div class="value">{ext_pct}%</div>
        <div class="sub">{cd["external"]:,} sessions</div>
      </div>
      <div class="card dir">
        <div class="label">Direct</div>
        <div class="value">{dir_pct}%</div>
        <div class="sub">{cd["direct"]:,} sessions</div>
      </div>
      <div class="card oth">
        <div class="label">Other / Unassigned</div>
        <div class="value">{oth_pct}%</div>
        <div class="sub">{cd["other"]:,} sessions</div>
      </div>
    </div>

    <div class="bar-wrap">
      <div class="bar-label"><span>Session origin breakdown</span><span>{cd["total"]:,} total sessions</span></div>
      <div class="bar">
        <div class="seg ext" style="width:{ext_pct}%">{ext_pct}%</div>
        <div class="seg dir" style="width:{dir_pct}%">{dir_pct}%</div>
        <div class="seg oth" style="width:{oth_pct}%">{oth_pct}%</div>
      </div>
      <div class="legend">
        <div class="legend-item"><div class="dot" style="background:var(--ext)"></div> External Discovery ({ext_pct}%)</div>
        <div class="legend-item"><div class="dot" style="background:var(--dir)"></div> Direct ({dir_pct}%)</div>
        <div class="legend-item"><div class="dot" style="background:var(--oth)"></div> Other / Unassigned ({oth_pct}%)</div>
      </div>
    </div>

    <table>
      <thead><tr><th>Channel Group</th><th class="num">Sessions</th><th class="num">% of Total</th></tr></thead>
      <tbody>{breakdown_rows}</tbody>
    </table>
  </div>

  <!-- ── Section 2: Search Behaviour ── -->
  <div class="section">
    <div class="section-title">2 · Session Behaviour: Search vs Content-Only</div>
    <div class="cards">
      <div class="card total">
        <div class="label">Total Sessions</div>
        <div class="value">{total_sessions:,}</div>
      </div>
      <div class="card srch">
        <div class="label">Used Search</div>
        <div class="value">{srch_pct}%</div>
        <div class="sub">{search_sessions:,} sessions fired a <em>search</em> event</div>
      </div>
      <div class="card nosrch">
        <div class="label">Content-Only (no search)</div>
        <div class="value">{no_srch_pct}%</div>
        <div class="sub">{no_search_sessions:,} sessions — browsed without searching</div>
      </div>
    </div>

    <div class="bar-wrap">
      <div class="bar-label"><span>Search interaction breakdown</span><span>{total_sessions:,} total sessions</span></div>
      <div class="bar">
        <div class="seg srch" style="width:{srch_pct}%">{srch_pct}%</div>
        <div class="seg nosrch" style="width:{no_srch_pct}%">{no_srch_pct}%</div>
      </div>
      <div class="legend">
        <div class="legend-item"><div class="dot" style="background:var(--srch)"></div> Used site search ({srch_pct}%)</div>
        <div class="legend-item"><div class="dot" style="background:var(--nosrch)"></div> Content-only — no search ({no_srch_pct}%)</div>
      </div>
    </div>

    <p style="font-size:0.82rem;color:var(--muted);margin-top:-20px;margin-bottom:32px">
      ⓘ &nbsp;"Used Search" = sessions in which the GA4 <code>search</code> event fired at least once.
      If your site uses a custom search event name, update <code>SEARCH_EVENT_NAME</code> in <code>fetch_ga4.py</code>.
    </p>
  </div>

</div>
<footer>Data from Google Analytics 4 · Property {PROPERTY_ID} · {START_DATE} → {END_DATE}</footer>
</body>
</html>"""
    return html


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n📊  GA4 Dashboard Generator")
    print(f"    Property: {PROPERTY_ID}")
    print(f"    Date range: {START_DATE} → {END_DATE}\n")

    print("🔑  Authenticating…")
    creds = get_credentials()
    client = BetaAnalyticsDataClient(credentials=creds)
    print("    ✓ Authenticated\n")

    print("📡  Fetching channel group data…")
    channel_rows = fetch_channel_data(client)
    channel_data = categorise_channels(channel_rows)
    print(f"    ✓ {len(channel_rows)} channel groups · {channel_data['total']:,} total sessions\n")

    print("📡  Fetching search behaviour data…")
    search_sessions, no_search_sessions, total_sessions = fetch_search_data(client)
    print(f"    ✓ {search_sessions:,} search sessions / {total_sessions:,} total\n")

    print("🖊   Building dashboard…")
    html = build_html(channel_data, search_sessions, no_search_sessions, total_sessions)
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"    ✓ Saved to: {OUTPUT_FILE.resolve()}\n")

    print(f"✅  Done! Open dashboard.html in your browser.\n")


if __name__ == "__main__":
    main()
