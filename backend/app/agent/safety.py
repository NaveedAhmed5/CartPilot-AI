"""Deterministic safety screen that runs *before* the LLM (zero token cost).

It catches the obvious cases: prompt injection / jailbreaks, requests for other
users' data, clearly off-topic tasks and oversized inputs. Anything subtler is
handled by the sales agent's system prompt, which also refuses off-topic requests.
Patterns are deliberately conservative: a false positive blocks a real shopper.
"""

import re
from dataclasses import dataclass
from typing import Optional

MAX_MESSAGE_CHARS = 2000


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: Optional[str] = None  # injection | other_user_data | off_topic | too_long | empty
    reply: Optional[str] = None


_I = re.IGNORECASE

INJECTION_PATTERNS = [
    r"\b(ignore|disregard|forget|override|bypass|skip)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|the|system|these|those|any)\b[^.\n]{0,25}\b(instructions?|prompts?|rules?|directions?|guidelines?|guardrails?|polic(y|ies)|restrictions?)",
    r"\b(reveal|show|print|display|repeat|leak|output|tell me|give me|share|dump|what (is|are))\b[^.\n]{0,30}\b(your|the)\s+(system\s+prompt|initial\s+prompt|hidden\s+(prompt|instructions?)|instructions|developer\s+(message|prompt)|internal\s+rules|configuration|prompt)",
    r"\bsystem\s+prompt\b",
    r"\b(you\s+are\s+now|from\s+now\s+on\s+you\s+are|act\s+as\s+(an?\s+)?(unrestricted|unfiltered|evil|different|new)|pretend\s+(to\s+be|you\s+are)|roleplay\s+as|role-play\s+as)\b",
    r"\b(developer|god|sudo|admin|debug|jailbreak|dan)\s+mode\b",
    r"\bjailbreak\b|\bDAN\b|do\s+anything\s+now",
    r"\bnew\s+instructions?\s*:",
    r"^\s*(system|assistant|developer)\s*:",
    r"</?\s*(system|instructions?|admin|developer)\s*>",
    r"\b(i\s+am|i'm)\s+(your|the|an?)\s+(admin|administrator|developer|creator|owner\s+of\s+cartpilot|system)\b",
    r"\b(set|change|make)\b[^.\n]{0,30}\bprices?\b[^.\n]{0,20}\b(to\s+)?(0|zero|free)\b",
    r"\b(execute|run)\b[^.\n]{0,20}\b(sql|query|code|command|script)\b",
    r"\b(drop|truncate|delete\s+from|insert\s+into|update\s+\w+\s+set)\b[^.\n]{0,40}\b(table|products|orders|users|database)\b",
]

OTHER_USER_PATTERNS = [
    r"\b(other|another|different|all|every)\s+(users?|customers?|people|buyers?|accounts?)('s|s')?\b[^.\n]{0,40}\b(orders?|data|address(es)?|details|memory|memories|preferences|phone|history|info(rmation)?|chats?|conversations?)",
    r"\b(orders?|data|address(es)?|details|memory|memories|preferences|phone(\s+numbers?)?|history|info(rmation)?|chats?|conversations?)\b[^.\n]{0,30}\b(of|for|from|belonging\s+to)\s+(other|another|all|every|different)\s+(users?|customers?|people|accounts?)",
    r"\buser[_\s-]?id\s*[:=#]?\s*[\"']?[a-z0-9_\-]{2,}[\"']?[^.\n]{0,40}\b(orders?|data|address|details|memory|preferences|history)\b",
    r"\bwhat\s+(did|has|have)\s+(user|customer|account)\s+[\"']?[\w\-]+[\"']?\s+(order|ordered|buy|bought|purchase|purchased)",
    r"\b(orders?|data|address|details|memory|preferences|history)\b[^.\n]{0,30}\b(of|for)\s+user[_\s-]?(id)?\s*[:=#]?\s*[a-z0-9_\-]{2,}",
    r"\b(list|show|give|export|dump)\b[^.\n]{0,20}\ball\s+(the\s+)?(users|customers|orders|accounts)\b",
    r"\bsomeone\s+else('s)?\s+(order|data|account|address|details)",
]

STORE_WORDS = re.compile(
    r"\b(?:hoodies?|hoody|tees?|t-?shirts?|shirts?|jerseys?|jackets?|bombers?|vests?|puffers?|coats?|caps?|"
    r"beanies?|hats?|bags?|pants|cargos?|denim|jeans|trousers|sneakers?|shoes?|footwear|outfits?|wear|wearing|"
    r"clothes|clothing|streetwear|fashion|style|styles|styling|sizes?|sizing|orders?|ordered|ordering|"
    r"deliver|delivery|delivered|shipping|ship|shipped|returns?|refunds?|exchanges?|prices?|stock|cart|"
    r"checkout|buy|buying|purchase|discounts?|coupons?|products?|catalog|store|shop|shopping|cartpilot|cod|"
    r"payment|gifts?)\b",
    _I,
)

OFF_TOPIC_PATTERNS = [
    r"\b(write|generate|create|give me|fix|debug|explain)\b[^.\n]{0,30}\b(code|program|script|function|algorithm|regex|sql query|python|javascript|java|c\+\+|html|css)\b",
    r"\b(write|compose|draft)\b[^.\n]{0,20}\b(essay|poem|story|song|lyrics|article|cover letter|resume|cv|thesis|speech|email|tweet)\b",
    r"\b(solve|integrate|differentiate|derivative|integral|equation|homework|assignment|exam)\b",
    r"\bcapital\s+of\b|\bprime\s+minister\b|\bpresident\s+of\b|\belections?\b|\bpolitic(s|al)\b",
    r"\bweather\b|\bforecast\b|\brecipe\b|\bhow\s+to\s+cook\b",
    r"\btranslate\b",
    r"\b(bitcoin|crypto(currency)?|stock\s+market|forex|invest(ment|ing)?)\b",
    r"\b(diagnos(e|is)|symptoms?|medicine|medication|dosage|prescription|legal\s+advice|lawyer|lawsuit)\b",
    r"\b(hack|hacking|malware|virus|exploit|phishing|ddos|bomb|weapon|drugs?)\b",
    r"\b(cricket|football|match)\s+(score|result)s?\b|\bwho\s+won\b",
    r"\btell\s+me\s+a\s+joke\b|\bmeaning\s+of\s+life\b",
]

REFUSALS = {
    "injection": (
        "I can't do that. I'm CartPilot, the shopping assistant for CartPilot Streetwear, and I can't "
        "change my instructions, reveal internal configuration or take on another role. I'm happy to help "
        "you find products, check sizes and stock, or place and track an order."
    ),
    "other_user_data": (
        "Sorry, I can't share or look up other customers' information. For privacy, I can only access "
        "your own orders and saved preferences. Would you like me to check your orders?"
    ),
    "off_topic": (
        "Sorry, that's outside what I can help with. I'm CartPilot, the shopping assistant for CartPilot "
        "Streetwear, so I can help with products, sizing, stock, orders, delivery and returns. What are "
        "you shopping for today?"
    ),
    "too_long": (
        f"That message is too long for me to process (limit {MAX_MESSAGE_CHARS} characters). Could you "
        "send a shorter version of your shopping question?"
    ),
    "empty": "I didn't catch that. What can I help you shop for today?",
}

_INJECTION = [re.compile(p, _I | re.MULTILINE) for p in INJECTION_PATTERNS]
_OTHER_USER = [re.compile(p, _I) for p in OTHER_USER_PATTERNS]
_OFF_TOPIC = [re.compile(p, _I) for p in OFF_TOPIC_PATTERNS]


def _block(reason: str) -> Verdict:
    return Verdict(False, reason, REFUSALS[reason])


def screen(message: str) -> Verdict:
    text = (message or "").strip()
    if not text:
        return _block("empty")
    if len(text) > MAX_MESSAGE_CHARS:
        return _block("too_long")
    if any(p.search(text) for p in _INJECTION):
        return _block("injection")
    if any(p.search(text) for p in _OTHER_USER):
        return _block("other_user_data")
    # Only block off-topic when the message has no shopping words at all.
    if not STORE_WORDS.search(text) and any(p.search(text) for p in _OFF_TOPIC):
        return _block("off_topic")
    return Verdict(True)


# ------------------------------------------------------------- confirmation intent
_AFFIRM = re.compile(
    r"\b(yes|yeah|yep|yup|ya|sure|ok|okay|confirm(ed)?|go\s+ahead|do\s+it|place\s+it|place\s+(the|my)\s+order|"
    r"proceed|absolutely|definitely|correct|haan|han|ji|jee|theek\s+hai|thik\s+hai|kar\s+do|done)\b|^\s*y\s*$|👍",
    _I,
)
_NEGATE_OR_CHANGE = re.compile(
    r"\b(no|nope|nah|not|don'?t|do\s+not|stop|wait|hold|change|instead|but|actually|wrong|nahi|nahin|mat)\b",
    _I,
)


_CANCEL_WORD = re.compile(r"\bcancel", _I)


def is_confirmation(message: str, action: Optional[str] = None) -> bool:
    """True only for an unambiguous 'yes' with no negation or requested change.
    "cancel" counts as a negation, except when confirming a cancellation."""
    text = (message or "").strip()
    if _CANCEL_WORD.search(text) and action != "cancel_order":
        return False
    return (
        bool(_AFFIRM.search(text))
        and not _NEGATE_OR_CHANGE.search(text)
        and "?" not in text
        and len(text) <= 120
    )
