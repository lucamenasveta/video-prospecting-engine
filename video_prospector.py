"""
Video Prospecting Engine — turn a prospect CSV into ready-to-record video assets.

For each prospect it finds one real, recent, cited buying signal, writes a
~30-second video script around it (hook -> bridge -> value -> soft CTA), drafts
an email subject line, and renders a branded 1280x720 thumbnail.

Two providers:
    anthropic  — Claude + the web_search tool (finds a real, cited signal). Needs
                 ANTHROPIC_API_KEY and the `anthropic` package.
    mock       — fully offline, deterministic. Synthesizes an obviously-fake
                 placeholder signal so you can demo the pipeline with no API.

Usage:
    python video_prospector.py prospects.csv
    python video_prospector.py prospects.csv --provider anthropic
    python video_prospector.py prospects.csv --brand "Lineage Studio" --limit 3

Outputs (default ./output):
    scripts.md      one section per prospect (signal, subject, script)
    results.csv     one row per prospect (machine-readable)
    gallery.html    thumbnails + scripts in a browsable grid
    thumbnails/*.png

Input CSV columns (extra columns are ignored):
    first_name, company, role, industry, website
"""

import argparse
import base64
import csv
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Prospect:
    first_name: str
    company: str
    role: str = ""
    industry: str = ""
    website: str = ""


@dataclass
class Asset:
    """Everything produced for one prospect, ready to record."""

    prospect: Prospect
    signal: str = ""
    signal_source: str = ""
    subject: str = ""
    stages: dict = field(default_factory=dict)  # hook / bridge / value / cta
    thumbnail_path: str = ""
    status: str = "ok"


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------


def slugify(text):
    """Filesystem-safe slug: 'Acme, Inc.' -> 'acme-inc'."""
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-") or "prospect"


def load_prospects(path):
    """Read the prospect CSV into a list of Prospect objects.

    Column names are matched case-insensitively; whitespace is trimmed. Rows
    without a company name are skipped (a video needs someone to send it to).
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    prospects = []
    for row in rows:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        company = r.get("company", "")
        if not company:
            continue
        prospects.append(
            Prospect(
                first_name=r.get("first_name", "") or "there",
                company=company,
                role=r.get("role", ""),
                industry=r.get("industry", ""),
                website=r.get("website", ""),
            )
        )
    return prospects


# ---------------------------------------------------------------------------
# Providers — each returns a dict: signal, signal_source, subject, stages
# ---------------------------------------------------------------------------

# What we sell in the script — a video producer pitching short-form video help.
OFFER = (
    "short, personalized prospecting videos your reps can send to book more "
    "first meetings"
)


def generate_mock(prospect):
    """Deterministic, offline asset generation. No network, no API key.

    The 'signal' here is clearly synthetic placeholder text — it is NOT a real
    citation. Use --provider anthropic for a genuine, web-sourced signal.
    """
    company = prospect.company
    industry = prospect.industry or "your space"

    # Pick a stable template from the company name so runs are reproducible.
    templates = [
        f"{company} just posted several new sales roles — a classic signal they're scaling outbound.",
        f"{company} recently announced a new funding round and is investing in growth.",
        f"{company} launched a new product line and is pushing hard into {industry}.",
        f"{company} is expanding into new markets after a strong quarter.",
    ]
    idx = int(hashlib.md5(company.encode()).hexdigest(), 16) % len(templates)
    signal = templates[idx]

    first = prospect.first_name
    hook_frag = signal.split(" — ")[0].rstrip(".")
    stages = {
        "hook": f"Hey {first} — saw that {hook_frag}.",
        "bridge": (
            f"When teams at companies like {company} scale outbound, the first "
            "thing that breaks is personalization at volume."
        ),
        "value": (
            f"That's exactly what I fix — I build {OFFER}. "
            "One rep I worked with doubled reply rates in three weeks."
        ),
        "cta": (
            f"Worth a quick look? I made this whole video for {company} in "
            "under two minutes — happy to show you how."
        ),
    }
    subject = f"quick idea for {company} (made you a 30-sec video)"

    return {
        "signal": signal,
        "signal_source": "mock-data (offline demo — not a real citation)",
        "subject": subject,
        "stages": stages,
    }


def generate_anthropic(prospect, model):
    """Use Claude + the web_search tool to find one real, cited buying signal
    and write the script around it. Returns the same dict shape as generate_mock.
    """
    import anthropic  # lazy import so mock mode needs no anthropic install

    client = anthropic.Anthropic()

    system = (
        "You are an expert SDR and short-form video scriptwriter. You research a "
        "prospect's company, find ONE real, recent, specific buying signal (a "
        "hiring push, funding round, product launch, exec hire, earnings note, "
        "etc.), and write a ~30-second spoken video script around it."
    )
    user = f"""Research this company and write a personalized video prospecting asset.

Prospect: {prospect.first_name}
Company: {prospect.company}
Role: {prospect.role or "unknown"}
Industry: {prospect.industry or "unknown"}
Website: {prospect.website or "unknown"}

What we sell: {OFFER}.

Steps:
1. Use web search to find ONE real, recent (last ~6 months) buying signal for {prospect.company}. Note the source URL.
2. Write a ~30-second spoken script (roughly 75-90 words total) in four beats:
   hook (name-drop the signal), bridge (tie it to a problem), value (what we do +
   a proof point), cta (a soft, low-friction ask).
3. Draft a short, lowercase, curiosity-driven email subject line.

Return ONLY a fenced ```json block as the LAST thing in your reply, with keys:
signal (string), source_url (string), subject (string),
hook (string), bridge (string), value (string), cta (string)."""

    messages = [{"role": "user", "content": user}]
    tools = [{"type": "web_search_20260209", "name": "web_search"}]

    # Server-side web_search can pause the turn at its iteration limit; resume.
    for _ in range(6):
        response = client.messages.create(
            model=model,
            max_tokens=4000,
            system=system,
            tools=tools,
            messages=messages,
        )
        if response.stop_reason == "pause_turn":
            messages = [
                {"role": "user", "content": user},
                {"role": "assistant", "content": response.content},
            ]
            continue
        break

    text = "".join(b.text for b in response.content if b.type == "text")
    data = _extract_json(text)

    return {
        "signal": data.get("signal", ""),
        "signal_source": data.get("source_url", ""),
        "subject": data.get("subject", ""),
        "stages": {
            "hook": data.get("hook", ""),
            "bridge": data.get("bridge", ""),
            "value": data.get("value", ""),
            "cta": data.get("cta", ""),
        },
    }


def _extract_json(text):
    """Pull the last JSON object out of a model reply (fenced or bare)."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = fenced or re.findall(r"(\{.*\})", text, re.DOTALL)
    for chunk in reversed(candidates):
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise ValueError("Could not parse a JSON object from the model response")


PROVIDERS = {"mock": generate_mock}


def generate(prospect, provider, model):
    if provider == "anthropic":
        return generate_anthropic(prospect, model)
    return generate_mock(prospect)


# ---------------------------------------------------------------------------
# Thumbnail rendering (Pillow) — branded 1280x720
# ---------------------------------------------------------------------------

_PALETTE = ["#E4572E", "#17BEBB", "#FFC914", "#2E86AB", "#A23B72", "#3BB273"]


def _load_font(size):
    """Load a real TrueType font if we can find one, else Pillow's default."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def _wrap(draw, text, font, max_width):
    """Greedy word-wrap `text` to fit `max_width` pixels."""
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render_thumbnail(asset, brand, out_path):
    """Render a branded 1280x720 thumbnail for one asset and save as PNG."""
    W, H = 1280, 720
    accent = _PALETTE[
        int(hashlib.md5(asset.prospect.company.encode()).hexdigest(), 16)
        % len(_PALETTE)
    ]
    img = Image.new("RGB", (W, H), "#0F1115")
    draw = ImageDraw.Draw(img)

    # Left accent bar.
    draw.rectangle([0, 0, 16, H], fill=accent)

    pad = 90
    brand_font = _load_font(30)
    company_font = _load_font(76)
    meta_font = _load_font(34)
    hook_font = _load_font(40)
    badge_font = _load_font(28)

    # Brand kicker (top).
    draw.text((pad, 70), brand.upper(), font=brand_font, fill="#8A8F98")

    # Company name (hero).
    company_lines = _wrap(draw, asset.prospect.company, company_font, W - 2 * pad)
    y = 150
    for line in company_lines[:2]:
        draw.text((pad, y), line, font=company_font, fill="#FFFFFF")
        y += 88

    # Contact + role.
    meta = asset.prospect.first_name
    if asset.prospect.role:
        meta += f"  ·  {asset.prospect.role}"
    draw.text((pad, y + 6), meta, font=meta_font, fill=accent)
    y += 78

    # Hook line from the script.
    hook = asset.stages.get("hook", "")
    for line in _wrap(draw, hook, hook_font, W - 2 * pad)[:3]:
        draw.text((pad, y), line, font=hook_font, fill="#D7DBE0")
        y += 52

    # Bottom badge: drawn play triangle + label (avoids missing-glyph tofu).
    badge = "30-SEC PERSONALIZED VIDEO"
    text_x = pad + 34
    bw = draw.textlength(badge, font=badge_font)
    draw.rounded_rectangle(
        [pad - 20, H - 110, text_x + bw + 20, H - 55], radius=12, fill=accent
    )
    draw.polygon(
        [(pad, H - 96), (pad, H - 70), (pad + 22, H - 83)], fill="#0F1115"
    )
    draw.text((text_x, H - 100), badge, font=badge_font, fill="#0F1115")

    img.save(out_path)


# ---------------------------------------------------------------------------
# Per-prospect processing
# ---------------------------------------------------------------------------


def process_prospect(prospect, provider, model, brand, out_dir):
    """Generate all assets for one prospect and return an Asset."""
    result = generate(prospect, provider, model)
    asset = Asset(
        prospect=prospect,
        signal=result["signal"],
        signal_source=result["signal_source"],
        subject=result["subject"],
        stages=result["stages"],
    )

    thumb_dir = out_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{slugify(prospect.company)}.png"
    render_thumbnail(asset, brand, thumb_path)
    asset.thumbnail_path = str(thumb_path.relative_to(out_dir))

    return asset


def spoken_script(asset):
    """Just the words the presenter says, in order — no stage labels."""
    order = ["hook", "bridge", "value", "cta"]
    return " ".join(asset.stages.get(k, "").strip() for k in order).strip()


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_scripts_md(assets, path):
    lines = ["# Video Prospecting Scripts\n"]
    for a in assets:
        p = a.prospect
        lines.append(f"## {p.company} — {p.first_name}")
        if p.role:
            lines.append(f"*{p.role}*\n")
        lines.append(f"**Buying signal:** {a.signal}")
        lines.append(f"**Source:** {a.signal_source}")
        lines.append(f"**Email subject:** {a.subject}\n")
        lines.append("**Script (~30s):**\n")
        for beat in ("hook", "bridge", "value", "cta"):
            lines.append(f"- **{beat.capitalize()}:** {a.stages.get(beat, '')}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_results_csv(assets, path):
    fields = [
        "first_name", "company", "role", "industry",
        "subject", "signal", "signal_source", "thumbnail", "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for a in assets:
            writer.writerow({
                "first_name": a.prospect.first_name,
                "company": a.prospect.company,
                "role": a.prospect.role,
                "industry": a.prospect.industry,
                "subject": a.subject,
                "signal": a.signal,
                "signal_source": a.signal_source,
                "thumbnail": a.thumbnail_path,
                "status": a.status,
            })


def _data_uri(png_path):
    """Base64-encode a PNG as a data: URI so the gallery is self-contained."""
    data = base64.b64encode(Path(png_path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def write_gallery_html(assets, brand, path, out_dir):
    cards = []
    for a in assets:
        p = a.prospect
        src = _data_uri(out_dir / a.thumbnail_path)
        cards.append(f"""
    <article class="card">
      <img src="{src}" alt="Thumbnail for {html.escape(p.company)}">
      <div class="body">
        <h2>{html.escape(p.company)} <span>· {html.escape(p.first_name)}</span></h2>
        <p class="signal"><strong>Signal:</strong> {html.escape(a.signal)}</p>
        <p class="subject"><strong>Subject:</strong> {html.escape(a.subject)}</p>
        <p class="script">{html.escape(spoken_script(a))}</p>
      </div>
    </article>""")

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(brand)} — Video Prospecting Gallery</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #0b0d10; color: #e7e9ee;
         font: 16px/1.5 -apple-system, Segoe UI, Roboto, sans-serif; }}
  header {{ padding: 40px 32px 8px; }}
  header h1 {{ margin: 0; font-size: 28px; }}
  header p {{ color: #8a8f98; margin: 6px 0 0; }}
  .grid {{ display: grid; gap: 24px; padding: 24px 32px 64px;
          grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }}
  .card {{ background: #14171c; border: 1px solid #23272e; border-radius: 14px;
          overflow: hidden; }}
  .card img {{ width: 100%; display: block; aspect-ratio: 16/9; object-fit: cover; }}
  .body {{ padding: 18px 20px 22px; }}
  .body h2 {{ margin: 0 0 10px; font-size: 20px; }}
  .body h2 span {{ color: #8a8f98; font-weight: 400; }}
  .signal, .subject {{ margin: 6px 0; font-size: 14px; }}
  .script {{ margin: 12px 0 0; color: #c3c8d0; font-size: 14px;
            border-left: 3px solid #2e86ab; padding-left: 12px; }}
  strong {{ color: #fff; }}
</style>
</head>
<body>
  <header>
    <h1>{html.escape(brand)} — Video Prospecting Gallery</h1>
    <p>{len(assets)} ready-to-record assets.</p>
  </header>
  <main class="grid">{''.join(cards)}
  </main>
</body>
</html>"""
    path.write_text(doc, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        description="Turn a prospect CSV into ready-to-record video prospecting assets."
    )
    parser.add_argument("input", help="prospect CSV (first_name, company, role, industry, website)")
    parser.add_argument("--provider", choices=["mock", "anthropic"], default="mock",
                        help="mock = offline demo (default); anthropic = Claude + web search")
    parser.add_argument("--model", default="claude-opus-5",
                        help="Claude model id for the anthropic provider")
    parser.add_argument("--brand", default="Your Studio",
                        help="brand name shown on thumbnails and the gallery")
    parser.add_argument("--output-dir", default="output", help="where to write outputs")
    parser.add_argument("--limit", type=int, default=0,
                        help="only process the first N prospects (0 = all)")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prospects = load_prospects(args.input)
    if args.limit:
        prospects = prospects[: args.limit]
    if not prospects:
        sys.exit("No prospects found in the input CSV.")

    assets = []
    for i, prospect in enumerate(prospects, 1):
        print(f"[{i}/{len(prospects)}] {prospect.company} …")
        assets.append(process_prospect(prospect, args.provider, args.model, args.brand, out_dir))

    write_scripts_md(assets, out_dir / "scripts.md")
    write_results_csv(assets, out_dir / "results.csv")
    write_gallery_html(assets, args.brand, out_dir / "gallery.html", out_dir)

    print(f"\nDone. Wrote {len(assets)} assets to {out_dir}/")
    print(f"  - {out_dir}/scripts.md")
    print(f"  - {out_dir}/results.csv")
    print(f"  - {out_dir}/gallery.html")


if __name__ == "__main__":
    main()
