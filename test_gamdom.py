from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://gamdom.com/sports")
    
    # wait for the main content to load
    page.wait_for_selector("div[data-reactroot]")  # adjust if needed

    # grab the page content
    content = page.content()
    print("Page length:", len(content))
    print(content[:1000])  # first 1000 chars to check

    browser.close()
