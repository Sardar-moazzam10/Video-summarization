import browser_cookie3
import http.cookiejar
import os

def save_youtube_cookies_to_netscape(file_path="cookies.txt"):
    try:
        # Load cookies from Chrome for YouTube domain
        chrome_cookies = browser_cookie3.chrome(domain_name='youtube.com')

        # Create a MozillaCookieJar (Netscape format)
        netscape_jar = http.cookiejar.MozillaCookieJar(file_path)

        # Convert each cookie from browser_cookie3 into the jar
        for cookie in chrome_cookies:
            netscape_jar.set_cookie(cookie)

        # Save to disk in proper format
        netscape_jar.save(ignore_discard=True, ignore_expires=True)

        print(f"✅ YouTube cookies saved to '{file_path}' in Netscape format.")

    except Exception as e:
        print(f"❌ Failed to save cookies: {str(e)}")

if __name__ == "__main__":
    save_youtube_cookies_to_netscape()
