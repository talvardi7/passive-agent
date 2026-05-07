"""
Passive Income Agent — Full Autonomous System
Every Monday at 09:00 UTC:
1. Posts to DEV.to (AI-generated article)
2. Sends newsletter via Beehiiv
3. Pulls stats from Gumroad + DEV.to + Beehiiv
4. Emails a full report to talvardi7@gmail.com
Zero involvement required.
"""

import os, sys, re, html, json, time, datetime, smtplib, requests, schedule
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from anthropic import Anthropic

# Force unbuffered output so Render logs show everything in real time
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)

# ── CONFIG ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
GUMROAD_TOKEN       = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
GUMROAD_PRODUCT_ID  = os.environ.get("GUMROAD_PRODUCT_ID", "nhltvo")
GUMROAD_PRODUCT_URL = os.environ.get("GUMROAD_PRODUCT_URL", f"https://gumroad.com/l/nhltvo")
DEVTO_API_KEY       = os.environ.get("DEVTO_API_KEY", "")
BEEHIIV_API_KEY     = os.environ.get("BEEHIIV_API_KEY", "")
BEEHIIV_PUB_ID      = os.environ.get("BEEHIIV_PUBLICATION_ID", "")
REPORT_EMAIL        = os.environ.get("REPORT_EMAIL", "talvardi7@gmail.com")
SMTP_EMAIL          = os.environ.get("SMTP_EMAIL", "talvardi7@gmail.com")
SMTP_PASSWORD       = os.environ.get("SMTP_APP_PASSWORD", "")
HN_USERNAME         = os.environ.get("HN_USERNAME", "")
HN_PASSWORD         = os.environ.get("HN_PASSWORD", "")

HAS_DEVTO      = DEVTO_API_KEY not in ("", "FILL_IN_LATER")
HAS_NEWSLETTER = BEEHIIV_API_KEY not in ("", "FILL_IN_LATER")
HAS_EMAIL      = SMTP_PASSWORD not in ("", "FILL_IN_LATER")
HAS_HN         = HN_USERNAME not in ("", "FILL_IN_LATER") and HN_PASSWORD not in ("", "FILL_IN_LATER")

client = Anthropic(api_key=ANTHROPIC_API_KEY)
STATE_FILE = "state.json"

DEVTO_TAGS_ROTATION = [
    ["ai", "productivity", "career", "engineering"],
    ["programming", "ai", "tutorial", "career"],
    ["webdev", "ai", "productivity", "beginners"],
    ["devops", "ai", "engineering", "tools"],
]

ANGLES = ["tutorial", "opinion", "case_study", "tip_list", "story"]
PUBLISH_DAYS = {0: "monday", 2: "wednesday", 4: "friday"}

# ── STATE ────────────────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"total_sales_baseline": 0, "week_number": 0, "posts_made": [], "weekly_sales": []}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def pick_angle(recent_angles):
    forbidden = set(recent_angles[-2:])
    start = len(recent_angles) % len(ANGLES)
    for i in range(len(ANGLES)):
        candidate = ANGLES[(start + i) % len(ANGLES)]
        if candidate not in forbidden:
            return candidate
    return ANGLES[0]

# ── STATS COLLECTION ─────────────────────────────────────────────────────────

def get_gumroad_stats():
    try:
        r = requests.get(
            f"https://api.gumroad.com/v2/products/{GUMROAD_PRODUCT_ID}",
            headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"},
            timeout=10
        )
        r.raise_for_status()
        p = r.json()["product"]
        return {
            "sales_count": p.get("sales_count", 0),
            "revenue": p.get("sales_usd_cents", 0) / 100,
            "views": p.get("views_count", 0),
            "ok": True
        }
    except Exception as e:
        print(f"  Gumroad stats error: {e}")
        return {"sales_count": 0, "revenue": 0, "views": 0, "ok": False}

def get_devto_stats():
    try:
        r = requests.get(
            "https://dev.to/api/articles/me",
            headers={"api-key": DEVTO_API_KEY},
            timeout=10
        )
        r.raise_for_status()
        articles = r.json()
        total_views = sum(a.get("page_views_count", 0) for a in articles)
        total_reactions = sum(a.get("public_reactions_count", 0) for a in articles)
        # Get follower count
        me = requests.get("https://dev.to/api/users/me",
            headers={"api-key": DEVTO_API_KEY}, timeout=10).json()
        return {
            "articles": len(articles),
            "total_views": total_views,
            "total_reactions": total_reactions,
            "followers": me.get("followers_count", 0),
            "ok": True
        }
    except Exception as e:
        print(f"  DEV.to stats error: {e}")
        return {"articles": 0, "total_views": 0, "total_reactions": 0, "followers": 0, "ok": False}

def get_beehiiv_stats():
    try:
        r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/subscriptions",
            headers={"Authorization": f"Bearer {BEEHIIV_API_KEY}"},
            params={"limit": 1},
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
        total_subs = data.get("total_results", 0)

        # Get latest post stats
        posts_r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts",
            headers={"Authorization": f"Bearer {BEEHIIV_API_KEY}"},
            params={"limit": 1, "status": "confirmed"},
            timeout=10
        )
        posts_r.raise_for_status()
        posts = posts_r.json().get("data", [])
        latest = posts[0] if posts else {}
        open_rate = latest.get("stats", {}).get("open_rate", 0)

        return {
            "subscribers": total_subs,
            "open_rate": round(open_rate * 100, 1) if open_rate else 0,
            "issues_sent": len(posts_r.json().get("data", [])),
            "ok": True
        }
    except Exception as e:
        print(f"  Beehiiv stats error: {e}")
        return {"subscribers": 0, "open_rate": 0, "issues_sent": 0, "ok": False}

# ── CONTENT GENERATION ───────────────────────────────────────────────────────

def extract_json(text):
    # Pull a JSON object out of model output that may be wrapped in markdown
    # fences (```json ... ```), have leading/trailing prose, or both.
    # Raises json.JSONDecodeError on failure with the offending text included
    # via the original exception (caller logs it).
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline != -1 else text[3:]
        text = text.rstrip()
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if not (text.startswith("{") or text.startswith("[")):
        first_brace = text.find("{")
        first_bracket = text.find("[")
        candidates = [i for i in (first_brace, first_bracket) if i != -1]
        if candidates:
            start = min(candidates)
            end = max(text.rfind("}"), text.rfind("]"))
            if end > start:
                text = text[start:end + 1]
    return json.loads(text, strict=False)

def generate_content(week_number, format_key, state):
    posts_made = state.get("posts_made", [])
    previous_titles = [p.get("title", p.get("subject", "")) for p in posts_made[-20:]]
    recent_angles = state.get("recent_angles", [])
    angle = pick_angle(recent_angles)

    tags = DEVTO_TAGS_ROTATION[len(posts_made) % len(DEVTO_TAGS_ROTATION)]

    weekly_titles = [
        p.get("title", "") for p in posts_made
        if p.get("week") == week_number and p.get("platform") == "devto"
    ]

    angle_hints = {
        "tutorial":   "step-by-step walkthrough with copy-paste blocks",
        "opinion":    "stake out a clear take, defend it with reasoning",
        "case_study": "tell a specific real example with numbers/outcomes",
        "tip_list":   "numbered list, each item self-contained and concrete",
        "story":      "narrative arc — situation, problem, what you tried, what worked",
    }
    angle_hint = angle_hints[angle]

    system = (
        "You are a senior software engineer writing for a technical audience. "
        "Write posts that are genuinely useful — concrete, specific, actionable. "
        "Never sound like marketing. Mention the product naturally at the end only. "
        "Vary topic and angle. "
        "CRITICAL OUTPUT FORMAT: Respond with a single raw JSON object and "
        "nothing else. The very first character must be `{` and the very last "
        "character must be `}`. Do NOT wrap the JSON in markdown code fences "
        "(no ```json, no ```). Do NOT include any prose, preamble, or "
        "explanation before or after the JSON. Inside string values, escape "
        "newlines as \\n."
    )

    prompts = {
        "devto_long": f"""Week {week_number} — Monday long-form DEV.to article on using AI for engineering productivity.
Angle: {angle} ({angle_hint}).
Product to mention at end: {GUMROAD_PRODUCT_URL}
Tags: {tags}
Do NOT repeat or rephrase any of these previous titles: {previous_titles}
Rules: title specific and useful (e.g. "The 5 AI prompts I use before every code review"),
body 500-800 words markdown, include 1-2 concrete copy-paste prompt examples,
end with one soft sentence mentioning "a prompt playbook I put together" with the link,
tone: practitioner to peers.
Return JSON: {{"title": "...", "body_markdown": "...", "tags": {json.dumps(tags)}}}""",

        "devto_medium": f"""Week {week_number} — Wednesday mid-length DEV.to piece. Different topic and angle from Monday.
Angle: {angle} ({angle_hint}).
Product: {GUMROAD_PRODUCT_URL}
Tags: {tags}
Do NOT repeat or rephrase any of these recent titles: {previous_titles}
Rules: title sharp and specific, body 300-500 words markdown, one concrete prompt or workflow example,
soft mention of the playbook link at the end. Tone: peer-to-peer, no fluff.
Return JSON: {{"title": "...", "body_markdown": "...", "tags": {json.dumps(tags)}}}""",

        "devto_roundup": f"""Week {week_number} — Friday weekly roundup DEV.to post.
This week you've already published these articles: {weekly_titles or '[none yet]'}
Angle: {angle} ({angle_hint}).
Product: {GUMROAD_PRODUCT_URL}
Tags: {tags}
Avoid these recent titles: {previous_titles}
Rules: title like "What I learned about AI workflows this week" or "3 things that worked, 1 that didn't",
body 250-400 words markdown that ties together the week's themes (reference your own articles by topic, not by linking),
soft playbook mention at the end. Casual reflective tone.
Return JSON: {{"title": "...", "body_markdown": "...", "tags": {json.dumps(tags)}}}""",

        "newsletter": f"""Week {week_number}. Newsletter issue for engineers interested in AI productivity.
Angle: {angle} ({angle_hint}).
Product link: {GUMROAD_PRODUCT_URL}
Avoid these recent subjects: {previous_titles}
Rules: subject specific and under 50 chars, 400-600 words HTML,
one concrete framework, 2-3 copy-paste prompt examples, soft product mention at end.
Return JSON: {{"subject": "...", "body_html": "..."}}""",

        "ih_draft": f"""Week {week_number} — Indie Hackers post draft (the user will paste this manually).
Voice: builder talking to other builders. First-person, conversational, specific numbers, no hype.
Angle: {angle} ({angle_hint}).
Product: {GUMROAD_PRODUCT_URL}
Avoid these recent titles: {previous_titles}
Rules: title under 70 chars (something like "Week N: what I shipped + what I'm learning"),
body 200-400 words markdown about something concrete you built/tried/learned this week,
end with a soft one-line mention of the playbook link only.
Return JSON: {{"title": "...", "body_markdown": "..."}}"""
    }

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": prompts[format_key]}]
    )
    raw_text = response.content[0].text
    try:
        out = extract_json(raw_text)
    except json.JSONDecodeError as e:
        preview = raw_text[:500].replace("\n", "\\n")
        raise ValueError(f"Model returned non-JSON ({e}). First 500 chars: {preview!r}") from e
    out["_angle"] = angle
    return out

# ── POSTING ──────────────────────────────────────────────────────────────────

def post_to_devto(content):
    r = requests.post(
        "https://dev.to/api/articles",
        headers={"api-key": DEVTO_API_KEY, "Content-Type": "application/json"},
        json={"article": {
            "title": content["title"],
            "body_markdown": content["body_markdown"],
            "published": True,
            "tags": content["tags"],
        }},
        timeout=15
    )
    r.raise_for_status()
    return r.json()

def post_newsletter(content):
    r = requests.post(
        f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts",
        headers={"Authorization": f"Bearer {BEEHIIV_API_KEY}", "Content-Type": "application/json"},
        json={
            "subject": content["subject"],
            "content": {"free": {"web": content["body_html"], "email": content["body_html"]}},
            "status": "confirmed",
            "send_at": int(time.time()) + 300,
        },
        timeout=15
    )
    r.raise_for_status()
    return r.json()

def post_to_hackernews(title, url):
    # HN has no submission API — log into news.ycombinator.com, scrape the
    # form's hidden fnid token, then submit via /r. Returns {"hn_url": "..."}
    # pointing at the user's submissions page.
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; PassiveAgent/1.0)"})

    login = session.post(
        "https://news.ycombinator.com/login",
        data={"acct": HN_USERNAME, "pw": HN_PASSWORD, "goto": "news"},
        timeout=15,
    )
    login.raise_for_status()
    if "Bad login" in login.text:
        raise RuntimeError("HN login failed (bad username or password)")

    submit_page = session.get("https://news.ycombinator.com/submit", timeout=15)
    submit_page.raise_for_status()
    if 'name="fnid"' not in submit_page.text:
        raise RuntimeError("HN submit form unavailable (account may be flagged or rate limited)")
    fnid = re.search(r'name="fnid"\s+value="([^"]+)"', submit_page.text).group(1)

    r = session.post(
        "https://news.ycombinator.com/r",
        data={
            "fnid": fnid,
            "fnop": "submit-page",
            "title": title[:80],
            "url": url,
            "text": "",
        },
        timeout=15,
        allow_redirects=False,
    )
    if r.status_code not in (200, 302):
        raise RuntimeError(f"HN submit failed with status {r.status_code}")
    return {"hn_url": f"https://news.ycombinator.com/submitted?id={HN_USERNAME}"}

# ── EMAIL REPORT ─────────────────────────────────────────────────────────────

def send_report(state, gumroad, devto, beehiiv, sales_baseline, results, articles=None, newsletter_posts=None, weekday=None):
    today = datetime.date.today()
    if weekday is None:
        weekday = today.weekday()
    is_monday = weekday == 0
    is_publish_day = weekday in PUBLISH_DAYS
    week = state["week_number"]
    new_sales = gumroad["sales_count"] - sales_baseline
    new_revenue = new_sales * 19
    total_rev = gumroad["revenue"]
    monthly_run_rate = (total_rev / max(week, 1)) * 4

    def pct_bar(current, goal, color):
        pct = min(100, round((current / goal) * 100)) if goal else 0
        filled = int(pct / 5)
        empty = 20 - filled
        bar = f'<span style="color:{color}">{"█" * filled}</span><span style="color:#E2E8F0">{"█" * empty}</span>'
        return bar, pct

    bar1, p1 = pct_bar(total_rev, 76, "#EF9F27")
    bar3, p3 = pct_bar(monthly_run_rate, 500, "#378ADD")
    bar6, p6 = pct_bar(monthly_run_rate, 2000, "#1D9E75")

    # Build articles section
    articles_html = ""
    if articles:
        rows = ""
        for a in articles[:10]:
            rows += f"""
            <tr>
              <td style="padding:10px 0;border-bottom:1px solid #F4F6FA;">
                <a href="{a['url']}" style="color:#0F1117;font-weight:500;text-decoration:none;font-size:13px">{a['title']}</a>
                <div style="font-size:11px;color:#9CA3AF;margin-top:2px">{a['published']} · {a['views']:,} views · {a['reactions']} reactions</div>
              </td>
              <td style="padding:10px 0;border-bottom:1px solid #F4F6FA;text-align:right;vertical-align:top">
                <a href="{a['url']}" style="font-size:11px;color:#378ADD;text-decoration:none">View ↗</a>
              </td>
            </tr>"""
        articles_html = f"""
    <div class="card">
      <p class="section-title">DEV.to articles ({len(articles)} live)</p>
      <table style="width:100%;border-collapse:collapse">{rows}</table>
      <a href="https://dev.to/dashboard" style="font-size:12px;color:#378ADD;text-decoration:none;display:block;margin-top:12px">Open DEV.to dashboard ↗</a>
    </div>"""

    # Build newsletter section
    newsletter_html = ""
    if newsletter_posts:
        rows = ""
        for p in newsletter_posts[:5]:
            rows += f"""
            <tr>
              <td style="padding:10px 0;border-bottom:1px solid #F4F6FA;">
                <a href="{p['url']}" style="color:#0F1117;font-weight:500;text-decoration:none;font-size:13px">{p['subject']}</a>
                <div style="font-size:11px;color:#9CA3AF;margin-top:2px">{p['sent']} · {p['open_rate']}% open rate</div>
              </td>
              <td style="padding:10px 0;border-bottom:1px solid #F4F6FA;text-align:right;vertical-align:top">
                <a href="{p['url']}" style="font-size:11px;color:#378ADD;text-decoration:none">View ↗</a>
              </td>
            </tr>"""
        newsletter_html = f"""
    <div class="card">
      <p class="section-title">Newsletter issues ({len(newsletter_posts)} sent)</p>
      <table style="width:100%;border-collapse:collapse">{rows}</table>
      <a href="https://app.beehiiv.com" style="font-size:12px;color:#378ADD;text-decoration:none;display:block;margin-top:12px">Open Beehiiv dashboard ↗</a>
    </div>"""

    # Published today section — render whenever results contain a published item.
    # (Decoupled from is_publish_day so the Thursday make-up post still surfaces.)
    published_today_html = ""
    if results:
        items = ""
        if results.get("devto"):
            r = results["devto"]
            label = {"devto_long": "DEV.to (long-form)", "devto_medium": "DEV.to (mid-length)", "devto_roundup": "DEV.to (weekly roundup)"}.get(r.get("format", ""), "DEV.to")
            link = f'<a href="{r["url"]}" style="color:#378ADD;text-decoration:none">View article ↗</a>' if r.get("url") else ""
            items += f'<div class="action-row"><span>{r["status"]}</span><span>{label}: <b>{r["title"]}</b> {link}</span></div>'
        if results.get("hn"):
            r = results["hn"]
            link = f'<a href="{r["url"]}" style="color:#378ADD;text-decoration:none">View on HN ↗</a>' if r.get("url") else ""
            items += f'<div class="action-row"><span>{r["status"]}</span><span>Hacker News: <b>{r["title"]}</b> {link}</span></div>'
        if results.get("newsletter"):
            r = results["newsletter"]
            items += f'<div class="action-row"><span>{r["status"]}</span><span>Newsletter: <b>{r["subject"]}</b></span></div>'
        if items:
            published_today_html = f"""
    <div class="card" style="border-left:3px solid #1D9E75">
      <p class="section-title">Published today</p>
      {items}
    </div>"""

    # Indie Hackers draft (Mondays only — paste-ready for the user)
    ih_draft_html = ""
    if is_monday and results.get("ih_draft") and results["ih_draft"].get("body"):
        d = results["ih_draft"]
        body_escaped = html.escape(d["body"])
        title_escaped = html.escape(d["title"])
        ih_draft_html = f"""
    <div class="card" style="border-left:3px solid #EF9F27">
      <p class="section-title">Indie Hackers draft (paste manually — 30 sec)</p>
      <p style="font-size:14px;font-weight:500;margin:0 0 12px;color:#0F1117">{title_escaped}</p>
      <pre style="background:#F4F6FA;padding:14px;border-radius:6px;font-family:ui-monospace,Menlo,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;color:#0F1117;margin:0">{body_escaped}</pre>
      <a href="https://www.indiehackers.com/post" style="font-size:12px;color:#378ADD;text-decoration:none;display:block;margin-top:12px">Open Indie Hackers ↗</a>
    </div>"""

    day_name = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}[weekday]
    published_anything = bool(published_today_html)
    day_label = f"{day_name} — Week {week}" if published_anything else str(today)
    subject_prefix = "🟢 New content published · " if published_anything else ""

    email_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F4F6FA; margin: 0; padding: 24px; }}
  .card {{ background: white; border-radius: 12px; padding: 24px; margin-bottom: 16px; border: 1px solid #E2E8F0; }}
  .header {{ background: #0F1117; border-radius: 12px; padding: 28px; margin-bottom: 16px; }}
  h1 {{ color: white; margin: 0 0 6px; font-size: 22px; font-weight: 500; }}
  .sub {{ color: #6B7280; font-size: 13px; margin: 0; }}
  .metric-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
  .metric {{ background: #F4F6FA; border-radius: 8px; padding: 14px; }}
  .metric-label {{ font-size: 11px; color: #6B7280; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; }}
  .metric-value {{ font-size: 24px; font-weight: 500; color: #0F1117; }}
  .metric-sub {{ font-size: 11px; color: #9CA3AF; margin-top: 2px; }}
  .section-title {{ font-size: 11px; font-weight: 500; color: #6B7280; text-transform: uppercase; letter-spacing: 0.06em; margin: 0 0 14px; }}
  .goal-row {{ margin-bottom: 14px; }}
  .goal-label {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }}
  .action-row {{ display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-bottom: 1px solid #F4F6FA; font-size: 13px; }}
  .action-row:last-child {{ border-bottom: none; }}
  .footer {{ font-size: 11px; color: #9CA3AF; text-align: center; margin-top: 24px; }}
</style></head>
<body>
  <div class="header">
    <h1>Daily Report — {day_label}</h1>
    <p class="sub">{today} · Automated by your passive income agent</p>
  </div>

  {published_today_html}
  {ih_draft_html}

  <div class="card">
    <p class="section-title">Today's numbers</p>
    <div class="metric-grid">
      <div class="metric">
        <div class="metric-label">New sales today</div>
        <div class="metric-value" style="color:{'#1D9E75' if new_sales > 0 else '#0F1117'}">{new_sales}</div>
        <div class="metric-sub">${new_revenue:.0f} earned today</div>
      </div>
      <div class="metric">
        <div class="metric-label">Total revenue</div>
        <div class="metric-value">$<span>{total_rev:.0f}</span></div>
        <div class="metric-sub">{gumroad['sales_count']} total sales</div>
      </div>
      <div class="metric">
        <div class="metric-label">Gumroad views</div>
        <div class="metric-value">{gumroad['views']:,}</div>
        <div class="metric-sub"><a href="https://app.gumroad.com/dashboard" style="color:#378ADD;text-decoration:none">Dashboard ↗</a></div>
      </div>
    </div>
  </div>

  <div class="card">
    <p class="section-title">Audience</p>
    <div class="metric-grid">
      <div class="metric">
        <div class="metric-label">DEV.to views</div>
        <div class="metric-value">{devto['total_views']:,}</div>
        <div class="metric-sub">{devto['articles']} articles · {devto['followers']} followers</div>
      </div>
      <div class="metric">
        <div class="metric-label">Newsletter subs</div>
        <div class="metric-value">{beehiiv['subscribers']:,}</div>
        <div class="metric-sub">{beehiiv['open_rate']}% open rate</div>
      </div>
      <div class="metric">
        <div class="metric-label">DEV.to reactions</div>
        <div class="metric-value">{devto['total_reactions']:,}</div>
        <div class="metric-sub">across all articles</div>
      </div>
    </div>
  </div>

  <div class="card">
    <p class="section-title">Goal progress</p>
    <div class="goal-row">
      <div class="goal-label"><span>Month 1 target: $76</span><span style="color:#EF9F27">{p1}%</span></div>
      <div style="font-family:monospace;font-size:13px">{bar1}</div>
    </div>
    <div class="goal-row">
      <div class="goal-label"><span>Month 3 target: $500/mo</span><span style="color:#378ADD">{p3}%</span></div>
      <div style="font-family:monospace;font-size:13px">{bar3}</div>
    </div>
    <div class="goal-row">
      <div class="goal-label"><span>Month 6 target: $2,000/mo</span><span style="color:#1D9E75">{p6}%</span></div>
      <div style="font-family:monospace;font-size:13px">{bar6}</div>
    </div>
  </div>

  {articles_html}
  {newsletter_html}

  <p class="footer">Next report tomorrow at 09:00 UTC · Nothing for you to do · talvardi7@gmail.com</p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{subject_prefix}${total_rev:.0f} total · {gumroad['sales_count']} sales · {devto['total_views']:,} views — {today}"
    msg["From"] = f"Passive Agent <{SMTP_EMAIL}>"
    msg["To"] = REPORT_EMAIL
    msg.attach(MIMEText(email_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, REPORT_EMAIL, msg.as_string())
    print(f"  Report emailed to {REPORT_EMAIL}")

# ── MAIN WEEKLY JOB ──────────────────────────────────────────────────────────

def get_devto_articles():
    """Returns list of published articles with title, url, views, reactions."""
    try:
        r = requests.get(
            "https://dev.to/api/articles/me/published",
            headers={"api-key": DEVTO_API_KEY},
            timeout=10
        )
        r.raise_for_status()
        articles = r.json()
        return [
            {
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "views": a.get("page_views_count", 0),
                "reactions": a.get("public_reactions_count", 0),
                "published": a.get("published_at", "")[:10],
            }
            for a in articles
        ]
    except Exception as e:
        print(f"  DEV.to articles error: {e}")
        return []

def get_beehiiv_posts():
    """Returns list of sent newsletter issues with title and link."""
    try:
        r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts",
            headers={"Authorization": f"Bearer {BEEHIIV_API_KEY}"},
            params={"limit": 10, "status": "confirmed"},
            timeout=10
        )
        r.raise_for_status()
        posts = r.json().get("data", [])
        return [
            {
                "subject": p.get("subject", ""),
                "url": p.get("web_url", "") or f"https://app.beehiiv.com",
                "sent": p.get("publish_at", "")[:10] if p.get("publish_at") else "",
                "open_rate": round((p.get("stats", {}).get("open_rate") or 0) * 100, 1),
            }
            for p in posts
        ]
    except Exception as e:
        print(f"  Beehiiv posts error: {e}")
        return []


def daily_job():
    state = load_state()
    today = datetime.date.today()
    weekday = today.weekday()
    is_publish_day = weekday in PUBLISH_DAYS

    # One-time Thursday make-up for the Wednesday missed during initial deploy.
    # Triggers only on 2026-05-07 specifically, and only if no DEV.to post for
    # today is already in posts_made — so retries are safe (failed attempts
    # leave no record, so the next run still tries) and every other Thursday
    # is untouched.
    THURSDAY_MAKEUP_DATE = "2026-05-07"
    already_posted_today = any(
        p.get("date") == str(today) and p.get("platform") == "devto"
        for p in state.get("posts_made", [])
    )
    if weekday == 3 and today.isoformat() == THURSDAY_MAKEUP_DATE and not already_posted_today:
        is_publish_day = True

    is_monday = weekday == 0
    results = {}

    print(f"\n[{datetime.datetime.now()}] ── Daily job ({today}) ──")

    # 1. Collect all stats
    print("  Collecting stats...")
    gumroad = get_gumroad_stats()
    devto_stats = get_devto_stats()
    beehiiv_stats = get_beehiiv_stats()
    articles = get_devto_articles()
    newsletter_posts = get_beehiiv_posts()

    print(f"  Gumroad: {gumroad['sales_count']} sales | ${gumroad['revenue']:.2f}")
    print(f"  DEV.to:  {devto_stats['total_views']} views | {devto_stats['followers']} followers")
    print(f"  Beehiiv: {beehiiv_stats['subscribers']} subs | {beehiiv_stats['open_rate']}% open rate")

    # 2. Publish new content on Mon/Wed/Fri
    if is_publish_day:
        if is_monday:
            state["week_number"] += 1
        week = state["week_number"]
        devto_format = {0: "devto_long", 2: "devto_medium", 3: "devto_medium", 4: "devto_roundup"}[weekday]
        day_name_log = PUBLISH_DAYS.get(weekday, "thursday")
        print(f"  {day_name_log.title()} — publishing {devto_format} (week {week})")

        if HAS_DEVTO:
            try:
                c = generate_content(week, devto_format, state)
                angle = c.pop("_angle", "")
                resp = post_to_devto(c)
                url = resp.get("url", "")
                results["devto"] = {"status": "✅", "title": c["title"], "url": url, "format": devto_format}
                state["posts_made"].append({"platform": "devto", "format": devto_format, "angle": angle, "title": c["title"], "url": url, "week": week, "date": str(today)})
                state.setdefault("recent_angles", []).append(angle)
                print(f"  DEV.to: ✅ \"{c['title']}\" [{angle}]")
            except Exception as e:
                results["devto"] = {"status": "❌", "title": str(e), "url": "", "format": devto_format}
                print(f"  DEV.to: ❌ {e}")

        time.sleep(3)

        if HAS_HN and results.get("devto", {}).get("status") == "✅" and results["devto"].get("url"):
            try:
                hn_resp = post_to_hackernews(results["devto"]["title"], results["devto"]["url"])
                results["hn"] = {"status": "✅", "title": results["devto"]["title"], "url": hn_resp["hn_url"]}
                state["posts_made"].append({"platform": "hackernews", "title": results["devto"]["title"], "url": results["devto"]["url"], "week": week, "date": str(today)})
                print(f"  Hacker News: ✅ submitted \"{results['devto']['title']}\"")
            except Exception as e:
                results["hn"] = {"status": "❌", "title": str(e), "url": ""}
                print(f"  Hacker News: ❌ {e}")

            time.sleep(3)

        if is_monday and HAS_NEWSLETTER:
            try:
                c = generate_content(week, "newsletter", state)
                angle = c.pop("_angle", "")
                post_newsletter(c)
                results["newsletter"] = {"status": "✅", "subject": c["subject"]}
                state["posts_made"].append({"platform": "newsletter", "angle": angle, "subject": c["subject"], "week": week, "date": str(today)})
                state.setdefault("recent_angles", []).append(angle)
                print(f"  Newsletter: ✅ \"{c['subject']}\" [{angle}]")
            except Exception as e:
                results["newsletter"] = {"status": "❌", "subject": str(e)}
                print(f"  Newsletter: ❌ {e}")

        if is_monday:
            try:
                c = generate_content(week, "ih_draft", state)
                angle = c.pop("_angle", "")
                results["ih_draft"] = {"status": "📝", "title": c["title"], "body": c["body_markdown"], "angle": angle}
                state.setdefault("ih_drafts", []).append({"title": c["title"], "angle": angle, "week": week, "date": str(today)})
                state.setdefault("recent_angles", []).append(angle)
                print(f"  Indie Hackers draft: 📝 \"{c['title']}\" [{angle}]")
            except Exception as e:
                results["ih_draft"] = {"status": "❌", "title": str(e), "body": ""}
                print(f"  Indie Hackers draft: ❌ {e}")

    # 3. Track daily stats
    sales_baseline = state.get("total_sales_baseline", 0)
    state.setdefault("daily_stats", []).append({
        "date": str(today),
        "sales_count": gumroad["sales_count"],
        "revenue": gumroad["revenue"],
        "devto_views": devto_stats["total_views"],
        "beehiiv_subs": beehiiv_stats["subscribers"],
    })
    state["total_sales_baseline"] = gumroad["sales_count"]
    save_state(state)

    # 4. Send daily email
    if HAS_EMAIL:
        try:
            send_report(state, gumroad, devto_stats, beehiiv_stats,
                        sales_baseline, results, articles, newsletter_posts, weekday)
        except Exception as e:
            print(f"  Email: ❌ {e}")

    print(f"[{datetime.datetime.now()}] ── Daily job complete ──\n")

# ── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🤖 Passive Income Agent")
    print(f"   DEV.to:     {'✅' if HAS_DEVTO else '⏭️ '}")
    print(f"   Hacker News:{'✅' if HAS_HN else '⏭️ '}")
    print(f"   Newsletter: {'✅' if HAS_NEWSLETTER else '⏭️ '}")
    print(f"   Email:      {'✅' if HAS_EMAIL else '⏭️ '}")
    print(f"   Reporting:  {REPORT_EMAIL}")
    print(f"   Schedule:   daily 09:00 UTC · posts Mon/Wed/Fri (newsletter+IH draft on Mon)\n")

    daily_job()

    schedule.every().day.at("09:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(60)
