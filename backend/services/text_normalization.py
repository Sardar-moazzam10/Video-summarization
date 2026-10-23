"""Small upstream filters for obvious ASR control/noise fragments."""
import re

_NOISE_TOKEN = re.compile(r"\[(?:noise|inaudible|music|applause|silence|laughter)\]", re.I)
_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.UNICODE)

def sanitize_asr_fragment(value: object) -> str:
    text = _NOISE_TOKEN.sub(" ", str(value or ""))
    text = " ".join(text.split()).strip(" .,:;!?-–—")
    if not text or _PUNCT_ONLY.fullmatch(text):
        return ""
    return text

def sanitize_asr_items(values, *, min_words: int = 2, limit: int | None = None):
    result = []
    seen = set()
    for value in values or []:
        clean = sanitize_asr_fragment(value)
        if len(clean.split()) < min_words or clean.casefold() in seen:
            continue
        seen.add(clean.casefold())
        result.append(clean)
        if limit is not None and len(result) >= limit:
            break
    return result


def topic_keyphrase(texts):
    """Choose a source-attested phrase instead of a sentence's first words."""
    from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
    filler = set("like just really going know want need okay actually look looks good say said make thing things let's you're you'll i'm working turn left right hey hello yes no sir madam".split())
    stop = set(ENGLISH_STOP_WORDS) | filler
    clean = [sanitize_asr_fragment(t).lower() for t in texts if t]
    if not clean:
        return ""
    try:
        # Keep stop words during n-gram construction, then reject phrases that
        # contain them; removing them first invents phrases never spoken.
        vectorizer = TfidfVectorizer(ngram_range=(2, 3), token_pattern=r"(?u)\b[a-z][a-z'-]+\b")
        matrix = vectorizer.fit_transform(clean)
        terms = vectorizer.get_feature_names_out()
        scores = matrix.sum(axis=0).A1
        def valid(term):
            words = term.split()
            if any(word in stop for word in words):
                return False
            if len(set(words)) <= max(1, len(words) // 2):
                return False
            if words and words[0] in {"i", "you", "we", "they", "turn", "go", "come"}:
                return False
            return any(len(word) >= 4 for word in words)

        candidates = [(float(scores[i]) * len(term.split()) ** 0.5, term)
                      for i, term in enumerate(terms) if valid(term)]
        return max(candidates, default=(0, ""))[1]
    except ValueError:
        return ""


def sanitize_summary_text(text: str) -> str:
    """Clean punctuation spacing artifacts, deduplicate stuttered words, and ensure complete terminal punctuation."""
    if not text or not str(text).strip():
        return ""
    # 1. Clean spacing before punctuation marks (e.g. "output ." -> "output.")
    cleaned = re.sub(r"\s+([.,!?;:])", r"\1", str(text))
    # 2. Fix multiple redundant periods (e.g. ".. " -> ". ")
    cleaned = re.sub(r"\.{2,}", ".", cleaned)
    # 3. Deduplicate immediate stuttered words (e.g. "and and" -> "and", "the the" -> "the")
    cleaned = re.sub(r"\b(and|the|that|in|to|of|is|a|an)\s+\1\b", r"\1", cleaned, flags=re.IGNORECASE)
    # 4. Collapse multi-spaces
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    # 5. Ensure complete sentence termination (do not leave trailing incomplete fragment)
    if cleaned and cleaned[-1] not in ".!?":
        last_punct = max(cleaned.rfind("."), cleaned.rfind("!"), cleaned.rfind("?"))
        if last_punct > 0:
            cleaned = cleaned[:last_punct + 1].strip()
        else:
            cleaned = cleaned + "."
    return cleaned

