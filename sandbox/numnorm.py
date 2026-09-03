"""Thousands-separator normalization — the ONE shared implementation (F1).

PR #11 built this logic for C3 inside evals/reply-draft/properties.py, then its own
`_needle_matches` fix (C4) reused `_norm_digits` instead — the helper the PR1a brief
said must never be used for numeric comparison, because it strips ',' and '.'
indiscriminately: `_norm_digits('65,00') == '6500'`, so a European comma-decimal for
SIXTY-FIVE passed a needle check for six-and-a-half thousand (F1 in
docs/exam-audit-2026-07-22.md §A0). Promoted here so runner.py and properties.py
share one implementation instead of drifting apart again.

Semantics: remove THOUSANDS SEPARATORS ONLY — never a decimal point.
Anything not matching the unambiguous grouped shape is returned UNCHANGED
(fail closed): an unnormalized token can only make an absence check flag MORE and
a presence check match LESS, which is the safe direction for both.
"""
import re

# Digit-grouped number: 1-3 leading digits, then groups of EXACTLY 3 behind one
# consistent separator ("6,500", "6.500", "1,234,567"). Optionally a decimal part of
# 1-2 digits behind the OTHER separator ("1,234,567.89"). A group of exactly 3 after
# a separator is a thousands separator in both locales (NL "6.500" = EN "6,500" =
# six thousand five hundred); 1-2 digits after a separator is a decimal ("65.00").
GROUPED = re.compile(r"\d{1,3}([.,])\d{3}(?:\1\d{3})*")
GROUPED_DEC = re.compile(r"\d{1,3}([.,])\d{3}(?:\1\d{3})*([.,])\d{1,2}")


def strip_thousands(tok: str) -> str:
    """Remove THOUSANDS SEPARATORS ONLY — never a decimal point.

    '6,500' -> '6500', NL '6.500' -> '6500', '1,234,567.89' -> '1234567.89';
    '65.00' stays '65.00' (a decimal — sixty-five, not 6500) and '1.5' stays '1.5'.
    Anything not matching the unambiguous grouped shape is returned UNCHANGED (fail
    closed). Do NOT swap this for runner._norm_digits — that strips '.' and ','
    entirely, so an invented '65.00' would be judged already-present against an
    input containing '6500', and an answer's '65,00' would match an expected
    '6500' (see the C3 warning and F1 in docs/exam-audit-2026-07-22.md).
    """
    tok = tok.rstrip(".,")  # trailing separator is sentence punctuation, not data
    m = GROUPED_DEC.fullmatch(tok)
    if m and m.group(1) != m.group(2):
        return tok.replace(m.group(1), "")
    m = GROUPED.fullmatch(tok)
    if m:
        return tok.replace(m.group(1), "")
    return tok
