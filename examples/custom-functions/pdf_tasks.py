import os
import asyncio
import uuid
from urllib.parse import urlparse
from pydantic import BaseModel, HttpUrl
from browser_use.agent.views import ActionResult
from browser_use import Controller, BrowserContext
from appdirs import user_download_dir

controller = Controller()

class DownloadPDFParams(BaseModel):
    url: HttpUrl  # Safer validation than just str

@controller.registry.action("Download PDF from URL", param_model=DownloadPDFParams)
async def download_pdf(params: DownloadPDFParams, browser: BrowserContext) -> ActionResult:
    page = await browser.get_current_page()

    # More reliable and user-contextual download path
    download_path = os.path.join(user_download_dir("browser_use"), "pdfs")
    os.makedirs(download_path, exist_ok=True)

    downloaded = asyncio.Event()

    async def handle_download(download) -> None:
        try:
            path = await download.path()
            if not path:
                print("[!] No path returned for download.")
                return

            file_name = os.path.basename(path)
            target_path = os.path.join(download_path, file_name)

            # Prevent overwriting
            if os.path.exists(target_path):
                name, ext = os.path.splitext(file_name)
                target_path = os.path.join(download_path, f"{name}_{uuid.uuid4().hex[:8]}{ext}")

            await download.save_as(target_path)
            print(f"[+] Saved PDF to: {target_path}")
        except Exception as e:
            print(f"[!] Download error: {e}")
        finally:
            downloaded.set()  # Ensure it doesn't hang

    page.on("download", handle_download)

    print(f"[~] Navigating to {params.url}")
    try:
        response = await page.goto(params.url, wait_until="load", timeout=15_000)
    except Exception as e:
        raise Exception(f"Navigation error: {e}") from e

    if not response or not response.ok:
        status = response.status if response else 'no response'
        raise Exception(f"Failed to load the page: {params.url} (status: {status})")

    frames = page.frames
    print(f"[~] Found {len(frames)} frame(s)")
    for frame in frames:
        frame_url = frame.url.lower()
        if frame_url.endswith(".pdf") and frame_url != params.url.lower():
            print(f"[~] Navigating iframe to PDF: {frame_url}")
            try:
                await frame.goto(frame_url, wait_until="load")
            except Exception as e:
                print(f"[!] Failed to navigate iframe to PDF: {e}")

    try:
        await asyncio.wait_for(downloaded.wait(), timeout=15)
    except asyncio.TimeoutError:
        raise Exception("Download event did not trigger — the PDF may not be downloadable or is protected by JS mechanisms.")

    return ActionResult(
        extracted_content=f"Downloaded PDF from {params.url} to '{download_path}'",
        include_in_memory=True
    )
