# glade/classify.py
import re

_BANK_PROVIDERS = r"(chase|wells|wellsfargo|bofa|bank of america|citibank|citi|pnc|usaa|capital ?one|discover|fifth ?third|truist|td|huntington|ally|synchrony|comenity|navy federal|nfcu|credit union)"
_CARD_HINTS      = r"(credit\s*card|visa|mastercard|amex|american express|discover|capital ?one|synchrony|comenity)"
_VEHICLE_HINTS   = r"(vehicle|auto|vin|title|registration|insurance\s*card)"
_UTILITY_HINTS   = r"(utility|electric|water|internet|phone|gas|sewer|trash|cable|bill)"
_LEASE_HINTS     = r"(lease|rental|rent|timeshare)"
_LAWSUIT_HINTS   = r"(lawsuit|summons|complaint|garnish|judgment|v\.\s|vs\.\s)"
_MORTGAGE_HINTS  = r"(mortgage|hoa|homeowner|home owners|association)"
_INCOME_HINTS    = r"(pay\s*stub|paystub|payroll|wage|income)"
_TAX_HINTS       = r"(tax\s*return|return\s*transcript|\b20\d{2}\s+tax|\btax liability)"

def classify_for_checklist(ai_name: str) -> tuple[str, str]:
    """
    Returns (checklist, title)
      checklist ∈ {"initial","additional"}
      title     ∈ {"Personal Info","Bank statements",...}
    """
    s = ai_name or ""
    s_lower = s.lower()

    # --- Initial checklist (ID/DL/SS/Passport) ---
    if re.search(r"\b(id|dl|ss|passport|pass\s*port)\b", s_lower):
        return "initial", "Personal Info"

    # --- Additional checklist buckets ---
    if re.search(_BANK_PROVIDERS, s_lower) or "statement" in s_lower or "bank" in s_lower:
        return "additional", "Bank statements"

    if re.search(_VEHICLE_HINTS, s_lower):
        return "additional", "Vehicle information"

    if re.search(_INCOME_HINTS, s_lower):
        return "additional", "Income"

    if re.search(_TAX_HINTS, s_lower) or "tax return" in s_lower:
        return "additional", "Tax returns"

    if re.search(_LAWSUIT_HINTS, s_lower):
        return "additional", "Lawsuits"

    if re.search(_LEASE_HINTS, s_lower):
        return "additional", "Lease"

    if re.search(_CARD_HINTS, s_lower) or re.search(r"-\d{4}\b", s_lower):
        return "additional", "Credit Card"

    if re.search(_UTILITY_HINTS, s_lower) or "utility" in s_lower:
        return "additional", "Utility"

    if "credit counseling" in s_lower or "certificate of counseling" in s_lower:
        return "additional", "Credit Counseling"

    if re.search(_MORTGAGE_HINTS, s_lower):
        return "additional", "Mortgage/HOA"

    # Default bucket when we can't tell—still goes to Additional
    return "additional", "UnrecognizableDoc"
