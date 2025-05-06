import os
import asyncio
from pydantic import BaseModel
from browser_use.agent.views import ActionResult
from browser_use import Controller, BrowserContext

controller = Controller()

class DownloadPDFParams(BaseModel):
    url: str

@controller.registry.action("Download PDF from URL", param_model=DownloadPDFParams)
async def download_pdf(params: DownloadPDFParams, browser: BrowserContext):
    page = await browser.get_current_page()
    download_path = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_path, exist_ok=True)

    downloaded = asyncio.Event()

    async def handle_download(download):
        try:
            path = await download.path()
            if path:
                file_name = os.path.basename(path)
                target_path = os.path.join(download_path, file_name)
                await download.save_as(target_path)
                print(f"[+] Saved PDF to: {target_path}")
                downloaded.set()
        except Exception as e:
            print(f"[!] Download error: {e}")

    page.on("download", handle_download)

    print(f"[~] Navigating to {params.url}")
    response = await page.goto(params.url, wait_until="load", timeout=15000)

    if not response or not response.ok:
        raise Exception(f"Failed to load the page: {params.url} (status: {response.status if response else 'no response'})")

    # Look for iframes if PDF did not trigger
    frames = page.frames
    print(f"[~] Found {len(frames)} frame(s)")
    for frame in frames:
        frame_url = frame.url
        if frame_url.lower().endswith(".pdf"):
            print(f"[~] Navigating iframe to PDF: {frame_url}")
            try:
                await frame.goto(frame_url, wait_until="load")
            except Exception as e:
                print(f"[!] Failed to navigate iframe to PDF: {e}")

    # Wait for download event to complete
    try:
        await asyncio.wait_for(downloaded.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise Exception("Download event did not trigger — PDF may not be downloadable or site uses JS-based download.")

    return ActionResult(
        extracted_content=f"Downloaded PDF from {params.url} to '{download_path}'",
        include_in_memory=True
    )
    
