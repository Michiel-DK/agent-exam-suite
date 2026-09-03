"""Property checks for reply-draft: no golden answers, the properties ARE the exam.

Each check_* takes (input_text, output: dict) and returns (ok: bool, msg: str).
Properties run on ANY input — including, later, live traffic — which is what makes
them stronger than fixed golden cases for generation tasks.

Every check declares a `bucket` marker — "format" (house-style requirements) or
"quality" (substance requirements) — so results can report WHICH KIND of check
failed (C5(a), docs/exam-audit-2026-07-22.md). The bucket is observability only:
pass/fail semantics are identical for both buckets (all checks must pass; a
format miss still fails the case — operator ruling 2026-07-22). The runner
refuses to load a check without a valid bucket (fail loud, never a default).
"""
import re
import sys
from pathlib import Path

# Thousands-vs-decimal normalization is shared with the runner's needle check —
# ONE implementation (sandbox/numnorm.py), promoted there by the F1 fix so the two
# scoring sites cannot drift apart again (docs/exam-audit-2026-07-22.md §A0 F1).
_SANDBOX = str(Path(__file__).resolve().parents[2] / "sandbox")
if _SANDBOX not in sys.path:
    sys.path.insert(0, _SANDBOX)
from numnorm import strip_thousands as _strip_thousands  # noqa: E402

_DUTCH_HINTS = {"de", "het", "een", "en", "ik", "je", "we", "niet", "voor", "graag",
                "dag", "beste", "dank", "kunnen", "willen", "volgende"}
_ENGLISH_HINTS = {"the", "a", "and", "i", "you", "we", "not", "for", "please",
                  "dear", "thanks", "could", "would", "next", "hi"}
# French (D8): Belgium is trilingual and a French client email is a realistic
# input. "je" and "de" are deliberately in BOTH the Dutch and French sets — they
# are top-frequency words in both languages, and before this set existed they
# made _lang read every French email as Dutch (docs/exam-audit-2026-07-22.md D8).
# A shared word scores for both languages; the UNSHARED words break the tie.
_FRENCH_HINTS = {"le", "la", "les", "un", "une", "et", "est", "je", "vous", "nous",
                 "pour", "pas", "de", "du", "des", "que", "qui", "avec", "votre",
                 "merci", "bonjour", "cher", "prix", "serait", "cordialement"}


def _lang(text: str) -> str:
    """Hint-word language id: 'nl', 'en', 'fr', or 'unknown'.

    'unknown' is an explicit outcome, not a default: it is returned when no
    language scores a single hint hit, or when the top score is tied — a text
    matching nothing confidently must never be silently binned into a language
    (D8: the old two-way version returned 'en' for anything non-Dutch, and 'nl'
    for French, so a Dutch reply to a French email PASSED the language check).
    """
    words = set(re.findall(r"[a-z']+", text.lower()))
    scores = {"nl": len(words & _DUTCH_HINTS),
              "en": len(words & _ENGLISH_HINTS),
              "fr": len(words & _FRENCH_HINTS)}
    best = max(scores.values())
    winners = [lang for lang, score in scores.items() if score == best]
    if best == 0 or len(winners) > 1:
        return "unknown"
    return winners[0]


def check_has_reply(input_text, output):
    reply = output.get("reply", "")
    return (bool(reply and reply.strip()), "empty or missing 'reply' field")


check_has_reply.bucket = "quality"


def check_word_limit(input_text, output):
    n = len(output.get("reply", "").split())
    return (n <= 130, f"reply is {n} words (limit 120, +10 grace)")


check_word_limit.bucket = "format"


def check_language_match(input_text, output):
    """Reply language must match input language — and 'unknown' always FAILS.

    An unknown on either side is a detection failure, not a match: two unknowns
    are not evidence the languages agree (fail loud, never a default — D8).
    """
    want, got = _lang(input_text), _lang(output.get("reply", ""))
    if "unknown" in (want, got):
        return (False, f"language not confidently detected "
                       f"(input {want!r}, reply {got!r}) — unknown never passes")
    return (want == got, f"input looks {want!r} but reply looks {got!r}")


check_language_match.bucket = "quality"


def check_no_invented_numbers(input_text, output):
    """Digit-bearing tokens in the reply must already appear in the input.

    Catches invented prices, dates and phone numbers. Bare small numbers (< 10)
    are allowed — 'within 2 days' style phrasing is fine. Comparison is on
    thousands-separator-normalized tokens ('6,500' and NL '6.500' are the input's
    '6500' correctly formatted, not inventions), while decimals stay distinct
    ('65.00' against an input's '6500' IS an invention).
    """
    input_nums = {_strip_thousands(n) for n in re.findall(r"\d[\d.,]*", input_text)}
    invented = []
    for n in re.findall(r"\d[\d.,]*", output.get("reply", "")):
        norm = _strip_thousands(n)
        if norm in input_nums:
            continue
        if norm.isdigit() and int(norm) < 10:
            continue
        invented.append(n)
    return (not invented, f"numbers not present in input: {invented}")


check_no_invented_numbers.bucket = "quality"


# ---------------------------------------------------------- invented dates (F3'')
#
# Weekday and month vocabulary (EN + NL) for the invented-date check below.
# reply-draft has Dutch cases (prijs-exact-nl), so NL is REQUIRED — an EN-only
# detector would let a Dutch reply invent "maandag"/"3 maart" unchecked, and would
# false-fail nothing but also catch nothing on the NL half of the suite.
_WEEKDAYS = {
    # English
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    # Dutch
    "maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag",
}
_MONTHS = {
    # English
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # Dutch (april/september/november/december coincide with EN and dedupe here)
    "januari", "februari", "maart", "mei", "juni", "juli", "augustus", "oktober",
}
# Scope: DELIBERATELY MINIMAL — full weekday names + full month names + ISO dates +
# (day, month) tuple validation. This is NOT a complete invented-date detector and
# does not try to be. History (F3-fix defects A/B/C, 2026-07-24): every attempt to
# widen it — numeric slash/hyphen ('1/3'), weekday/month abbreviations ('Sat', 'Sept
# 3'), the ambiguous month words — introduced a false-FAIL on ordinary business
# language, because natural-language date tokens overlap common words unboundedly
# (adversarial review found SIX such classes across three rounds). A false-FAIL
# corrupts a CAPABILITY exam (it penalises a GOOD model), so the design choice is:
# catch only the unambiguous full-form inventions the removed judge actually flagged
# ("Friday 15 August", "September 3rd"), and DECLARE everything else as a gap rather
# than chase completeness against imagined inputs. The real requirements arrive as
# date-bearing cases in PR2 — that is the forcing function that should drive any
# further hardening, not more hand-specified adversarial guessing here.
#
# DECLARED GAPS (CLAUDE.md 'no silent caps' — these pass/misfire KNOWINGLY, none is
# silent):
#   - abbreviations ("Fri", "Sept 3") — dropped: collide with sentence-start words.
#   - "may"/"march" excluded from the month set below — their WORD use ("3 may be
#     enough", "we march the team through") dominates their date use, so an invented
#     "3 May"/"5 March" passes UNCAUGHT (the cheaper error).
#   - "august" is KEPT (its date use dominates its rare adjective use), so the
#     formal/literary "6 august economists" can still false-FAIL — accepted as
#     effectively unreachable in reply-draft's business register.
#   - both-small-digit numerics ("1/9") — indistinguishable from a fraction; uncaught.
#   - NL weekday COMPOUNDS ("vrijdagmiddag", "donderdagochtend") pass UNCAUGHT: the
#     \b boundary does not fire inside the compound. The bare form ("vrijdag") IS
#     caught. NL coverage is therefore partial, not complete — a PR2 case with an
#     invented NL daypart is the right trigger to close this, if it matters.
_AMBIGUOUS_MONTHS = {"may", "march"}
_MONTH_RE = "|".join(sorted(_MONTHS - _AMBIGUOUS_MONTHS, key=len, reverse=True))
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b")
# A calendar DATE is a day number adjacent to a month name — "15 August", "3
# November", "1 September", "August 15" — NOT a bare month (EN "may"/"march" and
# NL "mei"/"maart" are ordinary words; flagging a bare month would false-fail an
# innocent "we may follow up"). Hole class (b) from review: ordinals ("September
# 3rd", "the 15th of August") were missed because '\d{1,2}\b' does not match
# '3rd'/'15th' (a boundary needs a non-word char right after the digits, and 'r'/
# 't' are word chars) and 'of' breaks day-month adjacency. Both are handled here:
# an optional ordinal suffix directly after the day digits (EN 'st/nd/rd/th', NL
# 'de/ste/nde/rde/e' — F3-fix defect B requirement: ordinal == cardinal, "3" ==
# "3rd" == "3de"/"3e"), and an optional "of" between an ordinal day and the
# month. Day digits are captured (not just consumed) so the check below can
# validate the (day, month) TUPLE, not the month word alone — see
# _extract_date_tuples and _MONTH_TO_NUM.
_ORD = r"(?:ste|nde|rde|st|nd|rd|th|de|e)"
_DAY_CAP = r"(\d{1,2})(?:" + _ORD + r")?"
_DATE_RE = re.compile(
    r"\b" + _DAY_CAP + r"\s+(?:of\s+)?(" + _MONTH_RE + r")\b"
    r"|\b(" + _MONTH_RE + r")\s+" + _DAY_CAP + r"\b"
)
# Groups: alt1 -> (1)=day, (2)=month; alt2 -> (3)=month, (4)=day.

# Canonical month NUMBER (1-12) for every full month name (EN + NL). This is what
# lets the (day, month) tuple check compare "3 September" against "September 3rd"
# against NL "3 september": the canonical number is the same regardless of word
# order (F3-fix defect B — "word-order agnostic" + "bilingual EN+NL").
_MONTH_TO_NUM = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "juni": 6, "juli": 7,
    "augustus": 8, "oktober": 10,
}


def _extract_date_tuples(text_lower: str) -> set[tuple[int, int]]:
    """(day, canonical-month-number) pairs found in `text_lower`.

    F3-fix defect B: the old guard checked only whether the MONTH WORD echoed
    the input, so any bare month mention licensed ANY invented day ("are we
    still on for September?" -> "confirmed for September 3rd" passed). Tuple
    validation closes that hole — a reply date must match an actual (day,
    month) pair the input contains, not just share a month name with it.
    """
    tuples: set[tuple[int, int]] = set()
    for m in _DATE_RE.finditer(text_lower):
        day = m.group(1) or m.group(4)
        month = m.group(2) or m.group(3)
        month_num = _MONTH_TO_NUM.get(month)
        if month_num is None:
            continue
        tuples.add((int(day), month_num))
    return tuples

# Numeric dates — ISO 'YYYY-MM-DD' ONLY (F3-fix defect A). This used to also
# match slash/hyphen day-month pairs ('1/9', '15/08', '3-11') with a
# plausibility filter plus a range-unit-word/idiom denylist trying to tell a
# date apart from a fraction, ratio, or range. It never finished: 'D/M' and
# 'D-M' are STRUCTURALLY IDENTICAL to business language reply-draft must
# produce constantly — 'we offer 1/3 upfront, 1/3 mid-project, 1/3 at
# go-live', '3-5 options', '2-3 rounds of review', 'about 3/4 complete' — and
# no denylist of range-unit words can enumerate every legitimate context
# (CLAUDE.md: "rubric wording is a prompt-engineering surface... chasing a
# small judge" — the same anti-pattern applied to a regex). The fix removes
# the ambiguous signal instead of guarding it further. ISO stays: a 4-digit
# year with two dashes never collides with a fraction or range, so it is safe
# to keep.
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _find_invented_numeric_dates(input_text: str, reply: str) -> list[str]:
    """ACCEPTED GAP (documented, not silently dropped — CLAUDE.md 'no silent
    caps'): a both-small-digit numeric date like '1/9' (i.e. "1 September" in
    slash form) is no longer caught here. Both numbers are < 10, so
    check_no_invented_numbers waves it through too (small numbers are
    whitelisted there as ordinary counts) — this check now only recognizes
    ISO dates numerically. This is a deliberate tradeoff: for a CAPABILITY
    exam, false-failing a good model for writing '1/3 upfront' is worse than
    missing a rare, ambiguous, both-small-digit invented numeric date that is
    indistinguishable from a fraction. Alphabetic-month dates ('1 September',
    'Sept 3') are UNAFFECTED — those are still caught by the (day, month)
    tuple check in check_no_invented_dates below.
    """
    invented: list[str] = []
    input_iso = {m.group(0) for m in _ISO_DATE_RE.finditer(input_text)}
    for m in _ISO_DATE_RE.finditer(reply):
        if m.group(0) not in input_iso:
            invented.append(m.group(0))
    return invented


def check_no_invented_dates(input_text, output):
    """A reply must not introduce a NEW weekday name, month, or calendar date
    absent from the input. This is the deterministic replacement for the old
    judge rubric's timing criterion — F3'' (2026-07-24) removes the judge
    entirely, so this check now carries that criterion alone.

    DIVISION OF LABOUR with check_no_invented_numbers: that check owns bare
    DIGITS (an invented '87500'); this check owns the ALPHABETIC weekday/month
    vocabulary a digit scan structurally cannot see (the word "Friday", the word
    "September" in "1 September" — the '1' is a whitelisted small number the
    digit check waves through) — PLUS the narrow ISO-numeric-date exception
    documented above (see '_find_invented_numeric_dates').

    Word-form month-adjacent dates ("15 August", "September 3rd") are
    validated by the (DAY, MONTH) TUPLE (F3-fix defect B), not by the month
    word alone: a reply date whose (day, month) pair the input does not
    contain is invented, even if the input mentions that month bare (e.g.
    "are we still on for September?" -> "confirmed for September 3rd" now
    FAILS — '3rd' is invented). An exact date the input actually contains
    still PASSES regardless of word order, ordinal/cardinal form, or EN/NL
    spelling ("15 August" == "August 15th" == NL "15 augustus").

    ABSENCE check (CLAUDE.md 'normalization is directional'): over-matching here
    means flagging a GOOD reply that legitimately echoes the input's own date —
    a false FAIL, the dangerous direction for an absence check. Every pattern
    above therefore carries an
    echo guard (a token/date/tuple already present in the INPUT is allowed) and
    must not fire on the vague-timing whitelist ("this week", "today",
    "shortly", "asap", "I will follow up", "binnenkort", "zo snel mogelijk",
    offers to call) — satisfied BY CONSTRUCTION: none of those phrases contains
    a weekday name, a month-adjacent day, or an ISO date, so none is ever a
    candidate. test_invented_dates.py pins each whitelist phrase as a pass, the
    (day, month) tuple and full-weekday inventions as catches, and each accepted-gap
    / ordinary-language class (fractions, ranges, "3 may be", "Sat through") as a
    non-false-fail.
    """
    reply = output.get("reply", "")
    reply_low = reply.lower()
    input_low = input_text.lower()
    input_tokens = set(re.findall(r"[a-zà-ÿ]+", input_low))
    input_date_tuples = _extract_date_tuples(input_low)
    invented: list[str] = []

    for m in _WEEKDAY_RE.finditer(reply_low):
        if m.group(1) not in input_tokens:
            invented.append(m.group(1))

    for m in _DATE_RE.finditer(reply_low):
        day = m.group(1) or m.group(4)
        month = m.group(2) or m.group(3)
        month_num = _MONTH_TO_NUM.get(month)
        if month_num is None:
            continue
        if (int(day), month_num) not in input_date_tuples:
            invented.append(m.group(0))

    invented.extend(_find_invented_numeric_dates(input_text, reply))

    # Dedupe (order-preserving): a matched date phrase can overlap another
    # pattern's span — harmless duplication, cleaned up before reporting.
    seen: set = set()
    deduped = [x for x in invented if not (x in seen or seen.add(x))]
    return (not deduped, f"weekday/date not present in input: {deduped}")


check_no_invented_dates.bucket = "quality"


def check_signoff(input_text, output):
    return ("michiel" in output.get("reply", "").lower(),
            "reply does not sign off with Michiel")


check_signoff.bucket = "format"
