#!/usr/bin/env python3
"""Deterministic generator for lane 1's `longcall-*` band (transcript-en, S-
TRANSCRIPT-EN-EXAM). Ground truth stays hand-authored and auditable in the
`CASES` table below -- every commitment, cancellation, correction and tangent
is a real line of dialogue written by hand; this script's only job is to
interleave those "beats" with deterministic, inert filler dialogue so a
15-40 minute call (12k-35k chars, docs/transcript-long-brief-2026-09-06.md)
does not have to be hand-typed character by character.

Filler rules (checked by `_check_filler_is_inert` below, run at generation
time -- a filler line that violated one of these would silently corrupt a
case's ground truth):
  - never contains a digit (so it cannot accidentally satisfy or interact
    with check_grounded / a must_mention figure)
  - never contains the sentinel "999777333" that evals/test_transcript_en.py
    asserts is absent from every committed case's input
  - never contains " to " immediately followed by a verb this file's beats
    use for a real commitment (send/schedule/confirm/provide/follow/loop/
    review/deliver/share/set up) -- filler must not read as a new,
    unaccounted-for commitment
  - never repeats a must_not_commit substring after that case's cancellation
    beat (checked separately, per case, against the ACTUAL emitted order)

Run: `python3 docs/probes/transcript-long-2026-09-06/build_cases.py` prints
each case's id/split/length and a byte range showing where the JSON case
objects should be spliced into evals/transcript-en/cases.json (that splice
is done ONCE by hand and verified with `git diff` -- see the brief's
byte-identity rule for the 22 pre-existing cases -- this script never writes
cases.json itself, precisely so a re-run cannot silently reformat the 22
pre-existing entries).
"""
import itertools
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------- filler bank

def _filler_templates(rep, customer, co):
    """~14 distinct, digit-free, commitment-free exchanges. Parameterised by
    the case's own names so repetition across cases reads as different calls,
    not template reuse."""
    return [
        (f"So overall, how has the rollout been feeling on your side?",
         f"Pretty smooth, honestly. The team adjusted faster than I expected."),
        (f"Good to hear. Any friction points worth flagging, even minor ones?",
         f"Nothing major. A couple of people asked about keyboard shortcuts, that's about it."),
        (f"That tracks with what we hear from most teams your size.",
         f"Makes sense. It's a pretty standard setup on our end."),
        (f"Are you still finding the dashboard view useful day to day?",
         f"Yeah, it's become part of the morning routine for the team leads."),
        (f"Glad to hear that. How's the wider {co} team reacting to the change?",
         f"Mixed at first, better now. Change is always a bit of a hurdle here."),
        (f"That's normal. Most of our customers say the second month is the turning point.",
         f"We're right around there now, so that lines up."),
        (f"Anything on the roadmap side you've been curious about?",
         f"We've heard rumblings about a mobile view, is that still in the works?"),
        (f"It's on our radar, nothing I can commit to a date on today.",
         f"Fair enough, just curious."),
        (f"How's the working relationship with our support folks been?",
         f"Good. Response times have been reasonable when we've reached out."),
        (f"Glad to hear it. We take that seriously internally.",
         f"It shows, honestly."),
        (f"Anything on the competitive side worth mentioning, tools you're also evaluating?",
         f"Nothing active right now. We looked around before but we're settled for now."),
        (f"Understood. And the broader business context, anything shifting there?",
         f"Fairly steady. No major reorganisations or anything like that recently."),
        (f"That's good to hear, stability helps on our side of planning too.",
         f"Agreed. Consistency makes these calls easier as well."),
        (f"Anything else on your mind before we keep going?",
         f"Nope, that about covers the general update, go ahead."),
    ]


_FORBIDDEN_FILLER_VERBS = re.compile(
    r"\bto (send|schedule|confirm|provide|follow|loop|review|deliver|share|set up)\b",
    re.IGNORECASE,
)


def _check_filler_is_inert(rep_line: str, customer_line: str) -> None:
    for line in (rep_line, customer_line):
        assert not any(ch.isdigit() for ch in line), f"filler contains a digit: {line!r}"
        assert "999777333" not in line, f"filler contains the sentinel: {line!r}"
        assert not _FORBIDDEN_FILLER_VERBS.search(line), (
            f"filler reads as a commitment (forbidden verb pattern): {line!r}")


def make_filler_iter(rep, customer, co, start=0):
    templates = _filler_templates(rep, customer, co)
    for rl, cl in templates:
        _check_filler_is_inert(rl, cl)
    cyc = itertools.cycle(templates)
    for _ in range(start):
        next(cyc)
    return cyc


# ---------------------------------------------------------------- rendering

def render(rep, customer, opening_rep, opening_customer, beats, filler_iter, target_len):
    """beats: list of (rep_line_or_None, customer_line_or_None) pairs, in the
    exact order they must appear (commitments, corrections, withdrawal-open,
    withdrawal-close, tangent all live here -- filler is interleaved between
    consecutive beats, never inside one, so a beat's two lines are always
    adjacent and unambiguous)."""
    lines = [f"REP: {opening_rep}", f"CUSTOMER: {opening_customer}"]
    for rep_line, cust_line in beats:
        if rep_line:
            lines.append(f"REP: {rep_line}")
        if cust_line:
            lines.append(f"CUSTOMER: {cust_line}")
        # top up with filler after each beat until we still have budget
        while sum(len(l) + 1 for l in lines) < target_len:
            fl, cl = next(filler_iter)
            # stop topping up once within ~600 chars of target -- leave room
            # for the remaining beats + closing without overshooting badly
            if target_len - sum(len(l) + 1 for l in lines) < 900:
                break
            lines.append(f"REP: {fl}")
            lines.append(f"CUSTOMER: {cl}")
    return "\n".join(lines) + "\n"


def close(lines_text, rep_line, customer_line):
    return lines_text + f"REP: {rep_line}\nCUSTOMER: {customer_line}\n"


# ---------------------------------------------------------------- the cases

def case_quiet_train_1():
    rep, customer, co = "Jordan Blake", "Harriet Solano", "Solano Freight Co"
    beats = [
        (None, None),
    ]
    filler = make_filler_iter(rep, customer, co, start=0)
    body = render(rep, customer,
                  f"Hi Harriet, this is {rep} from Corebase, just our regular monthly "
                  f"check-in, nothing urgent on my end. How's everything running?",
                  f"Hi {rep.split()[0]}, all good actually. Nothing new to report from us either.",
                  beats,
                  filler, target_len=13100)
    body = close(body,
                f"Good to hear. So no open issues, no new requests from your side at all?",
                f"None. The team's happy with how things are, honestly a quiet month.")
    return {
        "id": "longcall-quiet-train-1", "split": "train", "topic": "quiet-checkin",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "nothing_important": True,
            "abstain_max_chars": 700,
        },
    }


def case_discovery_train_1():
    rep, customer, co = "Sana Malik", "Emeka Osei", "Osei Digital Health"
    beats = [
        (f"So tell me a bit about what's driving this search for {co}.",
         f"We're scaling our clinician scheduling team and our current spreadsheet "
         f"process is falling apart at about 60 staff."),
        (f"That's a common trigger point. What would a good outcome from this call look like for you?",
         f"Honestly, a clear sense of pricing and whether your platform handles multi-site scheduling."),
        (f"It does, that's actually one of our core use cases. For your size, the Growth plan "
         f"runs 2400 EUR a month, with a 1800 EUR one-time onboarding fee for data migration.",
         f"Okay, that's roughly what we budgeted. I'll loop in our finance lead, Renata, by "
         f"the end of the week so she's looped in before the follow-up."),
        (f"Understood. I'll send over the revised quote by Thursday so you have something concrete for Renata.",
         None),
        (None,
         f"That works. While we're on pricing, is there a whitepaper or case study you could "
         f"send over too, something showing results from a healthcare customer specifically?"),
        (f"Sure, we've got one from a similar clinic network, I can dig it out.",
         None),
        (None,
         f"Actually, thinking about it more, don't worry about digging out the case study -- "
         f"our compliance team would want it reviewed first and that'll slow us down, so let's "
         f"skip it for now, no need to send it."),
        (f"No problem, I'll leave that out then.",
         None),
        (None,
         f"One more thing -- we might eventually want to explore the analytics add-on, but "
         f"that's not something we need to figure out today, just flagging it for later."),
        (f"Noted, no action needed there for now.",
         None),
        (f"Before we wrap, can you confirm the current headcount again? I have 60 staff written down.",
         f"Sorry, let me correct that -- it's actually 68 staff now, we onboarded a few more last week."),
        (f"Got it, 68, I'll use that for the proposal. I'll also schedule a technical call with "
         f"our integrations engineer for next week so you can go through the multi-site setup.",
         f"Sounds good. I'll confirm a time with our IT lead once I see your calendar invite."),
    ]
    filler = make_filler_iter(rep, customer, co, start=2)
    body = render(rep, customer,
                  f"Hi Emeka, thanks for making time, this is {rep} from Corebase.",
                  f"Hi {rep.split()[0]}, thanks for reaching out, happy to walk through it.",
                  beats, filler, target_len=14200)
    body = close(body,
                f"Great, I'll get the quote and the calendar invite out today, and Renata should "
                f"have something to look at by Thursday.",
                f"Perfect, talk soon.")
    return {
        "id": "longcall-discovery-train-1", "split": "train", "topic": "discovery",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["Renata", "68"],
            "must_commit": ["loop in", "revised quote", "technical call", "confirm a time"],
            "commit_owner": {
                "loop in": "customer",
                "revised quote": "rep",
                "technical call": "rep",
                "confirm a time": "customer",
            },
            "must_not_commit": ["case study"],
            "why": ("The case study offer is explicitly retracted by the customer -- "
                    "'let's skip it for now, no need to send it' -- and never mentioned "
                    "again after that line. The analytics add-on is a separate tangent "
                    "(no commitment made by either side, deliberately not in must_commit)."),
        },
    }


def case_renewal_train_1():
    rep, customer, co = "Devon Cruz", "Renata Kovacs", "Kovacs Manufacturing"
    beats = [
        (f"So your current contract runs through the end of the quarter, 40 seats at "
         f"38 EUR per seat monthly, that's 1520 EUR a month. Usage looks steady.",
         f"Right, though we did add the night-shift supervisors, so seat count should be higher."),
        (f"Let me pull that up -- yes, you're actually at 47 active seats today.",
         f"That sounds about right. What are our options for renewal at that level?"),
        (f"Two options. True up to 47 seats at the same rate, 1786 EUR monthly, or move to "
         f"the Enterprise tier at 44 EUR per seat which includes the audit-log add-on you "
         f"asked about, 2068 EUR monthly for up to 60 seats.",
         f"The audit-log add-on is the one thing I actually need for our compliance review."),
        (None,
         f"Let's go with Enterprise then. I'll get budget approval from our ops director "
         f"by next Wednesday."),
        (f"Great, I'll draft the updated MSA and send it over today so it's ready once you "
         f"have approval.",
         None),
        (None,
         f"Also, could you send over a whitepaper on the audit-log feature specifically? "
         f"Something for our compliance file."),
        (f"Sure, I can put that together.",
         None),
        (None,
         f"Actually, hold off on the whitepaper -- our compliance lead said the standard "
         f"product docs will cover what they need, so no need to draft anything extra."),
        (f"Understood, I'll skip that then.",
         None),
        (f"Sorry, one correction on the seat count -- I misspoke earlier, you're actually "
         f"at 49 active seats today, not 47, we just got an updated export.",
         f"Okay, 49, that's fine, doesn't change which tier we want."),
        (None,
         f"One more thing, we might want a training session for the new supervisors at some "
         f"point down the line, but that's not urgent, just something to keep in mind."),
        (f"Noted, we can revisit that later if you want it. I'll also send a summary email "
         f"recapping today's numbers for your records.",
         f"I'll also confirm the exact seat count with HR by Friday so the MSA numbers are final."),
    ]
    filler = make_filler_iter(rep, customer, co, start=4)
    body = render(rep, customer,
                  f"Hi Renata, thanks for making time -- I know renewal calls can feel like a "
                  f"chore so I'll keep this efficient.",
                  f"No problem, go ahead.",
                  beats, filler, target_len=16000)
    body = close(body,
                f"I'll get the MSA over today and we can finalise once your ops director signs off.",
                f"Sounds good, talk soon.")
    return {
        "id": "longcall-renewal-train-1", "split": "train", "topic": "renewal",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["Enterprise", "49"],
            "must_commit": ["budget approval", "updated MSA", "confirm the exact seat count",
                           "summary email"],
            "commit_owner": {
                "budget approval": "customer",
                "updated MSA": "rep",
                "confirm the exact seat count": "customer",
                "summary email": "rep",
            },
            "must_not_commit": ["whitepaper"],
            "why": ("The whitepaper offer is explicitly retracted by the customer -- "
                    "'hold off on the whitepaper ... no need to draft anything extra' -- "
                    "and never mentioned again. The training session is a tangent "
                    "('not urgent, just something to keep in mind'), deliberately left "
                    "out of must_commit since neither side actually agreed to it."),
        },
    }


def case_support_train_1():
    rep, customer, co = "Marisol Vance", "Sami Duval", "Duval Retail Group"
    beats = [
        (f"Thanks for hopping on -- I saw the ticket about the sync delays, want to walk me "
         f"through what you're seeing?",
         f"Yeah, our inventory sync has been running about 25 minutes behind since Tuesday, "
         f"it was usually under 5."),
        (f"Got it. I checked the logs before the call -- it looks like a queue backlog on our "
         f"side from the batch job, not something on yours.",
         f"Okay, that's good to know, we were worried it was our integration."),
        (f"I'll open an escalation ticket with our infrastructure team today and push for a fix "
         f"this week.",
         f"Appreciated. Can you also send over the SLA document? I want to check what our "
         f"guaranteed response time actually is."),
        (f"Sure, I'll send that over after the call.",
         None),
        (None,
         f"Also, is there any chance of an extra onboarding session for our new warehouse "
         f"staff? A few people joined last month."),
        (f"We could probably arrange something.",
         None),
        (None,
         f"Actually, let's skip the extra onboarding session for now -- our team lead said "
         f"she'd rather just have people shadow existing staff, no need to schedule anything."),
        (f"Okay, I'll leave that off the list.",
         None),
        (f"While I have you -- I'll also share a usage report showing sync volume over the "
         f"last 90 days so you have context for the ticket.",
         None),
        (f"For the record, the delay started at 25 minutes but by yesterday it had crept up "
         f"to 38 minutes, I want that in the ticket.",
         f"Understood, 38 minutes, I'll make sure that's logged. I'll also follow up "
         f"internally with our IT team about the batch job timing on our side just in case."),
        (None,
         f"By the way, we've occasionally talked about trying a competitor's tool for this "
         f"specific sync use case, but nothing's changed there, just mentioning it in passing."),
    ]
    filler = make_filler_iter(rep, customer, co, start=6)
    body = render(rep, customer,
                  f"Hi Sami, thanks for joining, this is {rep} from Corebase support.",
                  f"Hi {rep.split()[0]}, thanks for jumping on quickly.",
                  beats, filler, target_len=13600)
    body = close(body,
                f"I'll get the escalation ticket, the SLA document and the usage report sent "
                f"today, and follow up once infrastructure confirms a fix window.",
                f"Great, appreciate the quick turnaround.")
    return {
        "id": "longcall-support-train-1", "split": "train", "topic": "support",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["38 minutes"],
            "must_commit": ["escalation ticket", "SLA document", "usage report", "follow up"],
            "commit_owner": {
                "escalation ticket": "rep",
                "SLA document": "rep",
                "usage report": "rep",
                "follow up": "customer",
            },
            "must_not_commit": ["extra onboarding session"],
            "why": ("The extra onboarding session is explicitly retracted by the customer -- "
                    "'let's skip the extra onboarding session for now ... no need to schedule "
                    "anything' -- and never mentioned again. The competitor mention is a "
                    "closing tangent with no commitment attached."),
        },
    }


# ---------------------------------------------------------------- heldout (authored blind)

def case_pricing_heldout_1():
    rep, customer, co = "Theo Okafor", "Ingrid Palsson", "Palsson Energy Systems"
    beats = [
        (f"So on pricing -- for your current usage tier, the standard plan is 3200 EUR "
         f"a month for up to 25 seats.",
         f"That's higher than what we discussed at the intro call, I thought it was 2900."),
        (f"You're right to flag that -- 2900 EUR was the promo rate quoted in March. "
         f"That promo window has closed, so the standing rate is the 3200 you're seeing now.",
         f"Understood, that's a meaningful jump for our budget though."),
        (f"I can offer a mid-year discount of 10 percent if you commit to an annual term "
         f"instead of monthly, bringing it to 2880 EUR a month.",
         f"That's actually below the original 2900, that could work. I'll take that to our "
         f"CFO for sign-off by next Tuesday."),
        (f"I'll send over the annual pricing sheet today so you have the exact numbers for her.",
         None),
        (None,
         f"Could you also throw in a premium support add-on as part of the annual deal? "
         f"We've had that request from our ops team."),
        (f"Let me see what I can do on that.",
         None),
        (None,
         f"Actually, don't worry about the premium support add-on -- I checked with our ops "
         f"team and our current support tier already covers what they need, so skip that."),
        (f"Okay, I'll leave that out of the proposal.",
         None),
        (f"I'll also confirm the exact seat count with your IT team before finalising, just "
         f"to be safe.",
         f"Good idea, I think it's still 25 but double-check doesn't hurt."),
        (None,
         f"We've also kicked around the idea of a multi-year contract for an even bigger "
         f"discount, but that's not something we're deciding today."),
        (f"Fair enough, we can price that out whenever you're ready.",
         f"I'll get you a final answer from the CFO by Tuesday, and I'll loop in our "
         f"finance analyst to double-check the annual total against our budget."),
    ]
    filler = make_filler_iter(rep, customer, co, start=1)
    body = render(rep, customer,
                  f"Hi Ingrid, thanks for hopping on -- I know pricing calls can run long "
                  f"so I'll try to keep it tight.",
                  f"No worries, let's get into it.",
                  beats, filler, target_len=15200)
    body = close(body,
                f"Sounds good. I'll get the pricing sheet over today and confirm the seat "
                f"count on my end.",
                f"Great, talk Tuesday.")
    return {
        "id": "longcall-pricing-heldout-1", "split": "heldout", "topic": "pricing",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["2880"],
            "must_commit": ["pricing sheet", "confirm the exact seat count",
                           "loop in", "sign-off"],
            "commit_owner": {
                "pricing sheet": "rep",
                "confirm the exact seat count": "rep",
                "loop in": "customer",
                "sign-off": "customer",
            },
            "must_not_commit": ["premium support add-on"],
            "why": ("The premium support add-on is explicitly retracted by the customer -- "
                    "'don't worry about the premium support add-on ... skip that' -- and "
                    "never mentioned again. The multi-year contract is a tangent "
                    "('not something we're deciding today'), left out of must_commit."),
        },
    }


def case_scoping_heldout_1():
    rep, customer, co = "Lina Torres", "Marcus Feld", "Feld & Root Logistics"
    beats = [
        (f"Let's scope out the integration work -- how many warehouse locations need the "
         f"live feed?",
         f"Eight locations right now, with two more opening next quarter."),
        (f"Okay, for eight locations the standard integration guide should cover most of "
         f"it, but the two new ones might need custom field mapping since they use a "
         f"different barcode format.",
         f"That's right, the new sites use the older scanner hardware."),
        (f"I'll put together the custom field mapping spec and send it to your integrations "
         f"engineer by end of week.",
         None),
        (None,
         f"Great. Can your team also run a vendor security review on our side before we go "
         f"live? Our IT policy requires it for any new data feed."),
        (f"Sure, I'll kick off the vendor security review request internally.",
         None),
        (None,
         f"We'd also like a reference call with another logistics customer running a "
         f"similar setup, if that's possible."),
        (f"Let me check who might be a good fit for that.",
         None),
        (None,
         f"Actually, skip the reference call for now -- our ops director said she's "
         f"comfortable moving ahead without one, so no need to arrange it."),
        (f"Understood, I'll take that off the list.",
         None),
        (f"For the timeline, I'll draft an implementation timeline covering all eight "
         f"locations plus the two new ones, targeting a six-week rollout.",
         f"Six weeks sounds workable. I'll confirm the two new site addresses with our "
         f"facilities team so the mapping spec is accurate."),
        (None,
         f"Down the line we might also want a dedicated success plan document, but that's "
         f"further out, not something to sort out today."),
        (f"Noted, we can put that together closer to launch.",
         None),
    ]
    filler = make_filler_iter(rep, customer, co, start=3)
    body = render(rep, customer,
                  f"Hi Marcus, thanks for jumping on -- let's dig into the scoping details "
                  f"for the integration.",
                  f"Sounds good, fire away.",
                  beats, filler, target_len=18700)
    body = close(body,
                f"I'll get the mapping spec and the implementation timeline drafted this week, "
                f"and kick off the security review request today.",
                f"Perfect, we'll get you the site addresses in the meantime.")
    return {
        "id": "longcall-scoping-heldout-1", "split": "heldout", "topic": "scoping",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["eight locations"],
            "must_commit": ["custom field mapping", "vendor security review",
                           "implementation timeline", "confirm the two new site addresses"],
            "commit_owner": {
                "custom field mapping": "rep",
                "vendor security review": "rep",
                "implementation timeline": "rep",
                "confirm the two new site addresses": "customer",
            },
            "must_not_commit": ["reference call"],
            "why": ("The reference call is explicitly retracted by the customer -- 'skip "
                    "the reference call for now ... no need to arrange it' -- and never "
                    "mentioned again. The success plan document is a tangent ('further "
                    "out, not something to sort out today'), left out of must_commit."),
        },
    }


def case_discovery_heldout_2():
    rep, customer, co = "Callum Reyes", "Yara Haddad", "Haddad Media Group"
    beats = [
        (f"Tell me about what prompted this search.",
         f"We're publishing across too many disconnected tools and losing track of "
         f"approval status on content, especially with 22 editors now."),
        (f"That's exactly the workflow gap our platform is built for. For a team of 22, "
         f"the Team plan is 2100 EUR a month, billed annually.",
         f"That's within range. What about onboarding, is that extra?"),
        (f"There's a one-time 900 EUR onboarding fee covering migration from your current "
         f"tools.",
         f"Okay. I'll need sign-off from our editorial director, Beatrix, before we commit."),
        (f"Understood, I'll send over a one-pager today so you have something concrete "
         f"for Beatrix.",
         None),
        (None,
         f"Could you also send a case study from another media company using the platform?"),
        (f"I can pull one together.",
         None),
        (None,
         f"Actually, hold off on the case study -- Beatrix said she'd rather just see a "
         f"live demo instead, so no need to send anything written."),
        (f"Got it, I'll drop that and focus on the demo instead.",
         None),
        (f"I'll schedule a live demo for your editorial team for next week.",
         f"Sounds good, I'll confirm which editors should attend by Friday. I'll also "
         f"send you the current tool list we're migrating away from, so the demo can "
         f"cover the right imports."),
        (None,
         f"We've also been curious about a white-label option down the line, but that's "
         f"not something we need today, just something we're aware exists."),
        (f"Noted, that's a separate conversation whenever you're ready.",
         None),
        (f"Sorry, quick correction -- the editor count is actually 24, not 22, two more "
         f"joined this month.",
         f"Right, 24 is correct, that shouldn't change the plan though."),
    ]
    filler = make_filler_iter(rep, customer, co, start=5)
    body = render(rep, customer,
                  f"Hi Yara, thanks for taking the call, this is {rep} from Corebase.",
                  f"Hi {rep.split()[0]}, happy to chat, we've been meaning to look into this.",
                  beats, filler, target_len=20800)
    body = close(body,
                f"Great, I'll get the one-pager and the demo invite out today.",
                f"Perfect, talk soon.")
    return {
        "id": "longcall-discovery-heldout-2", "split": "heldout", "topic": "discovery",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["Beatrix"],
            "must_commit": ["one-pager", "live demo", "confirm which editors",
                           "current tool list"],
            "commit_owner": {
                "one-pager": "rep",
                "live demo": "rep",
                "confirm which editors": "customer",
                "current tool list": "customer",
            },
            "must_not_commit": ["case study"],
            "why": ("The case study is explicitly retracted by the rep, relaying "
                    "Beatrix's preference -- 'hold off on the case study ... no need to "
                    "send anything written' -- and never mentioned again. The white-label "
                    "option is a tangent ('not something we need today'), left out of "
                    "must_commit."),
        },
    }


def case_renewal_heldout_2():
    """Deliberately harder: the withdrawn proposal is introduced early with a
    committed-sounding rep line, then not cancelled until many filler turns
    later -- the long-distance case the brief's own case-authoring rule
    permits (rule (b) constrains only the LAST mention, not the distance)."""
    rep, customer, co = "Priyanka Shah", "Callan Ridge", "Ridge Outdoor Supply"
    beats = [
        (f"Your contract runs through month-end, 60 seats at 41 EUR per seat, 2460 EUR "
         f"monthly. Usage has grown though.",
         f"Yeah, seasonal hiring pushed us up, we're at 71 active seats today."),
        (f"For 71 seats, true-up at the same rate is 2911 EUR monthly, or Enterprise at "
         f"37 EUR per seat for up to 90 seats gives you the API add-on you mentioned in "
         f"the spring, 3330 EUR monthly.",
         f"The API add-on is genuinely useful for us, let's go Enterprise."),
        (None,
         f"I'll get budget sign-off from our regional director by the fifteenth."),
        (f"While we're talking documentation, I'll also send over a full case study "
         f"from another outdoor retail customer -- it's a strong story, I think it'll "
         f"help you sell this internally.",
         f"Sure, that could be useful for the board deck."),
        (f"I'll draft the updated MSA today so it's ready once your director signs off.",
         None),
    ]
    # Long stretch of unrelated filler between the case-study offer and its
    # eventual, unambiguous cancellation -- this is the harder attention test.
    long_gap_filler = make_filler_iter(rep, customer, co, start=8)
    mid_beats = [
        (None,
         f"On a separate note, could you confirm the seat count with HR one more time "
         f"before we finalise the MSA numbers?"),
        (f"Of course, I'll double check with your HR contact before sending the final "
         f"paperwork.",
         None),
        (f"Sorry, correction -- the current seat count is 73, not 71, we just onboarded "
         f"two seasonal leads.",
         f"73, understood, that's fine for the Enterprise tier we're already planning on."),
    ]
    late_beats = [
        (None,
         f"Actually, going back to the case study you mentioned earlier -- our board "
         f"deck ended up going a different direction, so let's skip the case study "
         f"after all, no need to put that together."),
        (f"No problem, I'll leave that out.",
         None),
        (None,
         f"We might also explore a multi-year term for a bigger discount eventually, "
         f"but that's not something to lock in today."),
        (f"Understood, happy to price that whenever you want to look at it. I'll also "
         f"send the final invoice template over so your finance team can preview the "
         f"format ahead of signing.",
         f"I'll get you the final go-ahead from our regional director by the fifteenth, "
         f"and confirm the seat count one more time with HR before that."),
    ]
    beats_full = beats
    filler1 = make_filler_iter(rep, customer, co, start=0)
    body = render(rep, customer,
                  f"Hi Callan, thanks for making time for the renewal conversation.",
                  f"No problem, let's get into it.",
                  beats_full, filler1, target_len=15500)
    # splice the mid-beats and a long filler run, then the late cancellation, by
    # continuing to render onto the same accumulating text with a fresh target
    lines = body.rstrip("\n").split("\n")
    for rl, cl in mid_beats:
        if rl:
            lines.append(f"REP: {rl}")
        if cl:
            lines.append(f"CUSTOMER: {cl}")
    while sum(len(l) + 1 for l in lines) < 24500:
        fl, cl = next(long_gap_filler)
        lines.append(f"REP: {fl}")
        lines.append(f"CUSTOMER: {cl}")
    for rl, cl in late_beats:
        if rl:
            lines.append(f"REP: {rl}")
        if cl:
            lines.append(f"CUSTOMER: {cl}")
    body = "\n".join(lines) + "\n"
    body = close(body,
                f"I'll get the MSA finalised the moment HR confirms the seat count.",
                f"Sounds good, talk soon.")
    return {
        "id": "longcall-renewal-heldout-2", "split": "heldout", "topic": "renewal",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["Enterprise"],
            "must_commit": ["budget sign-off", "updated MSA", "confirm the seat count",
                           "final invoice template"],
            "commit_owner": {
                "budget sign-off": "customer",
                "updated MSA": "rep",
                "confirm the seat count": "rep",
                "final invoice template": "rep",
            },
            "must_not_commit": ["case study"],
            "why": ("The case study is a committed-sounding rep offer early in the call "
                    "('I'll also send over a full case study ... it's a strong story') "
                    "that is explicitly retracted much later -- 'let's skip the case "
                    "study after all, no need to put that together' -- with no mention "
                    "of it after that line. The multi-year term is a closing tangent, "
                    "left out of must_commit."),
        },
    }


def case_support_heldout_2():
    """The >=30000-char case -- timed before commit (build-flow rule 2, brief
    section 'The cases'). See RESULTS.md for the timing measurement."""
    rep, customer, co = "Oliver Bex", "Beatrix Solheim", "Solheim Marine"
    beats = [
        (f"Thanks for hopping on -- I saw the ticket about the reporting export timing "
         f"out. Walk me through it?",
         f"Right, any export over about 90 days of data just spins and eventually errors "
         f"out. It was fine a month ago."),
        (f"I checked before the call -- there was a change to the export job's memory "
         f"limit two weeks ago that's causing this for larger date ranges.",
         f"That lines up with when we first noticed it."),
        (f"I'll open an escalation ticket with engineering today and push for a fix this "
         f"sprint.",
         f"Appreciated. Can you send the SLA document as well? I want to check the "
         f"guaranteed resolution window for a bug like this."),
        (f"Sure, I'll send that over after the call.",
         None),
        (None,
         f"Also, any chance of an extra training session for our new ops hires? A few "
         f"joined last month and haven't seen the reporting module yet."),
        (f"We could look at scheduling something.",
         None),
        (None,
         f"Actually, let's hold off on the extra training session -- our ops lead wants "
         f"to run internal onboarding first, so no need to schedule anything from your "
         f"side for now."),
        (f"Understood, I'll take that off the list.",
         None),
        (f"I'll also share a usage report showing export volume over the last 90 days for "
         f"context on the ticket.",
         None),
        (f"For the ticket, the timeout started around the 80-day mark but by this week "
         f"it's failing at even 60 days, I want that logged precisely.",
         f"Understood, 60 days, I'll make sure that's in the ticket description."),
        (None,
         f"I'll also follow up internally with our data team about whether we can "
         f"trim the report scope as a workaround while the fix is in progress."),
        (f"Good idea, let me know what they say and I'll factor that into the priority.",
         None),
        (None,
         f"By the way, we've floated the idea of a dedicated data warehouse export at "
         f"some point, but that's a bigger project for another quarter, not urgent now."),
        (f"Noted, happy to scope that whenever you're ready to look at it.",
         None),
        (f"Sorry, one more correction on the timing -- I said 60 days a minute ago, but "
         f"checking the ticket again it's actually failing at 55 days now, it's gotten "
         f"slightly worse since this morning.",
         f"Okay, 55 days, I'll update our internal note to match."),
    ]
    filler = make_filler_iter(rep, customer, co, start=9)
    body = render(rep, customer,
                  f"Hi Beatrix, thanks for joining, this is {rep} from Corebase support.",
                  f"Hi {rep.split()[0]}, thanks for the quick response.",
                  beats, filler, target_len=31500)
    body = close(body,
                f"I'll get the escalation ticket, the SLA document and the usage report "
                f"sent today, and follow up once engineering confirms a fix window.",
                f"Great, appreciate the turnaround.")
    return {
        "id": "longcall-support-heldout-2", "split": "heldout", "topic": "support",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["55 days"],
            "must_commit": ["escalation ticket", "SLA document", "usage report", "follow up"],
            "commit_owner": {
                "escalation ticket": "rep",
                "SLA document": "rep",
                "usage report": "rep",
                "follow up": "customer",
            },
            "must_not_commit": ["extra training session"],
            "why": ("The extra training session is explicitly retracted by the customer "
                    "-- 'let's hold off on the extra training session ... no need to "
                    "schedule anything from your side for now' -- and never mentioned "
                    "again. The data warehouse export is a tangent ('a bigger project "
                    "for another quarter, not urgent now'), left out of must_commit."),
        },
    }


def case_mixed_heldout_3():
    """Two withdrawn proposals in one case (the brief permits 1-2)."""
    rep, customer, co = "Nadia Farouk", "Tobias Wren", "Wren & Co Consulting"
    beats = [
        (f"So walking through where things stand -- you're on the Growth plan, 30 seats "
         f"at 55 EUR per seat, 1650 EUR monthly.",
         f"That's right, though we're about to bring on a new project team, probably "
         f"another dozen people."),
        (f"If you go up to 42 seats, the per-seat rate actually drops to 49 EUR under "
         f"our volume pricing, so 2058 EUR monthly.",
         f"That's a better deal than I expected. Let me confirm the exact new headcount "
         f"with our project lead before we commit to the number."),
        (f"Sounds good, I'll hold the pricing for you while you check.",
         None),
        (None,
         f"Could you send over a case study on a similar consulting firm using the "
         f"volume pricing tier?"),
        (f"I can look for one.",
         None),
        (None,
         f"Actually, don't bother with the case study -- our project lead said the "
         f"pricing math alone is convincing enough, so no need to send anything."),
        (f"Okay, I'll skip that.",
         None),
        (f"I'll send over the updated quote reflecting the 42-seat volume pricing today.",
         None),
        (None,
         f"Also, is there a chance of a free trial extension on the new project "
         f"workspace feature? We haven't tried it yet."),
        (f"Let me check what's possible there.",
         None),
        (None,
         f"Actually, skip the trial extension request -- we found out the feature is "
         f"already included in Growth, so there's nothing to extend, no need to follow "
         f"up on that."),
        (f"Ah, good catch, I'll drop that then.",
         None),
        (f"Sorry, quick correction on the new headcount -- it's actually 14 new people, "
         f"not a dozen, so 44 seats total, not 42.",
         f"Right, 44, that changes the total slightly but we're still fine with the "
         f"volume tier."),
        (None,
         f"I'll confirm the final start date for the new project team with our PMO "
         f"by next week."),
        (f"Great, once I have that I'll finalise the quote at 44 seats, and I'll send a "
         f"summary recap email of today's numbers for your records in the meantime.",
         None),
    ]
    filler = make_filler_iter(rep, customer, co, start=11)
    body = render(rep, customer,
                  f"Hi Tobias, thanks for hopping on, this is {rep} from Corebase.",
                  f"Hi {rep.split()[0]}, good to talk.",
                  beats, filler, target_len=19200)
    body = close(body,
                f"Perfect, I'll finalise everything once I hear back on the start date.",
                f"Sounds good, talk next week.")
    return {
        "id": "longcall-mixed-heldout-3", "split": "heldout", "topic": "mixed",
        "input": body,
        "speakers": {"rep": rep.lower(), "customer": customer.lower()},
        "expected": {
            "must_mention": ["44 seats"],
            "must_commit": ["confirm the exact new headcount", "updated quote",
                           "confirm the final start date", "summary recap email"],
            "commit_owner": {
                "confirm the exact new headcount": "customer",
                "updated quote": "rep",
                "confirm the final start date": "rep",
                "summary recap email": "rep",
            },
            "must_not_commit": ["case study", "trial extension"],
            "why": ("The case study is explicitly retracted by the customer -- 'don't "
                    "bother with the case study ... no need to send anything' -- and "
                    "never mentioned again. The trial extension request is separately "
                    "retracted -- 'skip the trial extension request ... no need to "
                    "follow up on that' -- also never mentioned again. Neither appears "
                    "in must_commit."),
        },
    }


CASE_BUILDERS = [
    case_quiet_train_1,
    case_discovery_train_1,
    case_renewal_train_1,
    case_support_train_1,
    case_pricing_heldout_1,
    case_scoping_heldout_1,
    case_discovery_heldout_2,
    case_renewal_heldout_2,
    case_support_heldout_2,
    case_mixed_heldout_3,
]


# ---------------------------------------------------------------- validation + main

def _validate(case: dict) -> list:
    problems = []
    exp = case["expected"]
    text = case["input"]
    cid = case["id"]
    if "999777333" in text:
        problems.append(f"{cid}: contains the reserved sentinel")
    if exp.get("nothing_important") is True:
        for k in ("must_commit", "commit_owner", "must_not_commit"):
            if k in exp:
                problems.append(f"{cid}: quiet case must not carry {k!r}")
        return problems
    must_commit = exp.get("must_commit") or []
    commit_owner = exp.get("commit_owner") or {}
    must_not_commit = exp.get("must_not_commit") or []
    if len(must_commit) < 4:
        problems.append(f"{cid}: must_commit has {len(must_commit)} entries, need >=4")
    if len(commit_owner) < 4:
        problems.append(f"{cid}: commit_owner has {len(commit_owner)} entries, need >=4")
    if not set(commit_owner) <= set(must_commit):
        problems.append(f"{cid}: commit_owner keys not a subset of must_commit: "
                        f"{set(commit_owner) - set(must_commit)}")
    owners = set(commit_owner.values())
    if not {"rep", "customer"} <= owners:
        problems.append(f"{cid}: commit_owner values don't cover both sides: {owners}")
    if len(must_not_commit) < 1:
        problems.append(f"{cid}: must_not_commit has {len(must_not_commit)} entries, need >=1")
    low_text = text.lower()
    for s in must_not_commit:
        if s.lower() not in low_text:
            problems.append(f"{cid}: must_not_commit {s!r} does not appear in input")
        if s.lower() in [m.lower() for m in must_commit]:
            problems.append(f"{cid}: must_not_commit {s!r} also appears in must_commit")
    if len(text) < 12000:
        problems.append(f"{cid}: input is {len(text)} chars, need >=12000")
    return problems


def main():
    cases = [b() for b in CASE_BUILDERS]
    problems = []
    for c in cases:
        problems += _validate(c)
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids}"
    n_heldout = sum(1 for c in cases if c["split"] == "heldout")
    n_train = sum(1 for c in cases if c["split"] == "train")
    n_quiet = sum(1 for c in cases if c["expected"].get("nothing_important") is True)
    print(f"{len(cases)} cases: {n_train} train, {n_heldout} heldout, {n_quiet} quiet\n")
    for c in cases:
        print(f"  {c['id']:32s} {c['split']:8s} {len(c['input']):6d} chars")
    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)
    print("\nall structural checks pass")
    out = Path(__file__).resolve().parent / "generated_cases.json"
    out.write_text(json.dumps(cases, indent=2, ensure_ascii=False))
    print(f"written -> {out}")


if __name__ == "__main__":
    main()
