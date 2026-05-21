"""
Comet Configuration — Windows 10/11 optimized
All constants in one place. Never hardcode values outside this file.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Directories ────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent.parent
COMET_DIR       = BASE_DIR / "comet"
SCREENSHOTS_DIR = COMET_DIR / "screenshots"
DOWNLOADS_DIR   = COMET_DIR / "downloads"
MEMORY_DIR      = COMET_DIR / "memory"
LOGS_DIR        = COMET_DIR / "logs"
DATA_DIR        = COMET_DIR / "data"

for _d in [SCREENSHOTS_DIR, DOWNLOADS_DIR, MEMORY_DIR, LOGS_DIR, DATA_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Gemini (Google AI Studio) ──────────────────────────────────
GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL         = "gemini-2.5-pro-preview-05-06"
GEMINI_VISION_MODEL  = "gemini-2.5-pro-preview-05-06"
LLM_TEMPERATURE      = 0.1
LLM_MAX_TOKENS       = 8192

# ── Chrome Profile (Windows 10 / 11) ─────────────────────────
# Persistent context = zero 2FA / zero Captcha
CHROME_USER_DATA_DIR = os.getenv(
    "CHROME_USER_DATA_DIR",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
)
CHROME_PROFILE       = os.getenv("CHROME_PROFILE", "Default")

CHROME_EXECUTABLES_WIN = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

# ── Browser behaviour ─────────────────────────────────────────
HEADLESS              = False
DEFAULT_TIMEOUT       = 30_000   # ms
NAVIGATION_TIMEOUT    = 60_000   # ms
SCREENSHOT_ON_ERROR   = True

# ── Human simulation (anti-bot) ───────────────────────────────
TYPING_DELAY_MIN  = 50    # ms  per character
TYPING_DELAY_MAX  = 150   # ms  per character
ACTION_PAUSE_MIN  = 1.0   # seconds between actions
ACTION_PAUSE_MAX  = 3.0   # seconds between actions

# ── ReAct loop ────────────────────────────────────────────────
MAX_REACT_ITERATIONS = 50
HISTORY_WINDOW       = 10

# ── Retry & resilience ────────────────────────────────────────
RETRY_MAX_ATTEMPTS        = 3
RETRY_WAIT_SECONDS        = 2.0
CIRCUIT_BREAKER_THRESHOLD = 5

# ── Memory (ChromaDB) ─────────────────────────────────────────
CHROMA_COLLECTION = "comet_memory"
MEMORY_TOP_K      = 5

# ── Captcha (optional — 2captcha.com) ────────────────────────
CAPTCHA_API_KEY = os.getenv("CAPTCHA_API_KEY", "")
CAPTCHA_SERVICE = os.getenv("CAPTCHA_SERVICE", "2captcha")

# ── Paths for all 5 use-cases ─────────────────────────────────
DEFAULT_LEADS_FILE  = str(DATA_DIR / "leads.xlsx")
DEFAULT_OUTPUT_FILE = str(DATA_DIR / "output.xlsx")
DEFAULT_REPORT_FILE = str(DATA_DIR / "report.docx")
