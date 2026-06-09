"""
Automatically books a desk in OfficeSpace.

Usage:
    python book_desk.py              # Books for tomorrow (or days_ahead from config)
    python book_desk.py --date TODAY # Books for today
    python book_desk.py --dry-run    # Shows what it would do without booking
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("booking.log"),
    ],
)
log = logging.getLogger(__name__)


def load_config():
    config_path = Path("config.json")
    if not config_path.exists():
        log.error("config.json not found. Run from the project directory.")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


def get_target_date(config, override=None):
    if override and override.upper() == "TODAY":
        return datetime.now().date()
    days_ahead = config.get("days_ahead", 1)
    return (datetime.now() + timedelta(days=days_ahead)).date()


def check_session(session_file):
    path = Path(session_file)
    if not path.exists():
        log.error(f"Session file '{session_file}' not found.")
        log.error("Run setup_session.py first to log in and save your session.")
        sys.exit(1)


def try_book_desk(page, config, target_date, dry_run=False):
    url = config["officespace_url"].rstrip("/")
    floor_name = config.get("floor_name", "").strip()
    area_name = config.get("area_name", "").strip()
    location_name = config.get("location_name", "").strip()
    start_time = config.get("booking_start_time", "09:00")
    end_time = config.get("booking_end_time", "17:00")
    date_str = target_date.strftime("%Y-%m-%d")
    date_display = target_date.strftime("%B %-d, %Y")

    log.info(f"Navigating to {url}")
    page.goto(url, wait_until="networkidle", timeout=30000)

    # OfficeSpace uses hash-based or path-based routing — navigate to the room booking section
    # Try common OfficeSpace booking URL patterns
    booking_url = f"{url}/#/book-a-desk"
    log.info(f"Navigating to booking page: {booking_url}")
    page.goto(booking_url, wait_until="networkidle", timeout=30000)

    # If redirected to login, session has expired
    if "login" in page.url.lower() or "sso" in page.url.lower() or "auth" in page.url.lower():
        log.error("Session has expired. Run setup_session.py again to refresh your login.")
        sys.exit(2)

    log.info(f"Booking desk for {date_display}")

    # Wait for the booking interface to load
    page.wait_for_load_state("networkidle", timeout=15000)

    # --- Select date ---
    log.info(f"Selecting date: {date_display}")
    _select_date(page, target_date)

    # --- Select location/floor/area if configured ---
    if location_name:
        log.info(f"Selecting location: {location_name}")
        _select_option_by_text(page, location_name, context="location")

    if floor_name:
        log.info(f"Selecting floor: {floor_name}")
        _select_option_by_text(page, floor_name, context="floor")

    if area_name:
        log.info(f"Selecting area: {area_name}")
        _select_option_by_text(page, area_name, context="area")

    # --- Find and click an available desk ---
    log.info("Looking for available desks...")
    desk = _find_available_desk(page)

    if not desk:
        log.error("No available desks found for the selected date/area.")
        sys.exit(3)

    desk_name = desk.get_attribute("aria-label") or desk.get_attribute("title") or "unknown desk"
    log.info(f"Found available desk: {desk_name}")

    if dry_run:
        log.info(f"[DRY RUN] Would book: {desk_name} on {date_display}")
        return True

    # Click the desk
    desk.click()
    page.wait_for_timeout(1000)

    # --- Confirm booking ---
    confirmed = _confirm_booking(page)
    if confirmed:
        log.info(f"✓ Successfully booked desk '{desk_name}' for {date_display}")
        _take_screenshot(page, f"booking_confirmed_{date_str}.png")
        return True
    else:
        log.error("Booking confirmation failed.")
        _take_screenshot(page, f"booking_failed_{date_str}.png")
        return False


def _select_date(page, target_date):
    """Try multiple strategies to select the target date."""
    date_str_iso = target_date.strftime("%Y-%m-%d")
    date_str_display = target_date.strftime("%m/%d/%Y")

    # Strategy 1: Look for a date input
    date_inputs = page.locator("input[type='date']")
    if date_inputs.count() > 0:
        date_inputs.first.fill(date_str_iso)
        return

    # Strategy 2: Look for a date picker button and navigate to the correct month/day
    date_button_selectors = [
        f"[data-date='{date_str_iso}']",
        f"[aria-label*='{target_date.strftime('%B')}']",
        f"td[data-day='{target_date.day}']",
        f"button[aria-label*='{target_date.strftime('%B %-d')}']",
    ]
    for selector in date_button_selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                el.click()
                page.wait_for_timeout(500)
                return
        except Exception:
            continue

    # Strategy 3: Find any visible date picker and type the date
    pickers = page.locator("input[placeholder*='date' i], input[placeholder*='Date']")
    if pickers.count() > 0:
        pickers.first.fill(date_str_display)
        pickers.first.press("Enter")
        return

    log.warning("Could not find a date selector — proceeding and hoping the default date is correct.")


def _select_option_by_text(page, text, context=""):
    """Click a dropdown option or button matching the given text."""
    selectors = [
        f"text='{text}'",
        f"[aria-label*='{text}']",
        f"option:has-text('{text}')",
        f"li:has-text('{text}')",
        f"[title='{text}']",
    ]
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.is_visible():
                el.click()
                page.wait_for_timeout(500)
                log.info(f"Selected {context}: {text}")
                return
        except Exception:
            continue

    # Try selecting from a <select> dropdown
    selects = page.locator("select")
    for i in range(selects.count()):
        select = selects.nth(i)
        try:
            select.select_option(label=text)
            log.info(f"Selected {context} via dropdown: {text}")
            return
        except Exception:
            continue

    log.warning(f"Could not find {context} option '{text}' — skipping.")


def _find_available_desk(page):
    """
    Find a clickable available desk element.
    OfficeSpace uses SVG floor maps or grid views — try both.
    """
    page.wait_for_timeout(2000)  # Let the map render

    # Common selectors for available desks in OfficeSpace
    available_selectors = [
        # SVG-based floor map
        "g.desk.available",
        "g[class*='desk'][class*='available']",
        "rect.available",
        # List/grid view
        "[class*='desk'][class*='available']:not([class*='unavailable'])",
        "[data-status='available']",
        "[aria-label*='Available']",
        "button[class*='desk']:not([disabled])",
        # Generic green/available state
        ".desk-available",
        ".available-desk",
    ]

    for selector in available_selectors:
        try:
            desks = page.locator(selector)
            if desks.count() > 0:
                log.info(f"Found {desks.count()} available desk(s) via selector: {selector}")
                return desks.first
        except Exception:
            continue

    return None


def _confirm_booking(page):
    """Click the confirm/book button in the booking modal."""
    page.wait_for_timeout(1000)

    confirm_selectors = [
        "button:has-text('Book')",
        "button:has-text('Confirm')",
        "button:has-text('Reserve')",
        "button:has-text('Book Desk')",
        "button:has-text('Save')",
        "[class*='confirm']",
        "[class*='book-btn']",
    ]

    for selector in confirm_selectors:
        try:
            btn = page.locator(selector).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(2000)
                # Check for success indicators
                success_selectors = [
                    "text='successfully'",
                    "text='booked'",
                    "text='confirmed'",
                    "text='reservation'",
                    "[class*='success']",
                    "[class*='confirmation']",
                ]
                for ss in success_selectors:
                    if page.locator(ss).count() > 0:
                        return True
                # If no explicit success message, assume it worked if no error shown
                error_selectors = ["[class*='error']", "text='failed'", "text='error'"]
                for es in error_selectors:
                    if page.locator(es).count() > 0:
                        log.error(f"Booking error detected: {page.locator(es).first.inner_text()}")
                        return False
                return True  # No error shown, assume success
        except Exception:
            continue

    log.error("Could not find a confirm/book button.")
    return False


def _take_screenshot(page, filename):
    try:
        page.screenshot(path=filename, full_page=False)
        log.info(f"Screenshot saved: {filename}")
    except Exception as e:
        log.warning(f"Could not save screenshot: {e}")


def main():
    parser = argparse.ArgumentParser(description="Automatically book a desk in OfficeSpace")
    parser.add_argument("--date", help="Date override: TODAY or YYYY-MM-DD (default: days_ahead from config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be booked without actually booking")
    args = parser.parse_args()

    config = load_config()
    session_file = config.get("session_file", "session.json")
    headless = config.get("headless", True)
    retry_attempts = config.get("retry_attempts", 3)
    retry_delay = config.get("retry_delay_seconds", 30)

    if "YOUR_COMPANY" in config["officespace_url"]:
        log.error("Please update 'officespace_url' in config.json before running.")
        sys.exit(1)

    check_session(session_file)
    target_date = get_target_date(config, args.date)

    log.info(f"=== Desk Booking Agent ===")
    log.info(f"Target date: {target_date}")
    log.info(f"Dry run: {args.dry_run}")

    for attempt in range(1, retry_attempts + 1):
        log.info(f"Attempt {attempt}/{retry_attempts}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=headless)
                context = browser.new_context(storage_state=session_file)
                page = context.new_page()

                success = try_book_desk(page, config, target_date, dry_run=args.dry_run)

                browser.close()

                if success:
                    sys.exit(0)
                else:
                    log.warning(f"Attempt {attempt} failed.")

        except PlaywrightTimeoutError as e:
            log.error(f"Timeout on attempt {attempt}: {e}")
        except SystemExit as e:
            raise
        except Exception as e:
            log.error(f"Unexpected error on attempt {attempt}: {e}", exc_info=True)

        if attempt < retry_attempts:
            log.info(f"Retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    log.error(f"All {retry_attempts} attempts failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
