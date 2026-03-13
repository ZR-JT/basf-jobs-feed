import json
import re
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_URL = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"
BASE_URL = "https://ZR-JT.github.io/basf-jobs-feed"

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[äÄ]', 'ae', text)
    text = re.sub(r'[öÖ]', 'oe', text)
    text = re.sub(r'[üÜ]', 'ue', text)
    text = re.sub(r'[ß]', 'ss', text)
    text = re.sub(r'[^a-z0-9]+', '-', text)
    text = text.strip('-')
    return text

async def scrape_jobs():
    api_key = None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()

        async def handle_request(request):
            nonlocal api_key
            if "searchui.search.windows.net" in request.url:
                headers = dict(request.headers)
                found_key = (
                    headers.get("api-key") or
                    headers.get("Api-Key") or
                    headers.get("authorization") or ""
                )
                if found_key:
                    api_key = found_key

        context.on("request", handle_request)
        await page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        await browser.close()

    if not api_key:
        print("❌ Kein API Key gefunden!")
        return

    print("✅ API Key gefunden")

    PREFERRED_LOCALES = ["en_US", "de_DE", "de_AT", "de_CH"]
    PAGE_SIZE = 1000
    all_raw_jobs = []
    skip = 0

    async with aiohttp.ClientSession() as session:
        while True:
            search_body = {
                "search": "*",
                "filter": "addresses/any(a: a/country eq 'Germany')",
                "select": "*",
                "top": PAGE_SIZE,
                "skip": skip,
                "count": True
            }
            async with session.post(
                AZURE_URL,
                headers={"api-key": api_key, "Content-Type": "application/json"},
                json=search_body
            ) as resp:
                if resp.status != 200:
                    err = await resp.text()
                    print(f"❌ Fehler bei skip={skip}: {err[:300]}")
                    break
                data = await resp.json()

            batch = data.get("value", [])
            total_count = data.get("@odata.count", "?")
            if skip == 0:
                print(f"API meldet @odata.count: {total_count}")

            all_raw_jobs.extend(batch)
            print(f"  skip={skip}: {len(batch)} geladen (gesamt: {len(all_raw_jobs)})")

            if len(batch) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

    print(f"Rohdaten: {len(all_raw_jobs)} (inkl. alle Locales)")

    # Deduplizieren
    job_map = {}
    for job in all_raw_jobs:
        full_id = str(job.get("jobId", ""))
        numeric_id = full_id.split("-")[0] if "-" in full_id else full_id
        language = job.get("language", "")
        if numeric_id not in job_map:
            job_map[numeric_id] = job
        else:
            current_lang = job_map[numeric_id].get("language", "")
            current_pref = PREFERRED_LOCALES.index(current_lang) if current_lang in PREFERRED_LOCALES else 999
            new_pref = PREFERRED_LOCALES.index(language) if language in PREFERRED_LOCALES else 999
            if new_pref < current_pref:
                job_map[numeric_id] = job

    print(f"Nach Deduplizierung: {len(job_map)} unique Jobs")

    jobs = []
    for numeric_id, job in job_map.items():
        addr = {}
        addresses = job.get("addresses", [])
        if isinstance(addresses, list) and addresses:
            addr = addresses[0] if isinstance(addresses[0], dict) else {}

        recruiter_raw = job.get("recruiter") or {}
        recruiter = {}
        if recruiter_raw:
            recruiter = {
                "name": f"{recruiter_raw.get('firstName', '')} {recruiter_raw.get('lastName', '')}".strip(),
                "email": recruiter_raw.get("email", ""),
                "phone": recruiter_raw.get("phone", "")
            }
            recruiter = {k: v for k, v in recruiter.items() if v}

        raw_desc = job.get("description") or ""
        description = strip_html(raw_desc)[:500]

        city = addr.get("city") or addr.get("locationCity") or "Unbekannt"
        state = addr.get("state") or "Unbekannt"

        entry = {
            "job_id": numeric_id,
            "title": (job.get("title") or "").strip(),
            "url": job.get("link") or f"https://basf.jobs/job/{numeric_id}/",
            "city": city,
            "state": state,
            "country": addr.get("country") or "Germany",
            "company": job.get("legalEntity") or "BASF",
            "business_unit": job.get("businessUnit") or "",
            "department": job.get("department") or "",
            "job_field": job.get("jobField") or job.get("category") or "",
            "job_level": job.get("jobLevel") or job.get("customfield1") or "",
            "job_type": job.get("jobType") or job.get("customfield5") or "",
            "hybrid": job.get("hybrid") or False,
            "date_posted": job.get("datePosted") or "",
            "description": description,
            "recruiter": recruiter if recruiter else None,
        }
        entry = {k: v for k, v in entry.items() if v is not None and v != "" and v != {}}
        jobs.append(entry)

    # Nach Datum sortieren (neueste zuerst)
    jobs.sort(key=lambda j: j.get("date_posted", ""), reverse=True)

    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # jobs.json speichern
    output = {
        "last_updated": timestamp,
        "total_active": len(jobs),
        "jobs": jobs
    }
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ jobs
