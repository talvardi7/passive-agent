# Passive Income Agent — Setup Guide
## From zero to fully autonomous in ~45 minutes

---

## What this does
Every Monday at 9am UTC, automatically:
1. Checks your Gumroad sales
2. Generates fresh content using Claude AI
3. Posts to Reddit, LinkedIn, Twitter/X
4. Sends your newsletter via Beehiiv
5. Emails you a weekly sales report

Your involvement: read the weekly email. That's it.

---

## Step 1 — Get a free server (10 min)

1. Go to **render.com** and sign up (free)
2. Click **New → Background Worker**
3. Connect your GitHub account
4. Upload the agent files to a new GitHub repo (or use the Render shell)
5. Set environment variables in Render dashboard (see Step 3)

**Alternative: Railway.app** (also free tier, easier UI)
- railway.app → New Project → Deploy from GitHub

---

## Step 2 — Get your API keys (25 min)

### Anthropic (Claude API) — 5 min
1. Go to console.anthropic.com
2. API Keys → Create Key
3. Copy it → paste as `ANTHROPIC_API_KEY`

### Gumroad — 3 min
1. gumroad.com → Settings → Advanced
2. "Generate Access Token"
3. Your product ID is in your product URL: gumroad.com/l/**THIS_PART**

### Reddit — 5 min
1. reddit.com/prefs/apps → "Create another app"
2. Choose **script** type
3. Name: "PassiveAgent", redirect: http://localhost
4. Copy client_id (under app name) and secret

### LinkedIn — 8 min
1. linkedin.com/developers → Create App
2. Add "Share on LinkedIn" product
3. Generate OAuth 2.0 token with `w_member_social` scope
4. Get your person URN: visit `https://api.linkedin.com/v2/userinfo` with your token

### Twitter/X — 5 min
1. developer.twitter.com → Create Project → Create App
2. Set permissions to **Read and Write**
3. Generate Access Token & Secret (under "Keys and Tokens")

### Beehiiv (newsletter) — 3 min
1. beehiiv.com → Sign up free
2. Settings → Integrations → API
3. Create API key, copy Publication ID

### Gmail App Password (for report emails) — 2 min
1. myaccount.google.com → Security
2. 2-Step Verification must be ON
3. Search "App passwords" → Generate → Select "Mail"
4. Copy the 16-character password

---

## Step 3 — Deploy (10 min)

### On Render.com:
```bash
# In Render dashboard → Environment tab, add each variable from .env.template
# Then in the Build Command field:
pip install -r requirements.txt

# Start Command:
python agent.py
```

### Or run locally first to test:
```bash
cd passive_agent
pip install -r requirements.txt
cp .env.template .env
# Fill in your .env file with real keys
export $(cat .env | xargs)
python agent.py
```

---

## Step 4 — Verify it's working

On first run the agent will:
- Post to Reddit immediately (check your Reddit profile)
- Post to LinkedIn (check your feed)
- Send a Twitter thread (check your profile)
- Send your newsletter issue 1
- Email you a report

If anything fails, the weekly report will show ❌ with the error.

---

## What to expect week by week

| Week | Expected outcome |
|------|-----------------|
| 1–2  | First posts live, 0–3 sales |
| 3–4  | Reddit karma building, 3–10 sales |
| 5–8  | SEO traffic starts, 10–30 sales/mo |
| 2–3 months | $200–$600/mo passive |
| 4–6 months | $500–$2000/mo with zero involvement |

---

## Costs

| Service | Cost |
|---------|------|
| Render.com (server) | Free tier |
| Anthropic API | ~$2–5/month |
| Beehiiv newsletter | Free up to 2,500 subscribers |
| Reddit, LinkedIn, Twitter | Free |
| **Total** | **~$2–5/month** |

---

## Troubleshooting

**Agent not posting to Reddit:**
- Check your Reddit account has karma (new accounts get blocked)
- Solution: manually post 3-4 times first, then let agent take over

**LinkedIn token expired:**
- LinkedIn tokens expire every 60 days
- Solution: refresh at linkedin.com/developers every 2 months

**Twitter rate limited:**
- Free tier allows 1,500 tweets/month — you're safe
- If blocked: wait 15 min, agent will retry next week

---

## Files in this package
- `agent.py` — the full autonomous agent
- `requirements.txt` — Python dependencies
- `.env.template` — all environment variables you need to fill
- `SETUP.md` — this guide
