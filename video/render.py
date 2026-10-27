"""Render scenes.html to a 1080p MP4, one deterministic frame per tick.

    uv run --with playwright python video/render.py                  # full video
    uv run --with playwright python video/render.py --stills 3 20 45 # check a few frames as PNGs
    uv run --with playwright python video/render.py --preview        # README preview from the MP4

Needs Google Chrome and ffmpeg. The encode stays under GitHub's 10 MB limit for inline video.
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
FPS = 30
# GitHub only plays uploaded videos inline, but it animates WebP images from the repo.
PREVIEW_FPS = 10
PREVIEW_WIDTH = 1280


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "app-scout-demo.mp4")
    parser.add_argument("--stills", type=float, nargs="*", help="render PNGs at these seconds instead")
    parser.add_argument("--preview", action="store_true", help="build the README's animated WebP from the MP4")
    args = parser.parse_args()

    if args.preview:
        build_preview(args.out, HERE / "app-scout-demo.webp")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.goto((HERE / "scenes.html").as_uri())
        page.wait_for_timeout(500)

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


def build_preview(video: Path, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                        f"fps={PREVIEW_FPS},scale={PREVIEW_WIDTH}:-1:flags=lanczos", f"{tmp}/f%04d.png"], check=True)
        frames = sorted(Path(tmp).glob("f*.png"))
        subprocess.run(["img2webp", "-loop", "0", "-lossy", "-q", "60", "-m", "4", "-d", str(1000 // PREVIEW_FPS),
                        "-mixed", *map(str, frames), "-o", str(out)], check=True, capture_output=True)


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
