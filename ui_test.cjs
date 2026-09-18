const puppeteer = require('puppeteer');
const fs = require('fs');
const execSync = require('child_process').execSync;

(async () => {
    console.log("Starting puppeteer...");
    const browser = await puppeteer.launch({
        headless: "new",
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();
    
    // 1. Load the search page
    console.log("Navigating to frontend...");
    await page.goto('http://127.0.0.1:3000/search-by-keywords', { waitUntil: 'networkidle2' });
    
    // Check if redirect to login happened. (It has <ProtectedRoute> but maybe user is logged in via mock?)
    // Let's type in the search bar.
    console.log("Typing search query...");
    await page.waitForSelector('input[type="text"]', {timeout: 5000}).catch(()=>console.log("No input found, might be logged out"));
    // Actually the mock auth usually allows standard access or we need to login
    
    const html = await page.content();
    if(html.includes("login") || html.includes("Login")) {
        console.log("Need to login...");
        // find login fields if necessary
    }
    
    // Let's just output the page content to see if we're on the right page
    console.log("Page title:", await page.title());
    fs.writeFileSync('page.html', html);
    
    await browser.close();
})();
