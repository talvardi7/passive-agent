# Etsy agent

Generates Etsy listings (titles, descriptions, tags) and matching image-generation prompts for digital download products. Runs as part of the existing daily job on Render — no separate deploy.

## How it works

1. You add a product idea to `etsy_queue.json` at the project root (via the GitHub web editor — no local Python needed).
2. You push the change. Render auto-deploys.
3. The next time `daily_job` fires (on deploy startup OR at 09:00 UTC), the agent reads `etsy_queue.json`, finds any item whose `id` is not already in `state.etsy_processed`, generates listings + image prompts via the Anthropic API, and includes them in the daily email.
4. The item's `id` is recorded in `state.json` so the same item is **never re-processed** — even across redeploys.

## Queue schema

`etsy_queue.json`:

```json
{
  "items": [
    {
      "id": "wedding-planner-001",
      "niche": "wedding planning",
      "product": "12-month engagement planner with budget tracker, vendor checklist, and seating chart templates",
      "min_price": 7,
      "max_price": 12,
      "n_listings": 10,
      "n_image_prompts": 15,
      "image_style": "minimalist black and white, sage green accents"
    }
  ]
}
```

| Field | Required | Default | Notes |
|---|---|---|---|
| `id` | yes | — | Unique string. Used for idempotency. Once processed, never re-runs. |
| `niche` | yes | — | Etsy sub-niche (e.g. `"wedding planning"`, `"meal prep"`). Drives keyword strategy. |
| `product` | yes | — | The actual thing you're selling. Be specific — generic in, generic out. |
| `min_price` | no | 5.0 | Lower bound for `suggested_price_usd` field on each generated listing. |
| `max_price` | no | 15.0 | Upper bound. |
| `n_listings` | no | 10 | How many listing variations to generate (different angles per variation). |
| `n_image_prompts` | no | 15 | How many image-gen prompts to generate (mix of hero/mockup/flatlay/detail/lifestyle). |
| `image_style` | no | "" | Style direction for the photos. E.g. `"minimalist black and white"`, `"warm earth tones, hygge"`. |

## What you get back (via email)

A new section in the daily report titled **"Etsy queue — generated today"**, with one card per processed item containing:

- Each generated listing as a `<details>` toggle (title, angle, category, price, tags, full description)
- All image-generation prompts as a numbered list, each labeled with use case (hero / mockup / flatlay / detail / lifestyle)

You then:
1. Copy/paste the listing into Etsy's "Add a listing" form (manual upload — Etsy ToS requires this until you've got their API approved)
2. Run each image prompt through Midjourney / DALL-E / Replicate to produce the actual photos
3. Polish the result in Canva
4. Publish

## Adding to the queue (no local Python needed)

1. Open https://github.com/talvardi7/passive-agent/blob/main/etsy_queue.json
2. Click the pencil icon to edit
3. Add a new item to the `items` array
4. Commit (top of page) — this auto-pushes to main
5. Render auto-deploys (~5 min)
6. Wait for the next daily email (or restart the Render service to trigger immediately)

## Roadmap (not yet built)

- **Stage 2** — wire up image generation via Replicate API (so the agent produces actual images, not just prompts). Adds ~$0.005-0.05/image cost.
- **Stage 3** — Etsy API integration: auto-create listings on your shop, track sales, auto-generate variations of bestsellers. Requires approved Etsy developer account.
- **Stage 4** — bestseller iteration loop: read sales data daily, queue more variations of winners, retire underperformers automatically.

## Why a queue file instead of a CLI

Your local machine doesn't have Python. Render's shell access depends on plan tier. A queue file in git is the lowest-friction interface: you edit one JSON file in GitHub's web UI and the agent picks up the work autonomously.
