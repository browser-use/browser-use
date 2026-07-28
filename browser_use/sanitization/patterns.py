# Placeholder regex registry for detectors
import re

def get_default_patterns():
    return {
        "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "phone": re.compile(r"\b(?:\+?\d[\s-]?)?(?:\(\d{1,4}\)|\d{1,4})[\s-]?\d{3,4}[\s-]?\d{3,4}\b"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "jwt": re.compile(r"\beyJ[\w-]*\.[\w-]*\.[\w-]*\b"),
        "api_key": re.compile(r"\b(?:sk|rk|pk)_[A-Za-z0-9]{16,}[^\s]*\b"),
        "oauth_token": re.compile(r"\b(?:ya29\.[A-Za-z0-9-_]+|gho_[A-Za-z0-9]{36,})\b"),
        "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,30}\b"),
    }
