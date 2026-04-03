"""
Crawl4Noobs — server.py
Serves the UI and runs all scraping in the background.

Requirements:
    pip install flask aiohttp

Usage:
    python server.py
    Then open http://localhost:8080
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from flask import Flask, jsonify, request, send_file

# ── Paths ─────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent
DB_F    = APP_DIR / "jobs.db"
CFG_F   = APP_DIR / "config.json"
OUT_DIR = APP_DIR / "output"

DEFAULT_CFG = {
    "api_url":    "http://localhost:11235",
    "output_dir": str(OUT_DIR),
}

# ── App state ─────────────────────────────────────────────────────────────────

app   = Flask(__name__, static_folder=None)
jobs: dict[str, dict] = {}
lock  = threading.Lock()

# ── Config ────────────────────────────────────────────────────────────────────

def load_cfg() -> dict:
    if CFG_F.exists():
        try:
            return {**DEFAULT_CFG, **json.loads(CFG_F.read_text())}
        except Exception:
            pass
    return dict(DEFAULT_CFG)

def save_cfg(c: dict) -> None:
    CFG_F.write_text(json.dumps(c, indent=2))

# ── Database ──────────────────────────────────────────────────────────────────

def init_db() -> None:
    con = sqlite3.connect(DB_F)
    con.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, data TEXT, ts TEXT)")
    con.commit()
    con.close()

def db_save(job: dict) -> None:
    con = sqlite3.connect(DB_F)
    con.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?)",
                (job["id"], json.dumps(job, ensure_ascii=False), job.get("created", "")))
    con.commit()
    con.close()

def db_load() -> list[dict]:
    con = sqlite3.connect(DB_F)
    rows = con.execute("SELECT data FROM jobs ORDER BY ts DESC LIMIT 500").fetchall()
    con.close()
    out = []
    for (d,) in rows:
        try:
            out.append(json.loads(d))
        except Exception:
            pass
    return out

def db_delete(job_id: str) -> None:
    con = sqlite3.connect(DB_F)
    con.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    con.commit()
    con.close()

# ── Crawler ───────────────────────────────────────────────────────────────────

PRESETS: dict[str, dict] = {
    "just_text": {"depth": 1, "js": False, "fmt": "markdown"},
    "full_page":  {"depth": 2, "js": True,  "fmt": "markdown"},
    "data_only":  {"depth": 1, "js": False, "fmt": "json"},
}

SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".wav", ".avi",
}


def norm(u: str) -> str:
    return u.split("#")[0].split("?")[0].rstrip("/")


def ok_link(href: str, domain: str, prefix: str) -> bool:
    try:
        p = urlparse(href)
        if p.scheme not in ("http", "https"):
            return False
        if p.hostname != domain:
            return False
        if any(p.path.lower().endswith(e) for e in SKIP_EXT):
            return False
        if prefix and not p.path.startswith(prefix):
            return False
        return True
    except Exception:
        return False


def mk_markdown(name: str, seed: str, articles: list[dict]) -> str:
    lines = [
        f"# {name}\n\n",
        f"Source: {seed}  \n",
        f"Pages: {len(articles)}  \n",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n",
        "## Contents\n\n",
    ]
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a['title']}]({a['url']})\n")
    lines.append("\n---\n\n")
    for a in articles:
        lines.append(f"## {a['title']}\n\n**URL:** {a['url']}  \n")
        if a.get("desc"):
            lines.append(f"**Summary:** {a['desc']}\n\n")
        lines.append(f"---\n\n{a['content']}\n\n---\n\n")
    return "".join(lines)


async def crawl_job(job_id: str) -> None:
    with lock:
        job = jobs.get(job_id)
    if not job:
        return

    cfg     = load_cfg()
    pc      = PRESETS.get(job["preset"], PRESETS["just_text"])
    max_d   = pc["depth"] - 1       # 0 = just seed, 1 = seed + links, …
    max_pg  = int(job.get("max_pages") or 200)
    api_url = cfg["api_url"]
    prefix  = job.get("prefix", "")

    job["status"]  = "running"
    job["started"] = datetime.now().isoformat()

    visited:  set[str]   = set()
    articles: list[dict] = []
    # queue items: (url, depth)
    queue: list[tuple[str, int]] = [(norm(u), 0) for u in job["urls"]]

    def log(msg: str) -> None:
        job.setdefault("log", []).insert(0, msg)
        job["log"] = job["log"][:50]

    async with aiohttp.ClientSession() as sess:
        while queue and len(visited) < max_pg:
            if job.get("status") == "cancelled":
                break

            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            job["current_url"] = url
            total = len(visited) + len(queue)
            job["progress"] = min(int(len(visited) / max(total, 1) * 100), 95)
            log(f"⟳ {url}")

            try:
                payload = {
                    "urls": [url],
                    "crawler_params": {
                        "headless": True,
                        "javascript_enabled": pc["js"],
                    },
                    "extra": {"wait_for_network_idle_page_load_time": 1.5},
                }
                async with sess.post(
                    f"{api_url}/crawl",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=90),
                ) as r:
                    res_data = await r.json()

                res     = (res_data.get("results") or [{}])[0]
                md_obj  = res.get("markdown") or {}
                content = md_obj.get("fit_markdown") or md_obj.get("raw_markdown") or ""
                meta    = res.get("metadata") or {}
                title   = (meta.get("title") or "").split("|")[0].strip() or url
                desc    = meta.get("description") or ""

                if content.strip():
                    articles.append({
                        "url":     url,
                        "title":   title,
                        "desc":    desc,
                        "content": content.strip(),
                    })
                    job["pages_done"] = len(articles)
                    log(f"✓ {title[:80]}")
                else:
                    log(f"⚠ Empty: {url}")

                # Discover linked pages if depth allows
                if depth < max_d:
                    try:
                        domain = urlparse(url).hostname or ""
                        base   = f"{urlparse(url).scheme}://{domain}"
                    except Exception:
                        domain = ""
                        base   = ""

                    for lk in (res.get("links") or {}).get("internal", []):
                        href = lk.get("href", "")
                        if not href:
                            continue
                        if href.startswith("/"):
                            href = base + href
                        elif not href.startswith("http"):
                            continue
                        href = norm(href)
                        already_queued = any(q[0] == href for q in queue)
                        if href not in visited and not already_queued:
                            if ok_link(href, domain, prefix):
                                queue.append((href, depth + 1))

            except Exception as exc:
                log(f"✗ {exc}")

            await asyncio.sleep(0.4)

    # ── Build and save output file ────────────────────────────────────────────
    out_dir = Path(job.get("output_dir") or cfg.get("output_dir") or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe  = re.sub(r"[^a-z0-9]+", "_", job["name"].lower()).strip("_") or "output"
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{safe}_{ts}"

    if pc["fmt"] == "json":
        fname += ".json"
        body   = json.dumps(
            {"name": job["name"], "url": job["url"], "pages": articles},
            indent=2, ensure_ascii=False,
        )
    else:
        fname += ".md"
        body   = mk_markdown(job["name"], job["url"], articles)

    (out_dir / fname).write_text(body, encoding="utf-8")

    if job.get("status") != "cancelled":
        job["status"] = "done"
    job["progress"]         = 100
    job["pages_done"]       = len(articles)
    job["output_file"]      = fname
    job["output_path"]      = str(out_dir / fname)
    job["output_dir_final"] = str(out_dir)
    job["finished"]         = datetime.now().isoformat()
    job["current_url"]      = ""
    log(f"✅ {len(articles)} pages → {fname}")
    db_save(job)


def _run_thread(job_id: str) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(crawl_job(job_id))
    except Exception as exc:
        with lock:
            j = jobs.get(job_id)
            if j:
                j["status"] = "error"
                j["error"]  = str(exc)
    finally:
        loop.close()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_file(APP_DIR / "index.html")


@app.route("/api/health")
def health():
    cfg = load_cfg()
    try:
        import urllib.request
        with urllib.request.urlopen(cfg["api_url"] + "/health", timeout=4) as r:
            data = json.loads(r.read())
        return jsonify({"status": "online", "detail": data})
    except Exception as e:
        return jsonify({"status": "offline", "error": str(e)}), 503


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(load_cfg())
    c = {**load_cfg(), **request.json}
    save_cfg(c)
    return jsonify({"ok": True})


@app.route("/api/pick-folder", methods=["POST"])
def pick_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Choose where to save scraped files")
        root.destroy()
        return jsonify({"folder": folder or ""})
    except Exception as e:
        return jsonify({"folder": "", "error": str(e)})


@app.route("/api/open-folder", methods=["POST"])
def open_folder_route():
    folder = request.json.get("folder", "") or load_cfg().get("output_dir", "") or str(OUT_DIR)
    folder = str(Path(folder))
    try:
        if sys.platform == "win32":
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/jobs")
def list_jobs():
    with lock:
        all_j = list(jobs.values())
    return jsonify(sorted(all_j, key=lambda j: j.get("created", ""), reverse=True))


@app.route("/api/job/<jid>")
def get_job(jid):
    with lock:
        j = jobs.get(jid)
    return jsonify(j) if j else (jsonify({"error": "not found"}), 404)


@app.route("/api/scrape", methods=["POST"])
def scrape():
    data = request.json or {}
    raw  = data.get("urls", "")
    if isinstance(raw, str):
        raw = [u.strip() for u in raw.splitlines() if u.strip()]
    if not raw:
        return jsonify({"error": "No URLs provided"}), 400

    # Prevent re-scraping URLs already running or completed
    with lock:
        active_urls: set[str] = set()
        for j in jobs.values():
            if j["status"] in ("running", "done"):
                active_urls.update(norm(u) for u in j.get("urls", []))
        new_urls = [u for u in raw if norm(u) not in active_urls]

    skipped = len(raw) - len(new_urls)
    if not new_urls:
        return jsonify({
            "error": f"All {len(raw)} URL(s) have already been scraped or are running.",
            "skipped": skipped,
        }), 409

    try:
        name = urlparse(new_urls[0]).hostname.replace("www.", "")
    except Exception:
        name = new_urls[0][:40]

    cfg   = load_cfg()
    jid   = str(uuid.uuid4())[:8]
    job: dict = {
        "id":               jid,
        "name":             data.get("name") or name,
        "url":              new_urls[0],
        "urls":             new_urls,
        "preset":           data.get("preset", "just_text"),
        "status":           "running",
        "progress":         0,
        "pages_done":       0,
        "max_pages":        int(data.get("max_pages") or 200),
        "prefix":           data.get("prefix", ""),
        "output_dir":       data.get("output_dir") or cfg.get("output_dir") or str(OUT_DIR),
        "output_file":      None,
        "output_path":      None,
        "output_dir_final": None,
        "log":              [],
        "current_url":      "",
        "created":          datetime.now().isoformat(),
        "started":          None,
        "finished":         None,
        "error":            None,
        "skipped":          skipped,
    }

    with lock:
        jobs[jid] = job

    threading.Thread(target=_run_thread, args=(jid,), daemon=True).start()
    return jsonify(job), 201


@app.route("/api/job/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    with lock:
        j = jobs.get(jid)
        if j and j["status"] == "running":
            j["status"] = "cancelled"
    return jsonify({"ok": True})


@app.route("/api/job/<jid>", methods=["DELETE"])
def del_job(jid):
    with lock:
        jobs.pop(jid, None)
    db_delete(jid)
    return jsonify({"ok": True})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()

    # Restore completed jobs from DB; mark interrupted ones as errored
    for j in db_load():
        if j.get("status") in ("running", "waiting"):
            j["status"] = "error"
            j["error"]  = "Server was restarted"
        jobs[j["id"]] = j

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Open browser after server starts
    def _open_browser() -> None:
        time.sleep(1.5)
        webbrowser.open("http://localhost:8080")

    threading.Thread(target=_open_browser, daemon=True).start()

    print("\n  ✓ Crawl4Noobs running at http://localhost:8080")
    print("  Press Ctrl+C to stop.\n")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
