# Video Prospecting Engine

Turn a raw prospect CSV into **ready-to-record personalized video prospecting assets**.

For each prospect the tool:

1. **Finds one real, recent, cited buying signal** (hiring push, funding, launch, exec hire…) via Claude + web search.
2. **Writes a ~30-second video script** around it: hook → bridge → value → soft CTA.
3. **Drafts an email subject line.**
4. **Renders a branded 1280×720 thumbnail.**

Outputs a `scripts.md`, a `results.csv`, and a browsable `gallery.html`.

Built by a video producer moving into an SDR/BDR role — it's the proof-of-work: research → message → asset, at volume, the way a rep actually preps outreach.

## Providers

| Provider | What it does | Needs |
|---|---|---|
| `mock` (default) | Fully offline. Synthesizes an **obviously-fake placeholder** signal so you can demo the whole pipeline with no API key. | nothing |
| `anthropic` | Uses Claude + the `web_search` tool to find a **genuine, cited** signal and write the script around it. | `ANTHROPIC_API_KEY`, `anthropic` package |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Offline demo over the sample CSV:
python video_prospector.py prospects.csv --brand "Lineage Studio"

# Real, web-sourced signals (needs ANTHROPIC_API_KEY):
export ANTHROPIC_API_KEY=sk-ant-...
python video_prospector.py prospects.csv --provider anthropic --brand "Lineage Studio"
```

Open `output/gallery.html` in a browser to see the thumbnails and scripts.

## Input format

A CSV with these columns (extra columns are ignored):

```csv
first_name,company,role,industry,website
Priya,Ramp,VP Sales,fintech,ramp.com
```

Only `company` is required; missing `first_name` falls back to "there".

## Options

| Flag | Default | Meaning |
|---|---|---|
| `--provider` | `mock` | `mock` or `anthropic` |
| `--model` | `claude-opus-5` | Claude model id (anthropic provider) |
| `--brand` | `Your Studio` | Brand shown on thumbnails and the gallery |
| `--output-dir` | `output` | Where outputs are written |
| `--limit N` | `0` (all) | Only process the first N prospects |

## Outputs

```
output/
├── scripts.md        one section per prospect (signal, subject, script)
├── results.csv       one row per prospect (machine-readable)
├── gallery.html      thumbnails + scripts in a grid
└── thumbnails/*.png  branded 1280×720 images
```

`output/` and `.env` are gitignored.
