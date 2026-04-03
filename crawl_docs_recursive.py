"""
Recursively scrape a documentation site using the Crawl4AI Docker API.
Follows all internal links within the allowed URL prefixes.
Saves output to ./output/<name>.md

Features:
  - Resume support: progress is saved to ./output/progress.json after every
    SAVE_EVERY pages, so re-running continues from where it left off.
  - Skips binary/asset extensions and noisy URL patterns.
  - Extracts fit_markdown (cleaner) or raw_markdown as fallback.

Requirements:
  pip install aiohttp
  docker run -p 11235:11235 unclecode/crawl4ai:latest

Usage:
  python crawl_docs_recursive.py
"""

import asyncio
import aiohttp
import json
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE      = "http://localhost:11235"
OUTPUT_DIR    = Path("./output")
OUTPUT        = OUTPUT_DIR / "docs.md"
PROGRESS_FILE = OUTPUT_DIR / "progress.json"

# Starting pages — the crawler will discover and follow links from here
SEEDS = [
    "https://example.com/docs/",
]

# Only follow links that stay within these path prefixes
ALLOWED_PREFIXES = [
    "https://example.com/docs/",
]

# Skip these file extensions
SKIP_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".jar", ".war",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".xml", ".json", ".yaml", ".yml",
}

# Skip URLs containing these strings
SKIP_PATTERNS = [
    "/javadoc/", "/api/", "/_/", "/download", "/releases",
    "github.com", "twitter.com", "linkedin.com",
]

# Save progress to disk every N pages
SAVE_EVERY = 50

CRAWL_PAYLOAD = {
    "crawler_params": {"headless": True},
    "extra": {"wait_for_network_idle_page_load_time": 2.0},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_allowed(url: str) -> bool:
    if not any(url.startswith(p) for p in ALLOWED_PREFIXES):
        return False
    path = urlparse(url).path.lower()
    if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
        return False
    if any(pat in url for pat in SKIP_PATTERNS):
        return False
    return True


def normalize(url: str) -> str:
    """Strip fragments, query strings, and trailing slashes."""
    return url.split("#")[0].split("?")[0].rstrip("/")


def save_progress(visited: set, queue: list, articles: list) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps({"visited": list(visited), "queue": queue, "articles": articles},
                   ensure_ascii=False),
        encoding="utf-8",
    )


def load_progress() -> tuple[set, list, list]:
    if not PROGRESS_FILE.exists():
        return set(), [normalize(u) for u in SEEDS], []
    data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return (
        set(data.get("visited", [])),
        data.get("queue", [normalize(u) for u in SEEDS]),
        data.get("articles", []),
    )


async def crawl(session: aiohttp.ClientSession, url: str) -> dict:
    payload = {**CRAWL_PAYLOAD, "urls": [url]}
    async with session.post(
        f"{API_BASE}/crawl",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=90),
    ) as resp:
        return await resp.json()


def build_markdown(articles: list) -> str:
    lines = [
        "# Documentation Archive\n\n",
        f"Total pages crawled: {len(articles)}\n\n",
        f"Sources: {', '.join(ALLOWED_PREFIXES)}\n\n",
        "---\n\n## Table of Contents\n\n",
    ]
    for i, a in enumerate(articles, 1):
        anchor = re.sub(r"[^a-z0-9-]", "", a["title"].lower().replace(" ", "-"))[:60]
        lines.append(f"{i}. [{a['title']}](#{anchor})\n")
    lines.append("\n---\n\n")
    for a in articles:
        anchor = re.sub(r"[^a-z0-9-]", "", a["title"].lower().replace(" ", "-"))[:60]
        lines.append(f"## {a['title']}\n\n")
        lines.append(f'<a name="{anchor}"></a>\n\n')
        lines.append(f"**URL:** {a['url']}  \n")
        if a["description"]:
            lines.append(f"**Summary:** {a['description']}\n\n")
        lines.append(f"---\n\n{a['content']}\n\n---\n\n")
    return "".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    async with aiohttp.ClientSession() as session:

        # Health check
        try:
            async with session.get(f"{API_BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                health = await r.json()
                print(f"crawl4ai status: {health.get('status')}\n")
        except Exception as e:
            print(f"ERROR: crawl4ai not reachable at {API_BASE} — {e}")
            return

        visited, queue, articles = load_progress()
        resumed = len(visited) > 0
        if resumed:
            print(f"Resuming from page {len(visited)+1} ({len(articles)} articles saved, {len(queue)} in queue)\n")
        else:
            print(f"Starting fresh crawl of {SEEDS} ...\n")

        pages_this_run = 0

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            pages_this_run += 1

            print(f"[{len(visited):04d}] {url} ...", end=" ", flush=True)
            try:
                result = await crawl(session, url)
                res = result["results"][0]

                md = res.get("markdown", {})
                content = md.get("fit_markdown") or md.get("raw_markdown") or ""
                meta = res.get("metadata", {})
                title = meta.get("title", "").split("|")[0].strip() or url
                description = meta.get("description", "")

                if content.strip():
                    articles.append({
                        "url": url, "title": title,
                        "description": description, "content": content.strip(),
                    })
                    print(f'OK — "{title}"')
                else:
                    print("SKIP (empty content)")

                # Queue newly discovered internal links
                internal_links = res.get("links", {}).get("internal", [])
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                new_links = 0
                for link in internal_links:
                    href = link.get("href", "")
                    if not href:
                        continue
                    if href.startswith("/"):
                        href = base + href
                    elif not href.startswith("http"):
                        href = urljoin(url, href)
                    href = normalize(href)
                    if is_allowed(href) and href not in visited and href not in queue:
                        queue.append(href)
                        new_links += 1
                if new_links:
                    print(f"      -> queued {new_links} new links (queue: {len(queue)})")

            except Exception as e:
                print(f"ERROR: {e}")

            if pages_this_run % SAVE_EVERY == 0:
                save_progress(visited, queue, articles)
                print(f"      [progress saved — {len(articles)} articles, {len(queue)} remaining]")

            await asyncio.sleep(0.3)

        print(f"\n{'='*60}")
        print(f"Crawled {len(articles)} pages total. Building markdown...")

        md_text = build_markdown(articles)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(md_text, encoding="utf-8")
        print(f"Saved to: {OUTPUT}  ({OUTPUT.stat().st_size // 1024} KB)")

        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
            print("Progress file removed (crawl complete).")


asyncio.run(main())
