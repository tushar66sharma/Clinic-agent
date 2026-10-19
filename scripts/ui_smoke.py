"""Browser smoke test of the dashboard's main journeys, at desktop and mobile sizes.

Prerequisites: the API is running and serving the built dashboard (see README), and
Playwright is installed:  pip install playwright && python -m playwright install chromium

    python scripts/ui_smoke.py [--base http://localhost:8000] [--screenshots docs/screenshots]

Checks, per viewport:
  1. Inbox loads; "Process all" runs the sample set to completion (reuses cached AI answers).
  2. An emergency message shows the emergency banner and the escalation action.
  3. New message: an empty submit shows validation errors; an example message is processed.
  4. Staff queues, Schedule, Evaluation and System pages render their content.
  5. No browser console errors, no horizontal scrolling on any page.
Exit code 1 if any check fails.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}
failures: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        failures.append(what)


def no_horizontal_scroll(page: Page, where: str) -> None:
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    check(overflow <= 1, f"{where}: no horizontal scroll (overflow {overflow}px)")


def shot(page: Page, path: Path, full: bool = True) -> None:
    page.evaluate("window.scrollTo(0, 0)")  # keeps sticky headers in place in full-page shots
    page.wait_for_timeout(900)  # let smooth scrolling finish
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(path), full_page=full)


def nav(page: Page, mobile: bool, label: str) -> None:
    if mobile:
        page.get_by_role("button", name="Open menu").click()
    page.get_by_role("navigation", name="Main").get_by_role("link", name=label).click()


def run(base: str, shots: Path) -> None:
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, size in VIEWPORTS.items():
            mobile = name == "mobile"
            print(f"\n[{name} {size['width']}x{size['height']}]")
            page = browser.new_page(viewport=size)
            errors: list[str] = []
            page.on("console", lambda m, errs=errors: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))

            # 1. Inbox and batch processing
            page.goto(base + "/")
            expect(page.get_by_role("heading", name="Inbox")).to_be_visible()
            if not mobile:  # run the batch once, on desktop
                page.get_by_role("button", name="Process all").click()
                page.get_by_role("dialog").get_by_role("button", name="Start").click()
                expect(page.get_by_text("40 of 40 processed")).to_be_visible(timeout=600_000)
                check(True, "Process all finished 40 messages")
            no_horizontal_scroll(page, "inbox")
            shot(page, shots / f"{name}-inbox.png", full=False)

            # 2. Emergency detail
            page.get_by_role("button", name="Aisha Johnson").first.click()
            alert = page.get_by_role("alert").filter(has_text="Possible emergency")
            expect(alert).to_be_visible(timeout=20_000)
            check(page.get_by_text("Escalate emergency").first.is_visible(), "emergency shows escalation action")
            no_horizontal_scroll(page, "message detail")
            shot(page, shots / f"{name}-emergency-detail.png")

            # 3. New message: validation, then an example
            nav(page, mobile, "New message")
            page.get_by_role("button", name="Process message").click()
            check(page.get_by_text("Enter the sender's name.").is_visible(), "empty form shows validation errors")
            page.get_by_role("button", name="Refill", exact=True).click()
            page.get_by_role("button", name="Process message").click()
            expect(page.get_by_text("Reply draft (for staff review)")).to_be_visible(timeout=180_000)
            check(page.get_by_text("Prepare refill for approval").first.is_visible(), "refill example processed")
            no_horizontal_scroll(page, "new message")
            shot(page, shots / f"{name}-new-message.png")

            # 4. Other pages
            for label, marker, file in [
                ("Staff queues", "Tickets", "queues"),
                ("Schedule", "Dr. Maya Patel", "schedule"),
                ("Evaluation", "Emergency recall", "evaluation"),
                ("System", "Clinic configuration", "system"),
            ]:
                nav(page, mobile, label)
                expect(page.get_by_text(marker).first).to_be_visible(timeout=20_000)
                check(True, f"{label} renders")
                no_horizontal_scroll(page, label)
                shot(page, shots / f"{name}-{file}.png")

            if not mobile:
                behaviour_checks(page, base, errors)

            check(not errors, f"no browser console errors {errors[:3] if errors else ''}")
            page.close()
        browser.close()


def behaviour_checks(page: Page, base: str, errors: list[str]) -> None:
    """Manual test plan section H, automated (desktop only)."""
    print("  -- dashboard behaviour (manual plan section H)")
    # H2: date-of-birth format validation
    nav(page, False, "New message")
    page.get_by_label("Date of birth (optional)").fill("20-11-1990")
    page.get_by_role("button", name="Process message").click()
    check(page.get_by_text("Use the format YYYY-MM-DD.").is_visible(), "H2 wrong date-of-birth format is rejected")

    # H3: reset dialog can be cancelled with the button and with Esc
    nav(page, False, "Staff queues")
    page.get_by_role("button", name="Reset clinic data").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    check(not dialog.is_visible(), "H3 reset dialog closes on Cancel")
    page.get_by_role("button", name="Reset clinic data").click()
    page.keyboard.press("Escape")
    check(not page.get_by_role("dialog").is_visible(), "H3 reset dialog closes on Esc")

    # H4 / H5: schedule shows holidays and provider leave
    nav(page, False, "Schedule")
    page.get_by_label("Date").fill("2026-11-27")
    expect(page.get_by_text("Clinic closed (holiday)")).to_be_visible(timeout=10_000)
    check(True, "H4 27 Nov shows clinic closed (holiday)")
    page.get_by_label("Date").fill("2026-11-18")
    expect(page.get_by_text("On leave").first).to_be_visible(timeout=10_000)
    check(True, "H5 18 Nov shows Dr. Okafor on leave")

    # H8: keyboard users get a skip link first, and focus is visible
    page.goto(base + "/")
    expect(page.get_by_role("heading", name="Inbox")).to_be_visible()
    page.wait_for_load_state("networkidle")  # styles applied before measuring the outline
    page.keyboard.press("Tab")
    focused = page.evaluate("document.activeElement && document.activeElement.textContent")
    check("Skip to content" in (focused or ""), "H8 first Tab reaches 'Skip to content'")
    outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
    check(outline not in ("none", ""), f"H8 focused element has a visible outline ({outline})")

    # H9: copy button on a processed reply
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.get_by_role("button", name="Robert Chen").first.click()
    copy = page.get_by_role("button", name="Copy", exact=True)  # a message body mentions "copy"
    expect(copy).to_be_visible(timeout=20_000)
    copy.click()
    expect(page.get_by_role("button", name="Copied", exact=True)).to_be_visible(timeout=5_000)
    check(True, "H9 Copy button confirms 'Copied'")

    # H10: server unreachable -> clear message with Try again, not a blank page
    nav(page, False, "Staff queues")
    before = len(errors)
    page.route("**/api/queues", lambda route: route.abort())
    page.get_by_role("button", name="Refresh").click()
    expect(page.get_by_text("Cannot reach the server")).to_be_visible(timeout=10_000)
    check(page.get_by_role("button", name="Try again").is_visible(),
          "H10 unreachable server shows a clear error with Try again")
    page.unroute("**/api/queues")
    # The blocked request above is logged by the browser on purpose; drop only that entry.
    errors[before:] = [e for e in errors[before:] if "ERR_FAILED" not in e]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--screenshots", type=Path, default=Path("docs/screenshots"))
    a = ap.parse_args()
    run(a.base, a.screenshots)
    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{len(failures)} FAILED'}")
    sys.exit(1 if failures else 0)
