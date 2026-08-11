GA4 Dashboard Generator — Setup Guide
======================================

STEP 1: Install Python
----------------------
Download from https://www.python.org/downloads/ (3.9 or later).
During install, tick "Add Python to PATH".

Verify: open a new Command Prompt and run:
    python --version


STEP 2: Install dependencies
-----------------------------
Open Command Prompt in this folder (ga4_dashboard), then run:

    pip install -r requirements.txt


STEP 3: Create a Google Cloud OAuth credential
-----------------------------------------------
You need a client_secret.json file. Do this once:

  a) Go to https://console.cloud.google.com/
  b) Create a project (or use an existing one), e.g. "GA4 Dashboard"
  c) Enable the API:
       APIs & Services → Enable APIs → search "Google Analytics Data API" → Enable
  d) Create credentials:
       APIs & Services → Credentials → + Create Credentials → OAuth client ID
       - Application type: Desktop app
       - Name: GA4 Dashboard (anything)
       → Click Create
  e) Download the JSON file → rename it to  client_secret.json
  f) Copy client_secret.json into this folder (next to fetch_ga4.py)

  ⚠️  If you see "This app isn't verified":
       - Click "Advanced" → "Go to [app] (unsafe)" — safe to do for your own script
       OR add your email as a Test User:
         APIs & Services → OAuth consent screen → Test users → + Add users


STEP 4: Run the script
-----------------------
    python fetch_ga4.py

A browser window will open asking you to sign in with your Google account
and grant read-only access to Google Analytics. Accept.

The script saves a token.json file so you won't be asked again.


STEP 5: View the dashboard
---------------------------
Open the generated file in any browser:
    ga4_dashboard\dashboard.html


NOTES
-----
- Date range defaults to the last 90 days. Change START_DATE / END_DATE in fetch_ga4.py.
- The "Used Search" metric counts sessions where GA4's built-in `search` event fired.
  If your site uses a custom event name (e.g. "site_search"), update the string
  "search" in the fetch_search_data() function.
- Re-run any time to refresh the dashboard with the latest data.
- token.json contains your OAuth token — do not share or commit it.
- client_secret.json contains your app credentials — do not share or commit it.
