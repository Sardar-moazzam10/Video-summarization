import asyncio
import json
import time
from playwright.async_api import async_playwright
from backend.core.database import get_database
from backend.core.security import create_access_token, create_refresh_token

QUERY = "linear regression and logistic regression"

async def run_browser_audit():
    db = await get_database()
    user = await db["users"].find_one()
    if not user:
        print("Error: No user found in DB")
        return

    user_id = str(user.get("user_id") or user.get("username"))
    auth_version = int(user.get("auth_version", 0))
    role = user.get("role", "admin")

    token = create_access_token({
        "sub": user_id,
        "auth_version": auth_version,
        "role": role,
    })
    refresh = create_refresh_token({
        "sub": user_id,
        "auth_version": auth_version,
        "role": role,
    })

    user_obj = {
        "user_id": user_id,
        "username": user.get("username", "admin"),
        "email": user.get("email", "admin@vidfusion.com"),
        "role": role,
    }

    async with async_playwright() as p:
        # Launch real chrome
        browser = await p.chromium.launch(
            executable_path="/opt/google/chrome/chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )

        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # Capture console messages
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))

        # Navigate and seed localStorage
        await page.goto("http://localhost:3000/login")
        await page.evaluate(f"""() => {{
            localStorage.setItem('access_token', '{token}');
            localStorage.setItem('refresh_token', '{refresh}');
            localStorage.setItem('user', JSON.stringify({json.dumps(user_obj)}));
        }}""")

        print("\n--- Step 1: Navigate to /search-by-keywords ---")
        await page.goto("http://localhost:3000/search-by-keywords")
        await page.wait_for_load_state("networkidle")

        # Initial UI check
        title = await page.title()
        print(f"Page loaded: {title}")

        input_sel = 'input[type="text"]'
        await page.wait_for_selector(input_sel)

        # Type query
        print(f"--- Step 2: Entering query: '{QUERY}' ---")
        await page.fill(input_sel, QUERY)

        # Click Search and observe progressive rendering
        search_btn = page.locator('button:has-text("Search")').first
        t_start = time.perf_counter()
        await search_btn.click()
        print("Clicked search. Monitoring progressive card rendering...")

        # Poll every 200ms for cards appearing and progress indicator
        card_counts_timeline = []
        loading_seen = False
        progress_text_seen = []

        for _ in range(50):  # up to 10 seconds
            await asyncio.sleep(0.2)
            elapsed = time.perf_counter() - t_start
            
            # Check cards rendered
            cards = await page.locator('.kw-card').all()
            card_count = len(cards)
            card_counts_timeline.append((round(elapsed, 2), card_count))

            # Check loading state / progress text
            progress_el = page.locator('text=/Scanning/i')
            if await progress_el.count() > 0:
                loading_seen = True
                txt = await progress_el.first.inner_text()
                if txt not in progress_text_seen:
                    progress_text_seen.append(txt)

            # Check if loading indicator is gone and we have results
            spinner = page.locator('.animate-spin')
            spinner_count = await spinner.count()
            if card_count > 0 and spinner_count == 0 and elapsed > 1.0:
                print(f"Search completed around {elapsed:.2f}s!")
                break

        total_search_time = time.perf_counter() - t_start
        print(f"Total search duration: {total_search_time:.2f}s")
        print(f"Progressive timeline (seconds, rendered cards): {card_counts_timeline[:12]}")
        print(f"Progress states observed: {progress_text_seen}")

        # Audit rendered video cards
        cards = await page.locator('.kw-card').all()
        print(f"\n--- Step 3: Audit Rendered Video Cards ({len(cards)} cards) ---")

        card_details = []
        for i, card in enumerate(cards):
            title_el = card.locator('h3, .font-semibold').first
            title_text = await title_el.inner_text() if await title_el.count() > 0 else "Unknown Title"
            
            # Channel name
            channel_el = card.locator('text=/•/').first
            channel_text = await card.locator('.text-white\\/45, .text-sm').first.inner_text() if await card.locator('.text-white\\/45, .text-sm').count() > 0 else ""

            # Thumbnail
            img = card.locator('img').first
            has_thumb = await img.count() > 0
            thumb_src = await img.get_attribute('src') if has_thumb else None

            # Moments
            moment_btns = await card.locator('button:has-text(":")').all()
            moments_count = len(moment_btns)
            
            # Extract timestamps and text
            sample_moments = []
            for m_btn in moment_btns[:6]:
                m_text = await m_btn.inner_text()
                sample_moments.append(m_text.replace('\n', ' '))

            card_details.append({
                "index": i + 1,
                "title": title_text,
                "has_thumb": has_thumb,
                "moments_count": moments_count,
                "sample_moments": sample_moments,
            })
            print(f"Card {i+1}: '{title_text[:40]}' | Moments: {moments_count} | HasThumb: {has_thumb}")

        # Step 4: Test Interactive Features
        print("\n--- Step 4: Test Interactive Actions ---")
        if len(cards) > 0:
            first_card = cards[0]
            
            # 1. Watch / Seek button
            watch_btn = first_card.locator('button:has-text("Watch")').first
            if await watch_btn.count() > 0:
                print("Found 'Watch' button. Testing click...")
                await watch_btn.click()
                await asyncio.sleep(0.5)
                # Check if embedded player opened
                iframe = page.locator('iframe')
                print(f"Player iframe count after clicking Watch: {await iframe.count()}")

            # 2. Add to Merge checkbox / select
            select_btn = first_card.locator('input[type="checkbox"], button:has-text("Select"), button:has-text("Merge")').first
            if await select_btn.count() > 0:
                print(f"Testing selection for card 1...")
                await select_btn.click()
                await asyncio.sleep(0.3)
                # Check if FloatingSelectionBar / MultiSelectBar is visible
                bar = page.locator('text=/selected/i')
                print(f"Multi-select bar visible: {await bar.count() > 0}")

            # 3. YouTube link check
            yt_link = first_card.locator('a[href*="youtube.com"]').first
            if await yt_link.count() > 0:
                href = await yt_link.get_attribute('href')
                print(f"YouTube external link: {href}")

        # Step 5: Test Second Search (Stale results clearing)
        print("\n--- Step 5: Testing Second Search & Clearing Stale Results ---")
        await page.fill(input_sel, "support vector machines")
        await page.locator('button:has-text("Search")').first.click()
        await asyncio.sleep(0.1)
        # Verify previous cards are cleared immediately
        immediate_cards = await page.locator('.kw-card').count()
        print(f"Cards count immediately upon second search submit: {immediate_cards} (Expect 0)")
        await page.wait_for_timeout(2000)
        second_search_cards = await page.locator('.kw-card').count()
        print(f"Second search rendered {second_search_cards} cards.")

        # Step 6: Test Mobile Viewport
        print("\n--- Step 6: Testing Mobile Viewport (375x812) ---")
        await page.set_viewport_size({"width": 375, "height": 812})
        await asyncio.sleep(0.5)
        is_search_visible = await page.locator(input_sel).is_visible()
        mobile_cards = await page.locator('.kw-card').count()
        print(f"Mobile layout: Search input visible={is_search_visible}, Cards visible={mobile_cards}")

        # Save screenshot for visual artifact
        await page.screenshot(path="keyword_page_audit.png", full_page=True)
        print("Screenshot saved as keyword_page_audit.png")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_browser_audit())

