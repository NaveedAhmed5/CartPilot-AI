"""Long-term memory helpers (per user_id, stored in Postgres `user_memories`).

Two ways facts get saved:
1. Deterministic extraction here, for explicit statements such as "my size is M" or
   "I live in Lahore". It runs on every turn and costs no tokens.
2. The agent's `save_user_preference` tool, for anything the model judges to be a
   lasting preference (style, budget, favourite colours, ...).
"""

import re
from typing import Any, Dict, Optional

PK_CITIES = [
    "Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta",
    "Sialkot", "Hyderabad", "Gujranwala", "Bahawalpur", "Sargodha", "Sukkur", "Abbottabad",
    "Mardan", "Larkana", "Sheikhupura", "Rahim Yar Khan", "Gujrat", "Sahiwal", "Okara", "Mirpur",
    "Muzaffarabad", "Gilgit", "Skardu", "Hunza", "Murree", "Jhelum", "Kasur", "Dera Ghazi Khan",
    "Wah Cantt", "Taxila", "Chitral", "Swat", "Mingora", "Nawabshah", "Mirpur Khas", "Gwadar",
]
_CITY_ALT = "|".join(sorted((re.escape(c) for c in PK_CITIES), key=len, reverse=True))

_SIZE_WORDS = {
    "xs": "XS", "extra small": "XS", "s": "S", "small": "S", "m": "M", "medium": "M", "l": "L",
    "large": "L", "xl": "XL", "extra large": "XL", "xxl": "XXL", "2xl": "XXL", "double xl": "XXL",
}
_SIZE_ALT = r"(xxl|2xl|double xl|xl|extra large|extra small|xs|small|medium|large|s|m|l)"

SIZE_RE = re.compile(
    rf"\b(?:my\s+size\s+is|i\s+(?:usually\s+|normally\s+|always\s+)?wear(?:\s+a)?(?:\s+size)?|"
    rf"i(?:'m|\s+am)\s+(?:a\s+)?(?:size\s+)?|my\s+(?:t-?shirt|shirt|hoodie|clothing)\s+size\s+is|"
    rf"remember\s+(?:that\s+)?(?:my\s+size\s+is|i\s+wear))\s*{_SIZE_ALT}\b(?!\s*(?:years?|kg|cm|ft|minutes?))",
    re.IGNORECASE,
)
CITY_RE = re.compile(
    rf"\b(?:i\s+live\s+in|i(?:'m|\s+am)\s+(?:from|based\s+in|in)|living\s+in|i\s+stay\s+in|my\s+city\s+is|"
    rf"based\s+(?:out\s+of|in))\s+({_CITY_ALT})\b",
    re.IGNORECASE,
)
NAME_RE = re.compile(
    r"\b(?:my\s+name\s+is|call\s+me|mera\s+naam)\s+([A-Z][a-zA-Z]{1,20}(?:\s+[A-Z][a-zA-Z]{1,20})?)",
)
NAME_RE_CI = re.compile(r"\b(?:my\s+name\s+is|call\s+me)\s+([a-zA-Z]{2,20})\b", re.IGNORECASE)
BUDGET_RE = re.compile(
    r"\bmy\s+budget\s+is\s+(?:around\s+|about\s+|under\s+|below\s+|max\s+)?(?:rs\.?\s*|pkr\s*)?([0-9][0-9,]{2,8})",
    re.IGNORECASE,
)
_NAME_STOP = {"the", "a", "an", "you", "it", "me", "please", "back", "later", "now"}


def extract_facts(message: str) -> Dict[str, str]:
    """Pull explicit, lasting profile facts out of a user message."""
    facts: Dict[str, str] = {}
    text = message or ""
    m = SIZE_RE.search(text)
    if m:
        raw = m.group(1).lower()
        facts["preferred_size"] = _SIZE_WORDS.get(raw, raw.upper())
    m = CITY_RE.search(text)
    if m:
        city = m.group(1)
        facts["city"] = next((c for c in PK_CITIES if c.lower() == city.lower()), city.title())
    m = NAME_RE.search(text) or NAME_RE_CI.search(text)
    if m and m.group(1).split()[0].lower() not in _NAME_STOP:
        facts["name"] = m.group(1).strip().title()
    m = BUDGET_RE.search(text)
    if m:
        facts["budget"] = f"PKR {m.group(1).replace(',', '')}"
    return facts


def format_profile(profile: Optional[Dict[str, Any]]) -> str:
    if not profile:
        return "No saved preferences yet."
    labels = {
        "name": "Name", "preferred_size": "Preferred size", "city": "City",
        "budget": "Budget", "style_notes": "Style notes",
    }
    parts = [f"{label}: {profile[k]}" for k, label in labels.items() if profile.get(k)]
    return "; ".join(parts) if parts else "No saved preferences yet."
