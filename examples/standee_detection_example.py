import os
import sys
import logging
import asyncio
import argparse
from pathlib import Path
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from browser_use import Agent
from browser_use.browser.browser import Browser, BrowserConfig
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def extract_cdp_port():
    """Extract CDP port for Devin environment"""
    import subprocess
    
    cmd = "ps aux | grep -o '\\-\\-remote-debugging-port=[0-9]\\+' | awk -F= '{print $2}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        return None
        
    ports = result.stdout.strip().split('\n')
    ports = [p for p in ports if p]
    
    if not ports:
        return None
        
    port_counts = {}
    for port in ports:
        if port in port_counts:
            port_counts[port] += 1
        else:
            port_counts[port] = 1
            
    most_common_port = max(port_counts.items(), key=lambda x: x[1])[0]
    return int(most_common_port)
    
async def take_screenshot(context, name):
    """Take a screenshot during navigation"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    page = await context.get_current_page()
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{name}_{timestamp}.png")
    await page.screenshot(path=screenshot_path)
    logger.info(f"Screenshot saved: {screenshot_path}")
    return screenshot_path
    
async def process_photo_with_standee_detection(agent, photo_url):
    """Process a photo URL with standee detection"""
    detector = agent.get_tool('standee_detection')
    if not detector:
        logger.error("Standee detection tool not initialized")
        return False
        
    result = detector.detect_from_url(photo_url)
    
    if result.get('success'):
        detections = result.get('detections', [])
        if detections:
            logger.info(f"Found {len(detections)} standee(s) in photo: {photo_url}")
            for i, det in enumerate(detections):
                logger.info(f"  Standee {i+1} - Confidence: {det['confidence']:.4f}")
            return True
        else:
            logger.info(f"No standees detected in photo: {photo_url}")
            return False
    else:
        logger.error(f"Detection failed: {result.get('error')}")
        return False
        
async def naver_maps_standee_detection(
    task=None,
    model="gpt-4o",
    use_azure=False,
    headless=True,
    advanced_mode=True,
    cdp_port=None,
    enable_screenshots=False
):
    """Run Naver Maps standee detection with browser-use"""
    browser_config = BrowserConfig(
        advanced_mode=advanced_mode,
        headless=headless,
        cdp_url=f"http://localhost:{cdp_port}" if cdp_port else None,
        disable_security=True  # Enable cross-origin iframe access
    )
    
    browser = Browser(config=browser_config)
    
    if use_azure:
        from langchain_openai import AzureChatOpenAI
        
        azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        azure_api_key = os.environ.get("AZURE_OPENAI_KEY")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_GPT_4O")
        
        if not all([azure_endpoint, azure_api_key, api_version, deployment]):
            raise ValueError("Azure OpenAI credentials not properly configured")
            
        llm = AzureChatOpenAI(
            azure_endpoint=azure_endpoint,
            azure_deployment=deployment,
            api_key=azure_api_key,
            api_version=api_version
        )
    else:
        llm = ChatOpenAI(model=model)
        
    if not task:
        task = """
        Go to Naver Maps and search for the restaurant - 반포식스 덕수궁점
        Navigate to the photos section
        For each photo in the 외부 (exterior) category:
        1. Extract the photo URL
        2. Process the photo with standee detection
        3. Log any photos with standee detections
        """
        
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser,
        tools=['standee_detection']
    )
    
    try:
        await agent.run()
        
        photo_urls = agent.state.extracted_data.get('photo_urls', [])
        
        for url in photo_urls:
            await process_photo_with_standee_detection(agent, url)
            
    except Exception as e:
        logger.error(f"Error during processing: {str(e)}")
    finally:
        await browser.close()
        
async def main():
    parser = argparse.ArgumentParser(description='Standee detection with browser-use')
    parser.add_argument('--use-azure', action='store_true', help='Use Azure OpenAI')
    parser.add_argument('--model', default='gpt-4o', help='Model name')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--no-headless', action='store_false', dest='headless', help='Run in visible mode')
    parser.add_argument('--advanced-mode', action='store_true', help='Enable advanced mode')
    parser.add_argument('--no-advanced-mode', action='store_false', dest='advanced_mode', help='Disable advanced mode')
    parser.add_argument('--cdp-port', type=int, help='CDP port for browser connection')
    parser.add_argument('--screenshots', action='store_true', help='Enable screenshots')
    parser.add_argument('--task', type=str, help='Custom task to perform')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        
    if not args.cdp_port:
        args.cdp_port = extract_cdp_port()
        if args.cdp_port:
            logger.info(f"Detected CDP port: {args.cdp_port}")
            
    await naver_maps_standee_detection(
        task=args.task,
        model=args.model,
        use_azure=args.use_azure,
        headless=args.headless,
        advanced_mode=args.advanced_mode,
        cdp_port=args.cdp_port,
        enable_screenshots=args.screenshots
    )
    
if __name__ == "__main__":
    asyncio.run(main())
