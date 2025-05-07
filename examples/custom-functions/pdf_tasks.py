import os
import asyncio
from pydantic import BaseModel
from browser_use.agent.views import ActionResult
from browser_use import Controller, BrowserContext

controller = Controller()

class DownloadPDFParams(BaseModel):
    url: str

@controller.registry.action("Download PDF from URL", param_model=DownloadPDFParams)
async def download_pdf(params: DownloadPDFParams, browser: BrowserContext) -> ActionResult:
    page = await browser.get_current_page()
    download_path = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_path, exist_ok=True)

    downloaded = asyncio.Event()

    async def handle_download(download) -> None:
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
    response = await page.goto(params.url, wait_until="load", timeout=15_000)

    if not response or not response.ok:
        status = response.status if response else 'no response'
        raise Exception(f"Failed to load the page: {params.url} (status: {status})")

    print(f"[~] Found {len(page.frames)} frame(s)")
    for frame in page.frames:
        if frame.url.lower().endswith(".pdf"):
            print(f"[~] Navigating iframe to PDF: {frame.url}")
            try:
                await frame.goto(frame.url, wait_until="load")
            except Exception as e:
                print(f"[!] Failed to navigate iframe to PDF: {e}")

    try:
        await asyncio.wait_for(downloaded.wait(), timeout=10)
    except asyncio.TimeoutError:
        raise Exception("Download event did not trigger — PDF may not be downloadable or site uses JS-based download.")

    return ActionResult(
        extracted_content=f"Downloaded PDF from {params.url} to '{download_path}'",
        include_in_memory=True
    )
