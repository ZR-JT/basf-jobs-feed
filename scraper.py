import json
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"

async def scrape_jobs():
    api_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Jeden Netzwerk-Request mitschneiden
        async def handle_response(response):
            url = response.url
            # Nur JSON-Antworten die nach Jobs aussehen
            if any(x in url.lower() for x in ["job", "search", "career", "vacancy", "position", "api"]):
                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        body = await response.json()
                        api_responses.append({
                            "url": url,
                            "status": response.status,
                            "data_preview": str(body)[:300]
                        })
                        print(f"✅ JSON API gefunden: {url}")
                        print(f"   Preview: {str(body)[:200]}\n")
                except Exception as e:
                    pass

        page.on("response", handle_response)

        print("Lade Seite und warte auf API-Calls...")
        await page.goto(SEARCH_URL, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(5000)

        # Alle abgefangenen Requests ausgeben
        print(f"\n=== {len(api_responses)} JSON API-Calls gefunden ===")
        for r in api_responses:
            print(f"URL: {r['url']}")
            print(f"Status: {r['status']}")
            print(f"Data: {r['data_preview']}")
            print("---")

        # Versuche Jobs direkt aus API-Response zu extrahieren
        jobs = []
        for r in api_responses:
            url = r["url"]
            if len(jobs) > 0:
                break
            try:
                response = await page.request.get(url)
                data = await response.json()

                # Häufige JSON-Strukturen probieren
                candidates = []
                if isinstance(data, list):
                    candidates = data
                elif "jobs" in data:
                    candidates = data["jobs"]
                elif "results" in data:
                    candidates = data["results"]
                elif "data" in data:
                    candidates = data["data"] if isinstance(data["data"], list) else []
                elif "items" in data:
                    candidates = data["items"]

                print(f"\nKandidaten gefunden: {len(candidates)} in {url}")

                for item in candidates[:5]:
                    print(f"  Felder: {list(item.keys()) if isinstance(item, dict) else item}")

                jobs = candidates
            except Exception as e:
                print(f"Fehler bei {url}: {e}")

        await browser.close()

    # Ergebnis speichern
    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "api_calls_found": [r["url"] for r in api_responses],
        "jobs": jobs[:5]  # erstmal nur 5 zum Testen
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fertig. {len(jobs)} Jobs, {len(api_responses)} API-Calls abgefangen.")

asyncio.run(scrape_jobs())
