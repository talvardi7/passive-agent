"""
Static blog publisher for GitHub Pages.

Publishes each article as a standalone HTML page under docs/posts/ and
regenerates docs/index.html, committing both via the GitHub Contents API.
GitHub Pages then serves them at the custom domain (BLOG_DOMAIN).

Why GitHub Pages + custom domain: HN domain-banned dev.to (2026-05-18), and
both Medium and Hashnode retired their free publishing APIs. A blog on a
domain we own can't be rug-pulled, and its URLs are HN-submittable.

No markdown library needed: we reuse DEV.to's already-rendered body_html.
"""

import os
import re
import json
import base64
import datetime
import html as html_mod

import requests

GITHUB_BLOG_TOKEN = os.environ.get("GITHUB_BLOG_TOKEN", "")
GITHUB_BLOG_REPO  = os.environ.get("GITHUB_BLOG_REPO", "talvardi7/passive-agent")
GITHUB_BLOG_BRANCH = os.environ.get("GITHUB_BLOG_BRANCH", "main")
BLOG_DOMAIN       = os.environ.get("BLOG_DOMAIN", "theaileverageweekly.com")
BLOG_BRAND        = os.environ.get("BRAND_NAME", "The AI Leverage Weekly")
BLOG_TAGLINE      = os.environ.get("BRAND_TAGLINE", "Practical AI workflows for engineers")
# Where readers can subscribe (the Beehiiv publication). Optional.
BLOG_SUBSCRIBE_URL = os.environ.get("BLOG_SUBSCRIBE_URL", "https://theaileverageweekly.beehiiv.com/subscribe")

HAS_BLOG = GITHUB_BLOG_TOKEN not in ("", "FILL_IN_LATER")

GITHUB_API = "https://api.github.com"


def _headers():
    return {
        "Authorization": f"Bearer {GITHUB_BLOG_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def slugify(title, max_len=70):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:max_len].strip("-") or "post"


def _gh_get_sha(path):
    """Return the current blob SHA for a file in the repo, or None if absent."""
    r = requests.get(
        f"{GITHUB_API}/repos/{GITHUB_BLOG_REPO}/contents/{path}",
        headers=_headers(),
        params={"ref": GITHUB_BLOG_BRANCH},
        timeout=15,
    )
    if r.status_code == 200:
        return r.json().get("sha")
    return None


def _gh_put(path, content_str, message):
    """Create or update a file in the repo via the Contents API."""
    payload = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BLOG_BRANCH,
    }
    sha = _gh_get_sha(path)
    if sha:
        payload["sha"] = sha
    r = requests.put(
        f"{GITHUB_API}/repos/{GITHUB_BLOG_REPO}/contents/{path}",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


_PAGE_CSS = """
  :root {
    --ink: #18181b; --muted: #6b7280; --faint: #9ca3af;
    --accent: #4f46e5; --accent-dark: #4338ca;
    --border: #ececf0; --bg: #ffffff; --bg-soft: #f7f7fb;
    color-scheme: light;
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body { margin: 0; background: var(--bg); color: var(--ink); line-height: 1.6;
         font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
         -webkit-font-smoothing: antialiased; }
  .topbar { height: 4px; background: linear-gradient(90deg, #4f46e5, #7c6cf0); }
  .container { max-width: 720px; margin: 0 auto; padding: 0 22px; }
  a { color: var(--accent); }

  .site-header { border-bottom: 1px solid var(--border); }
  .site-header .container { display: flex; align-items: center; justify-content: space-between;
                            padding-top: 20px; padding-bottom: 20px; gap: 16px; }
  .brand { text-decoration: none; color: var(--ink); }
  .brand b { display: block; font-weight: 700; font-size: 17px; letter-spacing: -0.01em; }
  .brand span { display: block; font-weight: 400; font-size: 12px; color: var(--faint); margin-top: 1px; }
  .subscribe-btn { background: var(--accent); color: #fff; text-decoration: none; font-size: 14px;
                   font-weight: 600; padding: 9px 16px; border-radius: 8px; white-space: nowrap; }
  .subscribe-btn:hover { background: var(--accent-dark); }
  .nav-actions { display: flex; align-items: center; gap: 16px; }
  .nav-link { font-size: 14px; font-weight: 600; color: var(--muted); text-decoration: none; white-space: nowrap; }
  .nav-link:hover { color: var(--accent); }

  .hero { padding: 56px 0 8px; }
  .hero h1 { font-size: 34px; line-height: 1.15; letter-spacing: -0.02em; margin: 0 0 12px; }
  .hero p { font-size: 17px; color: var(--muted); margin: 0; max-width: 34em; }

  .posts { list-style: none; padding: 0; margin: 24px 0 0; }
  .posts li { padding: 26px 0; border-top: 1px solid var(--border); }
  .posts a.post-link { font-size: 22px; font-weight: 650; line-height: 1.3; letter-spacing: -0.01em;
                       color: var(--ink); text-decoration: none; }
  .posts a.post-link:hover { color: var(--accent); }
  .posts .date { display: block; font-size: 12px; color: var(--faint); margin-top: 8px;
                 text-transform: uppercase; letter-spacing: 0.05em; }

  article { padding: 44px 0 0; }
  .back { font-size: 14px; color: var(--muted); text-decoration: none; }
  .back:hover { color: var(--accent); }
  article h1 { font-size: 36px; line-height: 1.18; letter-spacing: -0.02em; margin: 22px 0 12px; }
  .post-meta { font-size: 12px; color: var(--faint); text-transform: uppercase;
               letter-spacing: 0.05em; margin-bottom: 36px; }
  .post-body { font-family: Georgia, 'Times New Roman', serif; font-size: 19px; line-height: 1.75; color: #27272a; }
  .post-body p { margin: 0 0 22px; }
  .post-body h2 { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                  font-size: 25px; letter-spacing: -0.01em; margin: 44px 0 14px; }
  .post-body h3 { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                  font-size: 20px; margin: 32px 0 10px; }
  .post-body a { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
  .post-body ul, .post-body ol { padding-left: 24px; margin: 0 0 22px; }
  .post-body li { margin: 6px 0; }
  .post-body blockquote { margin: 24px 0; padding: 4px 20px; border-left: 3px solid var(--accent);
                          color: var(--muted); font-style: italic; }
  .post-body pre { background: #f6f8fa; border: 1px solid var(--border); border-radius: 8px;
                   padding: 16px 18px; overflow-x: auto; font-size: 14.5px; line-height: 1.6;
                   font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .post-body code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                    font-size: 0.86em; background: #f1f1f5; padding: 2px 6px; border-radius: 4px; }
  .post-body pre code { background: none; padding: 0; font-size: inherit; }
  .post-body img { max-width: 100%; height: auto; border-radius: 8px; }

  .cta { margin: 56px 0 0; padding: 28px; background: var(--bg-soft);
         border: 1px solid var(--border); border-radius: 12px; text-align: center; }
  .cta h3 { margin: 0 0 6px; font-size: 19px; }
  .cta p { margin: 0 0 18px; color: var(--muted); font-size: 15px; }

  .read-next { margin: 48px 0 0; padding-top: 28px; border-top: 1px solid var(--border); }
  .read-next h3 { margin: 0 0 14px; font-size: 13px; text-transform: uppercase;
                  letter-spacing: 0.06em; color: var(--faint); }
  .read-next ul { list-style: none; padding: 0; margin: 0; }
  .read-next li { padding: 8px 0; }
  .read-next a { font-size: 17px; font-weight: 600; color: var(--ink); text-decoration: none; }
  .read-next a:hover { color: var(--accent); }

  .site-footer { margin-top: 64px; border-top: 1px solid var(--border); }
  .site-footer .container { padding: 26px 22px; font-size: 13px; color: var(--faint);
                            display: flex; gap: 16px; flex-wrap: wrap; justify-content: space-between; }
  .site-footer a { color: var(--muted); text-decoration: none; }
  .site-footer a:hover { color: var(--accent); }

  @media (max-width: 600px) {
    .hero { padding-top: 40px; }
    .hero h1 { font-size: 28px; }
    article h1 { font-size: 28px; }
    .post-body { font-size: 18px; }
    .posts a.post-link { font-size: 20px; }
  }
"""


def _subscribe_btn():
    if not BLOG_SUBSCRIBE_URL:
        return ""
    return f'<a class="subscribe-btn" href="{html_mod.escape(BLOG_SUBSCRIBE_URL)}">Subscribe</a>'


def _header_html():
    return f"""<div class="topbar"></div>
  <header class="site-header">
    <div class="container">
      <a class="brand" href="/"><b>{html_mod.escape(BLOG_BRAND)}</b><span>{html_mod.escape(BLOG_TAGLINE)}</span></a>
      <span class="nav-actions"><a class="nav-link" href="/free-prompts.html">Free prompts</a>{_subscribe_btn()}</span>
    </div>
  </header>"""


def _footer_html():
    sub = f' &middot; <a href="{html_mod.escape(BLOG_SUBSCRIBE_URL)}">Subscribe</a>' if BLOG_SUBSCRIBE_URL else ""
    year = datetime.date.today().year
    return f"""<footer class="site-footer">
    <div class="container">
      <span>&copy; {year} {html_mod.escape(BLOG_BRAND)}</span>
      <span><a href="/">All posts</a> &middot; <a href="/free-prompts.html">Free prompts</a>{sub}</span>
    </div>
  </footer>"""


def _subscribe_cta():
    if not BLOG_SUBSCRIBE_URL:
        return ""
    return f"""<div class="cta">
      <h3>Get the next one in your inbox</h3>
      <p>{html_mod.escape(BLOG_TAGLINE)}. One issue a week, no fluff.</p>
      <a class="subscribe-btn" href="{html_mod.escape(BLOG_SUBSCRIBE_URL)}">Subscribe free</a>
    </div>"""


def _meta_description(body_html, fallback=""):
    """Plain-text summary (~155 chars) for <meta description> / OG / Twitter,
    derived from the article body so each page has a unique, relevant snippet —
    the single biggest on-page lever for search click-through."""
    text = re.sub(r"<[^>]+>", " ", body_html or "")
    text = html_mod.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return fallback or BLOG_TAGLINE
    if len(text) > 155:
        text = text[:155].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def _jsonld(data):
    return f'<script type="application/ld+json">{json.dumps(data, ensure_ascii=False)}</script>'


def _head(title, description="", canonical="", og_type="website"):
    """Central SEO head. title is already HTML-escaped by callers."""
    desc = html_mod.escape((description or BLOG_TAGLINE)[:200])
    canon_url = canonical or f"https://{BLOG_DOMAIN}/"
    canon_esc = html_mod.escape(canon_url)
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <link rel="canonical" href="{canon_esc}">
  <meta property="og:type" content="{og_type}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:url" content="{canon_esc}">
  <meta property="og:site_name" content="{html_mod.escape(BLOG_BRAND)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{desc}">
  <style>{_PAGE_CSS}</style>
</head>"""


def _read_next_html(recent_posts, current_slug):
    """Up to 3 links to other recent posts — internal linking improves crawl
    depth and keeps readers on the site (both help SEO)."""
    if not recent_posts:
        return ""
    others = [p for p in sorted(recent_posts, key=lambda p: p.get("date", ""), reverse=True)
              if p.get("slug") and p.get("slug") != current_slug][:3]
    if not others:
        return ""
    links = ""
    for p in others:
        links += (f'      <li><a href="/posts/{p["slug"]}.html">'
                  f'{html_mod.escape(p.get("title", ""))}</a></li>\n')
    return f"""<nav class="read-next" aria-label="More posts">
      <h3>Read next</h3>
      <ul>
{links}      </ul>
    </nav>"""


def _article_html(title, body_html, date_str, recent_posts=None):
    safe_title = html_mod.escape(title)
    slug = slugify(title)
    url = f"https://{BLOG_DOMAIN}/posts/{slug}.html"
    description = _meta_description(body_html)
    jsonld = _jsonld({
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title,
        "description": description,
        "datePublished": date_str,
        "url": url,
        "mainEntityOfPage": url,
        "author": {"@type": "Organization", "name": BLOG_BRAND},
        "publisher": {"@type": "Organization", "name": BLOG_BRAND},
    })
    return f"""<!DOCTYPE html>
<html lang="en">
{_head(f"{safe_title} — {html_mod.escape(BLOG_BRAND)}", description=description, canonical=url, og_type="article")}
<body>
  {_header_html()}
  <div class="container">
    <article>
      <a class="back" href="/">&larr; All posts</a>
      <h1>{safe_title}</h1>
      <div class="post-meta">{html_mod.escape(date_str)}</div>
      <div class="post-body">{body_html}</div>
      {_subscribe_cta()}
      {_read_next_html(recent_posts, slug)}
    </article>
  </div>
  {_footer_html()}
  {jsonld}
</body>
</html>"""


def _index_html(posts):
    """posts: list of {title, slug, date} dicts, any order. Newest first by date."""
    ordered = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)
    items = ""
    for p in ordered:
        t = html_mod.escape(p.get("title", ""))
        slug = p.get("slug", "")
        d = html_mod.escape(p.get("date", ""))
        items += f"""      <li>
        <a class="post-link" href="/posts/{slug}.html">{t}</a>
        <span class="date">{d}</span>
      </li>\n"""
    home = f"https://{BLOG_DOMAIN}/"
    index_desc = f"{BLOG_TAGLINE}. Concrete prompts, workflows, and lessons from shipping software with AI."
    jsonld = _jsonld({
        "@context": "https://schema.org",
        "@type": "Blog",
        "name": BLOG_BRAND,
        "description": index_desc,
        "url": home,
        "publisher": {"@type": "Organization", "name": BLOG_BRAND},
    })
    return f"""<!DOCTYPE html>
<html lang="en">
{_head(html_mod.escape(BLOG_BRAND), description=index_desc, canonical=home, og_type="website")}
<body>
  {_header_html()}
  <div class="container">
    <section class="hero">
      <h1>{html_mod.escape(BLOG_BRAND)}</h1>
      <p>{html_mod.escape(index_desc)}</p>
    </section>
    <ul class="posts">
{items}    </ul>
  </div>
  {_footer_html()}
  {jsonld}
</body>
</html>"""


# Free lead-magnet prompts — a genuinely useful, linkable free asset. Doubles
# as an SEO landing page ("free AI prompts for engineers"), a conversion
# surface (subscribe CTA), and a taste of the paid 50-prompt product.
_FREE_PROMPTS = [
    ("Pre-PR self-review",
     "You are a senior engineer reviewing my diff before I open a PR. Here is the diff:\n\n[PASTE DIFF]\n\nList, in priority order: (1) bugs or edge cases I likely missed, (2) anything that will confuse a reviewer, (3) tests I should add. Be specific and cite the exact lines. Don't praise; only flag what needs attention."),
    ("Debug a stack trace",
     "Here is a stack trace and the relevant code. Stack trace:\n\n[PASTE]\n\nCode:\n\n[PASTE]\n\nGive me the 3 most likely root causes ranked by probability, the single fastest check to confirm each, and the minimal fix for the most likely one. Assume I know the codebase; skip the basics."),
    ("Plan a refactor safely",
     "I want to refactor [DESCRIBE]. Before any code, produce: (1) the smallest first step that's independently shippable, (2) the exact order of steps so the system stays green at every commit, (3) what could break and how I'd catch it. Then wait for me to approve the plan."),
    ("Break down a fuzzy task for estimation",
     "Here's a ticket: [PASTE]. Decompose it into concrete subtasks of <1 day each. For each, note the main unknown and how to resolve it cheaply. Flag the 1-2 subtasks most likely to blow up the estimate, and why."),
    ("Draft an ADR",
     "Help me write an Architecture Decision Record for: [DECISION]. Context: [CONSTRAINTS]. Output the standard ADR sections (Context, Decision, Alternatives considered, Consequences). For alternatives, give the honest trade-off that made me reject each — not strawmen."),
    ("Generate the test cases I'd forget",
     "Here is a function and its intended behavior:\n\n[PASTE]\n\nList the test cases worth writing, grouped as: happy path, boundaries, error handling, and concurrency/ordering if relevant. For each, one line on what it protects against. Then write the table-driven tests in [LANGUAGE/FRAMEWORK]."),
    ("Rubber-duck a design before you build",
     "I'm about to build [DESIGN]. Act as a skeptical staff engineer. Ask me the 5 questions that would most likely expose a flaw in this design, one at a time, waiting for my answer before the next. Don't propose solutions until you've heard my answers."),
    ("Review someone else's PR fast",
     "Here's a PR diff I need to review:\n\n[PASTE]\n\nSummarize what it does in 3 bullets, then give me only the comments worth leaving: correctness risks, missing tests, and anything that increases long-term maintenance cost. Skip style nits a linter would catch."),
]


def _free_prompts_html():
    home = f"https://{BLOG_DOMAIN}/"
    url = f"{home}free-prompts.html"
    title = f"8 Free AI Prompts for Engineers — {html_mod.escape(BLOG_BRAND)}"
    desc = ("8 copy-paste AI prompts engineers actually use: pre-PR self-review, "
            "debugging, refactor planning, ADRs, test generation, and more.")
    cards = ""
    for i, (name, prompt) in enumerate(_FREE_PROMPTS, 1):
        cards += (f'<h2>{i}. {html_mod.escape(name)}</h2>\n'
                  f'<pre><code>{html_mod.escape(prompt)}</code></pre>\n')
    jsonld = _jsonld({
        "@context": "https://schema.org", "@type": "WebPage",
        "name": "8 Free AI Prompts for Engineers", "description": desc, "url": url,
        "publisher": {"@type": "Organization", "name": BLOG_BRAND},
    })
    return f"""<!DOCTYPE html>
<html lang="en">
{_head(title, description=desc, canonical=url, og_type="website")}
<body>
  {_header_html()}
  <div class="container">
    <article>
      <a class="back" href="/">&larr; All posts</a>
      <h1>8 Free AI Prompts for Engineers</h1>
      <div class="post-meta">Copy, paste, adapt — no signup required</div>
      <div class="post-body">
        <p>These are eight of the prompts I actually reach for while shipping software with AI. Steal them. Each is written to give you a useful answer on the first try — replace the bracketed parts and go.</p>
        {cards}
      </div>
      {_subscribe_cta()}
    </article>
  </div>
  {_footer_html()}
  {jsonld}
</body>
</html>"""


def publish_free_prompts_page():
    """Generate/refresh the free lead-magnet prompts page. Cheap + idempotent."""
    _gh_put("docs/free-prompts.html", _free_prompts_html(), "Update free prompts page")
    return f"https://{BLOG_DOMAIN}/free-prompts.html"


def _sitemap_xml(posts):
    home = f"https://{BLOG_DOMAIN}/"
    rows = [f"  <url><loc>{home}</loc></url>",
            f"  <url><loc>{home}free-prompts.html</loc></url>"]
    for p in sorted(posts, key=lambda p: p.get("date", ""), reverse=True):
        slug = p.get("slug", "")
        if not slug:
            continue
        lastmod = html_mod.escape(p.get("date", ""))
        rows.append(f"  <url><loc>https://{BLOG_DOMAIN}/posts/{slug}.html</loc>"
                    f"<lastmod>{lastmod}</lastmod></url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def _robots_txt():
    return (f"User-agent: *\nAllow: /\n\n"
            f"Sitemap: https://{BLOG_DOMAIN}/sitemap.xml\n")


def publish_article(title, body_html, date_str, recent_posts=None):
    """Publish one article page. Returns (slug, public URL). Raises on failure.
    recent_posts (prior posts) powers the internal 'Read next' links."""
    slug = slugify(title)
    page = _article_html(title, body_html, date_str, recent_posts=recent_posts)
    _gh_put(f"docs/posts/{slug}.html", page, f"Publish post: {title}")
    return slug, f"https://{BLOG_DOMAIN}/posts/{slug}.html"


def update_index(posts):
    """Regenerate docs/index.html plus sitemap.xml and robots.txt from the full
    posts list (sitemap + robots help search engines discover every post)."""
    _gh_put("docs/index.html", _index_html(posts), "Update blog index")
    _gh_put("docs/sitemap.xml", _sitemap_xml(posts), "Update sitemap")
    _gh_put("docs/robots.txt", _robots_txt(), "Update robots.txt")
    publish_free_prompts_page()
