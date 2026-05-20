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
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { font-family: Georgia, 'Times New Roman', serif; max-width: 680px; margin: 0 auto;
         color: #1a1a1a; line-height: 1.7; padding: 32px 20px 64px; background: #fff; }
  a { color: #4f46e5; }
  .masthead { border-bottom: 1px solid #e5e7eb; padding-bottom: 16px; margin-bottom: 32px; }
  .masthead .brand { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em;
                     color: #6b7280; text-decoration: none; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .masthead .tagline { font-size: 12px; color: #9ca3af; margin-top: 2px;
                       font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  h1 { font-size: 30px; line-height: 1.25; margin: 0 0 8px; }
  .post-date { font-size: 13px; color: #9ca3af; margin-bottom: 28px;
               font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .post-body h2 { font-size: 21px; margin-top: 32px; }
  .post-body pre { background: #f4f4f4; border-left: 3px solid #4f46e5; padding: 14px 16px;
                   overflow-x: auto; border-radius: 4px; font-size: 14px;
                   font-family: ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; }
  .post-body code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.92em; }
  .footer { margin-top: 48px; padding-top: 24px; border-top: 1px solid #e5e7eb;
            font-size: 14px; color: #6b7280;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
  .post-list { list-style: none; padding: 0; }
  .post-list li { padding: 16px 0; border-bottom: 1px solid #f0f0f0; }
  .post-list a { font-size: 19px; text-decoration: none; font-weight: 600; }
  .post-list .date { display: block; font-size: 13px; color: #9ca3af; margin-top: 4px;
                     font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }
"""


def _masthead_html():
    return f"""<div class="masthead">
    <a class="brand" href="/">{html_mod.escape(BLOG_BRAND)}</a>
    <div class="tagline">{html_mod.escape(BLOG_TAGLINE)}</div>
  </div>"""


def _footer_html():
    sub = f' &middot; <a href="{html_mod.escape(BLOG_SUBSCRIBE_URL)}">Subscribe to the newsletter</a>' if BLOG_SUBSCRIBE_URL else ""
    return f"""<div class="footer">
    <a href="/">&larr; All posts</a>{sub}
  </div>"""


def _article_html(title, body_html, date_str):
    safe_title = html_mod.escape(title)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} — {html_mod.escape(BLOG_BRAND)}</title>
  <style>{_PAGE_CSS}</style>
</head>
<body>
  {_masthead_html()}
  <article>
    <h1>{safe_title}</h1>
    <div class="post-date">{html_mod.escape(date_str)}</div>
    <div class="post-body">{body_html}</div>
  </article>
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
        items += f"""    <li>
      <a href="/posts/{slug}.html">{t}</a>
      <span class="date">{d}</span>
    </li>\n"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_mod.escape(BLOG_BRAND)}</title>
  <style>{_PAGE_CSS}</style>
</head>
<body>
  {_masthead_html()}
  <ul class="post-list">
{items}  </ul>
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
