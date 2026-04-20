"""
THE SCOUT — Python Fetcher (Phase 3)
=====================================
Playwright-based Indeed bulk resume downloader.
Saves PDFs to ./scout_imports/ named as: LastName_FirstName_Score.pdf

Requirements:
    pip install playwright python-dotenv
    playwright install chromium

Usage:
    1. Copy .env.example to .env and fill in credentials
    2. python scout_fetcher.py --job-id <INDEED_JOB_ID> [--max 50]
"""

import asyncio
import argparse
import re
import os
import json
import time
from pathlib import Path
from datetime import datetime

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeoutError
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[Scout Fetcher] Install requirements: pip install playwright python-dotenv && playwright install chromium")
    exit(1)

# ─── CONFIG ──────────────────────────────────────────────────────
INDEED_EMAIL    = os.getenv("INDEED_EMAIL", "")
INDEED_PASSWORD = os.getenv("INDEED_PASSWORD", "")
OUTPUT_DIR      = Path("scout_imports")
LOG_FILE        = Path("scout_fetcher_log.json")
DELAY_BETWEEN   = 1.8   # seconds between downloads (be polite to Indeed)
HEADLESS        = False  # Set True for unattended runs after testing

# ─── HELPERS ─────────────────────────────────────────────────────
def sanitize_filename(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\- ]', '', name).strip().replace(' ', '_')

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "▶", "OK": "✓", "WARN": "⚠", "ERR": "✗"}.get(level, "·")
    print(f"  [{timestamp}] {prefix} {msg}")

# ─── MAIN FETCHER ────────────────────────────────────────────────
async def fetch_resumes(job_id: str, max_candidates: int = 50):
    OUTPUT_DIR.mkdir(exist_ok=True)
    downloaded = []
    skipped    = []

    # Load prior log to avoid re-downloading
    prior_ids = set()
    if LOG_FILE.exists():
        try:
            data = json.loads(LOG_FILE.read_text())
            prior_ids = set(data.get("downloaded_ids", []))
            log(f"Loaded {len(prior_ids)} previously downloaded IDs")
        except Exception:
            pass

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page    = await context.new_page()

        # ── 1. LOGIN ─────────────────────────────────────────────
        log("Navigating to Indeed Employer login...")
        await page.goto("https://employers.indeed.com/", wait_until="networkidle")

        try:
            # Handle email step
            await page.fill('input[type="email"], input[name="__email"]', INDEED_EMAIL, timeout=8000)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)

            # Password step
            await page.fill('input[type="password"], input[name="__password"]', INDEED_PASSWORD, timeout=8000)
            await page.keyboard.press("Enter")
            await page.wait_for_load_state("networkidle", timeout=15000)
            log("Login submitted", "OK")
        except PWTimeoutError:
            log("Login form not found — may already be logged in or page structure changed", "WARN")

        # Check for 2FA prompt
        if await page.locator('text=verification code').count() > 0:
            log("Two-factor authentication required — complete it manually in the browser window", "WARN")
            input("  Press ENTER after completing 2FA...")

        # ── 2. NAVIGATE TO JOB CANDIDATES ────────────────────────
        candidates_url = f"https://employers.indeed.com/candidates?jobId={job_id}"
        log(f"Navigating to job {job_id} candidates list...")
        await page.goto(candidates_url, wait_until="networkidle")
        await page.wait_for_timeout(2000)

        # ── 3. COLLECT CANDIDATE LINKS ───────────────────────────
        log("Scanning candidate list...")
        # Indeed uses various selectors; try common ones
        selectors_to_try = [
            'a[data-tn-element="viewApplicant"]',
            'a[href*="/viewjob"]',
            '.app-list-item a',
            '[data-testid="candidate-name"] a',
        ]

        candidate_links = []
        for sel in selectors_to_try:
            links = await page.locator(sel).all()
            if links:
                for link in links:
                    href = await link.get_attribute("href")
                    text = (await link.text_content() or "").strip()
                    if href and text:
                        candidate_links.append({"name": text, "href": href})
                break

        if not candidate_links:
            log("No candidate links found via known selectors. Page may require manual inspection.", "WARN")
            log("Dumping page HTML for debugging...", "WARN")
            html = await page.content()
            Path("scout_debug_page.html").write_text(html)
            log("Saved scout_debug_page.html — inspect to find correct selectors", "WARN")
            await browser.close()
            return

        total = min(len(candidate_links), max_candidates)
        log(f"Found {len(candidate_links)} candidates. Processing up to {total}.", "OK")

        # ── 4. DOWNLOAD LOOP ──────────────────────────────────────
        for idx, cand in enumerate(candidate_links[:total]):
            name   = cand["name"]
            href   = cand["href"]
            cand_id = re.sub(r'\W+', '', href)[-20:]  # rough unique ID from URL

            if cand_id in prior_ids:
                log(f"[{idx+1}/{total}] SKIP (already downloaded): {name}")
                skipped.append(name)
                continue

            log(f"[{idx+1}/{total}] Opening: {name}")

            try:
                full_url = href if href.startswith("http") else "https://employers.indeed.com" + href
                cand_page = await context.new_page()
                await cand_page.goto(full_url, wait_until="networkidle", timeout=20000)
                await cand_page.wait_for_timeout(1200)

                # Attempt to find and click resume download
                download_selectors = [
                    'button:has-text("Download")',
                    'a:has-text("Download Resume")',
                    '[data-tn-element="downloadResume"]',
                    'button[aria-label*="download"]',
                    'a[download]',
                ]

                downloaded_file = None
                for dl_sel in download_selectors:
                    btn = cand_page.locator(dl_sel).first
                    if await btn.count() > 0:
                        async with cand_page.expect_download(timeout=15000) as dl_info:
                            await btn.click()
                        download = await dl_info.value
                        # Get inline score if visible (Indeed shows match score)
                        score = "00"
                        try:
                            score_el = cand_page.locator('[data-tn-element="matchScore"], .match-score').first
                            if await score_el.count() > 0:
                                raw_score = (await score_el.text_content() or "").strip()
                                score = re.sub(r'\D', '', raw_score)[:3] or "00"
                        except Exception:
                            pass

                        safe_name = sanitize_filename(name)
                        filename  = f"{safe_name}_{score}.pdf"
                        dest_path = OUTPUT_DIR / filename
                        await download.save_as(str(dest_path))
                        downloaded_file = str(dest_path)
                        log(f"  Saved: {filename}", "OK")
                        break

                if not downloaded_file:
                    log(f"  No download button found for {name}", "WARN")
                    skipped.append(name)
                else:
                    downloaded.append({"name": name, "file": downloaded_file, "id": cand_id})
                    prior_ids.add(cand_id)

                await cand_page.close()
                await asyncio.sleep(DELAY_BETWEEN)

            except PWTimeoutError:
                log(f"  Timeout processing {name}", "WARN")
                skipped.append(name)
            except Exception as e:
                log(f"  Error on {name}: {e}", "ERR")
                skipped.append(name)

        await browser.close()

    # ── 5. SAVE LOG ───────────────────────────────────────────────
    log_data = {
        "run_at": datetime.now().isoformat(),
        "job_id": job_id,
        "downloaded": [d["name"] for d in downloaded],
        "skipped": skipped,
        "downloaded_ids": list(prior_ids)
    }
    LOG_FILE.write_text(json.dumps(log_data, indent=2))

    print("\n" + "="*50)
    print(f"  SCOUT FETCHER COMPLETE")
    print(f"  Downloaded : {len(downloaded)}")
    print(f"  Skipped    : {len(skipped)}")
    print(f"  Output dir : {OUTPUT_DIR.resolve()}")
    print(f"  Log        : {LOG_FILE.resolve()}")
    print("="*50)
    print(f"\n  Drop the contents of '{OUTPUT_DIR}/' into The Scout PWA.")


# ─── CLI ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The Scout — Indeed Resume Fetcher")
    parser.add_argument("--job-id", required=True, help="Indeed job ID from employer portal URL")
    parser.add_argument("--max", type=int, default=50, help="Max candidates to download (default: 50)")
    args = parser.parse_args()

    if not INDEED_EMAIL or not INDEED_PASSWORD:
        print("\n[Scout Fetcher] ERROR: Set INDEED_EMAIL and INDEED_PASSWORD in your .env file")
        print("  Copy .env.example to .env and fill in credentials.\n")
        exit(1)

    print("\n" + "="*50)
    print("  THE SCOUT — INDEED FETCHER")
    print(f"  Job ID  : {args.job_id}")
    print(f"  Max     : {args.max}")
    print(f"  Output  : {OUTPUT_DIR}/")
    print("="*50 + "\n")

    asyncio.run(fetch_resumes(job_id=args.job_id, max_candidates=args.max))
