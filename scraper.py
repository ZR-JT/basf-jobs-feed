import json
import re
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime
# Url
SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_URL = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
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
            print(f"  Seite skip={skip}: {len(batch)} Einträge geladen (gesamt: {len(all_raw_jobs)})")

            if len(batch) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

    print(f"Rohdaten gesamt: {len(all_raw_jobs)} Einträge (inkl. alle Locales)")

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

        entry = {
            "job_id": numeric_id,
            "title": (job.get("title") or "").strip(),
            "url": job.get("link") or f"https://basf.jobs/job/{numeric_id}/",
            "city": addr.get("city") or addr.get("locationCity") or "",
            "state": addr.get("state") or "",
            "country": addr.get("country") or job.get("country") or "Germany",
            "postal_code": addr.get("adcode") or job.get("adcode") or "",
            "company": job.get("legalEntity") or "BASF",
            "business_unit": job.get("businessUnit") or "",
            "department": job.get("department") or "",
            "job_field": job.get("jobField") or job.get("category") or "",
            "job_level": job.get("jobLevel") or job.get("customfield1") or "",
            "job_type": job.get("jobType") or job.get("customfield5") or "",
            "hybrid": job.get("hybrid") or False,
            "date_posted": job.get("datePosted") or "",
            "start_date": job.get("startDate") or "",
            "language": job.get("language") or "",
            "description": description,
            "recruiter": recruiter if recruiter else None,
            "valid": True
        }

        entry = {k: v for k, v in entry.items() if v is not None and v != "" and v != {}}
        entry["valid"] = True
        jobs.append(entry)

    print(f"\n📊 Statistiken:")
    print(f"  Unique Jobs: {len(jobs)}")
    print(f"  Mit URL: {sum(1 for j in jobs if j.get('url'))}")
    print(f"  Mit Beschreibung: {sum(1 for j in jobs if j.get('description'))}")
    print(f"  Mit Recruiter: {sum(1 for j in jobs if j.get('recruiter'))}")
    print(f"  Mit Datum: {sum(1 for j in jobs if j.get('date_posted'))}")
    print(f"  Hybrid: {sum(1 for j in jobs if j.get('hybrid'))}")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ jobs.json gespeichert — {len(jobs)} Jobs!")

    # HTML-Version generieren
    html_jobs = ""
    for j in jobs:
        recruiter_info = ""
        if j.get("recruiter"):
            r = j["recruiter"]
            recruiter_info = f'<p class="recruiter">Ansprechpartner: {r.get("name","")} | {r.get("email","")} | {r.get("phone","")}</p>'

        html_jobs += f"""
<div class="job">
  <h2><a href="{j.get('url','')}">{j.get('title','')}</a></h2>
  <p><strong>Ort:</strong> {j.get('city','')}, {j.get('state','')}</p>
  <p><strong>Unternehmen:</strong> {j.get('company','')}</p>
  <p><strong>Bereich:</strong> {j.get('job_field','')}</p>
  <p><strong>Abteilung:</strong> {j.get('department','')}</p>
  <p><strong>Level:</strong> {j.get('job_level','')}</p>
  <p><strong>Typ:</strong> {j.get('job_type','')}</p>
  <p><strong>Hybrid:</strong> {'Ja' if j.get('hybrid') else 'Nein'}</p>
  <p><strong>Veröffentlicht:</strong> {j.get('date_posted','')[:10]}</p>
  <p class="description">{j.get('description','')}</p>
  {recruiter_info}
</div>
"""

    html_content = f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>BASF Jobs Deutschland</title>
</head>
<body>
  <h1>BASF Stellenangebote Deutschland</h1>
  <p>Stand: {output['last_updated']} | Anzahl: {len(jobs)} Stellen</p>
  {html_jobs}
</body>
</html>"""

    with open("jobs.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"✅ jobs.html gespeichert!")

asyncio.run(scrape_jobs())
