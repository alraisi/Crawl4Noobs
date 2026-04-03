"""
Recursively scrape documentation from multiple seed URLs using the Crawl4AI Docker API.
Each seed's domain+path prefix acts as the boundary — the crawler won't wander outside it.
Saves output to ./output/docs.md grouped by domain.

Requirements:
  pip install aiohttp
  docker run -p 11235:11235 unclecode/crawl4ai:latest

Usage:
  python crawl_docs_multi_seed.py
"""

import asyncio
import aiohttp
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE   = "http://localhost:11235"
OUTPUT_DIR = Path("./output")
OUTPUT     = OUTPUT_DIR / "docs.md"

# Add as many seed URLs as you like.
# The crawler will follow all links that stay within the same domain+path prefix.
SEEDS = [
    "https://example.com/docs/getting-started",
    "https://another-site.com/docs/intro",
]

# Only follow links that stay within these domain+path prefixes.
# Auto-derived from SEEDS: everything under the same domain/path root.
ALLOWED_PREFIXES = [
    "https://example.com/docs/",
    "https://another-site.com/docs/",
]

CRAWL_PAYLOAD = {
    "crawler_params": {"headless": True},
    "extra": {"wait_for_network_idle_page_load_time": 2.0},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_allowed(url: str) -> bool:
    return any(url.startswith(p) for p in ALLOWED_PREFIXES)


def normalize(url: str) -> str:
    return url.split("#")[0].split("?")[0].rstrip("/")


async def crawl(session: aiohttp.ClientSession, url: str) -> dict:
    payload = {**CRAWL_PAYLOAD, "urls": [url]}
    async with session.post(
        f"{API_BASE}/crawl",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        return await resp.json()


def build_markdown(articles: list) -> str:
    # Group articles by domain
    groups: dict[str, list] = {}
    for a in articles:
        domain = urlparse(a["url"]).netloc
        groups.setdefault(domain, []).append(a)

    lines = [
        "# Documentation Archive\n\n",
        f"Total pages crawled: {len(articles)}\n\n",
        "**Sources:**\n",
    ]
    for prefix in ALLOWED_PREFIXES:
        lines.append(f"- {prefix}\n")
    lines.append("\n---\n\n## Table of Contents\n\n")

    idx = 1
    for domain, arts in groups.items():
        lines.append(f"### {domain}\n\n")
        for a in arts:
            anchor = re.sub(r"[^a-z0-9-]", "", a["title"].lower().replace(" ", "-"))[:60]
            lines.append(f"{idx}. [{a['title']}](#{anchor})\n")
            idx += 1
    lines.append("\n---\n\n")

    for domain, arts in groups.items():
        lines.append(f"# {domain}\n\n")
        for a in arts:
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
            print(f"crawl4ai status: {health.get('status')}\n")

        visited: set[str] = set()
        queue: list[str] = [normalize(u) for u in SEEDS]
        articles: list[dict] = []

        print("Starting recursive crawl...\n")

        while queue:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            print(f"[{len(visited):03d}] {url} ...", end=" ", flush=True)
            try:
                result = await crawl(session, url)
                res = result["results"][0]

                md = res.get("markdown", {})
                content = md.get("fit_markdown") or md.get("raw_markdown") or ""
                meta = res.get("metadata", {})
                title = meta.get("title", "").split("|")[0].strip() or url
                description = meta.get("description", "")

                articles.append({
                    "url": url, "title": title,
                    "description": description, "content": content.strip(),
                })
                print(f'OK — "{title}"')

                # Discover and queue new allowed links
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

            await asyncio.sleep(0.3)

        print(f"\n{'='*60}")
        print(f"Crawled {len(articles)} pages total. Building markdown...")

        md_text = build_markdown(articles)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(md_text, encoding="utf-8")
        print(f"Saved to: {OUTPUT}  ({OUTPUT.stat().st_size // 1024} KB)")


asyncio.run(main())
