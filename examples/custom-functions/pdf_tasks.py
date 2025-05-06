import os
import asyncio
from pydantic import BaseModel
from browser_use.agent.views import ActionResult
from browser_use import Controller, BrowserContext

controller = Controller()

class DownloadFileParams(BaseModel):
    url: str
    expected_type: str = "pdf"  # or "zip"

@controller.registry.action("Download file from URL", param_model=DownloadFileParams)
async def download_file(params: DownloadFileParams, browser: BrowserContext):
    page = await browser.get_current_page()
    download_path = os.path.join(os.getcwd(), 'downloads')
    os.makedirs(download_path, exist_ok=True)

    downloaded = asyncio.Event()
    file_result = {"path": None, "source": None}

    async def handle_download(download):
        try:
            file_path = await download.path()
            if file_path:
                file_name = os.path.basename(file_path)
                target_path = os.path.join(download_path, file_name)
                await download.save_as(target_path)
                print(f"[+] Saved file to: {target_path}")
                file_result["path"] = target_path
                downloaded.set()
        except Exception as e:
            print(f"[!] Download error: {e}")

    page.on("download", handle_download)

    print(f"[~] Navigating to {params.url}")
    response = await page.goto(params.url, wait_until="load", timeout=15000)
    if not response or not response.ok:
        raise Exception(f"Failed to load page: {params.url}")

    # Check MIME type
    content_type = response.headers.get("content-type", "")
    print(f"[i] MIME Type: {content_type}")
    if params.expected_type not in content_type and not content_type.startswith("text/html"):
        raise Exception(f"Unexpected content-type: {content_type}")

    # Check for iframe-based files
    frames = page.frames
    print(f"[~] Found {len(frames)} frame(s)")
    for frame in frames:
        frame_url = frame.url.lower()
        if frame_url.endswith(f".{params.expected_type}"):
            print(f"[~] Navigating to file inside iframe: {frame_url}")
            try:
                await frame.goto(frame_url, wait_until="load")
                file_result["source"] = frame_url
            except Exception as e:
                print(f"[!] Failed to load iframe file: {e}")

    # Try clicking common download buttons if visible
    selectors = [
        "a[download]", 
        "a[href$='.pdf']", 
        "a[href$='.zip']",
        "button.download",
        "button:has-text('Download')",
        "text=Download"
    ]

    for selector in selectors:
        try:
            if await page.is_visible(selector):
                print(f"[~] Clicking download trigger: {selector}")
                await page.click(selector)
                await asyncio.sleep(2)  # give time for download to begin
        except Exception:
            pass  # continue to next selector

    # Wait for the download to complete
    try:
        await asyncio.wait_for(downloaded.wait(), timeout=15)
    except asyncio.TimeoutError:
        raise Exception("Download did not complete — file may require JS events or credentials.")

    if not file_result["path"]:
        raise Exception("Download event triggered but file path missing.")

    return ActionResult(
        extracted_content=f"Downloaded {params.expected_type.upper()} from {file_result['source'] or params.url} to '{file_result['path']}'",
        include_in_memory=True
    )
