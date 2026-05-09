"""
Image generation via Replicate's FLUX models.

Given a list of {use_case, prompt} dicts (the output of generate_image_prompts),
generates real images and returns local paths. Falls through cleanly if
REPLICATE_API_TOKEN is missing -- the agent simply doesn't generate images.
"""

import os
import re
import time
import requests

REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
HAS_REPLICATE = REPLICATE_API_TOKEN not in ("", "FILL_IN_LATER")

# FLUX schnell -- the cheapest and fastest decent FLUX variant on Replicate,
# good enough for Etsy product photography mockups. ~$0.003 per image, ~5s.
# If you want higher quality at higher cost, switch to "black-forest-labs/flux-dev".
REPLICATE_MODEL = os.environ.get("REPLICATE_MODEL", "black-forest-labs/flux-schnell")

REPLICATE_API_BASE = "https://api.replicate.com/v1"


def _slugify(text, max_len=40):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len] or "image"


def _create_prediction(prompt_text, aspect_ratio="1:1"):
    """Start a Replicate prediction; returns the prediction dict."""
    r = requests.post(
        f"{REPLICATE_API_BASE}/models/{REPLICATE_MODEL}/predictions",
        headers={
            "Authorization": f"Bearer {REPLICATE_API_TOKEN}",
            "Content-Type": "application/json",
            "Prefer": "wait",  # Replicate will block up to 60s for the result
        },
        json={
            "input": {
                "prompt": prompt_text,
                "aspect_ratio": aspect_ratio,
                "output_format": "jpg",
                "output_quality": 90,
                "num_outputs": 1,
            }
        },
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _poll_for_completion(prediction_id, max_seconds=120):
    """Replicate's prefer:wait header usually returns the result inline. If it
    returns a still-running prediction, poll until done."""
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        r = requests.get(
            f"{REPLICATE_API_BASE}/predictions/{prediction_id}",
            headers={"Authorization": f"Bearer {REPLICATE_API_TOKEN}"},
            timeout=30,
        )
        r.raise_for_status()
        pred = r.json()
        status = pred.get("status")
        if status in ("succeeded", "failed", "canceled"):
            return pred
        time.sleep(2)
    raise TimeoutError(f"Replicate prediction {prediction_id} didn't finish in {max_seconds}s")


def _download_image(url, out_path):
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


def generate_images(prompts, output_dir, item_id="img", limit=None):
    """
    For each prompt dict ({use_case, prompt}), call Replicate, save the image
    locally, return list of {use_case, prompt, path, error}.

    `limit`: cap on how many prompts to actually generate (default: all of them).
    Use this to control cost when prompts are plentiful.
    """
    if not HAS_REPLICATE:
        return []

    os.makedirs(output_dir, exist_ok=True)
    if limit is not None:
        prompts = prompts[:limit]

    results = []
    for i, p in enumerate(prompts, 1):
        prompt_text = p.get("prompt", "") if isinstance(p, dict) else ""
        use_case = p.get("use_case", f"image_{i}") if isinstance(p, dict) else f"image_{i}"
        if not prompt_text:
            results.append({"use_case": use_case, "prompt": "", "path": None, "error": "empty prompt"})
            continue

        out = {"use_case": use_case, "prompt": prompt_text, "path": None, "error": None}
        try:
            print(f"  Etsy image {i}/{len(prompts)} [{use_case}]: generating via Replicate...")
            pred = _create_prediction(prompt_text)
            if pred.get("status") not in ("succeeded", "starting", "processing"):
                raise RuntimeError(f"Replicate returned status={pred.get('status')}: {pred.get('error', 'no error msg')}")

            if pred.get("status") != "succeeded":
                pred = _poll_for_completion(pred["id"])

            if pred.get("status") != "succeeded":
                raise RuntimeError(f"Replicate failed: status={pred.get('status')} error={pred.get('error', '')}")

            output = pred.get("output")
            if isinstance(output, list):
                output = output[0] if output else None
            if not output:
                raise RuntimeError(f"Replicate returned no output URL")

            slug = _slugify(use_case)
            filename = f"{item_id}_{i:02d}_{slug}.jpg"
            path = os.path.join(output_dir, filename)
            _download_image(output, path)
            out["path"] = path
            print(f"  Etsy image {i}/{len(prompts)} [{use_case}]: ✅ saved to {filename}")
        except Exception as e:
            out["error"] = str(e)
            print(f"  Etsy image {i}/{len(prompts)} [{use_case}]: ❌ {e}")

        results.append(out)

    return results
