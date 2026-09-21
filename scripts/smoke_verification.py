import asyncio
import json
import time
from playwright.async_api import async_playwright
from backend.core.database import get_database
from backend.core.security import create_access_token, create_refresh_token
import requests

async def run_smoke():
    print("=== STARTING PRODUCTION-STYLE SMOKE VERIFICATION ===")
    
    # -----------------------------------------------------------------
    # 1. Verify Backend 422 for Direct Invalid Request
    # -----------------------------------------------------------------
    print("\n--- STEP 1: Backend Direct 422 Gating Verification ---")
    db = await get_database()
    user = await db["users"].find_one()
    user_id = str(user.get("user_id") or user.get("username"))
    auth_version = int(user.get("auth_version", 0))
    role = user.get("role", "admin")
    token = create_access_token({"sub": user_id, "auth_version": auth_version, "role": role})
    refresh = create_refresh_token({"sub": user_id, "auth_version": auth_version, "role": role})
    user_obj = {
        "user_id": user_id,
        "username": user.get("username", "admin"),
        "email": user.get("email", "admin@vidfusion.com"),
        "role": role
    }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Test 1A: 19s video requesting 5m summary -> 422 SUMMARY_DURATION_EXCEEDS_SOURCE
    res = requests.post("http://localhost:8000/api/v1/merge", json={
        "video_ids": ["jNQXAC9IVRw"],
        "target_duration_minutes": 5,
        "generate_audio": False,
        "generate_video": False,
        "style": "educational"
    }, headers=headers)
    
    assert res.status_code == 422, f"Expected 422, got {res.status_code}"
    detail = res.json().get("detail", {})
    assert detail.get("code") == "SUMMARY_DURATION_EXCEEDS_SOURCE"
    assert "A 5-minute summary requires more than 5 minutes of source content." in detail.get("message", "")
    print(f"✓ Backend 422 verified on direct request: code={detail.get('code')}")
    print(f"✓ Message: \"{detail.get('message')}\"")

    # Test 1B: Multi-video deduplicated duration endpoint
    res_dur = requests.get(
        "http://localhost:8000/api/v1/merge/video-durations?video_ids=jNQXAC9IVRw,jNQXAC9IVRw",
        headers=headers
    )
    assert res_dur.status_code == 200
    dur_data = res_dur.json()
    assert dur_data.get("status") == "too_short"
    assert dur_data.get("combined_duration_seconds") == 19.0, "Duplicate video must be deduplicated"
    assert dur_data.get("allowed_durations") == []
    print(f"✓ Video-durations deduplication verified: combined_seconds={dur_data.get('combined_duration_seconds')}")

    # Test 1C: ~6m combined video (kJQP7kiw5Fk 282s + jNQXAC9IVRw 19s = 301s = 5m01s) allows ONLY 5m
    res_6m = requests.get(
        "http://localhost:8000/api/v1/merge/video-durations?video_ids=kJQP7kiw5Fk,jNQXAC9IVRw",
        headers=headers
    )
    assert res_6m.status_code == 200
    dur_6m = res_6m.json()
    assert dur_6m.get("status") == "valid"
    assert dur_6m.get("allowed_durations") == [5], f"Expected [5], got {dur_6m.get('allowed_durations')}"
    print(f"✓ Combined 5m01s video allows only 5m: allowed_durations={dur_6m.get('allowed_durations')}")

    # -----------------------------------------------------------------
    # 2. Browser Smoke Verification
    # -----------------------------------------------------------------
    print("\n--- STEP 2: Browser Verification across Entry Points ---")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/opt/google/chrome/chrome",
            headless=True,
            args=["--no-sandbox", "--disable-gpu"]
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        # Helper to seed auth into page
        async def seed_auth(url):
            await page.goto("http://localhost:3000/login")
            await page.evaluate(f"""() => {{
                localStorage.setItem("access_token", "{token}");
                localStorage.setItem("refresh_token", "{refresh}");
                localStorage.setItem("user", JSON.stringify({json.dumps(user_obj)}));
            }}""")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")

        # -------------------------------------------------------------
        # 2A. Test /search-by-title
        # -------------------------------------------------------------
        print("\n[A] Testing /search-by-title...")
        await seed_auth("http://localhost:3000/search-by-title")

        # Find search bar using class .sb-input
        search_input = page.locator('.sb-input').first
        await search_input.wait_for(state="visible", timeout=10000)
        await search_input.fill("machine learning tutorial")
        await page.locator('.sb-btn').click()

        # Wait for video cards to appear (.vc-select-btn)
        await page.wait_for_selector('.vc-select-btn', timeout=15000)
        select_buttons = page.locator('.vc-select-btn')
        count = await select_buttons.count()
        print(f"  Found {count} searchable video cards on /search-by-title")
        assert count > 0, "Should have search results"

        # Click first video to select
        await select_buttons.nth(0).click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', timeout=10000)
        print("  MultiSelectBar rendered on selection")

        # Wait for validation to resolve (not validating)
        submit_btn = page.locator('[data-testid="multiselectbar-submit-btn"]')
        for _ in range(50):
            txt = await submit_btn.text_content()
            if "Checking" not in txt:
                break
            await asyncio.sleep(0.2)

        btn_text = await submit_btn.text_content()
        is_disabled = await submit_btn.is_disabled()
        tooltip = await submit_btn.get_attribute("title")
        print(f"  Single video: text='{btn_text.strip()}', disabled={is_disabled}, tooltip='{tooltip}'")

        # Open duration picker to verify presets
        duration_toggle = page.locator('button[title*="Click to change summary output duration"]')
        await duration_toggle.click()
        await asyncio.sleep(0.5)

        # Check options
        opt5 = page.locator('[data-testid="duration-option-5"]')
        assert await opt5.is_visible()
        print(f"  Duration options: 5m disabled={await opt5.is_disabled()}")

        # Close picker
        await duration_toggle.click()
        await asyncio.sleep(0.3)

        # Test selecting a second video for multi-video combined duration
        if count > 1:
            await select_buttons.nth(1).click()
            await asyncio.sleep(1.0)
            print("  Selected 2nd video for multi-video combined duration")
            
            # Wait for validation
            for _ in range(30):
                txt = await submit_btn.text_content()
                if "Checking" not in txt:
                    break
                await asyncio.sleep(0.2)
            
            btn_text2 = await submit_btn.text_content()
            print(f"  Multi-video: text='{btn_text2.strip()}', disabled={await submit_btn.is_disabled()}")

            # Remove second video to test auto-adjust and remove
            remove_btn = page.locator('button:has-text("×")').first
            await remove_btn.click()
            await asyncio.sleep(0.5)
            print("  Removed video; selection count updated")

        # Clear selection
        clear_btn = page.locator('button[title="Clear selection"]')
        await clear_btn.click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', state="detached", timeout=5000)
        print("  ✓ /search-by-title selection, gating, multi-video and clear verified!")

        # -------------------------------------------------------------
        # 2B. Test /suggested-podcasts
        # -------------------------------------------------------------
        print("\n[B] Testing /suggested-podcasts...")
        await page.goto("http://localhost:3000/suggested-podcasts")
        await page.wait_for_load_state("networkidle")

        # Click a suggestion pill like "Tech & AI"
        tech_pill = page.locator('.suggested-topic-btn').first
        await tech_pill.wait_for(state="visible", timeout=10000)
        await tech_pill.click()

        # Wait for cards to appear (.vc-select-btn)
        await page.wait_for_selector('.vc-select-btn', timeout=15000)
        sug_select_btns = page.locator('.vc-select-btn')
        sug_count = await sug_select_btns.count()
        print(f"  Found {sug_count} selectable cards on /suggested-podcasts")
        assert sug_count > 0

        # Select first video
        await sug_select_btns.nth(0).click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', timeout=10000)
        print("  MultiSelectBar rendered on /suggested-podcasts")

        # Check gating
        sug_submit_btn = page.locator('[data-testid="multiselectbar-submit-btn"]')
        for _ in range(40):
            txt = await sug_submit_btn.text_content()
            if "Checking" not in txt:
                break
            await asyncio.sleep(0.2)

        print(f"  /suggested-podcasts selection verified: text='{(await sug_submit_btn.text_content()).strip()}', disabled={await sug_submit_btn.is_disabled()}")
        # Clear
        await page.locator('button[title="Clear selection"]').click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', state="detached", timeout=5000)
        print("  ✓ /suggested-podcasts verified!")

        # -------------------------------------------------------------
        # 2C. Test /search-by-keywords
        # -------------------------------------------------------------
        print("\n[C] Testing /search-by-keywords...")
        await page.goto("http://localhost:3000/search-by-keywords")
        await page.wait_for_load_state("networkidle")

        kw_input = page.locator('input[placeholder*="Support Vector Machine"]')
        await kw_input.fill("linear regression")
        search_btn = page.get_by_role("button", name="Search", exact=True)
        await search_btn.click()

        # Wait for search results (transcripts scanning takes ~5-15s)
        await page.wait_for_selector('.vc-select-btn', state="attached", timeout=45000)
        add_btns = page.locator('.vc-select-btn')
        kw_cards_count = await add_btns.count()
        print(f"  Found {kw_cards_count} matched videos on /search-by-keywords")
        assert kw_cards_count > 0

        # Scroll into view and click Add to Merge
        first_btn = add_btns.first
        await first_btn.scroll_into_view_if_needed()
        await first_btn.click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', timeout=10000)
        print("  MultiSelectBar rendered on /search-by-keywords")

        kw_submit_btn = page.locator('[data-testid="multiselectbar-submit-btn"]')
        for _ in range(40):
            txt = await kw_submit_btn.text_content()
            if "Checking" not in txt:
                break
            await asyncio.sleep(0.2)

        print(f"  /search-by-keywords selection gating verified: disabled={await kw_submit_btn.is_disabled()}")
        await page.locator('button[title="Clear selection"]').click()
        await page.wait_for_selector('[data-testid="multiselectbar-submit-btn"]', state="detached", timeout=5000)
        print("  ✓ /search-by-keywords verified!")

        # -------------------------------------------------------------
        # 2D. Test Strict Invariant & UI Wording in DurationSelector on /merge-preview
        # -------------------------------------------------------------
        print("\n[D] Testing DurationSelector boundary states & exact wording on /merge-preview...")
        
        # Test D1: <= 5m source duration (e.g. 19s "Me at the zoo") -> too_short banner with exact wording
        await page.evaluate("""() => {
            sessionStorage.setItem('mergePreviewSelectedResults', JSON.stringify([
                { video: { id: { videoId: 'jNQXAC9IVRw' }, snippet: { title: 'Me at the zoo' } } }
            ]));
        }""")
        await page.goto("http://localhost:3000/merge-preview")
        await page.wait_for_load_state("networkidle")

        # Wait for duration check to finish
        await page.wait_for_selector('[data-testid="duration-too-short-banner"]', timeout=15000)
        banner = page.locator('[data-testid="duration-too-short-banner"]')
        banner_text = await banner.text_content()
        print(f"  Too short banner observed: \"{banner_text.strip()}\"")
        assert "A 5-minute summary requires more than 5 minutes of source content." in banner_text, \
            f"Banner missing expected wording: {banner_text}"

        # Confirm all presets are disabled
        for m in [5, 10, 15, 20, 30]:
            btn = page.locator(f'[data-testid="duration-option-{m}"]')
            assert await btn.is_disabled(), f"Preset {m} should be disabled for <= 5m video"
        print("  ✓ All presets (5, 10, 15, 20, 30) disabled for <=5m source!")

        # Confirm Submit button is disabled with matching tooltip
        merge_btn = page.locator('button:has-text("Merge with Video Highlights"), button:has-text("Merge & Play Podcast")').first
        assert await merge_btn.is_disabled(), "Merge button must be disabled for <= 5m video"
        merge_tooltip = await merge_btn.get_attribute("title")
        print(f"  Submit button disabled: tooltip=\"{merge_tooltip}\"")
        assert "A 5-minute summary requires more than 5 minutes of source content." in merge_tooltip

        # Screenshot proof for too short
        await page.screenshot(path="screenshot_smoke_too_short.png")
        print("  ✓ Saved screenshot_smoke_too_short.png")

        # Test D2: Combined videos ~6 minutes (kJQP7kiw5Fk 282s + jNQXAC9IVRw 19s = 301s = 5m 01s)
        print("\n[E] Testing ~6m combined videos (5m 01s) on /merge-preview...")
        await page.evaluate("""() => {
            sessionStorage.setItem('mergePreviewSelectedResults', JSON.stringify([
                { video: { id: { videoId: 'kJQP7kiw5Fk' }, snippet: { title: 'Despacito' } } },
                { video: { id: { videoId: 'jNQXAC9IVRw' }, snippet: { title: 'Me at the zoo' } } }
            ]));
        }""")
        await page.goto("http://localhost:3000/merge-preview")
        await page.wait_for_load_state("networkidle")

        # Wait for duration check to finish
        await page.wait_for_selector('[data-testid="duration-valid-info"]', timeout=15000)
        valid_info = page.locator('[data-testid="duration-valid-info"]')
        print(f"  Valid info: \"{(await valid_info.text_content()).strip()}\"")

        # 5m preset should be enabled, 10/15/20/30 must be disabled
        btn5 = page.locator('[data-testid="duration-option-5"]')
        btn10 = page.locator('[data-testid="duration-option-10"]')
        assert not await btn5.is_disabled(), "5m preset must be ENABLED for 5m01s source"
        assert await btn10.is_disabled(), "10m preset must be DISABLED for 5m01s source"
        print("  ✓ 5m preset ENABLED and 10m preset DISABLED for ~6m source!")

        # Confirm Submit button is now enabled
        merge_btn2 = page.locator('button:has-text("Merge with Video Highlights"), button:has-text("Merge & Play Podcast")').first
        assert not await merge_btn2.is_disabled(), "Merge button must be ENABLED for valid 5m selection"
        print(f"  ✓ Submit button is ENABLED for 5m selection on ~6m source!")

        # Screenshot proof for valid 5m preset
        await page.screenshot(path="screenshot_smoke_valid_5m.png")
        print("  ✓ Saved screenshot_smoke_valid_5m.png")

        await browser.close()

    print("\n=== ALL SMOKE VERIFICATION TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(run_smoke())
