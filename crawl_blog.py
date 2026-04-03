"""
Scrape all blog articles from a site using the Crawl4AI Docker API.
Discovers article links from the blog index page, then scrapes each article.
Saves output to ./output/blog.md with a table of contents.

Requirements:
  pip install aiohttp
  docker run -p 11235:11235 unclecode/crawl4ai:latest

Usage:
  1. Set BLOG_INDEX to the blog listing page URL.
  2. Set BLOG_PATH_PREFIX to the URL pattern that identifies article links
     (e.g. "/blog/" means only links containing "/blog/" are collected).
  3. Run: python crawl_blog.py
"""

import asyncio
import aiohttp
import re
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE         = "http://localhost:11235"
OUTPUT_DIR       = Path("./output")
OUTPUT           = OUTPUT_DIR / "blog.md"

BLOG_INDEX       = "https://example.com/blog"   # The blog listing/index page
BLOG_PATH_PREFIX = "/blog/"                      # Path prefix that identifies article links

CRAWL_PAYLOAD = {
    "crawler_params": {"headless": True},
    "extra": {"wait_for_network_idle_page_load_time": 2.0},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

async def crawl(session: aiohttp.ClientSession, url: str) -> dict:
    payload = {**CRAWL_PAYLOAD, "urls": [url]}
    async with session.post(
        f"{API_BASE}/crawl",
        json=payload,
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        return await resp.json()


def build_markdown(articles: list, blog_index: str) -> str:
    lines = [
        "# Blog — Complete Archive\n\n",
        f"Source: {blog_index}  \n",
        f"Total articles: {len(articles)}\n\n",
        "---\n\n## Table of Contents\n\n",
    ]
    for i, a in enumerate(articles, 1):
        slug   = a["url"].split(BLOG_PATH_PREFIX)[-1].rstrip("/")
        anchor = re.sub(r"[^a-z0-9-]", "", slug.lower().replace(" ", "-"))
        lines.append(f"{i}. [{a['title']}](#{anchor})\n")
    lines.append("\n---\n\n")

    for a in articles:
        slug   = a["url"].split(BLOG_PATH_PREFIX)[-1].rstrip("/")
        anchor = re.sub(r"[^a-z0-9-]", "", slug.lower().replace(" ", "-"))
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
        async with session.get(f"{API_BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
            health = await r.json()
            print(f"crawl4ai status: {health.get('status')}\n")

        # Step 1: crawl blog index to discover article links
        print(f"Crawling blog index: {BLOG_INDEX}")
        result       = await crawl(session, BLOG_INDEX)
        res0         = result["results"][0]
        internal_links = res0.get("links", {}).get("internal", [])
        blog_links   = sorted(set(
            l["href"] for l in internal_links
            if BLOG_PATH_PREFIX in l.get("href", "") and l["href"] != BLOG_PATH_PREFIX
        ))
        print(f"Found {len(blog_links)} article links\n")

        if not blog_links:
            print("No articles found. Check BLOG_INDEX and BLOG_PATH_PREFIX.")
            return

        # Step 2: crawl each article
        articles: list[dict] = []
        for i, url in enumerate(blog_links, 1):
            slug = url.split(BLOG_PATH_PREFIX)[-1].rstrip("/")
            print(f"[{i:02d}/{len(blog_links)}] {slug} ...", end=" ", flush=True)
            try:
                result = await crawl(session, url)
                res    = result["results"][0]

                md          = res.get("markdown", {})
                content     = md.get("fit_markdown") or md.get("raw_markdown") or ""
                meta        = res.get("metadata", {})
                title       = meta.get("title", "").split("|")[0].strip() or slug
                description = meta.get("description", "")

                articles.append({
                    "url": url, "title": title,
                    "description": description, "content": content.strip(),
                })
                print(f'OK — "{title}"')
            except Exception as e:
                print(f"ERROR: {e}")

            await asyncio.sleep(0.3)

        # Step 3: build and save markdown
        print(f"\nBuilding markdown from {len(articles)} articles...")
        md_text = build_markdown(articles, BLOG_INDEX)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(md_text, encoding="utf-8")
        print(f"Saved to: {OUTPUT}  ({OUTPUT.stat().st_size // 1024} KB)")


asyncio.run(main())
