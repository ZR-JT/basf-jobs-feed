import json
import re
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2FcountryCity=Germany%7CBaden-W%C3%BCrttemberg%7CFreiburg+im+Breisgau&addresses%2FcountryCity=Germany%7CBaden-W%C3%BCrttemberg%7CGrenzach-Wyhlen&addresses%2FcountryCity=Germany%7CBaden-W%C3%BCrttemberg%7CMannheim&addresses%2FcountryCity=Germany%7CBayern%7CBurgbernheim&addresses%2FcountryCity=Germany%7CBayern%7CW%C3%BCrzburg&addresses%2FcountryCity=Germany%7CBerlin%7CBerlin&addresses%2FcountryCity=Germany%7CBrandenburg%7CSchwarzheide&addresses%2FcountryCity=Germany%7CHessen%7CFrankfurt+am+Main&addresses%2FcountryCity=Germany%7CHessen%7CLampertheim&addresses%2FcountryCity=Germany%7CNiedersachsen%7CLangelsheim&addresses%2FcountryCity=Germany%7CNiedersachsen%7CLemf%C3%B6rde&addresses%2FcountryCity=Germany%7CNiedersachsen%7CNienburg&addresses%2FcountryCity=Germany%7CNordrhein-Westfalen%7CD%C3%BCsseldorf&addresses%2FcountryCity=Germany%7CNordrhein-Westfalen%7CK%C3%B6ln&addresses%2FcountryCity=Germany%7CNordrhein-Westfalen%7CMonheim+am+Rhein&addresses%2FcountryCity=Germany%7CNordrhein-Westfalen%7CM%C3%B6nchengladbach&addresses%2FcountryCity=Germany%7CNordrhein-Westfalen%7CM%C3%BCnster&addresses%2FcountryCity=Germany%7CRemote&addresses%2FcountryCity=Germany%7CRheinland-Pfalz%7CAlbersweiler&addresses%2FcountryCity=Germany%7CRheinland-Pfalz%7CLimburgerhof&addresses%2FcountryCity=Germany%7CRheinland-Pfalz%7CLudwigshafen+am+Rhein&addresses%2FcountryCity=Germany%7CSachsen-Anhalt%7CGatersleben&addresses%2FcountryCity=Germany%7CTh%C3%BCringen%7CRudolstadt%2FcountryCity=Germany%7CBaden-Württemberg%7CBreitnau"
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

    print("✅ API Key gefunden")

    # Alle Locales abrufen, dann deduplizieren
    # Bevorzugte Reihenfolge: en_US > de_DE > andere
    PREFERRED_LOCALES = ["en_US", "de_DE", "de_AT", "de_CH"]

    search_body = {
        "search": "*",
"filter": "addresses/any(a: a/country eq 'Germany')",
        "select": "*",
        "top": 1000,
        "orderby": "datePosted desc"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            AZURE_URL,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=search_body
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                print(f"❌ Fehler: {err[:300]}")
                return
            data = await resp.json()
            raw_jobs = data.get("value", [])
            print(f"Rohdaten: {len(raw_jobs)} Einträge (inkl. alle Locales)")

    # Deduplizieren: pro numerischer Job-ID nur einen Eintrag behalten
    # jobId Format: "134069-fi_FI" → numeric_id = "134069"
    job_map = {}  # numeric_id → job dict

    for job in raw_jobs:
        full_id = str(job.get("jobId", ""))
        # Numerische ID extrahieren
        numeric_id = full_id.split("-")[0] if "-" in full_id else full_id
        language = job.get("language", "")

        if numeric_id not in job_map:
            job_map[numeric_id] = job
        else:
            # Bevorzugte Locale? Dann ersetzen
            current_lang = job_map[numeric_id].get("language", "")
            current_pref = PREFERRED_LOCALES.index(current_lang) if current_lang in PREFERRED_LOCALES else 999
            new_pref = PREFERRED_LOCALES.index(language) if language in PREFERRED_LOCALES else 999
            if new_pref < current_pref:
                job_map[numeric_id] = job

    print(f"Nach Deduplizierung: {len(job_map)} unique Jobs")

    jobs = []
    for numeric_id, job in job_map.items():

        # Adresse
        addr = {}
        addresses = job.get("addresses", [])
        if isinstance(addresses, list) and addresses:
            addr = addresses[0] if isinstance(addresses[0], dict) else {}

        # Recruiter
        recruiter_raw = job.get("recruiter") or {}
        recruiter = {}
        if recruiter_raw:
            recruiter = {
                "name": f"{recruiter_raw.get('firstName', '')} {recruiter_raw.get('lastName', '')}".strip(),
                "email": recruiter_raw.get("email", ""),
                "phone": recruiter_raw.get("phone", "")
            }
            recruiter = {k: v for k, v in recruiter.items() if v}

        # Beschreibung
        raw_desc = job.get("description") or ""
        description = strip_html(raw_desc)[:3000]

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

        # Leerstrings und None entfernen
        entry = {k: v for k, v in entry.items() if v is not None and v != "" and v != {}}
        entry["valid"] = True
        jobs.append(entry)

    # Stats
    print(f"\n📊 Statistiken:")
    print(f"  Unique Jobs: {len(jobs)}")
    print(f"  Mit URL: {sum(1 for j in jobs if j.get('url'))}")
    print(f"  Mit Recruiter: {sum(1 for j in jobs if j.get('recruiter'))}")
    print(f"  Mit Datum: {sum(1 for j in jobs if j.get('date_posted'))}")
    print(f"  Hybrid: {sum(1 for j in jobs if j.get('hybrid'))}")
        print(f"  Mit Beschreibung: {sum(1 for j in jobs if j.get('description'))}")
    print(f"  Job-Types: {set(j.get('job_type','') for j in jobs)}")
    print(f"  Job-Levels: {set(j.get('job_level','') for j in jobs)}")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ jobs.json gespeichert — {len(jobs)} deduplizierte Jobs!")

asyncio.run(scrape_jobs())
