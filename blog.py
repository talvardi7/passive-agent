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
      {_subscribe_btn()}
    </div>
  </header>"""


def _footer_html():
    sub = f' &middot; <a href="{html_mod.escape(BLOG_SUBSCRIBE_URL)}">Subscribe</a>' if BLOG_SUBSCRIBE_URL else ""
    year = datetime.date.today().year
    return f"""<footer class="site-footer">
    <div class="container">
      <span>&copy; {year} {html_mod.escape(BLOG_BRAND)}</span>
      <span><a href="/">All posts</a>{sub}</span>
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


def _head(title):
    return f"""<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{_PAGE_CSS}</style>
</head>"""


def _article_html(title, body_html, date_str):
    safe_title = html_mod.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
{_head(f"{safe_title} — {html_mod.escape(BLOG_BRAND)}")}
<body>
  {_header_html()}
  <div class="container">
    <article>
      <a class="back" href="/">&larr; All posts</a>
      <h1>{safe_title}</h1>
      <div class="post-meta">{html_mod.escape(date_str)}</div>
      <div class="post-body">{body_html}</div>
      {_subscribe_cta()}
    </article>
  </div>
  {_footer_html()}
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
    return f"""<!DOCTYPE html>
<html lang="en">
{_head(html_mod.escape(BLOG_BRAND))}
<body>
  {_header_html()}
  <div class="container">
    <section class="hero">
      <h1>{html_mod.escape(BLOG_BRAND)}</h1>
      <p>{html_mod.escape(BLOG_TAGLINE)}. Concrete prompts, workflows, and lessons from shipping software with AI.</p>
    </section>
    <ul class="posts">
{items}    </ul>
  </div>
  {_footer_html()}
</body>
</html>"""


def publish_article(title, body_html, date_str):
    """Publish one article page. Returns the public URL. Raises on failure."""
    slug = slugify(title)
    page = _article_html(title, body_html, date_str)
    _gh_put(f"docs/posts/{slug}.html", page, f"Publish post: {title}")
    return slug, f"https://{BLOG_DOMAIN}/posts/{slug}.html"


def update_index(posts):
    """Regenerate docs/index.html from the full posts list."""
    _gh_put("docs/index.html", _index_html(posts), "Update blog index")
