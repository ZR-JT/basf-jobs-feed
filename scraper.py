import json
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_API = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"

ARCHIVE_HINTS = [
    "leider ist diese stellenausschreibung nicht mehr verfügbar",
    "job posting is no longer available",
    "position has already been filled",
    "vielen dank, dass sie die karrierewebseite von basf nutzen",
]

async def scrape_jobs():
    captured_request = None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        # Request abfangen UND Headers + Body mitspeichern
        async def handle_request(request):
            nonlocal captured_request
            if "searchui.search.windows.net" in request.url and captured_request is None:
                try:
                    body = request.post_data
                    headers = dict(request.headers)
                    captured_request = {
                        "url": request.url,
                        "headers": headers,
                        "body": body
                    }
                    print(f"✅ Azure Request abgefangen!")
                    print(f"   Headers: {list(headers.keys())}")
                    print(f"   Body: {body[:300] if body else 'leer'}")
                except Exception as e:
                    print(f"Fehler beim Abfangen: {e}")

        page.on("request", handle_request)

        print("Lade Seite...")
        await page.goto(SEARCH_URL, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(5000)
        await browser.close()

    if not captured_request:
        print("❌ Kein Azure Request gefunden!")
        return

    # Azure API direkt aufrufen mit den echten Headers
    print("\nRufe Azure API direkt auf...")

    headers = captured_request["headers"]
    original_body = json.loads(captured_request["body"])

    # Deutschland-Filter + maximale Ergebnisse setzen
    search_body = {
        **original_body,
        "top": 1000,
        "filter": "addresses/any(a: a/country eq 'Germany')",
        "select": "jobId,title,locations,description,url,jobUrl,category,employmentType,postedDate"
    }

    print(f"Request Body: {json.dumps(search_body, indent=2)[:400]}")

    jobs = []
    async with aiohttp.ClientSession() as session:
        async with session.post(
            AZURE_API,
            headers=headers,
            json=search_body
        ) as response:
            print(f"Status: {response.status}")
            if response.status == 200:
                data = await response.json()
                print(f"Keys in Response: {list(data.keys())}")

                raw_jobs = data.get("value", data.get("results", []))
                print(f"Rohe Jobs gefunden: {len(raw_jobs)}")

                # Erste 3 Jobs zeigen um Feldnamen zu sehen
                if raw_jobs:
                    print(f"\nFelder eines Jobs: {list(raw_jobs[0].keys())}")
                    print(f"Beispiel-Job: {json.dumps(raw_jobs[0], ensure_ascii=False)[:400]}")

                for job in raw_jobs:
                    # Feldnamen flexibel auslesen
                    title = (
                        job.get("title") or
                        job.get("jobTitle") or
                        job.get("name") or ""
                    )
                    url = (
                        job.get("jobUrl") or
                        job.get("url") or
                        job.get("applyUrl") or ""
                    )
                    location = ""
                    loc = job.get("locations") or job.get("location") or job.get("addresses") or ""
                    if isinstance(loc, list) and loc:
                        location = loc[0].get("city", "") if isinstance(loc[0], dict) else str(loc[0])
                    elif isinstance(loc, str):
                        location = loc

                    if title and url:
                        jobs.append({
                            "title": title,
                            "url": url,
                            "location": location,
                            "valid": True
                        })
            else:
                error_text = await response.text()
                print(f"❌ Fehler: {error_text[:500]}")

    print(f"\n✅ {len(jobs)} Jobs gefunden")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("jobs.json gespeichert!")

asyncio.run(scrape_jobs())
