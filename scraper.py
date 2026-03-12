import json
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
import re

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_URL = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"

async def scrape_jobs():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        api_key = None
        request_body = None

        async def handle_request(request):
            nonlocal api_key, request_body
            if "searchui.search.windows.net" in request.url:
                headers = dict(request.headers)
                body = request.post_data or ""
                found_key = (
                    headers.get("api-key") or
                    headers.get("Api-Key") or
                    headers.get("authorization") or
                    ""
                )
                if found_key:
                    api_key = found_key
                    print(f"✅ API Key gefunden: {found_key[:40]}...")
                if body:
                    request_body = body
                    print(f"✅ Request Body: {body[:300]}")

        context.on("request", handle_request)

        print("Lade Seite...")
        await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        # Falls kein Key via Request: aus JS-Bundle extrahieren
        if not api_key:
            print("Suche API Key in JavaScript...")
            scripts = await page.eval_on_selector_all(
                "script[src]",
                "els => els.map(e => e.src)"
            )
            print(f"{len(scripts)} Script-Dateien gefunden")

            for script_url in scripts:
                try:
                    response = await page.request.get(script_url)
                    text = await response.text()
                    # Azure Search API Keys sind 52 Zeichen lang
                    matches = re.findall(r'["\']([A-Za-z0-9]{50,54})["\']', text)
                    if matches:
                        print(f"Mögliche Keys in {script_url}:")
                        for m in matches[:5]:
                            print(f"  {m}")
                        api_key = matches[0]
                except:
                    pass

        # Inline Scripts durchsuchen
        if not api_key:
            inline = await page.eval_on_selector_all(
                "script:not([src])",
                "els => els.map(e => e.textContent).filter(t => t.length > 50)"
            )
            for script_text in inline:
                matches = re.findall(r'apiKey["\s:=]+["\']([^"\']{20,60})["\']', script_text, re.IGNORECASE)
                if matches:
                    print(f"API Key in Inline-Script: {matches}")
                    api_key = matches[0]
                    break

        print(f"\nErgebnis:")
        print(f"  API Key: {api_key[:50] if api_key else 'NICHT GEFUNDEN'}")
        print(f"  Body: {request_body[:200] if request_body else 'NICHT GEFUNDEN'}")

        # Wenn Key gefunden: direkt Azure API aufrufen
        jobs = []
        if api_key:
            import aiohttp
            search_body = json.loads(request_body) if request_body else {
                "search": "*",
                "filter": "addresses/any(a: a/country eq 'Germany')",
                "top": 1000
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    AZURE_URL,
                    headers={
                        "api-key": api_key,
                        "Content-Type": "application/json"
                    },
                    json=search_body
                ) as resp:
                    print(f"\nAzure API Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        raw = data.get("value", [])
                        print(f"Jobs aus Azure: {len(raw)}")
                        if raw:
                            print(f"Felder: {list(raw[0].keys())}")
                        for job in raw:
                            title = job.get("title") or job.get("jobTitle") or ""
                            url = job.get("jobUrl") or job.get("url") or ""
                            loc = job.get("locations") or job.get("location") or ""
                            if isinstance(loc, list):
                                loc = loc[0].get("city", "") if isinstance(loc[0], dict) else str(loc[0])
                            if title:
                                jobs.append({"title": title, "url": url, "location": loc, "valid": True})
                    else:
                        err = await resp.text()
                        print(f"Fehler: {err[:300]}")

        await browser.close()

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "api_key_found": bool(api_key),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fertig: {len(jobs)} Jobs gespeichert")

asyncio.run(scrape_jobs())
