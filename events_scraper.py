import asyncio
import re
from playwright.async_api import async_playwright
from datetime import datetime

EVENTS_URL = "https://www.basf.com/global/de/careers/application/events"

async def scrape_events():
    all_events = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        print(f"📅 Lade Events: {EVENTS_URL}")
        await page.goto(EVENTS_URL, timeout=60000, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        # ── "Mehr anzeigen" so lange klicken bis der Button weg ist ──────────
        clicks = 0
        while True:
            # Mögliche Button-Texte auf der BASF-Seite
            btn = page.locator(
                "button:has-text('Mehr anzeigen'), "
                "button:has-text('Load more'), "
                "button:has-text('Weitere'), "
                "a:has-text('Mehr anzeigen'), "
                "[data-action*='load'], "
                "[class*='load-more'], "
                "[class*='loadmore']"
            ).first

            if await btn.count() == 0:
                print(f"  ✅ Kein 'Mehr anzeigen' Button mehr — {clicks} Klicks gesamt")
                break

            is_visible = await btn.is_visible()
            if not is_visible:
                print(f"  ✅ Button nicht mehr sichtbar — {clicks} Klicks gesamt")
                break

            try:
                await btn.scroll_into_view_if_needed()
                await btn.click()
                clicks += 1
                print(f"  🖱 Klick {clicks} auf 'Mehr anzeigen'")
                # Warten bis neue Inhalte geladen sind
                await page.wait_for_load_state("networkidle", timeout=10000)
                await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"  ⚠ Button-Klick Fehler: {e}")
                break

        # ── Alle Event-Elemente extrahieren ──────────────────────────────────
        # BASF nutzt eine Listen-Struktur — versuche mehrere Selektoren
        selectors_to_try = [
            ".cmp-events-list__item",
            ".events-list__item",
            "[class*='events-list'] li",
            "[class*='event-item']",
            "article[class*='event']",
            # Fallback: alle li die eine Zeit/Datum und Titel enthalten
            "li:has(time)",
            "li:has([class*='date'])",
        ]

        event_items = []
        for selector in selectors_to_try:
            items = await page.query_selector_all(selector)
            if len(items) > 0:
                print(f"  ✅ Selector '{selector}' → {len(items)} Elemente")
                event_items = items
                break

        print(f"  📋 Verarbeite {len(event_items)} Event-Elemente...")

        for item in event_items:
            try:
                # ── Datum ──
                date_el = await item.query_selector(
                    "time, [class*='date'], [class*='Date'], "
                    "[class*='time'], [class*='when']"
                )
                date_text = ""
                date_iso = ""
                if date_el:
                    date_text = (await date_el.inner_text()).strip()
                    date_iso = await date_el.get_attribute("datetime") or ""

                # ── Titel ──
                title_el = await item.query_selector(
                    "h2, h3, h4, "
                    "[class*='title'], [class*='Title'], [class*='headline'], "
                    "strong, b"
                )
                title = ""
                if title_el:
                    title = (await title_el.inner_text()).strip()

                # ── Lesen Sie mehr Link ──
                detail_url = ""
                link_el = await item.query_selector(
                    "a:has-text('Lesen Sie mehr'), "
                    "a:has-text('Read more'), "
                    "a:has-text('Details'), "
                    "a[href*='/events/']"
                )
                if not link_el:
                    # Fallback: erster <a> im Element
                    link_el = await item.query_selector("a[href]")

                if link_el:
                    href = await link_el.get_attribute("href")
                    if href:
                        if href.startswith("http"):
                            detail_url = href
                        elif href.startswith("/"):
                            detail_url = f"https://www.basf.com{href}"

                # ── Ort ──
                loc_el = await item.query_selector(
                    "[class*='location'], [class*='Location'], "
                    "[class*='place'], [class*='city'], [class*='venue']"
                )
                location = ""
                if loc_el:
                    location = (await loc_el.inner_text()).strip()

                # ── Format (online/präsenz) ──
                format_el = await item.query_selector(
                    "[class*='format'], [class*='type'], [class*='mode']"
                )
                event_format = ""
                if format_el:
                    event_format = (await format_el.inner_text()).strip()

                # ── Nur speichern wenn Titel vorhanden ──
                skip_titles = {"Mehr anzeigen", "Load more", "Alles Entfernen",
                               "Laufende und künftige", "Filtern", ""}
                if title and title not in skip_titles and len(title) > 3:
                    event = {
                        "title": title,
                        "date_text": date_text,
                        "date_iso": date_iso,
                        "location": location,
                        "format": event_format,
                        "url": detail_url,
                    }
                    # Duplikate vermeiden
                    is_dup = any(
                        e["title"] == title and e["date_iso"] == date_iso
                        for e in all_events
                    )
                    if not is_dup:
                        all_events.append(event)

            except Exception as e:
                print(f"  ⚠ Fehler bei Element: {e}")
                continue

        await browser.close()

    print(f"\n✅ {len(all_events)} Events gefunden")

    # ── Nach Datum sortieren ──────────────────────────────────────────────────
    def sort_key(e):
        return e.get("date_iso") or e.get("date_text") or ""
    all_events.sort(key=sort_key)

    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── events.html generieren ────────────────────────────────────────────────
    rows = ""
    for e in all_events:
        detail_link = (
            f'<p><strong>Link:</strong> {e["url"]}</p>'
            if e.get("url") else ""
        )
        rows += f"""<div class="event">
  <h2>{e['title']}</h2>
  <p><strong>Datum:</strong> {e['date_text']}{f" ({e['date_iso']})" if e.get('date_iso') and e['date_iso'] != e['date_text'] else ""}</p>
  {f'<p><strong>Ort:</strong> {e["location"]}</p>' if e.get('location') else ''}
  {f'<p><strong>Format:</strong> {e["format"]}</p>' if e.get('format') else ''}
  {detail_link}
</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><title>BASF Events &amp; Termine</title></head>
<body>
<h1>BASF Events &amp; Termine</h1>
<p>Stand: {timestamp} | {len(all_events)} Veranstaltungen</p>
{rows}
</body>
</html>"""

    with open("events.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ events.html gespeichert mit {len(all_events)} Events!")

asyncio.run(scrape_events())
