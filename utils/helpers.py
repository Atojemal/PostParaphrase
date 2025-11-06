import random
import re


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


def truncate_to_150_words(text: str) -> str:
    words = re.findall(r"\S+", text)
    if len(words) <= 150:
        return text
    return " ".join(words[:150])


def make_invite_code(user_id: str) -> str:
    """Create a simple invite code for a user."""
    return f"invite_{user_id}_{random.randint(1000,9999)}"


def split_paraphrases(text: str, expected: int):
    """
    Robustly split model output into `expected` paraphrases.

    Strategy (in order):
    1. If explicit separator token is present (###PARAPHRASE_SEPARATOR###), split on it.
    2. Use numbered headings (handles patterns like "1:", "1)", "1.", "**Paraphrased Version 1:**", etc.)
    3. Split by double-newlines.
    4. Fallback to approximate chunking.

    Returns a list with length >= expected (may supplement with fallback paraphrases).
    """
    if not text:
        return [fallback_paraphrase(text, i + 1) for i in range(expected)]

    txt = text.strip()

    # 1) Explicit separator (preferred if present)
    sep = "###PARAPHRASE_SEPARATOR###"
    if sep in txt:
        parts = [p.strip() for p in txt.split(sep) if p.strip()]
        if len(parts) >= expected:
            return parts[:expected]
        # if fewer, still return what we have (caller may supplement)
        return parts

    # 2) Numbered headings (handles markdown bold and other prefixes)
    # This regex finds lines that begin a paraphrase block:
    # - optional markdown asterisks/spaces
    # - optional words like "paraphrase", "paraphrased", "version"
    # - a number (1,2,...)
    # - punctuation like :, ), ., -
    heading_re = re.compile(
        r"(?im)^(?:\s*\**\s*(?:paraphrased(?:\s+version)?|paraphrase|version)?\s*)?(\d{1,2})\s*[:\)\-\.]\s*",
        flags=re.MULTILINE,
    )
    matches = list(heading_re.finditer(txt))
    if matches:
        slices = []
        for i, m in enumerate(matches):
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(txt)
            part = txt[start:end].strip()
            # Remove surrounding markdown or leftover headings
            part = re.sub(r"^\s*\**\s*", "", part).strip()
            if part:
                slices.append(part)
        if len(slices) >= expected:
            return [s.strip() for s in slices[:expected]]
        if slices:
            return slices

    # 3) Try splitting by double newline blocks
    parts = [p.strip() for p in re.split(r"\n{2,}", txt) if p.strip()]
    if len(parts) >= expected:
        return parts[:expected]
    if len(parts) > 0:
        return parts

    # 4) Fallback: chunk into approximate equal parts by words
    words = txt.split()
    per = max(1, len(words) // expected)
    out = []
    for i in range(expected):
        chunk = words[i * per: (i + 1) * per]
        out.append(" ".join(chunk).strip() or f"(paraphrase {i + 1})")
    return out


def fallback_paraphrase(prompt: str, idx: int):
    return f"(Fallback paraphrase {idx}) This is a simple rewrite due to API error."