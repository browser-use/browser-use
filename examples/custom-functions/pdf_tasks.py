import os
import asyncio
from pathlib import Path
from browser_use.agent.service import BrowserContext, registry
from patchright.async_api import Page


DOWNLOAD_DIR = Path(__file__).parent / "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


@registry.tool(name="download_pdf", description="Intercept and download PDF files on the current page")
async def download_pdf(browser: BrowserContext) -> str:
    """
    Intercepts .pdf requests and forces download. 
    Returns the path to the downloaded file(s) or a status message.
    """
    page = await browser.get_current_page()
    context = page.context

    downloads = []

    # Setup listener for downloads
    async def handle_download(download):
        path = await download.path()
        if path:
            target_path = DOWNLOAD_DIR / os.path.basename(path)
            await download.save_as(str(target_path))
            downloads.append(str(target_path))

    page.on("download", handle_download)

    # Intercept PDF requests and modify headers to force download
    await page.route("**/*", lambda route, request: asyncio.create_task(
        handle_route(route, request, page))
    )

    # Reload current page to apply route interception logic
    await page.reload()

    # Wait for any triggered downloads
    await asyncio.sleep(5)

    if not downloads:
        return "No PDFs downloaded."
    return f"Downloaded PDFs: {downloads}"


async def handle_route(route, request, page: Page):
    url = request.url
    if url.endswith(".pdf") and request.resource_type == "document":
        response = await page.context.request.get(url)
        await route.fulfill(
            status=response.status,
            headers={**response.headers, "Content-Disposition": "attachment"},
            body=await response.body()
        )
    else:
        await route.continue_()
