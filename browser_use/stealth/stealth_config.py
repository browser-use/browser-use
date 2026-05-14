class StealthConfig:
    """
    Stealth Mode configuration for Browser-Use.
    Helps agents bypass bot detection during web automation.
    """
    @staticmethod
    def get_stealth_args():
        return [
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "--window-size=1920,1080"
        ]

    @staticmethod
    def apply_stealth_js(page):
        # Inject script to override navigator.webdriver
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
