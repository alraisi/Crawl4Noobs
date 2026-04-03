/**
 * Scrape blog articles using Lightpanda (headless browser via Docker).
 * Alternative to crawl4ai — useful for JS-heavy sites without a Python setup.
 *
 * Requirements:
 *   docker pull lightpanda/browser:nightly
 *   node >= 18
 *
 * Usage:
 *   1. Set BASE_URL and BLOG_INDEX below.
 *   2. node crawl_blog_lightpanda.mjs
 */

import { execSync } from 'child_process';
import { writeFileSync, mkdirSync } from 'fs';
import { join } from 'path';

// ── Config ────────────────────────────────────────────────────────────────────

const BASE_URL   = 'https://example.com';
const BLOG_INDEX = 'https://example.com/blog';
const BLOG_PREFIX = '/blog/';          // URL path prefix that identifies article links
const OUTPUT_DIR = './output';
const OUTPUT     = join(OUTPUT_DIR, 'blog.md');

// ── Lightpanda fetch ──────────────────────────────────────────────────────────

function lightpandaFetch(url) {
  // Spin up a fresh Lightpanda container per fetch
  const cmd = `docker run --rm lightpanda/browser:nightly sh -c "lightpanda fetch '${url}'"`;
  try {
    return execSync(cmd, { timeout: 30000, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] });
  } catch (e) {
    return e.stdout || '';
  }
}

// ── HTML → Markdown ───────────────────────────────────────────────────────────

function htmlToMd(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/<nav[\s\S]*?<\/nav>/gi, '')
    .replace(/<header[\s\S]*?<\/header>/gi, '')
    .replace(/<footer[\s\S]*?<\/footer>/gi, '')
    .replace(/<h1[^>]*>([\s\S]*?)<\/h1>/gi, '\n\n# $1\n\n')
    .replace(/<h2[^>]*>([\s\S]*?)<\/h2>/gi, '\n\n## $1\n\n')
    .replace(/<h3[^>]*>([\s\S]*?)<\/h3>/gi, '\n\n### $1\n\n')
    .replace(/<h4[^>]*>([\s\S]*?)<\/h4>/gi, '\n\n#### $1\n\n')
    .replace(/<strong[^>]*>([\s\S]*?)<\/strong>/gi, '**$1**')
    .replace(/<b[^>]*>([\s\S]*?)<\/b>/gi, '**$1**')
    .replace(/<em[^>]*>([\s\S]*?)<\/em>/gi, '_$1_')
    .replace(/<i[^>]*>([\s\S]*?)<\/i>/gi, '_$1_')
    .replace(/<code[^>]*>([\s\S]*?)<\/code>/gi, '`$1`')
    .replace(/<pre[^>]*>([\s\S]*?)<\/pre>/gi, '\n\n```\n$1\n```\n\n')
    .replace(/<blockquote[^>]*>([\s\S]*?)<\/blockquote>/gi, (_, c) => '\n\n> ' + c.replace(/\n/g, '\n> ') + '\n\n')
    .replace(/<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi, '[$2]($1)')
    .replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, '\n- $1')
    .replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '\n\n$1\n\n')
    .replace(/<br\s*\/?>/gi, '  \n')
    .replace(/<hr\s*\/?>/gi, '\n\n---\n\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

function extractArticle(html, url) {
  const titleMatch = html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  const title = titleMatch
    ? titleMatch[1].replace(/<[^>]+>/g, '').trim()
    : html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1]?.split('|')[0]?.trim() || '';

  const dateMatch = html.match(/article:published_time"[^>]*content="([^"]+)"/i)
    || html.match(/<time[^>]*datetime="([^"]+)"/i);
  const date = dateMatch ? dateMatch[1].slice(0, 10) : '';

  const descMatch = html.match(/name="description"[^>]*content="([^"]+)"/i)
    || html.match(/property="og:description"[^>]*content="([^"]+)"/i);
  const description = descMatch ? descMatch[1] : '';

  const articleMatch = html.match(/<article[^>]*>([\s\S]*?)<\/article>/i)
    || html.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
  const content = htmlToMd(articleMatch ? articleMatch[1] : html);

  return { title, date, description, content, url };
}

// ── Main ──────────────────────────────────────────────────────────────────────

console.log(`Fetching blog index via Lightpanda: ${BLOG_INDEX}\n`);
const indexHtml = lightpandaFetch(BLOG_INDEX);

if (!indexHtml || indexHtml.length < 100) {
  console.error('Failed to fetch blog index. Is Docker running?');
  process.exit(1);
}

const escapedPrefix = BLOG_PREFIX.replace(/\//g, '\\/');
const linkRe = new RegExp(`href="(${escapedPrefix}[^"#?]+)"`, 'g');
const blogLinks = [...new Set([...indexHtml.matchAll(linkRe)].map(m => BASE_URL + m[1]))].sort();
console.log(`Found ${blogLinks.length} blog posts\n`);

const articles = [];

for (let i = 0; i < blogLinks.length; i++) {
  const url  = blogLinks[i];
  const slug = url.split(BLOG_PREFIX)[1];
  process.stdout.write(`[${String(i + 1).padStart(2, '0')}/${blogLinks.length}] ${slug} ... `);

  const html = lightpandaFetch(url);
  if (!html || html.length < 100) { console.log('SKIP (no content)'); continue; }

  const article = extractArticle(html, url);
  articles.push(article);
  console.log(`OK — "${article.title}"`);
}

console.log(`\nBuilding markdown from ${articles.length} articles...`);

let md = `# Blog — Complete Archive\n\n`;
md += `Source: ${BLOG_INDEX}  \nTotal articles: ${articles.length}\n\n---\n\n`;
md += `## Table of Contents\n\n`;

articles.forEach((a, i) => {
  const anchor = a.url.split(BLOG_PREFIX)[1].toLowerCase().replace(/[^a-z0-9]/g, '-');
  md += `${i + 1}. [${a.title || anchor}](#${anchor})\n`;
});
md += `\n---\n\n`;

for (const a of articles) {
  const anchor = a.url.split(BLOG_PREFIX)[1].toLowerCase().replace(/[^a-z0-9]/g, '-');
  md += `## ${a.title}\n\n<a name="${anchor}"></a>\n\n`;
  if (a.date)        md += `**Date:** ${a.date}  \n`;
  md += `**URL:** ${a.url}  \n`;
  if (a.description) md += `**Summary:** ${a.description}\n\n`;
  md += `---\n\n${a.content}\n\n---\n\n`;
}

mkdirSync(OUTPUT_DIR, { recursive: true });
writeFileSync(OUTPUT, md, 'utf8');
console.log(`\nSaved to: ${OUTPUT}`);
console.log(`Size: ${Math.round(Buffer.byteLength(md, 'utf8') / 1024)} KB`);
