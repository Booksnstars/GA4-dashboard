"""GA4 data fetching — shared by server.py."""

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric,
    FilterExpression, Filter, RunReportRequest,
    FilterExpressionList,
)

PROPERTIES = {
    "srm": "257995281",
    "sk":  "258026800",
    "us":  "264964195",
}

LOGIN_STATUS_VALUE = "true"   # value of customEvent:login_status that means logged in

CONTENT_URL_PATTERNS = [
    '/video/', '/foundations/', '/hnbk/', '/ency/', '/books/', '/cases/', '/skills/',
    '/book/', '/mono/', '/report/', '/chapter/', '/reference/',
    '/books-and-reference', '/methods-map', '/dict/', '/chpt/',
    '/referenceandbooks', '/business', '/videocollections',
    '/project-planner', '/which-stats-test',
]
ERROR_URL_PATTERNS = ['/error']  # matches /Error, /error/handleStatusCode, etc.
SEARCH_URL_PATTERNS = ['/search']  # kept for _contains_or filter; categorisation logic below

EXTERNAL_DISCOVERY_CHANNELS = {
    "Organic Search", "Organic Social", "Referral", "Organic Video",
    "Organic Shopping", "Display", "Paid Search", "Paid Social",
    "Paid Video", "Paid Other", "Affiliates", "Audio", "Cross-network",
    "Organic AI", "AI Search",
}
DIRECT_CHANNELS = {"Direct"}
EXCLUDED_CHANNELS = {"Unassigned"}


def _auth_filter():
    # Sessions where login_status = 'true' OR authentication_subscription starts with 'true'
    return FilterExpression(
        or_group=FilterExpressionList(expressions=[
            FilterExpression(filter=Filter(
                field_name="customEvent:login_status",
                string_filter=Filter.StringFilter(
                    value=LOGIN_STATUS_VALUE,
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )),
            FilterExpression(filter=Filter(
                field_name="customEvent:authentication_subscription",
                string_filter=Filter.StringFilter(
                    value="true",
                    match_type=Filter.StringFilter.MatchType.BEGINS_WITH,
                ),
            )),
        ])
    )


def _search_filter():
    return FilterExpression(
        or_group=FilterExpressionList(expressions=[
            FilterExpression(filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(
                    value="view_search_results",
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )),
            FilterExpression(filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(
                    value="search_within_content",
                    match_type=Filter.StringFilter.MatchType.EXACT,
                ),
            )),
        ])
    )


def _login_status_filter():
    """Auth filter using only customEvent:login_status — for properties that lack authentication_subscription."""
    return FilterExpression(filter=Filter(
        field_name="customEvent:login_status",
        string_filter=Filter.StringFilter(
            value=LOGIN_STATUS_VALUE,
            match_type=Filter.StringFilter.MatchType.EXACT,
        ),
    ))


def _us_search_filter():
    return FilterExpression(filter=Filter(
        field_name="eventName",
        string_filter=Filter.StringFilter(
            value="parasol_universal_search",
            match_type=Filter.StringFilter.MatchType.EXACT,
        ),
    ))


def _and(f1, f2):
    if f1 is None: return f2
    if f2 is None: return f1
    return FilterExpression(
        and_group=FilterExpressionList(expressions=[f1, f2])
    )


def _contains_or(field, patterns, case_sensitive=True):
    exprs = [FilterExpression(filter=Filter(
        field_name=field,
        string_filter=Filter.StringFilter(
            value=p,
            match_type=Filter.StringFilter.MatchType.CONTAINS,
            case_sensitive=case_sensitive,
        ),
    )) for p in patterns]
    return exprs[0] if len(exprs) == 1 else FilterExpression(or_group=FilterExpressionList(expressions=exprs))


def _event_exact(event_name):
    return FilterExpression(filter=Filter(
        field_name="eventName",
        string_filter=Filter.StringFilter(value=event_name, match_type=Filter.StringFilter.MatchType.EXACT),
    ))


def _categorise_landing(url):
    u = url.lower()
    path = u.split('?')[0].rstrip('/')   # path without query string or trailing slash

    # Error pages -- check before content so /error/* doesn't fall into other
    if any(p in path for p in ERROR_URL_PATTERNS):
        return 'error'

    # Content pages take priority
    if any(p in u for p in CONTENT_URL_PATTERNS):
        return 'content'

    # Search: /search/results (with or without query string) OR /search with a query string
    if '/search/results' in path or ('/search' in path and '?' in u):
        return 'search'

    # Portal/home: root domain or bare /search or /Search (no subpath, no query string)
    if path in ('', '/', '/home', '/index', '/search') or len(path) <= 1:
        return 'portal'

    return 'other'


def fetch_channel_data(client, property_id, start_date, end_date, auth_only=False,
                       auth_filter=None, base_filter=None):
    # base_filter: always-on filter applied before auth (e.g. scope to a specific event population)
    if auth_only:
        af = auth_filter if auth_filter is not None else _auth_filter()
    else:
        af = None
    dim_filter = _and(base_filter, af)
    resp = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name="sessionDefaultChannelGroup")],
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=dim_filter,
        limit=50,
    ))
    return [(r.dimension_values[0].value, int(r.metric_values[0].value))
            for r in resp.rows]


def fetch_search_data(client, property_id, start_date, end_date, auth_only=False,
                      srch_filter=None, content_patterns=None, auth_filter=None, base_filter=None):
    # srch_filter: FilterExpression for search events; defaults to SRM/SK standard events.
    # content_patterns: list of URL substrings for content detection; pass [] to skip content queries.
    # auth_filter: override the default two-dimension auth filter for properties that lack a dimension.
    # base_filter: always-on filter scoping the entire population (e.g. sessions with a specific event).
    if srch_filter is None:
        srch_filter = _search_filter()
    if content_patterns is None:
        content_patterns = CONTENT_URL_PATTERNS

    base = dict(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
    )
    if auth_only:
        auth_f = auth_filter if auth_filter is not None else _auth_filter()
    else:
        auth_f = None
    # Combine base_filter and auth into a single root filter applied to every query
    auth_f = _and(base_filter, auth_f)

    # Q1: total sessions
    total_resp = client.run_report(RunReportRequest(
        **base,
        metrics=[Metric(name="sessions")],
        dimension_filter=auth_f,
    ))
    total = int(total_resp.rows[0].metric_values[0].value) if total_resp.rows else 0

    # Q2: sessions with a search event
    srch_f    = _and(auth_f, srch_filter)
    srch_resp = client.run_report(RunReportRequest(
        **base,
        metrics=[Metric(name="sessions")],
        dimension_filter=srch_f,
    ))
    searched = int(srch_resp.rows[0].metric_values[0].value) if srch_resp.rows else 0

    if content_patterns:
        # Q3: sessions with any content page view
        content_f = _and(auth_f, _contains_or("pagePath", content_patterns, case_sensitive=False))
        cnt_resp  = client.run_report(RunReportRequest(
            **base,
            metrics=[Metric(name="sessions")],
            dimension_filter=content_f,
        ))
        sessions_with_content = int(cnt_resp.rows[0].metric_values[0].value) if cnt_resp.rows else 0

        # Q4: sessions with search event AND a content page view
        sc_f    = _and(srch_f, _contains_or("pagePath", content_patterns, case_sensitive=False))
        sc_resp = client.run_report(RunReportRequest(
            **base,
            metrics=[Metric(name="sessions")],
            dimension_filter=sc_f,
        ))
        searched_reached_content = int(sc_resp.rows[0].metric_values[0].value) if sc_resp.rows else 0

        # Q6: content page views where referrer was a search results page
        ref_f    = _and(auth_f, FilterExpression(filter=Filter(
            field_name="pageReferrer",
            string_filter=Filter.StringFilter(value="/search/results",
                                              match_type=Filter.StringFilter.MatchType.CONTAINS,
                                              case_sensitive=False),
        )))
        ref_resp = client.run_report(RunReportRequest(
            **base,
            metrics=[Metric(name="screenPageViews")],
            dimension_filter=ref_f,
        ))
        content_views_from_search = int(ref_resp.rows[0].metric_values[0].value) if ref_resp.rows else 0
    else:
        sessions_with_content = 0
        searched_reached_content = 0
        content_views_from_search = 0

    content_no_search = max(0, sessions_with_content - searched_reached_content)
    neither           = max(0, total - searched - content_no_search)

    print(f"  [S2 prop={property_id}] total={total:,}  searched={searched:,} ({_pct(searched, total):.1f}%)  "
          f"content_no_search={content_no_search:,}  neither={neither:,}  "
          f"sessions_with_content={sessions_with_content:,}  searched_reached_content={searched_reached_content:,}")

    # Q5: individual search events (uses the same filter as Q2)
    ev_resp = client.run_report(RunReportRequest(
        **base,
        metrics=[Metric(name="eventCount")],
        dimension_filter=srch_f,
    ))
    search_events = int(ev_resp.rows[0].metric_values[0].value) if ev_resp.rows else 0

    return {
        "total":                     total,
        "searched":                  searched,
        "content_no_search":         content_no_search,
        "neither":                   neither,
        "searched_reached_content":  searched_reached_content,
        "searched_no_content":       max(0, searched - searched_reached_content),
        "search_events":             search_events,
        "content_views_from_search": content_views_from_search,
    }


def categorise_channels(rows):
    external = direct = other = unassigned = 0
    breakdown = []
    for channel, sessions in rows:
        if channel in EXCLUDED_CHANNELS:
            unassigned += sessions
            continue
        breakdown.append({"channel": channel, "sessions": sessions})
        if channel in EXTERNAL_DISCOVERY_CHANNELS:
            external += sessions
        elif channel in DIRECT_CHANNELS:
            direct += sessions
        else:
            other += sessions
    total = external + direct + other
    return {
        "external": external, "direct": direct, "other": other, "total": total,
        "unassigned": unassigned,
        "breakdown": sorted(breakdown, key=lambda x: -x["sessions"]),
    }


def merge_channel_rows(rows_a, rows_b):
    counts = {}
    for channel, sessions in rows_a + rows_b:
        counts[channel] = counts.get(channel, 0) + sessions
    return list(counts.items())


def list_landing_pages_diagnostic(client, start_date, end_date):
    """Prints top 20 auth landing pages and top 20 landing pages classified as 'other'."""
    af = _auth_filter()
    for key, prop_id in PROPERTIES.items():
        resp = client.run_report(RunReportRequest(
            property=f"properties/{prop_id}",
            dimensions=[Dimension(name="landingPage")],
            metrics=[Metric(name="sessions")],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimension_filter=af,
            limit=100,
        ))
        rows = sorted(
            [(r.dimension_values[0].value, int(r.metric_values[0].value)) for r in resp.rows],
            key=lambda x: -x[1],
        )

        print(f"\n  [{key.upper()} - property {prop_id}] Top 20 auth landing pages:")
        for url, n in rows[:20]:
            cat = _categorise_landing(url)
            print(f"    {cat:<8}  {n:>8,}  {url}")

        others = [(url, n) for url, n in rows if _categorise_landing(url) == 'other']
        print(f"\n  [{key.upper()}] Top 20 'other' landing pages ({len(others)} total):")
        for url, n in others[:20]:
            print(f"             {n:>8,}  {url}")
    print()


def list_event_names(client, start_date, end_date):
    """Prints all event names found in both properties to the terminal."""
    for key, prop_id in PROPERTIES.items():
        resp = client.run_report(RunReportRequest(
            property=f"properties/{prop_id}",
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=200,
        ))
        events = sorted(
            [(r.dimension_values[0].value, int(r.metric_values[0].value)) for r in resp.rows],
            key=lambda x: -x[1],
        )
        print(f"\n  [{key.upper()} - property {prop_id}]")
        for name, count in events:
            print(f"    {name:<45} {count:>12,}")
    print()


AUTH_KEYWORDS = {"login", "auth", "sign", "user"}

def list_auth_events(client, start_date, end_date):
    """Prints event names matching auth-related keywords from both properties."""
    print(f"\n  Auth-related event names ({start_date} -> {end_date}):")
    for key, prop_id in PROPERTIES.items():
        resp = client.run_report(RunReportRequest(
            property=f"properties/{prop_id}",
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            limit=200,
        ))
        matches = sorted(
            [
                (r.dimension_values[0].value, int(r.metric_values[0].value))
                for r in resp.rows
                if any(kw in r.dimension_values[0].value.lower() for kw in AUTH_KEYWORDS)
            ],
            key=lambda x: -x[1],
        )
        print(f"\n  [{key.upper()} - property {prop_id}]")
        if matches:
            for name, count in matches:
                print(f"    {name:<45} {count:>12,}")
        else:
            print("    (no matches)")
    print()


def list_custom_dimension_values(client, start_date, end_date):
    """Prints distinct values for login_status and authentication_subscription in both properties."""
    dims = [
        ("customEvent:login_status",              "login_status"),
        ("customEvent:authentication_subscription","authentication_subscription"),
    ]
    for key, prop_id in PROPERTIES.items():
        print(f"\n  [{key.upper()} - property {prop_id}]")
        for api_name, label in dims:
            try:
                resp = client.run_report(RunReportRequest(
                    property=f"properties/{prop_id}",
                    dimensions=[Dimension(name=api_name)],
                    metrics=[Metric(name="sessions")],
                    date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                    limit=50,
                ))
                values = sorted(
                    [(r.dimension_values[0].value, int(r.metric_values[0].value)) for r in resp.rows],
                    key=lambda x: -x[1],
                )
                print(f"    {label}:")
                if values:
                    for val, count in values:
                        print(f"      {val!r:<35} {count:>12,} sessions")
                else:
                    print("      (no data)")
            except Exception as e:
                print(f"      (error: {e})")
    print()


def _pct(n, d):
    return round(n / d * 100, 1) if d else 0


def fetch_funnel_data(client, property_id, start_date, end_date, auth_only=False):
    af   = _auth_filter() if auth_only else None
    base = dict(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
    )

    # Direct session count (no dimension) -- same query as fetch_search_data Q1,
    # so Section 3 base matches Section 2 exactly.
    base_resp  = client.run_report(RunReportRequest(
        **base,
        metrics=[Metric(name="sessions")],
        dimension_filter=af,
    ))
    base_total = int(base_resp.rows[0].metric_values[0].value) if base_resp.rows else 0

    # Q1: sessions by landing page -> entry point breakdown (top 5,000 URLs per property).
    # Sessions beyond the 5,000th row are added to 'other' via the uncategorised remainder
    # so the five buckets always sum to base_total.
    lp_resp = client.run_report(RunReportRequest(
        **base,
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="sessions"), Metric(name="engagedSessions")],
        dimension_filter=af,
        limit=5000,
    ))
    entry_n   = {'content': 0, 'search': 0, 'portal': 0, 'error': 0, 'other': 0}
    entry_eng = {'content': 0, 'search': 0, 'portal': 0, 'error': 0, 'other': 0}
    for row in lp_resp.rows:
        cat = _categorise_landing(row.dimension_values[0].value)
        entry_n[cat]   += int(row.metric_values[0].value)
        entry_eng[cat] += int(row.metric_values[1].value)
    dim_total = sum(entry_n.values())
    # Sessions not covered by the top-5,000 rows are added to 'other' so the five
    # buckets always total base_total (matching Section 2's base).
    uncategorised = max(0, base_total - dim_total)
    entry_n['other'] += uncategorised
    total = base_total or dim_total

    print(f"  [S3 prop={property_id}] base_total={base_total:,}  "
          f"dim_total={dim_total:,}  lp_rows={len(lp_resp.rows):,}  uncategorised={uncategorised:,}  "
          f"search_landers={entry_n['search']:,}  ({_pct(entry_n['search'], total):.1f}%)")

    # Q2: content landers who searched (case-insensitive so mixed-case CQ URLs match)
    c_filter  = _and(af, _contains_or("landingPage", CONTENT_URL_PATTERNS, case_sensitive=False))
    cs_filter = _and(c_filter, _search_filter())
    r2 = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=cs_filter,
    ))
    c_searched = int(r2.rows[0].metric_values[0].value) if r2.rows else 0

    # Q3: search landers who clicked through to a content page
    s_filter  = _and(af, _contains_or("landingPage", SEARCH_URL_PATTERNS))
    sc_filter = _and(s_filter, _event_exact("search_content_clickthrough"))
    r3 = client.run_report(RunReportRequest(
        property=f"properties/{property_id}",
        metrics=[Metric(name="sessions")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=sc_filter,
    ))
    s_clicked = int(r3.rows[0].metric_values[0].value) if r3.rows else 0

    ct = entry_n['content'];   ce = entry_eng['content']
    st = entry_n['search'];    se = entry_eng['search']
    c_exit  = max(0, ct - ce);  c_other = max(0, ce - c_searched)
    s_exit  = max(0, st - se);  s_other = max(0, se - s_clicked)

    return {
        "base_total": base_total,
        "entry": {
            "total":   total,
            "content": {"n": ct,                "pct": _pct(ct,                total)},
            "search":  {"n": st,                "pct": _pct(st,                total)},
            "portal":  {"n": entry_n['portal'], "pct": _pct(entry_n['portal'], total)},
            "error":   {"n": entry_n['error'],  "pct": _pct(entry_n['error'],  total)},
            "other":   {"n": entry_n['other'],  "pct": _pct(entry_n['other'],  total)},
        },
        "content_landers": {
            "total":         ct,
            "exited":        {"n": c_exit,      "pct": _pct(c_exit,      ct)},
            "searched":      {"n": c_searched,  "pct": _pct(c_searched,  ct)},
            "other_engaged": {"n": c_other,     "pct": _pct(c_other,     ct)},
        },
        "search_landers": {
            "total":           st,
            "exited":          {"n": s_exit,    "pct": _pct(s_exit,    st)},
            "clicked_content": {"n": s_clicked, "pct": _pct(s_clicked, st)},
            "other_engaged":   {"n": s_other,   "pct": _pct(s_other,   st)},
        },
    }


def merge_funnel(f1, f2):
    def add_node(a, b, total):
        n = a["n"] + b["n"]
        return {"n": n, "pct": _pct(n, total)}

    t  = f1["entry"]["total"] + f2["entry"]["total"]
    ct = f1["content_landers"]["total"] + f2["content_landers"]["total"]
    st = f1["search_landers"]["total"]  + f2["search_landers"]["total"]

    return {
        "base_total": f1.get("base_total", 0) + f2.get("base_total", 0),
        "entry": {
            "total":   t,
            "content": add_node(f1["entry"]["content"], f2["entry"]["content"], t),
            "search":  add_node(f1["entry"]["search"],  f2["entry"]["search"],  t),
            "portal":  add_node(f1["entry"]["portal"],  f2["entry"]["portal"],  t),
            "error":   add_node(f1["entry"]["error"],   f2["entry"]["error"],   t),
            "other":   add_node(f1["entry"]["other"],   f2["entry"]["other"],   t),
        },
        "content_landers": {
            "total":         ct,
            "exited":        add_node(f1["content_landers"]["exited"],        f2["content_landers"]["exited"],        ct),
            "searched":      add_node(f1["content_landers"]["searched"],      f2["content_landers"]["searched"],      ct),
            "other_engaged": add_node(f1["content_landers"]["other_engaged"], f2["content_landers"]["other_engaged"], ct),
        },
        "search_landers": {
            "total":           st,
            "exited":          add_node(f1["search_landers"]["exited"],          f2["search_landers"]["exited"],          st),
            "clicked_content": add_node(f1["search_landers"]["clicked_content"], f2["search_landers"]["clicked_content"], st),
            "other_engaged":   add_node(f1["search_landers"]["other_engaged"],   f2["search_landers"]["other_engaged"],   st),
        },
    }


def fetch_all(client, start_date, end_date, auth_only=False):
    srm_ch = fetch_channel_data(client, PROPERTIES["srm"], start_date, end_date, auth_only)
    sk_ch  = fetch_channel_data(client, PROPERTIES["sk"],  start_date, end_date, auth_only)
    us_ch  = fetch_channel_data(client, PROPERTIES["us"],  start_date, end_date, auth_only,
                               auth_filter=_login_status_filter(), base_filter=_us_search_filter())

    srm_s = fetch_search_data(client, PROPERTIES["srm"], start_date, end_date, auth_only)
    sk_s  = fetch_search_data(client, PROPERTIES["sk"],  start_date, end_date, auth_only)
    # Universal Search uses its own event and has no content URL patterns yet
    us_s  = fetch_search_data(client, PROPERTIES["us"],  start_date, end_date, auth_only,
                              srch_filter=_us_search_filter(), content_patterns=[],
                              auth_filter=_login_status_filter(), base_filter=_us_search_filter())

    combined_ch = merge_channel_rows(srm_ch, sk_ch)

    def _sum(key):
        return srm_s[key] + sk_s[key]

    return {
        "srm": {
            "channels": categorise_channels(srm_ch),
            "search":   srm_s,
        },
        "sk": {
            "channels": categorise_channels(sk_ch),
            "search":   sk_s,
        },
        "us": {
            "channels": categorise_channels(us_ch),
            "search":   us_s,
        },
        "combined": {
            "channels": categorise_channels(combined_ch),
            "search": {
                "total":                     _sum("total"),
                "searched":                  _sum("searched"),
                "content_no_search":         _sum("content_no_search"),
                "neither":                   _sum("neither"),
                "searched_reached_content":  _sum("searched_reached_content"),
                "searched_no_content":       _sum("searched_no_content"),
                "search_events":             _sum("search_events"),
                "content_views_from_search": _sum("content_views_from_search"),
            },
        },
    }
