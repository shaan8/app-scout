"""Render scenes.html to a 1080p MP4, one deterministic frame per tick.

    uv run --with playwright python video/render.py                  # full video
    uv run --with playwright python video/render.py --stills 3 20 45 # check a few frames as PNGs
    uv run --with playwright python video/render.py --poster         # README poster image

Needs Google Chrome and ffmpeg. The encode stays under GitHub's 10 MB limit for inline video.
"""

import argparse
import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FPS = 30


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "app-scout-demo.mp4")
    parser.add_argument("--stills", type=float, nargs="*", help="render PNGs at these seconds instead")
    parser.add_argument("--poster", action="store_true", help="render the README poster (title frame + play button)")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.goto((HERE / "scenes.html").as_uri())
        page.wait_for_timeout(500)

        if args.poster:
            page.evaluate("render(4); document.getElementById('play').style.display = 'block'")
            page.screenshot(path=HERE / "poster.png")
            browser.close()
            return

        if args.stills:
            for t in args.stills:
                page.evaluate(f"render({t})")
                page.screenshot(path=HERE / f"still-{t:05.1f}.png")
            browser.close()
            return

        duration = page.evaluate("DURATION")
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-",
             "-c:v", "libx264", "-preset", "veryslow", "-crf", "22", "-tune", "animation", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(args.out)],
            stdin=subprocess.PIPE,
        )
        for frame in range(int(duration * FPS)):
            page.evaluate(f"render({frame / FPS})")
            ffmpeg.stdin.write(screenshot(page))
        ffmpeg.stdin.close()
        ffmpeg.wait()
        browser.close()


def screenshot(page, attempts: int = 3) -> bytes:
    # Chrome occasionally stalls on a frame when the machine is busy; a retry is enough.
    for attempt in range(attempts):
        try:
            return page.screenshot(type="png", timeout=120_000)
        except Exception:
            if attempt == attempts - 1:
                raise


if __name__ == "__main__":
    main()
