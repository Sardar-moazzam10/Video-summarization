import asyncio
import json
import time
from playwright.async_api import async_playwright
from backend.core.database import get_database
from backend.core.security import create_access_token, create_refresh_token

QUERY = "linear regression and logistic regression"

async def run_clean_audit():
    db = await get_database()
    user = await db["users"].find_one()
    user_id = str(user.get("user_id") or user.get("username"))
    auth_version = int(user.get("auth_version", 0))
    role = user.get("role", "admin")
    token = create_access_token({"sub": user_id, "auth_version": auth_version, "role": role})
    refresh = create_refresh_token({"sub": user_id, "auth_version": auth_version, "role": role})
    user_obj = {"user_id": user_id, "username": user.get("username", "admin"), "email": user.get("email", "admin@vidfusion.com"), "role": role}

    audit = {
        "ux_findings": {},
        "cards_detail": [],
        "quality_audit": {}
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/opt/google/chrome/chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # Seed auth
        await page.goto("http://localhost:3000/login")
        await page.evaluate(f"""() => {{
            localStorage.setItem("access_token", "{token}");
            localStorage.setItem("refresh_token", "{refresh}");
            localStorage.setItem("user", JSON.stringify({json.dumps(user_obj)}));
        }}""")

        # Navigate to search-by-keywords
        await page.goto("http://localhost:3000/search-by-keywords")
        await page.wait_for_load_state("networkidle")

        input_box = page.locator('input[placeholder*="Support Vector Machine"]')
        await input_box.click()
        await input_box.fill(QUERY)

        # 1. Progressive search observation
        t0 = time.perf_counter()
        await input_box.press("Enter")

        timeline = []
        progress_texts = []
        spinner_observed = False

        for _ in range(40):
            await asyncio.sleep(0.1)
            elapsed = time.perf_counter() - t0
            count = await page.locator('.kw-card').count()
            timeline.append((round(elapsed, 2), count))
            
            # Progress banner text
            banner = page.locator('.kw-progress-banner, div:has-text("Scanning")')
            if await banner.count() > 0:
                txt = await banner.first.inner_text()
                if txt and txt not in progress_texts:
                    progress_texts.append(txt)

            # Spinner
            spinner = page.locator('button[disabled]')
            if await spinner.count() > 0:
                spinner_observed = True

            if count >= 6 and await page.locator('button[disabled]').count() == 0 and elapsed > 0.6:
                break

        total_search_time = time.perf_counter() - t0
        cards = await page.locator('.kw-card').all()

        audit["ux_findings"]["search_time_s"] = round(total_search_time, 2)
        audit["ux_findings"]["progressive_timeline"] = timeline[:15]
        audit["ux_findings"]["progress_texts"] = progress_texts
        audit["ux_findings"]["spinner_resets_properly"] = (await page.locator('button[disabled]').count() == 0)
        audit["ux_findings"]["cards_count"] = len(cards)

        print(f"Loaded {len(cards)} cards in {total_search_time:.2f}s")

        # 2. Extract Card Details & Moments Quality
        total_moments = 0
        for i, card in enumerate(cards):
            title = await card.locator('h3').first.inner_text() if await card.locator('h3').count() > 0 else ""
            
            channel = ""
            channel_el = card.locator('.kw-card-channel').first
            if await channel_el.count() > 0:
                channel = await channel_el.inner_text()

            # Thumbnail
            img = card.locator('.kw-card-thumb img').first
            has_thumb = await img.count() > 0
            thumb_src = await img.get_attribute('src') if has_thumb else ""

            # Extract all moment links
            moment_links = await card.locator('.kw-match-link').all()
            moment_count = len(moment_links)
            total_moments += moment_count

            moments_data = []
            for m in moment_links:
                time_el = m.locator('.kw-match-time').first
                text_el = m.locator('.kw-match-text').first
                time_str = await time_el.inner_text() if await time_el.count() > 0 else ""
                context_str = await text_el.inner_text() if await text_el.count() > 0 else ""
                href = await m.get_attribute('href') or ""
                
                # Parse timestamp seconds from href
                import re
                t_match = re.search(r'&t=(\d+)s', href)
                sec = int(t_match.group(1)) if t_match else 0

                moments_data.append({
                    "time_str": time_str,
                    "seconds": sec,
                    "context": context_str,
                    "href": href
                })

            # Check YouTube button
            yt_btn = card.locator('a:has-text("YouTube")').first
            yt_href = await yt_btn.get_attribute('href') if await yt_btn.count() > 0 else ""

            card_entry = {
                "card_index": i + 1,
                "title": title,
                "channel": channel,
                "has_thumb": has_thumb,
                "thumb_src": thumb_src[:60] + "..." if thumb_src else "",
                "moment_count": moment_count,
                "youtube_href": yt_href,
                "moments": moments_data
            }
            audit["cards_detail"].append(card_entry)
            print(f"Card {i+1}: '{title[:35]}' - {moment_count} moments")

        audit["ux_findings"]["total_moments"] = total_moments

        # 3. Test Interactive Features on First Card
        first_card = cards[0]
        
        # Test Add to Merge
        select_btn = first_card.locator('.vc-select-btn').first
        await select_btn.click()
        await asyncio.sleep(0.3)
        multi_bar = page.locator('text=/selected/i')
        bar_visible = await multi_bar.count() > 0
        btn_text_after = await select_btn.inner_text()
        audit["ux_findings"]["add_to_merge_works"] = bar_visible
        audit["ux_findings"]["select_btn_text_after"] = btn_text_after
        print(f"Add to Merge: bar visible = {bar_visible}, button state = '{btn_text_after.strip()}'")

        # 4. Test Second Search (Stale Results Clearing)
        print("Testing Second Search (stale results clearing)...")
        await input_box.click()
        await input_box.fill("deep learning")
        await input_box.press("Enter")
        await asyncio.sleep(0.05)
        count_at_start = await page.locator('.kw-card').count()
        audit["ux_findings"]["stale_results_cleared_instantly"] = (count_at_start == 0)
        print(f"Cards count immediately upon 2nd search: {count_at_start} (Expect 0)")
        
        await asyncio.sleep(1.5)
        count_2nd_done = await page.locator('.kw-card').count()
        audit["ux_findings"]["second_search_results_rendered"] = count_2nd_done
        print(f"Second search completed with {count_2nd_done} cards")

        # 5. Mobile Layout Test
        print("Testing Mobile Viewport (375x812)...")
        await page.set_viewport_size({"width": 375, "height": 812})
        await asyncio.sleep(0.5)
        audit["ux_findings"]["mobile_input_visible"] = await input_box.is_visible()
        audit["ux_findings"]["mobile_cards_visible"] = (await page.locator('.kw-card').count()) > 0

        # Save screenshots
        await page.screenshot(path="audit_mobile.png", full_page=False)
        await page.set_viewport_size({"width": 1280, "height": 900})
        await page.screenshot(path="audit_desktop.png", full_page=False)

        # 6. Test Watch Button Navigation
        # Re-run the query so we have cards
        await input_box.fill(QUERY)
        await input_box.press("Enter")
        await asyncio.sleep(1.5)
        watch_btn = page.locator('.vc-btn--primary:has-text("Watch")').first
        await watch_btn.click()
        await asyncio.sleep(0.8)
        navigated_url = page.url
        audit["ux_findings"]["watch_navigated_url"] = navigated_url
        print(f"Watch button clicked: navigated to {navigated_url}")

        await browser.close()

    # Save data
    with open("ux_audit_report.json", "w") as f:
        json.dump(audit, f, indent=2)

    print("Audit JSON saved successfully!")

if __name__ == "__main__":
    asyncio.run(run_clean_audit())

