import json
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"

async def scrape_jobs():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        print("Lade Seite...")
        await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(8000)

        # Alle Links auf der Seite ausgeben
        all_links = await page.eval_on_selector_all(
            "a[href]",
            "els => [...new Set(els.map(e => e.href))].filter(h => h.includes('basf'))"
        )

        print(f"\n=== ALLE BASF LINKS ({len(all_links)}) ===")
        for link in all_links[:50]:
            print(link)

        # Seitentitel und etwas HTML ausgeben
        title = await page.title()
        print(f"\n=== SEITENTITEL ===\n{title}")

        # Ersten sichtbaren Text ausgeben
        body_text = await page.inner_text("body")
        print(f"\n=== ERSTER TEXT (500 Zeichen) ===\n{body_text[:500]}")

        # Screenshot speichern
        await page.screenshot(path="debug_screenshot.png", full_page=False)
        print("\nScreenshot gespeichert als debug_screenshot.png")

        await browser.close()

    # Leere JSON damit der Commit funktioniert
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": 0,
        "jobs": [],
        "debug": "siehe Actions Log für Link-Struktur"
    }
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

asyncio.run(scrape_jobs())
