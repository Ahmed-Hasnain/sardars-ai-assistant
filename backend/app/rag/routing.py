"""Conservative first-pass routing for internal assistant questions."""

import re
from typing import Literal


AnswerRoute = Literal["general", "company"]
COMPANY_IDENTITY = re.compile(r"\b(?:sardars?|you|your|yours|we|our|ours|us)\b", re.I)
COMPANY_FACT = re.compile(
    r"\b(?:price|pricing|cost|stock|inventory|availability|available|"
    r"return|refund|delivery|shipping|order|showroom|store|catalogue|catalog|"
    r"brand|brands|product|products|warranty|opening hours)\b", re.I
)
GENERAL_EDUCATION = re.compile(
    r"^(?:what is an?\b|what are\b|define an?\b|explain what\b|"
    r"explain an?\b|how (?:does|do)\b.+\bwork\b)", re.I
)
GREETING = re.compile(r"^(?:hi|hello|hey|thanks|thank you)[!. ]*$", re.I)


def route_question(question: str) -> AnswerRoute:
    text = question.strip()
    if COMPANY_IDENTITY.search(text):
        return "company"
    if GREETING.fullmatch(text):
        return "general"
    if GENERAL_EDUCATION.match(text) and not COMPANY_FACT.search(text):
        return "general"
    return "company"
