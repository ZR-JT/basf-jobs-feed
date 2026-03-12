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

    print("✅ API Key gefunden")

    jobs = []
    all_field_names = set()

    async with aiohttp.ClientSession() as session:

        # DEBUG: Ein Job mit allen Feldern anzeigen
        debug_body = {
            "search": "*",
            "filter": "addresses/any(a: a/country eq 'Germany')",
            "select": "*",
            "top": 1
        }
        async with session.post(
            AZURE_URL,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=debug_body
        ) as resp:
            data = await resp.json()
            sample = data.get("value", [])
            if sample:
                all_field_names = set(sample[0].keys())
                print("=== ALLE VERFÜGBAREN FELDER ===")
                print(json.dumps(sample[0], ensure_ascii=False, indent=2))

        # Alle Jobs mit allen Feldern abrufen
        search_body = {
            "search": "*",
            "filter": "addresses/any(a: a/country eq 'Germany')",
            "select": "*",
            "top": 1000,
            "orderby": "postedDate desc"
        }

        async with session.post(
            AZURE_URL,
            headers={"api-key": api_key, "Content-Type": "application/json"},
            json=search_body
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                print(f"Fehler: {err[:500]}")
                return
            data = await resp.json()
            raw_jobs = data.get("value", [])
            print(f"\n{len(raw_jobs)} Jobs geladen")

            for job in raw_jobs:

                # --- TITEL ---
                title = (
                    job.get("title") or
                    job.get("jobTitle") or
                    job.get("name") or ""
                ).strip()

                # --- URL ---
                url = ""
                for field in ["jobUrl", "url", "applyUrl", "detailUrl",
                               "link", "jobLink", "applyLink", "reqUrl"]:
                    val = job.get(field, "")
                    if val and str(val).startswith("http"):
                        url = val
                        break
                if not url:
                    job_id = (
                        job.get("jobId") or job.get("id") or
                        job.get("requisitionId") or job.get("reqId") or ""
                    )
                    if job_id:
                        url = f"https://basf.jobs/job/{job_id}"

                # --- LOCATION ---
                city = ""
                country = ""
                addresses = job.get("addresses", [])
                if isinstance(addresses, list) and addresses:
                    addr = addresses[0]
                    if isinstance(addr, dict):
                        city = addr.get("city") or addr.get("name") or ""
                        country = addr.get("country") or ""
                if not city:
                    for field in ["city", "location", "locationName", "jobLocation"]:
                        val = job.get(field, "")
                        if val:
                            city = val
                            break

                # --- BESCHREIBUNG ---
                description = (
                    job.get("description") or
                    job.get("jobDescription") or
                    job.get("shortDescription") or
                    job.get("summary") or
                    job.get("jobSummary") or
                    job.get("snippet") or ""
                )
                # HTML-Tags entfernen falls vorhanden
                if description and "<" in description:
                    import re
                    description = re.sub(r'<[^>]+>', ' ', description)
                    description = re.sub(r'\s+', ' ', description).strip()

                # --- ABTEILUNG / KATEGORIE ---
                department = (
                    job.get("department") or
                    job.get("division") or
                    job.get("businessUnit") or
                    job.get("category") or
                    job.get("jobCategory") or
                    job.get("functionalArea") or ""
                )

                # --- ANSTELLUNGSART ---
                employment_type = (
                    job.get("employmentType") or
                    job.get("jobType") or
                    job.get("contractType") or
                    job.get("workingTime") or
                    job.get("scheduleType") or ""
                )

                # --- DATUM ---
                posted_date = (
                    job.get("postedDate") or
                    job.get("datePosted") or
                    job.get("publishedDate") or
                    job.get("createdDate") or ""
                )
                closing_date = (
                    job.get("closingDate") or
                    job.get("expiryDate") or
                    job.get("applicationDeadline") or ""
                )

                # --- JOB ID ---
                job_id = (
                    job.get("jobId") or
                    job.get("id") or
                    job.get("requisitionId") or
                    job.get("reqId") or ""
                )

                # --- SPRACHE / SONSTIGES ---
                language = job.get("language") or job.get("jobLanguage") or ""
                remote = job.get("remote") or job.get("remoteWork") or job.get("workFromHome") or ""
                salary = job.get("salary") or job.get("compensation") or job.get("salaryRange") or ""
                experience = job.get("experienceLevel") or job.get("seniority") or job.get("level") or ""
                company = job.get("company") or job.get("employer") or job.get("legalEntity") or "BASF"

                if title:
                    entry = {
                        "title": title,
                        "url": url,
                        "city": city,
                        "country": country,
                        "department": department,
                        "employment_type": employment_type,
                        "experience_level": experience,
                        "company": company,
                        "posted_date": posted_date,
                        "closing_date": closing_date,
                        "remote": remote,
                        "salary": salary,
                        "language": language,
                        "description": description[:2000] if description else "",
                        "job_id": str(job_id),
                        "valid": True
                    }
                    # Leerstrings entfernen für saubere JSON
                    entry = {k: v for k, v in entry.items() if v != "" and v is not None}
                    entry["valid"] = True
                    jobs.append(entry)

    # Stats ausgeben
    print(f"\n📊 Statistiken:")
    print(f"  Jobs gesamt: {len(jobs)}")
    print(f"  Mit URL: {sum(1 for j in jobs if j.get('url'))}")
    print(f"  Mit City: {sum(1 for j in jobs if j.get('city'))}")
    print(f"  Mit Beschreibung: {sum(1 for j in jobs if j.get('description'))}")
    print(f"  Mit Abteilung: {sum(1 for j in jobs if j.get('department'))}")
    print(f"  Mit Anstellungsart: {sum(1 for j in jobs if j.get('employment_type'))}")
    print(f"  Mit Datum: {sum(1 for j in jobs if j.get('posted_date'))}")
    print(f"\n  Alle API-Felder: {sorted(all_field_names)}")

    output = {
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_active": len(jobs),
        "jobs": jobs
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("\n✅ jobs.json gespeichert!")

asyncio.run(scrape_jobs())
