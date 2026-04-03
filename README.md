# Crawl4Noobs

A clean, minimal UI for [Crawl4AI](https://crawl4ai.com) — built as a single-page application with no dependencies.

## Features

- **Scraper page** — Add URLs to scrape with configurable depth, output format, concurrency, include/exclude patterns, and advanced options (JS execution, sitemap, robots.txt, dedup, CSS selector)
- **Dashboard page** — Track all scrape jobs with status (Finished / In Progress / Not Started), progress bars, and per-site sync
- **Detail panel** — Slide-in panel with metrics, activity log, and actions (Sync, Download, Re-scrape, Remove)
- **Dark mode** — Toggleable, persisted to localStorage
- **Fully responsive** — Works at 1200px, 960px, and 640px breakpoints

## Usage

Just open `index.html` in your browser — no build step, no server required.

To connect it to a real Crawl4AI backend, replace the `startCrawl()` and `addToQueue()` functions in the script section with actual API calls to your Crawl4AI instance.

## Design

Built with the EZ Design System — warm neutrals, Space Grotesk headings, JetBrains Mono metrics, dark green accent.
