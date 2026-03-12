import json
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"

ARCHIVE_HINTS = [
    "leider ist diese stellenausschreibung nicht mehr verfügbar",
    "job posting is no longer available",
    "position has already been filled",
    "vielen dank, dass sie die karrierewebseite von basf nutzen",
    "zurück zu jobs",
]

async def is_job_active(page, url):
    try:
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        content = (await page.content()).lower()
        for hint in ARCHIVE_HINTS:
            if hint in content:
                return False
        title = await page.title()
        if not title or len(title.strip()) < 3:
            return False
        return True
    except:
        return False

async def scrape_jobs():
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        print("Lade Suchergebnisse...")
        await page.goto(SEARCH_URL, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        job_links = await page.eval_on_selector_all(
            "a[href*='/job/']",
            "els => [...new Set(els.map(e => e.href))]"
        )

        print(f"{len(job_links)} Job-Links gefunden. Prüfe jeden einzeln...")

        checked = 0
        for url in job_links:
            if len(results) >= 50:
                break
            if not url.startswith("https://basf.jobs"):
                continue

            job_page = await browser.new_page()
            active = await is_job_active(job_page, url)

            if active:
                try:
                    title = await job_page.title()
                    title = title.replace(" | BASF", "").replace(" - BASF", "").strip()

                    location = ""
                    try:
                        loc_el = await job_page.query_selector("[class*='location'], [class*='Location']")
                        if loc_el:
                            location = (await loc_el.inner_text()).strip()
                    except:
                        pass

                    results.append({
                        "title": title,
                        "url": url,
                        "location": location,
                        "valid": True
                    })
                    print(f"✅ {title}")
                except:
                    pass

            await job_page.close()
            checked += 1
            if checked % 10 == 0:
                print(f"  {checked} geprüft, {len(results)} aktiv...")

        await browser.close()

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(results),
        "jobs": results
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fertig: {len(results)} aktive Jobs gespeichert in jobs.json")

asyncio.run(scrape_jobs())
