"""
Etsy listing + image-prompt generators.

Pure functions: take a product spec, return structured Python data. No I/O,
no Etsy API calls (those come later). Uses Anthropic tool-use so the model
output is guaranteed structured and we never parse JSON from text.
"""

import os
import re
from anthropic import Anthropic

_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

LISTING_TOOL = {
    "name": "submit_listings",
    "description": "Return a batch of Etsy listing variations for a single product",
    "input_schema": {
        "type": "object",
        "properties": {
            "listings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Etsy title, max 140 chars, primary keyword first"},
                        "description": {"type": "string", "description": "Listing body, 200-400 words"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "Exactly 13 tags, each <=20 chars, lowercase, alphanumeric+spaces only"},
                        "category": {"type": "string", "description": "Full Etsy category path, e.g. 'Paper > Stationery > Planners'"},
                        "suggested_price_usd": {"type": "number"},
                        "angle": {"type": "string", "description": "What makes this variation distinct from the others (e.g. 'targets brides on a budget', 'emphasizes minimalism')"},
                    },
                    "required": ["title", "description", "tags", "category", "suggested_price_usd", "angle"],
                },
            }
        },
        "required": ["listings"],
    },
}

IMAGE_PROMPT_TOOL = {
    "name": "submit_image_prompts",
    "description": "Return a batch of image-generation prompts for an Etsy listing's photos",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "use_case": {"type": "string", "description": "What the image is for, e.g. 'main listing photo', 'mockup on iPad', 'flatlay with props', 'detail close-up'"},
                        "prompt": {"type": "string", "description": "20-60 word image-gen prompt, model-agnostic (works in Midjourney, DALL-E, Replicate)"},
                    },
                    "required": ["use_case", "prompt"],
                },
            }
        },
        "required": ["prompts"],
    },
}


def _clean_tag(t):
    # Etsy tag rules: <=20 chars, lowercase, alphanumeric + spaces, no commas
    t = re.sub(r"[^a-z0-9 ]", "", str(t).lower()).strip()
    t = re.sub(r"\s+", " ", t)
    return t[:20]


def generate_listings(niche, product, min_price=5.0, max_price=15.0, n=10):
    """Generate `n` Etsy listing variations for a niche+product. Returns list of dicts."""
    system = (
        "You are an Etsy SEO expert and copywriter. Your listings are tuned for "
        "Etsy's search algorithm and convert browsers into buyers. You know the rules:\n"
        "- Title <=140 chars, lead with the primary keyword, include 'digital download' "
        "or 'printable' if it's a digital product.\n"
        "- 13 tags exactly. Each tag <=20 chars, lowercase, only letters/numbers/spaces "
        "(no commas, no special chars). Mix short-tail and long-tail keywords.\n"
        "- Description structure: hook -> what's included -> who it's for -> instant "
        "download note -> soft CTA. 200-400 words.\n"
        "- Vary angle/hook across the batch so we can test which converts.\n"
        "Use the submit_listings tool to return your output."
    )

    prompt = (
        f"Generate {n} Etsy listing variations for this product:\n\n"
        f"Niche: {niche}\n"
        f"Product: {product}\n"
        f"Target price range: ${min_price:.2f}-${max_price:.2f}\n\n"
        f"Each variation should test a different angle (use case, buyer persona, "
        f"feature emphasis, season/occasion, etc.). Make them genuinely different, "
        f"not paraphrases of each other.\n\n"
        f"Call submit_listings with all {n} variations."
    )

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[LISTING_TOOL],
        tool_choice={"type": "tool", "name": LISTING_TOOL["name"]},
    )

    listings = None
    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            listings = list(dict(block.input).get("listings", []))
            break
    if listings is None:
        raise ValueError(f"Model didn't call submit_listings. stop_reason={response.stop_reason}")

    # Sanitize tags per Etsy's rules
    for L in listings:
        if isinstance(L.get("tags"), list):
            cleaned = []
            for t in L["tags"]:
                ct = _clean_tag(t)
                if ct and ct not in cleaned:
                    cleaned.append(ct)
            L["tags"] = cleaned[:13]

    return listings


def generate_image_prompts(product, style="", n=15):
    """Generate `n` image-gen prompts for a product's Etsy photos. Returns list of dicts."""
    style_clause = f" The visual style should be: {style}." if style else ""
    system = (
        "You write image-generation prompts that produce polished, photorealistic, "
        "Etsy-ready product photography. Your prompts work across Midjourney, DALL-E, "
        "and Stable Diffusion. You vary the use case, composition, lighting, and "
        "props across a batch so the buyer sees the product in multiple contexts."
    )

    prompt = (
        f"Generate {n} image-generation prompts for an Etsy listing of:\n\n"
        f"Product: {product}\n"
        f"{style_clause}\n\n"
        f"Etsy listings need 5-10 photos. Across the batch, cover these use cases:\n"
        f"- 1-2 main listing photos (clear hero shot, attention-grabbing)\n"
        f"- 2-3 mockups (product on a tablet, on a desk, on a wall, in-hand)\n"
        f"- 2-3 styled lifestyle shots with realistic props\n"
        f"- 2-3 flatlays\n"
        f"- 2-3 detail/close-up shots\n\n"
        f"Each prompt: 20-60 words, model-agnostic, includes lighting + color palette + "
        f"composition descriptors, avoids words that trigger content filters.\n\n"
        f"Call submit_image_prompts."
    )

    response = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[IMAGE_PROMPT_TOOL],
        tool_choice={"type": "tool", "name": IMAGE_PROMPT_TOOL["name"]},
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use":
            return list(dict(block.input).get("prompts", []))
    raise ValueError(f"Model didn't call submit_image_prompts. stop_reason={response.stop_reason}")
