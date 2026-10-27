"""Rule-based scan for text addressed to automated reviewers or AI (prompt injection).

Runs on the raw proposal text before and independently of the AI extractor, so a
manipulated extractor cannot hide a hit. Any hit flags the proposal for a human.
"""
import re

PATTERNS = {
    "rank_request": r"\brank\w*\b.{0,40}?\b(first|top|highest|number one|#\s?1)\b",
    "score_request": r"\b(full|maximum|max|perfect|top|highest)\s+(marks|score|scores|points|rating)\b",
    "ignore_instructions": r"\b(ignore|disregard|override|forget)\b.{0,40}?\b(instructions?|rules?|criteria|prompts?|guidelines)\b",
    "addressed_to_machine": r"\b(automated|automatic|ai|llm|machine|model)\s+(review\w*|evaluat\w*|scor\w*|system\w*|assistant\w*|grader\w*)",
    "claimed_approval": r"\bpre[\s-]?(approv|select|qualif)\w*|\balready\s+(been\s+)?approved\b",
    "system_prompt": r"\bsystem\s+prompt\b|\byou\s+are\s+now\b|\bas\s+an\s+ai\b",
}
_COMPILED = {name: re.compile(p, re.IGNORECASE | re.DOTALL) for name, p in PATTERNS.items()}


def scan(text):
    """Return [{'pattern': name, 'match': snippet}] for every hit."""
    return [{"pattern": name, "match": " ".join(m.group(0).split())}
            for name, rx in _COMPILED.items() for m in rx.finditer(text)]


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        with open(path, encoding="utf-8") as fh:
            print(path, scan(fh.read()) or "no hits")
