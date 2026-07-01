"""
Comet Vision — Gemini analyses screenshots to guide the agent.
Used as fallback when DOM is unreadable (React/Vue/SPA pages).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

import google.generativeai as genai

from comet.utils.logger import CometLogger
from comet.utils.retry import with_retry


class VisionBrain:
    """
    Visual intelligence layer for Comet.
    Sends screenshots to Gemini Vision and returns structured JSON decisions.
    """

    def __init__(self, logger: CometLogger,
                 api_key: str = "",
                 model: str = "gemini-2.5-pro-preview-05-06"):
        self.logger = logger
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model)

    def _img_part(self, path: Path) -> dict:
        return {
            "mime_type": "image/png",
            "data": base64.b64encode(path.read_bytes()).decode(),
        }

    def _parse(self, raw: str) -> dict:
        raw = re.sub(r"^```json\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        try:
            return json.loads(raw)
        except Exception:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
        return {"error": "parse_failed", "raw": raw[:300]}

    # ── Public methods ─────────────────────────────────────────

    @with_retry(max_attempts=3, wait_seconds=2.0, circuit_name="vision")
    async def analyze_page(self, screenshot: Path, goal: str) -> dict:
        """
        Full page analysis.
        Returns page description, suggested action and CSS selector hint.
        """
        prompt = f"""
        Tu es l'œil d'un agent web. Objectif : {goal}

        Analyse ce screenshot et retourne CE JSON exact (rien d'autre) :
        {{
            "page_description": "...",
            "visible_elements": ["..."],
            "suggested_action": "...",
            "target_element":   "...",
            "target_selector":  "CSS ou vide",
            "error_detected":   false,
            "error_message":    "",
            "captcha_detected": false,
            "loading":          false,
            "modal_open":       false
        }}
        """
        resp = self.model.generate_content([self._img_part(screenshot), prompt])
        result = self._parse(resp.text)
        self.logger.observation(
            f"Vision analyze → {result.get('suggested_action','?')}")
        return result

    @with_retry(max_attempts=3, wait_seconds=2.0, circuit_name="vision")
    async def find_element(self, screenshot: Path,
                           description: str,
                           width: int = 1280,
                           height: int = 800) -> dict:
        """
        Locate an element by natural-language description.
        Returns pixel coordinates for mouse click.
        """
        prompt = f"""
        Image : {width}x{height} px.
        Trouve l'élément : "{description}"

        Retourne UNIQUEMENT :
        {{
            "found": true/false,
            "x": <int>,
            "y": <int>,
            "confidence": <0.0-1.0>,
            "description": "..."
        }}
        """
        resp   = self.model.generate_content([self._img_part(screenshot), prompt])
        result = self._parse(resp.text)
        self.logger.observation(
            f"Vision find '{description}' → "
            f"found={result.get('found')}, "
            f"({result.get('x')},{result.get('y')}), "
            f"conf={result.get('confidence',0):.2f}"
        )
        return result

    @with_retry(max_attempts=2, wait_seconds=1.0, circuit_name="vision")
    async def detect_captcha(self, screenshot: Path) -> dict:
        """Detect and classify any CAPTCHA present on the page."""
        prompt = """
        Y a-t-il un CAPTCHA visible ? Retourne :
        {
            "detected": true/false,
            "type": "recaptcha_v2|recaptcha_v3|hcaptcha|image|text|none",
            "blocking": true/false
        }
        """
        resp = self.model.generate_content([self._img_part(screenshot), prompt])
        return self._parse(resp.text)

    @with_retry(max_attempts=2, wait_seconds=1.0, circuit_name="vision")
    async def read_text(self, screenshot: Path) -> str:
        """OCR — extract all visible text from the screenshot."""
        prompt = ("Retranscris EXACTEMENT tout le texte visible. "
                  "Préserve la structure. Texte brut uniquement.")
        resp = self.model.generate_content([self._img_part(screenshot), prompt])
        return resp.text.strip()
