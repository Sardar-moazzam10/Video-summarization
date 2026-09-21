import asyncio
import json
import time
from playwright.async_api import async_playwright
from backend.core.database import get_database
from backend.core.security import create_access_token, create_refresh_token

QUERY = "linear regression and logistic regression"

async def run_full_audit():
    db = await get_database()
    user = await db["users"].find_one()
    user_id = str(user.get("user_id") or user.get("username"))
    auth_version = int(user.get("auth_version", 0))
    role = user.get("role", "admin")
    token = create_access_token({"sub": user_id, "auth_version": auth_version, "role": role})
    refresh = create_refresh_token({"sub": user_id, "auth_version": auth_version, "role": role})
    user_obj = {"user_id": user_id, "username": user.get("username", "admin"), "email": user.get("email", "admin@vidfusion.com"), "role": role}

    audit_data = {
        "ux_findings": {},
        "cards_detail": [],
        "quality_audit": {},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/opt/google/chrome/chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        console_logs = []
        page.on("console", lambda m: console_logs.append(f"[{m.type}] {m.text}"))

        # 1. Login seed
        await page.goto("http://localhost:3000/login")
        await page.evaluate(f"""() => {{
            localStorage.setItem("access_token", "{token}");
            localStorage.setItem("refresh_token", "{refresh}");
            localStorage.setItem("user", JSON.stringify({json.dumps(user_obj)}));
        }}""")

        # 2. Navigate to /search-by-keywords
        await page.goto("http://localhost:3000/search-by-keywords")
        await page.wait_for_load_state("networkidle")

        input_box = page.locator('input[placeholder*="Support Vector Machine"]')
        await input_box.click()
        await input_box.fill(QUERY)

        # 3. Monitor progressive rendering
        t0 = time.perf_counter()
        await input_box.press("Enter")

        timeline = []
        progress_texts = []
        spinner_seen = False

        # Poll every 100ms for up to 5 seconds
        for _ in range(50):
            await asyncio.sleep(0.1)
            elapsed = time.perf_counter() - t0
            cards_count = await page.locator('.kw-card').count()
            timeline.append((round(elapsed, 2), cards_count))

            # check progress indicator text
            prog_el = page.locator('text=/Scanning/i, text=/English captions/i')
            if await prog_el.count() > 0:
                txt = await prog_el.first.inner_text()
                if txt and txt not in progress_texts:
                    progress_texts.append(txt)

            # check spinner / loading
            btn_spinner = page.locator('button[disabled]')
            if await btn_spinner.count() > 0:
                spinner_seen = True

            # If all cards loaded and spinner gone after 1s
            if cards_count >= 5 and await page.locator('button[disabled]').count() == 0 and elapsed > 0.8:
                break

        total_search_time = time.perf_counter() - t0
        cards = await page.locator('.kw-card').all()

        audit_data["ux_findings"]["search_time_s"] = round(total_search_time, 2)
        audit_data["ux_findings"]["progressive_timeline"] = timeline[:15]
        audit_data["ux_findings"]["progress_texts_seen"] = progress_texts
        audit_data["ux_findings"]["spinner_observed"] = spinner_seen
        audit_data["ux_findings"]["total_cards_rendered"] = len(cards)

        print(f"Rendered {len(cards)} cards in {total_search_time:.2f}s!")

        # 4. Detailed card inspection
        total_moments = 0
        for i, card in enumerate(cards):
            title = await card.locator('h3').first.inner_text() if await card.locator('h3').count() > 0 else "Unknown Title"
            
            # channel text
            channel = ""
            for selector in ['.kw-card-channel', 'p.text-xs', 'p.text-sm']:
                el = card.locator(selector).first
                if await el.count() > 0:
                    channel = await el.inner_text()
                    break

            # thumbnail
            img = card.locator('img').first
            has_thumb = await img.count() > 0
            thumb_src = await img.get_attribute('src') if has_thumb else ""

            # moment pills / buttons
            moment_btns = await card.locator('.kw-moment-btn, button:has-text(":")').all()
            moment_count = len(moment_btns)
            total_moments += moment_count

            moments_detail = []
            for btn in moment_btns:
                raw = await btn.inner_text()
                lines = [l.strip() for l in raw.split('\n') if l.strip()]
                timestamp = lines[0] if len(lines) > 0 else ""
                snippet = lines[1] if len(lines) > 1 else ""
                moments_detail.append({
                    "timestamp": timestamp,
                    "snippet": snippet,
                    "full_text": raw.replace('\n', ' -- ')
                })

            card_info = {
                "card_index": i + 1,
                "title": title,
                "channel": channel,
                "has_thumb": has_thumb,
                "thumb_src": thumb_src[:60] + "..." if thumb_src else "",
                "moment_count": moment_count,
                "moments": moments_detail
            }
            audit_data["cards_detail"].append(card_info)
            print(f"Card {i+1}: '{title[:35]}' - {moment_count} moments")

        audit_data["ux_findings"]["total_moments_count"] = total_moments

        # 5. Interactive UI Actions
        if len(cards) > 0:
            first_card = cards[0]
            
            # A. Watch Button & Seeker
            watch_btn = first_card.locator('button:has-text("Watch")').first
            watch_clicked = False
            iframe_src = ""
            if await watch_btn.count() > 0:
                await watch_btn.click()
                await asyncio.sleep(0.6)
                iframe = page.locator('iframe')
                if await iframe.count() > 0:
                    watch_clicked = True
                    iframe_src = await iframe.first.get_attribute('src') or ""
                print(f"Watch button clicked: opened iframe with src={iframe_src[:50]}")
            audit_data["ux_findings"]["watch_button_opens_player"] = watch_clicked
            audit_data["ux_findings"]["player_iframe_src"] = iframe_src

            # B. YouTube link
            yt_link = first_card.locator('a[href*="youtube.com"]').first
            yt_href = await yt_link.get_attribute('href') if await yt_link.count() > 0 else ""
            audit_data["ux_findings"]["youtube_button_href"] = yt_href
            print(f"YouTube external button href: {yt_href}")

            # C. Multi-select / Add to Merge
            checkbox = first_card.locator('input[type="checkbox"]').first
            if await checkbox.count() > 0:
                await checkbox.click()
                await asyncio.sleep(0.4)
                # Check for floating bar
                bar = page.locator('text=/selected/i')
                bar_visible = await bar.count() > 0
                audit_data["ux_findings"]["add_to_merge_bar_visible"] = bar_visible
                print(f"Add to Merge selection bar visible: {bar_visible}")

        # 6. Test Second Search & Stale Results Clearing
        print("Testing Second Search (stale results clearing)...")
        await input_box.click()
        await input_box.fill("deep learning")
        t_sec = time.perf_counter()
        await input_box.press("Enter")
        await asyncio.sleep(0.05)
        
        cards_immediately_after = await page.locator('.kw-card').count()
        audit_data["ux_findings"]["cards_cleared_immediately_on_search"] = (cards_immediately_after == 0)
        print(f"Cards immediately upon 2nd search: {cards_immediately_after} (Expect 0)")
        
        await asyncio.sleep(1.5)
        cards_after_2nd = await page.locator('.kw-card').count()
        audit_data["ux_findings"]["second_search_cards_rendered"] = cards_after_2nd
        print(f"Second search rendered: {cards_after_2nd} cards")

        # 7. Mobile Viewport test
        print("Testing Mobile Viewport (375x812)...")
        await page.set_viewport_size({"width": 375, "height": 812})
        await asyncio.sleep(0.5)
        audit_data["ux_findings"]["mobile_input_visible"] = await input_box.is_visible()
        audit_data["ux_findings"]["mobile_cards_visible"] = (await page.locator('.kw-card').count()) > 0

        # Desktop and Mobile Screenshots
        await page.screenshot(path="keyword_audit_mobile.png", full_page=False)
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.screenshot(path="keyword_audit_desktop.png", full_page=False)
        print("Screenshots saved: keyword_audit_desktop.png & keyword_audit_mobile.png")

        await browser.close()

    # Save detailed JSON report
    with open("ux_audit_report.json", "w") as f:
        json.dump(audit_data, f, indent=2)

    print("\nAudit finished successfully!")

if __name__ == "__main__":
    asyncio.run(run_full_audit())

