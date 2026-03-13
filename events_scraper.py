import asyncio
import re
from playwright.async_api import async_playwright
from datetime import datetime

EVENTS_URLS = [
    ("Karriere-Events", "https://www.basf.com/global/de/careers/application/events"),
    ("Ausbildungs-Events", "https://www.basf.com/global/de/careers/application/events/events-ausbildung"),
]

async def scrape_events():
    all_events = []

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )

        for category, url in EVENTS_URLS:
            print(f"\n📅 Lade {category}: {url}")
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(4000)

                # "Mehr zeigen" klicken bis alle Events geladen sind
                for _ in range(10):
                    try:
                        mehr_btn = page.locator("button:has-text('Mehr zeigen'), a:has-text('Mehr zeigen')")
                        if await mehr_btn.count() > 0:
                            await mehr_btn.first.click()
                            await page.wait_for_timeout(2000)
                        else:
                            break
                    except:
                        break

                # Events aus DOM extrahieren
                event_items = await page.query_selector_all(
                    ".event-item, .events-list__item, article.event, "
                    "[class*='event'], li[class*='event']"
                )

                print(f"  Gefundene DOM-Elemente: {len(event_items)}")

                # Fallback: alle Elemente mit Datum + Titel heuristisch finden
                if len(event_items) == 0:
                    content = await page.content()
                    # Direkte DOM-Abfrage nach Struktur im Screenshot
                    event_items = await page.query_selector_all(
                        "li:has(time), div:has(time), "
                        ".teaser, [class*='teaser'], "
                        "[class*='list-item']"
                    )
                    print(f"  Fallback-Elemente: {len(event_items)}")

                for item in event_items:
                    try:
                        # Datum
                        date_el = await item.query_selector("time, [class*='date'], [class*='Date']")
                        date_text = ""
                        date_iso = ""
                        if date_el:
                            date_text = (await date_el.inner_text()).strip()
                            date_iso = await date_el.get_attribute("datetime") or ""

                        # Titel
                        title_el = await item.query_selector("h2, h3, h4, [class*='title'], [class*='Title'], strong")
                        title = ""
                        if title_el:
                            title = (await title_el.inner_text()).strip()

                        # Link zur Detail-Seite
                        link_el = await item.query_selector("a:has-text('Lesen Sie mehr'), a[href*='/events/']")
                        detail_url = ""
                        if link_el:
                            href = await link_el.get_attribute("href")
                            if href:
                                if href.startswith("http"):
                                    detail_url = href
                                else:
                                    detail_url = f"https://www.basf.com{href}"

                        # Kalender-Link (.ics)
                        cal_el = await item.query_selector("a:has-text('Kalender'), a[href*='.ics'], a[href*='calendar']")
                        cal_url = ""
                        if cal_el:
                            cal_href = await cal_el.get_attribute("href")
                            if cal_href:
                                cal_url = cal_href if cal_href.startswith("http") else f"https://www.basf.com{cal_href}"

                        # Ort
                        loc_el = await item.query_selector("[class*='location'], [class*='Location'], [class*='place']")
                        location = ""
                        if loc_el:
                            location = (await loc_el.inner_text()).strip()

                        # Nur gültige Events (müssen Titel haben)
                        if title and len(title) > 3 and title not in ["Mehr zeigen", "Alles Entfernen"]:
                            event = {
                                "title": title,
                                "date_text": date_text,
                                "date_iso": date_iso,
                                "location": location,
                                "category": category,
                                "url": detail_url,
                                "calendar_url": cal_url,
                            }
                            # Duplikate vermeiden
                            if not any(e["title"] == title and e["date_iso"] == date_iso for e in all_events):
                                all_events.append(event)

                    except Exception as e:
                        print(f"  ⚠ Fehler bei Event-Item: {e}")
                        continue

            except Exception as e:
                print(f"  ❌ Fehler beim Laden von {url}: {e}")
            finally:
                await page.close()

        await browser.close()

    print(f"\n✅ {len(all_events)} Events gefunden")

    # Nach Datum sortieren
    def sort_key(e):
        return e.get("date_iso") or e.get("date_text") or ""
    all_events.sort(key=sort_key)

    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # events.html generieren
    rows = ""
    for e in all_events:
        url_link = f'<a href="{e["url"]}">Details →</a>' if e.get("url") else ""
        cal_link = f'<a href="{e["calendar_url"]}">📅 Zum Kalender</a>' if e.get("calendar_url") else ""

        rows += f"""<div class="event">
  <h2>{e['title']}</h2>
  <p><strong>Datum:</strong> {e['date_text']} {f"({e['date_iso']})" if e['date_iso'] and e['date_iso'] != e['date_text'] else ""}</p>
  {"<p><strong>Ort:</strong> " + e['location'] + "</p>" if e['location'] else ""}
  <p><strong>Kategorie:</strong> {e['category']}</p>
  {"<p>" + url_link + " " + cal_link + "</p>" if url_link or cal_link else ""}
</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Events & Termine</title></head>
<body>
<h1>BASF Events & Termine</h1>
<p>Stand: {timestamp} | {len(all_events)} Veranstaltungen</p>
{rows}
</body>
</html>"""

    with open("events.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ events.html gespeichert!")

asyncio.run(scrape_events())
