"""
Batch-scrape multiple documentation sites in one run using the Crawl4AI Docker API.
Each site is defined with a seed URL and an optional path prefix to constrain crawling.
Each site gets its own output file in ./output/

Requirements:
  pip install aiohttp
  docker run -p 11235:11235 unclecode/crawl4ai:latest

Usage:
  1. Edit the SITES list below with the sites you want to scrape.
  2. Run: python crawl_multi_site.py
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urljoin

import aiohttp

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE   = "http://localhost:11235"
OUTPUT_DIR = Path("./output")

CRAWL_PAYLOAD = {
    "crawler_params": {"headless": True},
    "extra": {"wait_for_network_idle_page_load_time": 2.5},
}


@dataclass(frozen=True)
class Site:
    seed: str           # Starting URL
    filename: str       # Output filename (saved in OUTPUT_DIR)
    title: str          # Human-readable name for the output header
    prefix: str = ""    # Allowed path prefix. Empty string = whole domain.


# ── Edit this list to add your sites ─────────────────────────────────────────

SITES: list[Site] = [
    Site(
        seed="https://docs.python.org/3/tutorial/index.html",
        filename="python_docs.md",
        title="Python 3 Tutorial",
        prefix="/3/tutorial",
    ),
    Site(
        seed="https://react.dev/learn",
        filename="react_docs.md",
        title="React — Learn",
        prefix="/learn",
    ),
    # Add more sites here:
    # Site(
    #     seed="https://your-docs-site.com/docs/",
    #     filename="your_site.md",
    #     title="Your Site Docs",
    #     prefix="/docs/",   # leave empty to crawl entire domain
    # ),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(url: str) -> str:
    return url.split("#")[0].split("?")[0].rstrip("/")


def is_allowed(url: str, domain: str, prefix: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.netloc == domain
            and parsed.scheme in ("http", "https")
            and (not prefix or parsed.path.startswith(prefix))
        )
    except Exception:
        return False


async def crawl_url(session: aiohttp.ClientSession, url: str) -> dict:
    payload = {**CRAWL_PAYLOAD, "urls": [url]}
    async with session.post(
        f"{API_BASE}/crawl",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=90),
    ) as resp:
        return await resp.json()


async def crawl_site(session: aiohttp.ClientSession, site: Site) -> list[dict]:
    parsed_seed = urlparse(site.seed)
    domain = parsed_seed.netloc
    base   = f"{parsed_seed.scheme}://{domain}"

    print(f"\n{'=' * 60}")
    print(f"  Site   : {site.title}")
    print(f"  Seed   : {site.seed}")
    print(f"  Domain : {domain}  |  Prefix : '{site.prefix or '(whole domain)'}'")
    print(f"{'=' * 60}")

    visited: set[str]  = set()
    queue: list[str]   = [normalize(site.seed)]
    articles: list[dict] = []

    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        print(f"  [{len(visited):03d}] {url} ...", end=" ", flush=True)
        try:
            result = await crawl_url(session, url)
            res = result["results"][0]

            md          = res.get("markdown") or {}
            content     = md.get("fit_markdown") or md.get("raw_markdown") or ""
            meta        = res.get("metadata") or {}
            title       = (meta.get("title") or "").split("|")[0].strip() or url
            description = meta.get("description") or ""

            articles.append({"url": url, "title": title,
                              "description": description, "content": content.strip()})
            print(f'OK — "{title}"')

            links_data = res.get("links") or {}
            all_links  = links_data.get("internal", []) + links_data.get("external", [])

            new_count = 0
            for link in all_links:
                href = link.get("href", "")
                if not href:
                    continue
                if href.startswith("/"):
                    href = base + href
                elif not href.startswith("http"):
                    href = urljoin(url, href)
                href = normalize(href)
                if is_allowed(href, domain, site.prefix) and href not in visited and href not in queue:
                    queue.append(href)
                    new_count += 1
            if new_count:
                print(f"      -> queued {new_count} new links (queue: {len(queue)})")

        except Exception as e:
            print(f"ERROR: {e}")

        await asyncio.sleep(0.3)

    return articles


def build_markdown(site: Site, articles: list[dict]) -> str:
    lines = [
        f"# {site.title}\n\n",
        f"Source: {site.seed}  \n",
        f"Total pages crawled: {len(articles)}\n\n",
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
        async with session.get(f"{API_BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
            health = await r.json()
            print(f"crawl4ai status: {health.get('status')}")

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        for site in SITES:
            articles = await crawl_site(session, site)
            output   = OUTPUT_DIR / site.filename
            output.write_text(build_markdown(site, articles), encoding="utf-8")
            print(f"\n  Saved {len(articles)} pages -> {output}  ({output.stat().st_size // 1024} KB)")

    print(f"\nAll done. Output files in: {OUTPUT_DIR}")


asyncio.run(main())
