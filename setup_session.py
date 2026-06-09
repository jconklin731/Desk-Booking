"""
Run this script ONCE to log in via SSO and save your session.
After this, book_desk.py will reuse the saved session automatically.

Usage:
    python setup_session.py
"""

import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


def load_config():
    config_path = Path("config.json")
    if not config_path.exists():
        print("ERROR: config.json not found. Make sure you're running from the project directory.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def setup_session():
    config = load_config()
    url = config["officespace_url"]
    session_file = config.get("session_file", "session.json")

    print(f"\n=== OfficeSpace Session Setup ===")
    print(f"URL: {url}")
    print(f"\nA browser window will open. Log in with your company SSO (Microsoft/Google/Okta/etc).")
    print("Once you are fully logged in and can see the OfficeSpace dashboard, press ENTER here.")
    print("Your session will be saved so future runs don't need you to log in again.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=50)
        context = browser.new_context()
        page = context.new_page()

        page.goto(url)
        print(f"Browser opened. Complete your SSO login now...")
        input("\nPress ENTER once you are logged into the OfficeSpace dashboard: ")

        # Confirm they're actually logged in
        current_url = page.url
        print(f"\nCurrent URL: {current_url}")

        # Save session state (cookies + local storage)
        context.storage_state(path=session_file)
        print(f"\n✓ Session saved to {session_file}")
        print("You can now run: python book_desk.py")
        print("Or set up the cron job with: python setup_cron.py\n")

        browser.close()


if __name__ == "__main__":
    setup_session()
