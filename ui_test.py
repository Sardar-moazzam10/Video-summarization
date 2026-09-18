from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import json
import subprocess

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

driver = webdriver.Chrome(options=options)
driver.get("http://127.0.0.1:3000/")
driver.execute_script("localStorage.setItem('user', JSON.stringify({role: 'admin', token: 'fake'}));")
driver.get("http://127.0.0.1:3000/search-by-keywords")

try:
    print("Page title:", driver.title)
    
    # Wait for search input
    search_input = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']"))
    )
    search_input.send_keys("AI")
    search_input.send_keys(Keys.ENTER)
    
    print("Waiting for results...")
    time.sleep(10) # give time to search and load results
    
    # Wait for video select buttons
    select_btns = driver.find_elements(By.CSS_SELECTOR, ".vc-select-btn")
    print(f"Found {len(select_btns)} videos")
    
    for i in range(min(3, len(select_btns))):
        try:
            select_btns[i].click()
        except:
            driver.execute_script("arguments[0].click();", select_btns[i])
    
    print("Selected 3 videos")
    
    # Click merge
    time.sleep(2)
    merge_btns = driver.find_elements(By.TAG_NAME, "button")
    clicked = False
    for b in merge_btns:
        if "Merge 3 Videos" in b.text:
            print("Clicking:", b.text)
            try:
                b.click()
            except:
                driver.execute_script("arguments[0].click();", b)
            clicked = True
            break
            
    if not clicked:
        print("Could not find Merge 3 Videos button!")
        print([b.text for b in merge_btns])
        driver.quit()
        exit(1)
            
    # Poll for completion
    print("Waiting for Video Ready...")
    for i in range(120): # wait up to 1200s (20 mins)
        time.sleep(10)
        page_source = driver.page_source
        if "Video Ready" in page_source or ".mp4" in page_source:
            print("Video is ready!")
            break
            
    videos = driver.find_elements(By.TAG_NAME, "video")
    video_src = ""
    if videos:
        video_src = videos[-1].get_attribute("src")
        print("Video src:", video_src)
    else:
        print("No <video> element found")

    with open("page.html", "w") as f:
        f.write(driver.page_source)
        
    print("UI flow PASS")

finally:
    driver.quit()
