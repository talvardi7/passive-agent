# Final setup — get it running on Render

You only need to do 3 things. Follow them in order. Don't skip ahead.

---

## 1. Create Gmail app password (3 min)

This is what the agent uses to send you the daily email reports.

1. Open https://myaccount.google.com/security
2. Look for **2-Step Verification**. If it says **Off**, click it and turn it on (you can't make an app password without it). Do this first; it takes ~2 min.
3. Once 2-Step Verification is on, open https://myaccount.google.com/apppasswords
4. In the "App name" field, type: `Passive Agent`
5. Click **Create**
6. Google will show you a 16-character password in a yellow box. **Remove the spaces** so it's one continuous string.
7. Save that 16-character string somewhere safe — it's the value for `SMTP_APP_PASSWORD` in step 3.

> If `myaccount.google.com/apppasswords` says "the setting you're looking for is not available," it means 2-Step Verification isn't fully on yet. Go back to step 2.

---

## 2. Create Hacker News account (2 min)

This is what the agent uses to submit your DEV.to articles to Hacker News on Mon/Wed/Fri.

1. Open https://news.ycombinator.com/login
2. The page has two forms — **Login** at the top, **Create Account** at the bottom. Use the bottom one.
3. Pick a username. Try `talvardi7` first; if taken, try `talvardi-builds` or `talvardi-ai`.
4. Pick a strong password (at least 12 characters, mix of letters/numbers).
5. Click **create account**.
6. Save the username and password somewhere safe — they're `HN_USERNAME` and `HN_PASSWORD` in step 3.

> Note: HN won't let new accounts post comments for ~2 weeks. URL submissions (which is what the agent does) work right away. So this is fine.

---

## 3. Paste environment variables into Render (3 min)

1. Open https://dashboard.render.com
2. Find your service connected to the `talvardi7/passive-agent` GitHub repo. Click it.
3. Click **Environment** in the left sidebar.
4. For each row in the table below, click **Add Environment Variable** (or update the existing row if it's already there). Type the **Key** exactly as shown, and put the **Value** as described.

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | copy from `passive_agent/.env` on your computer |
| `GUMROAD_ACCESS_TOKEN` | copy from `passive_agent/.env` |
| `GUMROAD_PRODUCT_ID` | `nhltvo` |
| `GUMROAD_PRODUCT_URL` | `https://gumroad.com/l/nhltvo` |
| `DEVTO_API_KEY` | copy from `passive_agent/.env` |
| `BEEHIIV_API_KEY` | copy from `passive_agent/.env` |
| `BEEHIIV_PUBLICATION_ID` | copy from `passive_agent/.env` |
| `REPORT_EMAIL` | `talvardi7@gmail.com` |
| `SMTP_EMAIL` | `talvardi7@gmail.com` |
| `SMTP_APP_PASSWORD` | the 16-character string from **Step 1** |
| `HN_USERNAME` | the username from **Step 2** |
| `HN_PASSWORD` | the password from **Step 2** |

> "Copy from `passive_agent/.env` on your computer" means: open the file at `C:\Users\talva\Downloads\passive_income_agent_FINAL_v2\passive_agent\.env` in Notepad, find the line for that key (e.g. `ANTHROPIC_API_KEY=sk-ant-api03-...`), and copy everything after the `=` sign.

5. Click **Save Changes** at the bottom. Render will start a redeploy automatically.
6. Click **Logs** in the left sidebar. Wait up to 90 seconds.
7. You should see this banner appear in the logs:

```
🤖 Passive Income Agent
   DEV.to:     ✅
   Hacker News:✅
   Newsletter: ✅
   Email:      ✅
```

**All four should be ✅.** If any are ⏭, that env var didn't get saved properly — go back to step 4 and re-paste it.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| One or more banner lines show ⏭ | The env var for that service is missing or empty in Render. Go back to step 4 and re-paste it. |
| Deploy fails — no banner appears | In Render → **Logs**, scroll up to find the error. Copy the last 20 lines and paste them in Claude Code. |
| No banner at all, no errors, just silence after 2 min | Render service might be paused. In dashboard → click your service → top-right **Manual Deploy** → **Deploy latest commit**. |
| You can't find your service on Render | If the deploy was never set up, that's a separate task — tell Claude Code "I never set up Render in the first place" and it'll walk you through that instead. |

---

## After all four are ✅

You're done. The agent runs daily at 09:00 UTC. You'll get an email report every day at `talvardi7@gmail.com`. The first auto-published post fires on the next Monday/Wednesday/Friday after the deploy goes live. Wait for it. Don't touch anything else.
