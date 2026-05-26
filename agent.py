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
from email.mime.image import MIMEImage
from anthropic import Anthropic

try:
    from etsy_agent.queue import process_etsy_queue
except Exception as _e:
    process_etsy_queue = None
    print(f"  (etsy_agent unavailable: {_e})")

try:
    import blog
except Exception as _e:
    blog = None
    print(f"  (blog module unavailable: {_e})")

# Force unbuffered output so Render logs show everything in real time
os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(line_buffering=True)

# ── CONFIG ───────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
GUMROAD_TOKEN        = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
GUMROAD_PRODUCT_ID   = os.environ.get("GUMROAD_PRODUCT_ID", "nhltvo")
GUMROAD_PRODUCT_URL  = os.environ.get("GUMROAD_PRODUCT_URL", f"https://gumroad.com/l/nhltvo")
GUMROAD_PRODUCT_NAME = os.environ.get("GUMROAD_PRODUCT_NAME", "The AI Leverage Playbook: 50 Prompts & Workflows for Engineers")
GUMROAD_PRODUCT_PRICE = os.environ.get("GUMROAD_PRODUCT_PRICE", "$19")
BRAND_NAME           = os.environ.get("BRAND_NAME", "The AI Leverage Weekly")
BRAND_TAGLINE        = os.environ.get("BRAND_TAGLINE", "Practical AI workflows for engineers")
# Free newsletter signup page. The PRIMARY call-to-action in cold channels
# (DEV.to / blog / IH) is now a free subscribe, not a cold $19 sale — the email
# list is the only asset that compounds, and the warm newsletter is where the
# paid product is actually sold.
NEWSLETTER_SUBSCRIBE_URL = os.environ.get("BLOG_SUBSCRIBE_URL", "https://theaileverageweekly.beehiiv.com/subscribe")
DEVTO_API_KEY       = os.environ.get("DEVTO_API_KEY", "")
BEEHIIV_API_KEY     = os.environ.get("BEEHIIV_API_KEY", "")
BEEHIIV_PUB_ID      = os.environ.get("BEEHIIV_PUBLICATION_ID", "")
REPORT_EMAIL        = os.environ.get("REPORT_EMAIL", "talvardi7@gmail.com")
SMTP_EMAIL          = os.environ.get("SMTP_EMAIL", "talvardi7@gmail.com")
SMTP_PASSWORD       = os.environ.get("SMTP_APP_PASSWORD", "")
HN_USERNAME         = os.environ.get("HN_USERNAME", "")
HN_PASSWORD         = os.environ.get("HN_PASSWORD", "")
# HN auto-submission default-off as of 2026-05-18. HN moderator confirmed
# dev.to is domain-banned on HN ("too many low-quality posts / promotional
# behavior"). Re-enable by setting HN_ENABLED=true on Render once we're
# submitting URLs from a non-banned platform (Hashnode, own domain, etc.).
HN_ENABLED          = os.environ.get("HN_ENABLED", "false").lower() == "true"

HAS_DEVTO      = DEVTO_API_KEY not in ("", "FILL_IN_LATER")
HAS_NEWSLETTER = BEEHIIV_API_KEY not in ("", "FILL_IN_LATER")
HAS_EMAIL      = SMTP_PASSWORD not in ("", "FILL_IN_LATER")
HAS_HN         = HN_USERNAME not in ("", "FILL_IN_LATER") and HN_PASSWORD not in ("", "FILL_IN_LATER")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# Allow state.json to live on a mounted persistent disk (e.g. Render's disk
# add-on) so it survives redeploys. Set STATE_DIR env var to the mount path.
# Without it, state lives in the working dir (gets wiped on each Render deploy).
_STATE_DIR = os.environ.get("STATE_DIR", "").strip()
if _STATE_DIR:
    os.makedirs(_STATE_DIR, exist_ok=True)
    STATE_FILE = os.path.join(_STATE_DIR, "state.json")
    print(f"  State persistence: {STATE_FILE}")
else:
    STATE_FILE = "state.json"

DEVTO_TAGS_ROTATION = [
    ["ai", "productivity", "career", "engineering"],
    ["programming", "ai", "tutorial", "career"],
    ["webdev", "ai", "productivity", "beginners"],
    ["devops", "ai", "engineering", "tools"],
]

ANGLES = ["tutorial", "opinion", "case_study", "tip_list", "story"]
PUBLISH_DAYS = {0: "monday", 2: "wednesday", 4: "friday"}


def tracked_url(campaign, source="devto"):
    """Append UTM parameters so we can see in Gumroad analytics which channel
    and which post produced a click. campaign is typically '<format>_<week>'."""
    sep = "&" if "?" in GUMROAD_PRODUCT_URL else "?"
    return f"{GUMROAD_PRODUCT_URL}{sep}utm_source={source}&utm_medium=article&utm_campaign={campaign}"

def subscribe_url(campaign, source="devto"):
    """Newsletter signup URL with UTM params so we can attribute which channel/
    post drove a subscribe. Mirrors tracked_url but points at the free list."""
    sep = "&" if "?" in NEWSLETTER_SUBSCRIBE_URL else "?"
    return f"{NEWSLETTER_SUBSCRIBE_URL}{sep}utm_source={source}&utm_medium=article&utm_campaign={campaign}"

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

def _devto_published_today():
    """Query DEV.to's API to see if our account already has a post dated
    today. Resilient to state.json wipes (which happen on Render redeploys).
    Returns False on any error so we don't accidentally block a legitimate
    first run for the day."""
    if not HAS_DEVTO:
        return False
    try:
        r = requests.get(
            "https://dev.to/api/articles/me/published",
            headers={"api-key": DEVTO_API_KEY},
            params={"per_page": 30},
            timeout=10,
        )
        r.raise_for_status()
        today_str = str(datetime.date.today())
        for a in r.json():
            if (a.get("published_at") or "")[:10] == today_str:
                return True
        return False
    except Exception as e:
        print(f"  DEV.to dedup check failed (treating as not-yet-posted): {e}")
        return False


def already_done_today(state, today, platform):
    """Idempotency: True if a post for this date+platform was already created.
    Checks state.json first; for DEV.to, falls back to the actual API (which
    is the authoritative record and survives state-file wipes on redeploy)."""
    today_str = str(today)
    if platform == "ih_draft":
        return any(d.get("date") == today_str for d in state.get("ih_drafts", []))
    # State-based check
    if any(p.get("platform") == platform and p.get("date") == today_str
           for p in state.get("posts_made", [])):
        return True
    # API-based fallback for DEV.to (the platform with the highest cost of a
    # duplicate, since each generates a real public article)
    if platform == "devto":
        return _devto_published_today()
    return False

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
        # Subscriber count + average open rate come from the publication-level
        # stats object. The /subscriptions endpoint switched to cursor
        # pagination and no longer returns `total_results`, so the old code
        # silently reported 0 subscribers forever. `expand[]=stats` is the
        # authoritative source.
        h = {"Authorization": f"Bearer {BEEHIIV_API_KEY}"}
        r = requests.get(
            f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}",
            headers=h,
            params={"expand[]": "stats"},
            timeout=10
        )
        r.raise_for_status()
        stats = r.json().get("data", {}).get("stats", {}) or {}
        total_subs = stats.get("active_subscriptions", 0)
        open_rate = stats.get("average_open_rate", 0) or 0

        # Count of confirmed (sent) issues — separate call, best-effort.
        issues_sent = 0
        try:
            posts_r = requests.get(
                f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts",
                headers=h,
                params={"limit": 100, "status": "confirmed"},
                timeout=10
            )
            posts_r.raise_for_status()
            issues_sent = len(posts_r.json().get("data", []))
        except Exception:
            pass

        return {
            "subscribers": total_subs,
            "open_rate": round(open_rate * 100, 1) if open_rate else 0,
            "issues_sent": issues_sent,
            "ok": True
        }
    except Exception as e:
        print(f"  Beehiiv stats error: {e}")
        return {"subscribers": 0, "open_rate": 0, "issues_sent": 0, "ok": False}

def log_metrics(gumroad, devto, beehiiv):
    """Append today's numbers to metrics/history.jsonl in the repo so we keep a
    daily time series that survives Render redeploys (which wipe state.json).
    Uses the same GitHub Contents API as the blog. One JSON row per day; a re-run
    on the same day overwrites that day's row instead of duplicating it. This is
    the foundation for tracking trends and judging what actually moves numbers.
    """
    if blog is None or not blog.HAS_BLOG:
        print("  Metrics log: skipped (no GitHub token)")
        return
    import base64
    path = "metrics/history.jsonl"
    today = str(datetime.date.today())
    content_views = devto.get("total_views", 0)
    product_views = gumroad.get("views", 0)
    row = {
        "date": today,
        "devto_views": content_views,
        "devto_articles": devto.get("articles", 0),
        "devto_reactions": devto.get("total_reactions", 0),
        "devto_followers": devto.get("followers", 0),
        "beehiiv_subs": beehiiv.get("subscribers", 0),
        "beehiiv_open_rate": beehiiv.get("open_rate", 0),
        "beehiiv_issues": beehiiv.get("issues_sent", 0),
        "gumroad_views": product_views,
        "gumroad_sales": gumroad.get("sales_count", 0),
        "gumroad_revenue": gumroad.get("revenue", 0),
        # Derived funnel ratios so trend analysis doesn't have to recompute them.
        "ctr_pct": round(product_views / content_views * 100, 3) if content_views else 0,
    }
    # Read existing file, drop any prior row for today (idempotent re-runs), append.
    lines = []
    try:
        r = requests.get(
            f"{blog.GITHUB_API}/repos/{blog.GITHUB_BLOG_REPO}/contents/{path}",
            headers=blog._headers(), params={"ref": blog.GITHUB_BLOG_BRANCH}, timeout=15)
        if r.status_code == 200:
            raw = base64.b64decode(r.json().get("content", "")).decode("utf-8")
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    if json.loads(line).get("date") != today:
                        lines.append(line)
                except Exception:
                    lines.append(line)  # keep malformed lines rather than lose data
    except Exception as e:
        print(f"  Metrics log: read failed ({e}) — starting fresh")
    lines.append(json.dumps(row))
    try:
        blog._gh_put(path, "\n".join(lines) + "\n", f"Log metrics {today}")
        print(f"  Metrics log: ✅ {today} ({len(lines)} day(s) tracked, CTR {row['ctr_pct']}%)")
    except Exception as e:
        print(f"  Metrics log: ❌ {e}")


# ── CONTENT GENERATION ───────────────────────────────────────────────────────

# Tool schemas — using the Anthropic tool-use API forces the model to return
# structured input instead of free-form text. The SDK delivers it as a parsed
# dict, sidestepping every JSON-string-parsing failure mode (markdown fences,
# unescaped quotes inside markdown, embedded newlines, etc).
DEVTO_TOOL = {
    "name": "submit_devto_article",
    "description": "Submit the generated DEV.to article",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Article title"},
            "body_markdown": {"type": "string", "description": "Full article body in markdown"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "DEV.to tags"},
        },
        "required": ["title", "body_markdown", "tags"],
    },
}

NEWSLETTER_TOOL = {
    "name": "submit_newsletter",
    "description": "Submit the generated newsletter issue",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "Subject line under 50 chars"},
            "body_html": {"type": "string", "description": "Newsletter body in HTML"},
        },
        "required": ["subject", "body_html"],
    },
}

IH_TOOL = {
    "name": "submit_ih_draft",
    "description": "Submit the generated Indie Hackers post draft",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Post title under 70 chars"},
            "body_markdown": {"type": "string", "description": "Post body in markdown"},
        },
        "required": ["title", "body_markdown"],
    },
}

TOOL_FOR_FORMAT = {
    "devto_long":    DEVTO_TOOL,
    "devto_medium":  DEVTO_TOOL,
    "devto_roundup": DEVTO_TOOL,
    "newsletter":    NEWSLETTER_TOOL,
    "ih_draft":      IH_TOOL,
}

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

    # Tracked URLs — one per format, so Gumroad analytics shows which channel
    # produced the click. utm_campaign embeds format + week.
    devto_long_url    = tracked_url(f"long_w{week_number}",    source="devto")
    devto_medium_url  = tracked_url(f"medium_w{week_number}",  source="devto")
    devto_roundup_url = tracked_url(f"roundup_w{week_number}", source="devto")
    newsletter_url    = tracked_url(f"newsletter_w{week_number}", source="newsletter")
    ih_url            = tracked_url(f"ih_w{week_number}",      source="indiehackers")

    # Subscribe URLs — the PRIMARY ask in cold channels is a free signup.
    sub_long_url    = subscribe_url(f"long_w{week_number}",    source="devto")
    sub_medium_url  = subscribe_url(f"medium_w{week_number}",  source="devto")
    sub_roundup_url = subscribe_url(f"roundup_w{week_number}", source="devto")
    sub_ih_url      = subscribe_url(f"ih_w{week_number}",      source="indiehackers")

    # CTA strategy (revised 2026-05-26): cold readers don't buy a $19 PDF on
    # first touch, so the END CTA in cold channels is now a FREE newsletter
    # signup — far higher conversion, and the list is the only compounding
    # asset. The paid product appears only as an optional mid-article soft aside
    # (no link), never as the closing ask. The paid pitch lives in the warm
    # newsletter, where the audience already opted in.
    cta_rules = f"""CTA RULES — the closing ask is a FREE newsletter signup, NOT a paid product.
- Goal: get the reader to subscribe to the free weekly newsletter "{BRAND_NAME}" — {BRAND_TAGLINE}. One concrete AI workflow per week.
- Voice: declarative, peer-to-peer. NEVER use "if you want" / "if this resonates" / "in case it's helpful" — low-confidence framing kills conversion.
- Good end CTA: "I break down one workflow like this every week in {BRAND_NAME} — practical, no fluff, free. Subscribe: LINK"
- The end CTA is the last paragraph, 2-3 sentences, and ends with the subscribe LINK as plain text.
- Do NOT pitch the paid product ({GUMROAD_PRODUCT_NAME}, {GUMROAD_PRODUCT_PRICE}) in the end CTA. It may appear ONLY where a format's rules explicitly allow a mid-article soft aside.
"""

    # The newsletter goes to people who already subscribed — this is the WARM
    # channel, so here the closing ask IS the paid product.
    newsletter_cta_rules = f"""CTA RULES — this is the newsletter (warm, opted-in audience), so the closing ask is the paid product.
- Product name (verbatim): "{GUMROAD_PRODUCT_NAME}" — {GUMROAD_PRODUCT_PRICE}
- What's inside: 50 prompts across code review, debugging, refactoring, sprint planning, ADRs, and test design.
- Voice: declarative, peer-to-peer. NEVER use "if you want" / "if this resonates" — low-confidence framing kills conversion.
- Good CTA: "The full set is in {GUMROAD_PRODUCT_NAME} — 50 prompts across code review, debugging, refactor, and sprint planning. {GUMROAD_PRODUCT_PRICE}: LINK"
"""

    system = (
        "You are a senior software engineer writing for a technical audience. "
        "Write posts that are genuinely useful — concrete, specific, actionable. "
        "The body should never sound like marketing. The end CTA is allowed to be direct and confident — "
        "treat it like recommending a tool to a colleague, not pitching a product. "
        "Vary topic and angle. Use the provided tool to return your output."
    )

    prompts = {
        "devto_long": f"""Week {week_number} — Monday long-form DEV.to article on using AI for engineering productivity.
Angle: {angle} ({angle_hint}).
Use these DEV.to tags: {tags}
Do NOT repeat or rephrase any of these previous titles: {previous_titles}

Rules:
- Title: specific and useful (e.g. "The 5 AI prompts I use before every code review"). No hype, no clickbait.
- Body: 500-800 words markdown. Include 1-2 concrete copy-paste prompt examples in code blocks.
- Include ONE mid-article soft mention: somewhere around the 60-70% point of the article (after introducing the main technique), add a one-line aside like "This pattern is one of the ones I've packaged into {GUMROAD_PRODUCT_NAME} — but the version below is enough to get value on its own." Then immediately keep teaching. The aside must NOT include a link.
- End CTA: free newsletter signup. Last paragraph, 2-3 sentences, declarative. Link: {sub_long_url}
- Tone: practitioner to peers.

{cta_rules}
Call submit_devto_article with the result.""",

        "devto_medium": f"""Week {week_number} — Wednesday mid-length DEV.to piece. Different topic and angle from Monday.
Angle: {angle} ({angle_hint}).
Use these DEV.to tags: {tags}
Do NOT repeat or rephrase any of these recent titles: {previous_titles}

Rules:
- Title: sharp and specific.
- Body: 300-500 words markdown, one concrete prompt or workflow example.
- End CTA: free newsletter signup. Last paragraph, 2-3 sentences, declarative. Link: {sub_medium_url}
- Tone: peer-to-peer, no fluff. No mid-article mention (article is too short).

{cta_rules}
Call submit_devto_article with the result.""",

        "devto_roundup": f"""Week {week_number} — Friday weekly roundup DEV.to post.
This week you've already published these articles: {weekly_titles or '[none yet]'}
Angle: {angle} ({angle_hint}).
Use these DEV.to tags: {tags}
Avoid these recent titles: {previous_titles}

Rules:
- Title: e.g. "What I learned about AI workflows this week" or "3 things that worked, 1 that didn't".
- Body: 250-400 words markdown that ties together the week's themes (reference your own articles by topic, not by linking).
- End CTA: free newsletter signup. Last paragraph, 2-3 sentences, declarative. Link: {sub_roundup_url}
- Tone: casual, reflective. No mid-article mention.

{cta_rules}
Call submit_devto_article with the result.""",

        "newsletter": f"""Week {week_number}. Newsletter issue for the "{BRAND_NAME}" publication — {BRAND_TAGLINE}.
Angle: {angle} ({angle_hint}).
Avoid these recent subjects: {previous_titles}

OUTPUT FORMAT — IMPORTANT: PLAIN TEXT ONLY. No HTML tags. No markdown syntax (no #, no **, no `, no [](), no ---). The body will be pasted directly into Beehiiv's visual editor, which renders plain text as paragraphs and does NOT interpret HTML or markdown.

Rules:
- Subject: specific, under 50 chars. Do NOT include the brand name in the subject (it shows up in Beehiiv's "from" field already).
- Body: 400-600 words of plain text.
- Body MUST start with these three lines, in order, separated by single newlines:
    Line 1: {BRAND_NAME} · Week {week_number}
    Line 2: {BRAND_TAGLINE}
    Line 3: (blank)
- After the masthead: the article title on its own line, then a blank line, then the body paragraphs.
- Paragraphs separated by ONE blank line (\\n\\n).
- For lists: each item on its own line starting with "- " (hyphen + space). No markdown bullets, no nested lists.
- For section headings: heading on its own line, blank line before and after. Capitalize the heading like a proper title (e.g., "The SCOPE Framework", "Step 1 — Dump the Situation"). Do not use #.
- For prompt/code examples: introduce with a sentence (e.g., "Here's the prompt I use:"), then a blank line, then the prompt on its own. Do not use code fences or backticks.
- End CTA: last 2-3 sentences as a single paragraph, declarative. Include the full URL as plain text (no markdown link syntax). Link: {newsletter_url}

The body field is called body_html for legacy compatibility — but put PLAIN TEXT in it, not HTML.

{newsletter_cta_rules}
Call submit_newsletter with the result.""",

        "ih_draft": f"""Week {week_number} — Indie Hackers post draft (the user will paste this manually).
Voice: builder talking to other builders. First-person, conversational, specific numbers, no hype.
Angle: {angle} ({angle_hint}).
Avoid these recent titles: {previous_titles}

Rules:
- Title: under 70 chars (e.g. "Week N: what I shipped + what I'm learning").
- Body: 200-400 words markdown about something concrete you built/tried/learned this week.
- End CTA: free newsletter signup. Last paragraph, 2-3 sentences, declarative. Link: {sub_ih_url}

{cta_rules}
Call submit_ih_draft with the result."""
    }

    tool = TOOL_FOR_FORMAT[format_key]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": prompts[format_key]}],
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
    )

    out = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            out = dict(block.input)
            break
    if out is None:
        # tool_choice forces a tool call, so this should never happen, but if
        # it ever does, surface what came back so we can debug fast.
        raise ValueError(f"Model didn't call the tool. stop_reason={response.stop_reason}, content={response.content!r}"[:500])

    # Clean up tags for DEV.to: max 4 tags, lowercase, alphanum-only (DEV.to limit)
    if "tags" in out:
        cleaned = []
        for t in out["tags"]:
            t = re.sub(r"[^a-z0-9]", "", str(t).lower())
            if t and t not in cleaned:
                cleaned.append(t)
        out["tags"] = cleaned[:4] or list(tags)

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

# Note: post_newsletter() was removed. Beehiiv moved the publish API to the
# enterprise-only tier (HTTP 403 "SEND_API_NOT_ENTERPRISE_PLAN"). The agent
# now generates a newsletter draft and includes it in the daily email --
# user pastes into Beehiiv's editor manually. Same pattern as ih_draft.

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
    # Content-lane daily report. Etsy results go in send_etsy_report() so the
    # two passive-income lanes don't get tangled in one email.
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

    # Funnel diagnostic — the whole product is passive monitoring, so the report
    # should say *where* the funnel leaks, not just list counts. The stages are:
    # content views (DEV.to) → product-page views (Gumroad) → sales. A 0 at any
    # stage with traffic upstream pinpoints exactly which step is broken. This is
    # the most decision-relevant signal: e.g. lots of readers but 0 product views
    # means the article→CTA click-through is the bottleneck, not the sales page.
    content_views = devto.get("total_views", 0)
    product_views = gumroad.get("views", 0)
    total_sales = gumroad.get("sales_count", 0)
    ctr = (product_views / content_views * 100) if content_views else 0
    conv = (total_sales / product_views * 100) if product_views else 0
    if content_views == 0:
        funnel_note, funnel_color = "No content views yet — nothing is reaching readers.", "#9CA3AF"
    elif product_views == 0:
        funnel_note, funnel_color = (f"{content_views:,} readers, but 0 reached the product page. "
                                     "The leak is upstream — the article→CTA click-through, not the sales page itself."), "#EF9F27"
    elif total_sales == 0:
        funnel_note, funnel_color = (f"{product_views:,} product-page views but 0 sales — readers click through, "
                                     "so the leak is the sales page / price / offer."), "#EF9F27"
    else:
        funnel_note, funnel_color = (f"{ctr:.1f}% of readers click through; "
                                     f"{conv:.1f}% of those buy."), "#1D9E75"

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
        if items:
            published_today_html = f"""
    <div class="card" style="border-left:3px solid #1D9E75">
      <p class="section-title">Published today</p>
      {items}
    </div>"""

    # Newsletter draft (Mondays only — paste into Beehiiv since their send API
    # is now enterprise-only)
    newsletter_draft_html = ""
    if is_monday and results.get("newsletter_draft") and results["newsletter_draft"].get("body_html"):
        d = results["newsletter_draft"]
        if d.get("status") == "❌":
            newsletter_draft_html = f"""
    <div class="card" style="border-left:3px solid #EF9F27">
      <p class="section-title">Newsletter draft — generation failed</p>
      <p style="margin:0;font-size:12px;color:#9CA3AF">{html.escape(str(d.get('subject', '')))[:300]}</p>
    </div>"""
        else:
            subject_escaped = html.escape(str(d["subject"]))
            body_escaped = html.escape(str(d["body_html"]))
            newsletter_draft_html = f"""
    <div class="card" style="border-left:3px solid #378ADD">
      <p class="section-title">Newsletter draft (paste into Beehiiv — 30 sec)</p>
      <p style="font-size:14px;font-weight:500;margin:0 0 12px;color:#0F1117">Subject: {subject_escaped}</p>
      <p style="font-size:11px;color:#6B7280;margin:0 0 8px">Body HTML (copy raw, paste into Beehiiv's HTML editor):</p>
      <pre style="background:#F4F6FA;padding:14px;border-radius:6px;font-family:ui-monospace,Menlo,monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;word-wrap:break-word;color:#0F1117;margin:0">{body_escaped}</pre>
      <a href="https://app.beehiiv.com" style="font-size:12px;color:#378ADD;text-decoration:none;display:block;margin-top:12px">Open Beehiiv ↗</a>
    </div>"""

    # Medium cross-post hint (Mondays only, when DEV.to publish succeeded).
    # We can't auto-post (Medium retired the API for new accounts), but Medium's
    # /p/import tool turns this into a ~30s manual step that preserves formatting
    # and auto-sets the canonical URL back to DEV.to.
    medium_crosspost_html = ""
    if is_monday and results.get("devto") and results["devto"].get("status") == "✅" and results["devto"].get("url"):
        devto_url = results["devto"]["url"]
        medium_crosspost_html = f"""
    <div class="card" style="border-left:3px solid #1D9E75">
      <p class="section-title">Cross-post to Medium (30 sec)</p>
      <ol style="margin:0;padding-left:20px;font-size:13px;line-height:1.8;color:#374151">
        <li>Open <a href="https://medium.com/p/import" style="color:#378ADD;text-decoration:none">medium.com/p/import</a></li>
        <li>Paste this URL: <code style="background:#F4F6FA;padding:2px 6px;border-radius:3px;font-size:12px;word-break:break-all">{html.escape(devto_url)}</code></li>
        <li>Click <b>Import</b> → review the preview → <b>Publish</b></li>
      </ol>
      <p style="font-size:11px;color:#9CA3AF;margin:12px 0 0">Medium auto-sets the canonical URL back to DEV.to — no SEO penalty for duplicate content.</p>
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
  {newsletter_draft_html}
  {medium_crosspost_html}
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
    <p class="section-title">Funnel — where it leaks</p>
    <div class="metric-grid">
      <div class="metric">
        <div class="metric-label">Content views</div>
        <div class="metric-value">{content_views:,}</div>
        <div class="metric-sub">DEV.to articles</div>
      </div>
      <div class="metric">
        <div class="metric-label">Product views</div>
        <div class="metric-value">{product_views:,}</div>
        <div class="metric-sub">{ctr:.1f}% click-through</div>
      </div>
      <div class="metric">
        <div class="metric-label">Sales</div>
        <div class="metric-value">{total_sales:,}</div>
        <div class="metric-sub">{conv:.1f}% of product views</div>
      </div>
    </div>
    <p style="margin:14px 0 0;font-size:12px;color:{funnel_color};line-height:1.5">{funnel_note}</p>
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

  <p class="footer">{BRAND_NAME} · Next report tomorrow at 09:00 UTC · Nothing for you to do</p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{subject_prefix}{BRAND_NAME} · ${total_rev:.0f} · {gumroad['sales_count']} sales · {devto['total_views']:,} views — {today}"
    msg["From"] = f"{BRAND_NAME} <{SMTP_EMAIL}>"
    msg["To"] = REPORT_EMAIL
    msg.attach(MIMEText(email_html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, REPORT_EMAIL, msg.as_string())
    print(f"  Report emailed to {REPORT_EMAIL}")


def send_etsy_report(state, etsy_results):
    # Etsy-lane email — separate from the content report so the two passive-
    # income lanes stay readable. Only sends when there's something to say.
    if not etsy_results:
        return

    today = datetime.date.today()
    success_count = sum(1 for r in etsy_results if not r.get("error"))
    error_count = len(etsy_results) - success_count

    cards = ""
    for item in etsy_results:
        item_id = html.escape(str(item.get("id", "")))
        product = html.escape(str(item.get("product", "")))
        niche = html.escape(str(item.get("niche", "")))
        if item.get("error"):
            cards += f"""
      <div class="card" style="border-left:3px solid #EF9F27">
        <p style="margin:0;font-weight:500;color:#0F1117;font-size:14px">❌ {item_id}</p>
        <p style="margin:6px 0;font-size:12px;color:#374151">{product}</p>
        <p style="margin:8px 0 0;font-size:12px;color:#9CA3AF">Error: <code style="background:#F4F6FA;padding:2px 6px;border-radius:3px;font-size:11px">{html.escape(str(item['error']))[:300]}</code></p>
        <p style="margin:8px 0 0;font-size:11px;color:#9CA3AF">This item was NOT marked processed; the agent will retry on the next run.</p>
      </div>"""
            continue

        listings = item.get("listings", []) or []
        prompts = item.get("image_prompts", []) or []
        images = item.get("images", []) or []

        listings_html = ""
        for i, L in enumerate(listings, 1):
            title = html.escape(str(L.get("title", "")))
            desc = html.escape(str(L.get("description", "")))
            tags = ", ".join(html.escape(str(t)) for t in (L.get("tags") or []))
            cat = html.escape(str(L.get("category", "")))
            price = L.get("suggested_price_usd", "")
            angle = html.escape(str(L.get("angle", "")))
            listings_html += f"""
        <details style="margin:8px 0;padding:10px;background:#F4F6FA;border-radius:6px">
          <summary style="cursor:pointer;font-weight:500;color:#0F1117;font-size:13px">{i}. {title}</summary>
          <div style="margin-top:10px;font-size:12px;color:#374151;line-height:1.5">
            <p style="margin:6px 0"><b>Angle:</b> {angle}</p>
            <p style="margin:6px 0"><b>Category:</b> {cat} &middot; <b>Price:</b> ${price}</p>
            <p style="margin:6px 0"><b>Tags:</b> {tags}</p>
            <pre style="background:white;padding:10px;border-radius:4px;font-family:ui-monospace,Menlo,monospace;font-size:11px;white-space:pre-wrap;word-wrap:break-word;color:#0F1117;margin:6px 0 0">{desc}</pre>
          </div>
        </details>"""

        prompts_html = ""
        for i, P in enumerate(prompts, 1):
            use_case = html.escape(str(P.get("use_case", "")))
            ptext = html.escape(str(P.get("prompt", "")))
            prompts_html += f"""
        <li style="margin:6px 0;font-size:12px;color:#374151"><b>{use_case}:</b> {ptext}</li>"""

        # Image-rendering summary line (only meaningful if Replicate is wired up)
        rendered_imgs = [i for i in images if i.get("path")]
        failed_imgs = [i for i in images if i.get("error")]
        images_summary = ""
        if rendered_imgs or failed_imgs:
            parts = []
            if rendered_imgs:
                parts.append(f"<b>{len(rendered_imgs)}</b> images attached to this email")
            if failed_imgs:
                parts.append(f"{len(failed_imgs)} failed")
            images_summary = f"""
        <p style="margin:8px 0 4px;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.06em">Images</p>
        <p style="margin:0 0 12px;font-size:12px;color:#374151">{' &middot; '.join(parts)}. Filenames begin with <code style="background:#F4F6FA;padding:1px 5px;border-radius:3px;font-size:11px">{item_id}_</code>.</p>"""

        cards += f"""
      <div class="card" style="border-left:3px solid #1D9E75">
        <p style="margin:0;font-weight:500;color:#0F1117;font-size:14px">✅ {item_id}</p>
        <p style="margin:6px 0;font-size:13px;color:#0F1117">{product}</p>
        <p style="margin:6px 0 14px;font-size:11px;color:#9CA3AF">Niche: {niche} &middot; {len(listings)} listings &middot; {len(prompts)} image prompts &middot; {len(rendered_imgs)} images rendered</p>
        {images_summary}
        <p style="margin:8px 0 4px;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.06em">Listings (click each to expand)</p>
        {listings_html}
        <p style="margin:14px 0 4px;font-size:11px;color:#6B7280;text-transform:uppercase;letter-spacing:0.06em">Image prompts</p>
        <ol style="padding-left:18px;margin:0">{prompts_html}</ol>
      </div>"""

    summary_line = f"{success_count} generated"
    if error_count:
        summary_line += f", {error_count} failed (will retry)"

    body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #F4F6FA; margin: 0; padding: 24px; }}
  .card {{ background: white; border-radius: 12px; padding: 22px; margin-bottom: 16px; border: 1px solid #E2E8F0; }}
  .header {{ background: #0F1117; border-radius: 12px; padding: 26px; margin-bottom: 16px; }}
  h1 {{ color: white; margin: 0 0 6px; font-size: 22px; font-weight: 500; }}
  .sub {{ color: #6B7280; font-size: 13px; margin: 0; }}
  .footer {{ font-size: 11px; color: #9CA3AF; text-align: center; margin-top: 24px; }}
</style></head>
<body>
  <div class="header">
    <h1>🛍️ Etsy Queue Report — {today}</h1>
    <p class="sub">{summary_line} &middot; Automated by your passive income agent</p>
  </div>
  {cards}
  <p class="footer">Add more product ideas at <a href="https://github.com/talvardi7/passive-agent/blob/main/etsy_queue.json" style="color:#378ADD;text-decoration:none">etsy_queue.json</a> on GitHub. Each item is processed exactly once.</p>
</body>
</html>"""

    # Mixed multipart so we can attach the generated images alongside the HTML.
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🛍️ Etsy · {summary_line} · {today}"
    msg["From"] = f"{BRAND_NAME} <{SMTP_EMAIL}>"
    msg["To"] = REPORT_EMAIL

    # The HTML body itself goes in an "alternative" sub-part so email clients
    # treat it as the readable body and the attachments as attachments.
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body, "html"))
    msg.attach(body_part)

    # Attach all rendered images across all items. Cap total size at ~22MB
    # (Gmail's hard limit is 25MB) just in case.
    total_bytes = 0
    for item in etsy_results:
        for img in (item.get("images") or []):
            path = img.get("path")
            if not path or not os.path.exists(path):
                continue
            try:
                with open(path, "rb") as f:
                    img_data = f.read()
                if total_bytes + len(img_data) > 22 * 1024 * 1024:
                    print(f"  Etsy email: attachment cap reached, skipping remaining images")
                    break
                part = MIMEImage(img_data, _subtype="jpeg")
                part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(path)}"')
                msg.attach(part)
                total_bytes += len(img_data)
            except Exception as e:
                print(f"  Etsy email: couldn't attach {path}: {e}")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, REPORT_EMAIL, msg.as_string())
    print(f"  Etsy report emailed to {REPORT_EMAIL} ({total_bytes // 1024} KB attached)")

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

    # Persist a daily time series (survives Render redeploys) for trend analysis.
    log_metrics(gumroad, devto_stats, beehiiv_stats)

    # 2. Publish new content on Mon/Wed/Fri
    if is_publish_day:
        # Gate week_number increment to once per calendar Monday, so multiple
        # daily_job invocations on the same Monday (e.g. due to a redeploy)
        # don't keep bumping the number.
        if is_monday and state.get("week_number_last_set") != str(today):
            state["week_number"] += 1
            state["week_number_last_set"] = str(today)
        week = state["week_number"]
        devto_format = {0: "devto_long", 2: "devto_medium", 3: "devto_medium", 4: "devto_roundup"}[weekday]
        day_name_log = PUBLISH_DAYS.get(weekday, "thursday")
        print(f"  {day_name_log.title()} — publishing {devto_format} (week {week})")

        if HAS_DEVTO and already_done_today(state, today, "devto"):
            print(f"  DEV.to: ⏭  already posted today, skipping")
        elif HAS_DEVTO:
            try:
                c = generate_content(week, devto_format, state)
                angle = c.pop("_angle", "")
                resp = post_to_devto(c)
                url = resp.get("url", "")
                results["devto"] = {"status": "✅", "title": c["title"], "url": url, "format": devto_format}
                state["posts_made"].append({"platform": "devto", "format": devto_format, "angle": angle, "title": c["title"], "url": url, "week": week, "date": str(today)})
                state.setdefault("recent_angles", []).append(angle)
                print(f"  DEV.to: ✅ \"{c['title']}\" [{angle}]")

                # Mirror to our own GitHub Pages blog (non-banned, HN-submittable
                # domain). Reuses DEV.to's rendered body_html. Best-effort: a blog
                # failure must not break the DEV.to success we already recorded.
                if blog is not None and blog.HAS_BLOG:
                    try:
                        body_html = resp.get("body_html", "") or c.get("body_markdown", "")
                        slug, blog_url = blog.publish_article(c["title"], body_html, str(today))
                        results["devto"]["blog_url"] = blog_url
                        state.setdefault("blog_posts", []).append({"title": c["title"], "slug": slug, "date": str(today)})
                        blog.update_index(state["blog_posts"])
                        print(f"  Blog: ✅ {blog_url}")
                    except Exception as be:
                        print(f"  Blog: ❌ {be}")
            except Exception as e:
                results["devto"] = {"status": "❌", "title": str(e), "url": "", "format": devto_format}
                print(f"  DEV.to: ❌ {e}")

        time.sleep(3)

        # HN submits the BLOG url, never the dev.to url (dev.to is domain-banned
        # on HN). If there's no blog url for today, we skip rather than submit a
        # banned link.
        hn_target_url = results.get("devto", {}).get("blog_url")
        if HAS_HN and not HN_ENABLED:
            print(f"  Hacker News: ⏸  disabled (HN_ENABLED=false). Flip to true once the blog is live on its custom domain.")
        elif HAS_HN and not hn_target_url:
            print(f"  Hacker News: ⏭  no blog URL for today; skipping (dev.to is domain-banned on HN, won't submit it)")
        elif HAS_HN and already_done_today(state, today, "hackernews"):
            print(f"  Hacker News: ⏭  already submitted today, skipping")
        elif HAS_HN:
            try:
                hn_resp = post_to_hackernews(results["devto"]["title"], hn_target_url)
                results["hn"] = {"status": "✅", "title": results["devto"]["title"], "url": hn_resp["hn_url"]}
                state["posts_made"].append({"platform": "hackernews", "title": results["devto"]["title"], "url": hn_target_url, "week": week, "date": str(today)})
                print(f"  Hacker News: ✅ submitted \"{results['devto']['title']}\" ({hn_target_url})")
            except Exception as e:
                results["hn"] = {"status": "❌", "title": str(e), "url": ""}
                print(f"  Hacker News: ❌ {e}")

            time.sleep(3)

        if is_monday and HAS_NEWSLETTER and already_done_today(state, today, "newsletter_draft"):
            print(f"  Newsletter draft: ⏭  already drafted today, skipping")
        elif is_monday and HAS_NEWSLETTER:
            try:
                c = generate_content(week, "newsletter", state)
                angle = c.pop("_angle", "")
                results["newsletter_draft"] = {"status": "📝", "subject": c["subject"], "body_html": c["body_html"], "angle": angle}
                state["posts_made"].append({"platform": "newsletter_draft", "angle": angle, "subject": c["subject"], "week": week, "date": str(today)})
                state.setdefault("recent_angles", []).append(angle)
                print(f"  Newsletter draft: 📝 \"{c['subject']}\" [{angle}]")
            except Exception as e:
                results["newsletter_draft"] = {"status": "❌", "subject": str(e), "body_html": ""}
                print(f"  Newsletter draft: ❌ {e}")

        if is_monday and already_done_today(state, today, "ih_draft"):
            print(f"  Indie Hackers draft: ⏭  already drafted today, skipping")
        elif is_monday:
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

    # 2b. Process Etsy queue (any items added to etsy_queue.json that haven't
    #     been generated yet). Falls through cleanly if queue is empty.
    etsy_results = []
    if process_etsy_queue is not None:
        try:
            etsy_results = process_etsy_queue(state)
        except Exception as e:
            print(f"  Etsy queue: ❌ {e}")

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

    # 4. Send the two daily emails — content lane and Etsy lane separately.
    # Guard against duplicate emails when a redeploy re-runs daily_job on the
    # same calendar day (the agent's own blog commits push to the repo, which
    # triggers a Render redeploy). Send at most once per day UNLESS this run
    # actually published something new.
    published_new = any(
        (results.get(k) or {}).get("status") in ("✅", "📝")
        for k in ("devto", "hn", "newsletter_draft", "ih_draft")
    )
    already_emailed_today = state.get("last_report_date") == str(today)
    if HAS_EMAIL and not published_new and already_emailed_today:
        print(f"  Email: ⏭  already sent today and nothing new published; skipping duplicate")
    elif HAS_EMAIL:
        try:
            send_report(state, gumroad, devto_stats, beehiiv_stats,
                        sales_baseline, results, articles, newsletter_posts, weekday)
            state["last_report_date"] = str(today)
            save_state(state)
        except Exception as e:
            print(f"  Email: ❌ {e}")
        try:
            send_etsy_report(state, etsy_results)
        except Exception as e:
            print(f"  Etsy email: ❌ {e}")

    print(f"[{datetime.datetime.now()}] ── Daily job complete ──\n")

# ── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"🤖 {BRAND_NAME} — passive income agent")
    print(f"   DEV.to:     {'✅' if HAS_DEVTO else '⏭️ '}")
    print(f"   Hacker News:{'✅' if HAS_HN and HN_ENABLED else ('⏸  (disabled — dev.to is banned on HN)' if HAS_HN else '⏭️ ')}")
    print(f"   Newsletter: {'✅' if HAS_NEWSLETTER else '⏭️ '}")
    print(f"   Email:      {'✅' if HAS_EMAIL else '⏭️ '}")
    print(f"   Reporting:  {REPORT_EMAIL}")
    print(f"   Schedule:   daily 09:00 UTC · posts Mon/Wed/Fri (newsletter+IH draft on Mon)\n")

    daily_job()

    schedule.every().day.at("09:00").do(daily_job)
    while True:
        schedule.run_pending()
        time.sleep(60)
