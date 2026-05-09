"""
Etsy queue processor.

Reads etsy_queue.json from the project root, processes any queue items whose
`id` is NOT yet in state['etsy_processed'], and returns the newly-generated
results so the daily report email can include them. Item IDs are recorded in
state on success so we don't re-process across deploys.
"""

import json
import os
import datetime

from .generators import generate_listings, generate_image_prompts

QUEUE_FILE = "etsy_queue.json"


def load_queue():
    if not os.path.exists(QUEUE_FILE):
        return {"items": []}
    try:
        with open(QUEUE_FILE) as f:
            return json.load(f)
    except Exception as e:
        print(f"  Etsy queue: failed to read {QUEUE_FILE}: {e}")
        return {"items": []}


def process_etsy_queue(state):
    """
    For every item in etsy_queue.json with an id we haven't seen, generate
    listings + image prompts and record the id in state['etsy_processed'].

    Returns a list of dicts (one per newly-processed item):
        [{
            "id": str, "niche": str, "product": str,
            "listings": [...], "image_prompts": [...],
            "error": Optional[str],
        }, ...]
    """
    queue = load_queue()
    items = queue.get("items", []) or []
    processed_ids = set(state.get("etsy_processed", []))
    today = str(datetime.date.today())

    results = []
    for item in items:
        item_id = item.get("id")
        if not item_id or item_id in processed_ids:
            continue

        niche = item.get("niche", "")
        product = item.get("product", "")
        if not niche or not product:
            print(f"  Etsy queue: skipping item {item_id!r} -- missing niche/product")
            continue

        n_listings = int(item.get("n_listings", 10))
        n_prompts = int(item.get("n_image_prompts", 15))
        min_price = float(item.get("min_price", 5))
        max_price = float(item.get("max_price", 15))
        style = item.get("image_style", "")

        out = {"id": item_id, "niche": niche, "product": product, "listings": [], "image_prompts": [], "error": None}
        try:
            print(f"  Etsy: generating listings for {item_id!r}: {product[:60]}...")
            out["listings"] = generate_listings(niche, product, min_price, max_price, n_listings)
            print(f"  Etsy: generating image prompts for {item_id!r}...")
            out["image_prompts"] = generate_image_prompts(product, style, n_prompts)
            processed_ids.add(item_id)
            state.setdefault("etsy_processed", []).append(item_id)
            state.setdefault("etsy_history", []).append({
                "id": item_id,
                "niche": niche,
                "product": product,
                "date": today,
                "listings_count": len(out["listings"]),
                "prompts_count": len(out["image_prompts"]),
            })
            print(f"  Etsy: ✅ {item_id!r} -- {len(out['listings'])} listings, {len(out['image_prompts'])} prompts")
        except Exception as e:
            out["error"] = str(e)
            print(f"  Etsy: ❌ {item_id!r} -- {e}")
            # Don't mark as processed; will retry on next run.

        results.append(out)

    return results
