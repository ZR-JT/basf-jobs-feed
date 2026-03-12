import json
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_URL = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"

async def scrape_jobs():
    api_key = None
    request_body = None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        async def handle_request(request):
            nonlocal api_key, request_body
            if "searchui.search.windows.net" in request.url:
                headers = dict(request.headers)
                body = request.post_data or ""
                found_key = (
                    headers.get("api-key") or
                    headers.get("Api-Key") or
                    headers.get("authorization") or ""
                )
                if found_key:
                    api_key = found_key
                if body:
                    request_body = body

        context.on("request", handle_request)
        await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await browser.close()

    if not api_key:
        print("❌ Kein API Key gefunden!")
        return

    print(f"✅ API Key gefunden")

    jobs = []
    async with aiohttp.ClientSession() as session:
        # Schritt 1: Alle Felder eines Jobs anzeigen
        debug_body = json.loads(request_body) if request_body else {}
        debug_body["top"] = 1
        debug_body["filter"] = "addresses/any(a: a/country eq 'Germany')"

        async with session.post(
            AZURE_URL,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=debug_body
        ) as resp:
            data = await resp.json()
            sample = data.get("value", [])
            if sample:
                print("=== ALLE FELDER EINES JOBS ===")
                print(json.dumps(sample[0], ensure_ascii=False, indent=2))

        # Schritt 2: Alle Jobs abrufen
        search_body = json.loads(request_body) if request_body else {}
        search_body["top"] = 1000
        search_body["filter"] = "addresses/any(a: a/country eq 'Germany')"

        async with session.post(
            AZURE_URL,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=search_body
        ) as resp:
            data = await resp.json()
            raw_jobs = data.get("value", [])
            print(f"\n{len(raw_jobs)} Jobs gefunden")

            for job in raw_jobs:
                # Titel
                title = (
                    job.get("title") or
                    job.get("jobTitle") or
                    job.get("name") or ""
                ).strip()

                # URL — alle möglichen Felder probieren
                url = ""
                for field in ["jobUrl", "url", "applyUrl", "detailUrl", "link",
                               "jobLink", "jobDetailUrl", "applyLink", "reqUrl"]:
                    val = job.get(field, "")
                    if val and val.startswith("http"):
                        url = val
                        break

                # Falls immer noch leer: URL aus jobId bauen
                if not url:
                    job_id = (
                        job.get("jobId") or
                        job.get("id") or
                        job.get("requisitionId") or
                        job.get("reqId") or ""
                    )
                    if job_id:
                        url = f"https://basf.jobs/job/{job_id}"

                # Location
                location = ""
                for field in ["city", "location", "locationName", "jobLocation"]:
                    val = job.get(field, "")
                    if val:
                        location = val
                        break

                if not location:
                    addresses = job.get("addresses", [])
                    if isinstance(addresses, list) and addresses:
                        addr = addresses[0]
                        if isinstance(addr, dict):
                            location = addr.get("city") or addr.get("name") or ""

                if title:
                    jobs.append({
                        "title": title,
                        "url": url,
                        "location": location,
                        "valid": True
                    })

    print(f"✅ {len(jobs)} Jobs verarbeitet")
    print(f"Mit URL: {sum(1 for j in jobs if j['url'])}")
    print(f"Mit Location: {sum(1 for j in jobs if j['location'])}")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("✅ jobs.json gespeichert!")

asyncio.run(scrape_jobs())
