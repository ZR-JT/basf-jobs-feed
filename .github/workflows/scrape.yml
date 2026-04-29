import json
import re
import asyncio
import aiohttp
from playwright.async_api import async_playwright
from datetime import datetime

SEARCH_URL = "https://basf.jobs/?currentPage=1&pageSize=1000&addresses%2Fcountry=Germany"
AZURE_URL = "https://searchui.search.windows.net/indexes/basf-prod/docs/search?api-version=2020-06-30"
BASE_URL = "https://ZR-JT.github.io/basf-jobs-feed"
EVENTS_URL = "https://www.basf.com/global/de/careers/events.html"

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
    return text.strip('-')

async def scrape_events(session):
    try:
        async with session.get(EVENTS_URL, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"⚠️ Events nicht erreichbar (Status {resp.status})")
                return []
            html = await resp.text()
        events = []
        ld_matches = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL)
        for ld in ld_matches:
            try:
                data = json.loads(ld)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") in ("Event", "EducationEvent", "BusinessEvent"):
                        events.append({
                            "title": item.get("name", ""),
                            "date": item.get("startDate", "")[:10] if item.get("startDate") else "",
                            "time": item.get("startDate", "")[11:16] if item.get("startDate") and "T" in item.get("startDate","") else "",
                            "location": item.get("location", {}).get("name", "") if isinstance(item.get("location"), dict) else str(item.get("location", "")),
                            "category": item.get("@type", "Event"),
                            "description": strip_html(item.get("description", ""))[:200],
                            "url": item.get("url", EVENTS_URL),
                        })
            except (json.JSONDecodeError, AttributeError):
                continue
        print(f"✅ {len(events)} Events gefunden")
        return events
    except Exception as e:
        print(f"⚠️ Events nicht ladbar: {e}")
        return []

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
                found_key = (headers.get("api-key") or headers.get("Api-Key") or
                             headers.get("authorization") or "")
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
        events_task = asyncio.create_task(scrape_events(session))

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

        events = await events_task

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

    jobs.sort(key=lambda j: j.get("date_posted", ""), reverse=True)
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── jobs.json (vollständig, für Detailansicht) ───────────────────────────
    output = {"last_updated": timestamp, "total_active": len(jobs), "jobs": jobs}
    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ jobs.json gespeichert — {len(jobs)} Jobs!")

    # ── NEU: jobs_mini.json (ultra-kompakt, für Primärsuche) ─────────────────
    # Nur 5 Felder: job_id, title, city, job_field, url
    # ~16 Tokens pro Eintrag → 197 Jobs ≈ 3.150 Tokens (passt ins Token-Budget)
    mini_jobs = []
    for j in jobs:
        mini_jobs.append({
            "i": j["job_id"],
            "t": j["title"],
            "c": j.get("city", ""),
            "s": j.get("state", ""),
            "f": j.get("job_field", ""),
            "l": j.get("job_level", ""),
            "u": j["url"],
            "d": j.get("date_posted", "")[:10],
        })
    mini_output = {"updated": timestamp, "total": len(mini_jobs), "jobs": mini_jobs}
    with open("jobs_mini.json", "w", encoding="utf-8") as f:
        json.dump(mini_output, f, ensure_ascii=False, separators=(',', ':'))
    print(f"✅ jobs_mini.json gespeichert — {len(mini_jobs)} Jobs (kompakt)!")

    # ── events.json + events.html ────────────────────────────────────────────
    events_output = {"last_updated": timestamp, "total_events": len(events), "events": events}
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(events_output, f, ensure_ascii=False, indent=2)

    if events:
        event_rows = ""
        for e in sorted(events, key=lambda x: x.get("date", ""), reverse=True):
            url = e.get("url", EVENTS_URL)
            title = e.get("title", "")
            date = e.get("date", "")
            time = e.get("time", "")
            location = e.get("location", "")
            category = e.get("category", "")
            description = e.get("description", "")
            time_str = f" | {time} Uhr" if time else ""
            loc_str = f" | {location}" if location else ""
            cat_str = f" | {category}" if category else ""
            event_rows += f"""<div class="event">
  <h2><a href="{url}">{title}</a></h2>
  <p><strong>Datum:</strong> {date}{time_str}{loc_str}{cat_str}</p>
  {f'<p>{description}</p>' if description else ''}
</div>
"""
    else:
        event_rows = "<p>Aktuell sind keine Events verfügbar.</p>"

    events_html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Karriere-Events</title></head>
<body>
<h1>BASF Karriere-Events</h1>
<p>Stand: {timestamp} | {len(events)} Event(s)</p>
{event_rows}
</body>
</html>"""
    with open("events.html", "w", encoding="utf-8") as f:
        f.write(events_html)
    print(f"✅ events.json + events.html gespeichert — {len(events)} Events!")

    # ── Regionen + index.html ────────────────────────────────────────────────
    import os
    regions = {}
    for j in jobs:
        key = (j.get("state", "Unbekannt"), j.get("city", "Unbekannt"))
        if key not in regions:
            regions[key] = []
        regions[key].append(j)

    sorted_regions = sorted(regions.keys(), key=lambda k: (k[0].lower(), k[1].lower()))
    os.makedirs("regions", exist_ok=True)
    region_slugs = {}

    for (state, city) in sorted_regions:
        slug = f"region-{slugify(state)}-{slugify(city)}"
        region_slugs[(state, city)] = slug
        region_jobs = regions[(state, city)]

        rows = ""
        for j in region_jobs:
            recruiter_str = ""
            if j.get("recruiter"):
                r = j["recruiter"]
                recruiter_str = f'{r.get("name","")} | {r.get("email","")} | {r.get("phone","")}'
            job_field = j.get("job_field", "")
            field_tag = f"[{job_field}] " if job_field else ""
            job_level = j.get("job_level", "")
            level_tag = f"[{job_level}] " if job_level else ""

            rows += f"""<div class="job">
  <h2><a href="{j.get('url','')}'">{j.get('title','')}</a></h2>
  <p><strong>Bereich:</strong> {job_field} | <strong>Level:</strong> {job_level}</p>
  <p><strong>Typ:</strong> {j.get('job_type','')} | <strong>Hybrid:</strong> {'Ja' if j.get('hybrid') else 'Nein'}</p>
  <p><strong>Veröffentlicht:</strong> {j.get('date_posted','')[:10]}</p>
  <p><strong>Beschreibung:</strong> {j.get('description','')}</p>
  {f'<p><strong>Ansprechpartner:</strong> {recruiter_str}</p>' if recruiter_str else ''}
</div>
"""

        html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Jobs – {city}, {state}</title></head>
<body>
<h1>BASF Jobs – {city}, {state}</h1>
<p>{len(region_jobs)} Stelle(n)</p>
{rows}
</body>
</html>"""
        with open(f"regions/{slug}.html", "w", encoding="utf-8") as f:
            f.write(html)

    print(f"✅ {len(sorted_regions)} Regionsseiten generiert!")

    # ── index.html (mit [job_field][job_level]-Tags) ──────────────────────────
    index_rows = ""
    current_state = None
    for (state, city) in sorted_regions:
        if state != current_state:
            if current_state is not None:
                index_rows += "</ul>\n"
            index_rows += f"<h2>{state}</h2>\n<ul>\n"
            current_state = state

        slug = region_slugs[(state, city)]
        region_jobs = regions[(state, city)]
        count = len(region_jobs)
        region_url = f"{BASE_URL}/regions/{slug}.html"
        index_rows += f'<li><a href="{region_url}">{city}</a> ({count} Stelle(n))<ul>\n'
        for j in region_jobs:
            job_field = j.get("job_field", "")
            field_tag = f"[{job_field}] " if job_field else ""
            job_level = j.get("job_level", "")
            level_tag = f"[{job_level}] " if job_level else ""
            index_rows += (
                f'  <li>{j.get("date_posted","")[:10]} – '
                f'{field_tag}{level_tag}'
                f'<a href="{j.get("url","")}">{j.get("title","")}</a></li>\n'
            )
        index_rows += f'</ul></li>\n'
    if current_state is not None:
        index_rows += "</ul>\n"

    index_html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Jobs Deutschland – Übersicht</title></head>
<body>
<h1>BASF Stellenangebote Deutschland</h1>
<p>Gesamt: {len(jobs)} Stellen | {len(sorted_regions)} Standorte</p>
{index_rows}
</body>
</html>"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ index.html gespeichert!")

    # ── index_lite.html ───────────────────────────────────────────────────────
    lite_rows = ""
    current_state = None
    for (state, city) in sorted_regions:
        if state != current_state:
            if current_state is not None:
                lite_rows += "</ul>\n"
            lite_rows += f"<h2>{state}</h2>\n<ul>\n"
            current_state = state
        slug = region_slugs[(state, city)]
        count = len(regions[(state, city)])
        region_url = f"{BASE_URL}/regions/{slug}.html"
        lite_rows += f'<li><a href="{region_url}">{city}</a> ({count} Stellen)</li>\n'
    if current_state is not None:
        lite_rows += "</ul>\n"

    lite_html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Jobs – Standortübersicht</title></head>
<body>
<h1>BASF Stellenangebote Deutschland</h1>
<p>Gesamt: {len(jobs)} Stellen | {len(sorted_regions)} Standorte</p>
{lite_rows}
</body>
</html>"""
    with open("index_lite.html", "w", encoding="utf-8") as f:
        f.write(lite_html)
    print(f"✅ index_lite.html gespeichert!")

asyncio.run(scrape_jobs())
