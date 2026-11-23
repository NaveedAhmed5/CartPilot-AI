#!/usr/bin/env python3
"""Drive the website end to end with Playwright and record docs/demo.gif.

    pip install playwright && playwright install chromium   # or use an installed Chrome
    python scripts/record_demo.py --site http://localhost:5173 --admin-password <ADMIN_PASSWORD>

Requires the site and API to be running. Uses a fresh demo account each run.
Frames are captured as screenshots and stitched into a GIF with ffmpeg.
"""

import argparse
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Recorder:
    def __init__(self, page: Page, folder: Path):
        self.page, self.folder, self.n = page, folder, 0

    def frame(self, repeat: int = 1) -> None:
        path = self.folder / f"f{self.n:05d}.png"
        self.page.screenshot(path=str(path))
        self.n += 1
        for _ in range(repeat - 1):
            shutil.copy(path, self.folder / f"f{self.n:05d}.png")
            self.n += 1

    def type(self, selector: str, text: str, chunk: int = 5) -> None:
        box = self.page.locator(selector)
        box.click()
        for i in range(0, len(text), chunk):
            box.press_sequentially(text[i:i + chunk])
            self.frame()

    def wait_reply(self, before: int, timeout_s: float = 90) -> str:
        page = self.page
        waited, captured = 0.0, 0
        while waited < timeout_s:
            count = page.locator(".bubble.assistant:not(.typing)").count()
            if count > before:
                break
            if captured < 6:
                self.frame()
                captured += 1
            page.wait_for_timeout(700)
            waited += 0.7
        page.wait_for_timeout(300)
        self.frame(repeat=10)
        return page.locator(".bubble.assistant:not(.typing)").last.inner_text()


def chat(rec: Recorder, text: str) -> str:
    before = rec.page.locator(".bubble.assistant:not(.typing)").count()
    rec.type(".chat-input textarea", text)
    rec.page.keyboard.press("Enter")
    reply = rec.wait_reply(before)
    print(f"> {text}\n< {reply[:160]!r}\n")
    return reply


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="http://localhost:5173")
    ap.add_argument("--admin-password", default="cartpilot-admin")
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo.gif"))
    ap.add_argument("--channel", default="chrome", help="'chrome' for an installed Chrome, '' for bundled Chromium")
    args = ap.parse_args()

    frames = Path(tempfile.mkdtemp(prefix="cp_frames_"))
    user = f"demo{uuid.uuid4().hex[:5]}"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel or None, headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 760})
        rec = Recorder(page, frames)

        page.goto(args.site, wait_until="networkidle")
        page.wait_for_timeout(600)
        rec.frame(repeat=8)

        # Create an account so the account page has data later.
        page.get_by_role("button", name="Sign in").first.click()
        page.get_by_role("tab", name="Create account").click()
        page.get_by_label("Your name").fill("Hamza")
        page.get_by_label("Username").fill(user)
        page.get_by_label("Password").fill("demo1234")
        rec.frame(repeat=3)
        page.locator(".auth-dialog").get_by_role("button", name="Create account").click()
        page.wait_for_timeout(800)

        page.get_by_role("button", name="Open chat with CartPilot").click()
        page.wait_for_timeout(400)
        rec.frame(repeat=4)

        chat(rec, "My size is M and I live in Lahore. Any hoodies under 7000?")
        reply = chat(rec, "I'll take the Karachi Underground hoodie in M. Phone 03001234567, House 12 Street 4 Gulberg III")
        if "confirm" not in reply.lower() and "yes" not in reply.lower():
            reply = chat(rec, "My name is Hamza Ali. Please prepare the order.")
        chat(rec, "yes")
        chat(rec, "Write me a poem about the moon")

        # New conversation: long-term memory.
        page.get_by_role("button", name="New chat").click()
        page.wait_for_timeout(300)
        rec.frame(repeat=3)
        chat(rec, "What size and city do you have saved for me?")
        page.get_by_role("button", name="Close chat").click()
        page.wait_for_timeout(400)

        page.get_by_role("link", name="My account").click()
        page.wait_for_timeout(1500)
        rec.frame(repeat=14)

        # Admin dashboard.
        page.goto(f"{args.site}/admin", wait_until="networkidle")
        page.get_by_label("Admin password").fill(args.admin_password)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_timeout(1500)
        rec.frame(repeat=14)
        for tab in ("Orders", "Conversations", "Customers"):
            page.get_by_role("button", name=tab, exact=True).click()
            page.wait_for_timeout(1200)
            rec.frame(repeat=10)
        browser.close()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    palette = frames / "palette.png"
    common = "fps=4,scale=960:-1:flags=lanczos"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "4", "-i", str(frames / "f%05d.png"),
                    "-vf", f"{common},palettegen=stats_mode=diff", str(palette)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "4", "-i", str(frames / "f%05d.png"),
                    "-i", str(palette), "-lavfi", f"{common}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4",
                    str(out)], check=True)
    shutil.rmtree(frames, ignore_errors=True)
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
