# Crawl4Noobs

A no-code GUI for [Crawl4AI](https://github.com/unclecode/crawl4ai) — for people who want to scrape websites without touching the command line.

---

## Getting started (2 steps)

**Step 1 — Start the engine** (one-time setup, needs [Docker](https://www.docker.com/products/docker-desktop/))

```bash
docker run -p 11235:11235 unclecode/crawl4ai:latest
```

**Step 2 — Open the app**

Double-click **`start.bat`** — the scraper opens in your browser automatically.

> On Mac/Linux: open `index.html` directly in your browser.

That's it. No install, no terminal, no config files.

---

## What it does

- Point it at any website and it downloads the content as Markdown, JSON, HTML, or plain text
- Follow links automatically to scrape entire documentation sites or blogs
- Track all your scrapes in one place with live progress bars
- Everything is saved locally — no accounts, no cloud, no tracking

## Views

**New Scrape** — Paste a URL, pick your options with big visual buttons, hit Start. No jargon:
- "How far should we go?" instead of "depth"
- "Load interactive content" instead of "execute JavaScript"
- "Slow / Normal / Fast" instead of concurrency numbers

**My Scrapes** — All your sites in one list. See what's done, what's running, what's waiting. Sync any site to pick up new pages.

**Settings** — Set your server URL and default save folder through the UI. No file editing needed.

## Python scripts (for power users)

The repo also includes ready-to-use Python scripts for common scraping patterns:

| Script | What it does |
|--------|-------------|
| `crawl_docs_recursive.py` | Recursively scrape a docs site. Resumes if interrupted. |
| `crawl_docs_multi_seed.py` | Scrape from multiple starting URLs, grouped by domain. |
| `crawl_multi_site.py` | Batch-scrape a list of sites, one output file each. |
| `crawl_blog.py` | Scrape all articles from a blog index page. |
| `crawl_blog_lightpanda.mjs` | Same as above but uses Lightpanda instead of Python. |

Each script has a config section at the top — edit the URLs and run it.

```bash
pip install aiohttp
python crawl_docs_recursive.py
```

## Crawl4AI

This repo includes Crawl4AI as a submodule (`crawl4ai/`). To pull it:

```bash
git submodule update --init
```

Full Crawl4AI docs: [crawl4ai.com](https://crawl4ai.com)
