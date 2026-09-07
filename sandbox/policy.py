#!/usr/bin/env python3
"""E12 escalation routing: a measured start-tier policy, per task.

    python3 sandbox/runner.py route [--agent X] [--results DIR]
    python3 sandbox/policy.py       [--agent X] [--results DIR]

The question this answers, which `diff` and `taxonomy` cannot: **which tier should
this task START on, and is escalating to a stronger one worth what it costs?**

Contract (each line is a constraint the tests pin):

* **Read-only and offline.** Loads `results/*.json`, calls no model, writes nothing.
  Two runs over the same corpus print byte-identical output. It is a REPORT, not a
  gate — deliberately absent from `check-all`, and it moves no score.
* **It refuses to recommend inside the noise band.** Heldout is single digits per
  exam, so a one-case accuracy difference is not a capability finding. Any set of
  models within `NOISE_BAND_CASES` of the leader comes back `cannot-distinguish`,
  never a pick. Cost may then break it — *equal-accuracy-cheaper* is a sound call,
  *equal-accuracy-better* is not.
* **Every comparative clause is derived from the number printed beside it.** No
  sentence in this module appends a fixed "pays more" / "is behind" / "leads by"
  without inspecting the ratio or gap it describes. Directions come from `cost_move`
  and `gap_phrase`, which decide the WORD from the ROUNDED value they print — so a
  sentence cannot contradict its own figures. (This is the defect that round-tripped
  the first attempt at this lane; see the block comment above `cost_move`.)
* **Every number carries its denominator.** Accuracy is reported as passed/total
  heldout CASES (not a bare score), and the noise band is printed as the actual
  percentage that one case is worth in that cohort.
* **Cohorts, not agents.** Two results files for the same exam are only comparable
  if they scored the SAME case set. `results/` accumulates across exam versions, so
  comparing a 10-case run against a 19-case run of the same exam would be a
  fabricated comparison. Files are grouped by their (case id, split) fingerprint and
  only compared inside a group.
* **Staleness is shown, never assumed away.** Each cohort is diffed against the
  exam's CURRENT `cases.json`; a cohort that no longer matches is labelled STALE with
  the case counts, because a route measured on a retired exam version is a historical
  fact, not a current recommendation.
* **Unknown cost is `cost-unknown`, never 0.** A results file with no
  `metrics_totals`, or one marked `complete: false` (metered calls were burned that
  the total cannot see), is excluded from every cost comparison and named in the
  output. An incomplete total is a FLOOR; ranking it against a complete one would
  invent a saving.
* **Fail loud.** A missing results directory raises. An empty one raises. An
  unreadable file raises (via `taxonomy.load_result_file` — the single shared
  results reader, not a second copy).
* **`insufficient-data`, never a guess.** An agent whose corpus cannot support a
  comparison (no files, or a cohort with a single model) gets an explicit
  `insufficient-data` verdict with the reason. There is no fallback heuristic.

NOTE on normalization: nothing here normalizes anything. Model names, case ids and
check ids are compared as exact strings, and cost is compared as a float. Do not
introduce a shared normalizer between this module's *presence* comparisons (does
this model appear in this cohort) and any absence check elsewhere — that directional
bug has shipped in this repo twice (CLAUDE.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import taxonomy  # noqa: E402  (the single shared results reader)
import stats  # noqa: E402  (A3: Wilson interval + paired sign test, single implementation)

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

# THE primary bar. One heldout case is the smallest difference the instrument can
# express, so a difference of one case is indistinguishable from noise. This is a
# CASE count, deliberately not a percentage: the percentage depends on the cohort's
# heldout size (2 cases -> 50%, 11 cases -> 9%) and is derived per cohort, never
# hardcoded. Injectable so a test can prove this guard — and not something else — is
# what produces a `cannot-distinguish` verdict.
NOISE_BAND_CASES = 1

# A DECLARED JUDGMENT, not a measurement — and printed as one. When the cheapest
# model on tokens is also the fastest, it wins outright and this floor never applies.
# It only bites on a TRADEOFF (cheaper on tokens, slower on the clock): then the token
# saving must clear this multiple to be worth accepting a latency regression for.
# Without it the command recommends swapping a champion out for an 8% token saving
# while running 1.7x slower (expense-categorization, E8-era corpus) — a confident
# verdict on a difference that does not deserve one, on the one axis the report itself
# labels "indicative, not measured".
COST_FLOOR_RATIO = 1.25

CANNOT_DISTINGUISH = "cannot-distinguish"
INSUFFICIENT_DATA = "insufficient-data"
COST_UNKNOWN = "cost-unknown"


# ---------------------------------------------------------------- cost

class Cost(NamedTuple):
    """Per-case cost, or an explicit reason it is unknown. `tokens`/`wall_ms` are
    None exactly when `known` is False — there is no zero-filled variant."""
    known: bool
    tokens: float | None
    wall_ms: float | None
    reason: str  # "" when known


def cost_per_case(data: dict) -> Cost:
    """Results dict -> per-case cost. THE single cost reader (`diff` calls it too).

    Per-case, not per-run: a raw total shifts with case count, so totals from a
    10-case cohort and a 19-case cohort are not comparable figures. Returns
    `known=False` — never a smaller number — whenever the block is absent, marked
    incomplete, or missing a field.
    """
    totals = data.get("metrics_totals")
    n = len(data.get("cases") or [])
    if not n:
        n = (data.get("train", {}).get("total") or 0) + \
            (data.get("heldout", {}).get("total") or 0)
    if not totals:
        return Cost(False, None, None, "no metrics_totals block (run predates "
                                       "cost columns, or every case errored)")
    if not n:
        return Cost(False, None, None, "no cases recorded, so per-case cost is "
                                       "undefined")
    if totals.get("complete") is False:
        unmetered = totals.get("unmetered_cases", "?")
        return Cost(False, None, None,
                    f"metrics_totals marked complete=false ({unmetered} of {n} cases "
                    f"unmetered) — the total is a FLOOR, not a comparable cost")
    tokens, wall = totals.get("total_tokens"), totals.get("wall_ms")
    if tokens is None or wall is None:
        missing = [k for k in ("total_tokens", "wall_ms") if totals.get(k) is None]
        return Cost(False, None, None, f"metrics_totals missing {', '.join(missing)}")
    return Cost(True, tokens / n, wall / n, "")


# -------------------------------------------------- direction-aware comparisons
#
# THE root-cause fix for the defect that round-tripped PR #24. That build printed
#
#   "...costs 0.6x tokens, 0.2x wall — escalating would pay more for no measured gain"
#
# on a real cohort where the alternative was 0.65x the tokens and 5x faster: the ratios
# were computed correctly and a FIXED comparative clause was appended without ever
# looking at them. 35 tests were green because the single fixture on that branch made
# the comparison come out the convenient way.
#
# The rule this section enforces, mechanically: **the direction word is derived from
# the same rounded value that is printed.** Not from a parallel computation, not from
# the branch you happen to be in — from `round(ratio, 2)`, the exact number the reader
# sees. A sentence and its own figure therefore cannot disagree; if the figure is
# 0.65x, the word is FEWER, in every branch, by construction.

RATIO_DP = 2  # printed precision AND the precision the direction is decided at


def _directed(ratio: float, more: str, less: str, same: str) -> tuple[int, str]:
    """(sign, "<figure>x <word>") — sign and figure from ONE rounded value.

    sign is +1/-1/0 for above/below/equal-to-1 AFTER rounding, so a ratio that prints
    as `1.00x` is never described as an increase.
    """
    shown = round(ratio, RATIO_DP)
    if shown > 1:
        return 1, f"{shown:.2f}x {more}"
    if shown < 1:
        return -1, f"{shown:.2f}x {less}"
    return 0, f"{shown:.2f}x {same}"


class CostMove(NamedTuple):
    """The price of moving FROM one model TO another, as a direction plus the figures
    the direction was derived from."""
    known: bool
    direction: str          # cheaper | pricier | mixed | same | COST_UNKNOWN
    text: str               # "0.65x tokens (FEWER) and 0.19x wall (FASTER)"
    token_ratio: float | None
    wall_ratio: float | None
    reason: str = ""        # why unknown; "" when known

    @property
    def savings(self) -> list[str]:
        """The axes that actually improved, as phrases — e.g.
        `["a 35% token saving", "an 81% wall-clock saving"]`.

        Empty unless something got cheaper. `direction == "cheaper"` only requires
        that NEITHER axis got worse and at least ONE improved, so a move can be
        "cheaper" on wall-clock alone with tokens flat: crediting a "0% token saving"
        there would name an axis with no benefit on it, which is the same defect
        class one rounding away. Each figure is derived from the SAME rounded ratio
        `text` prints.
        """
        out = []
        for ratio, label in ((self.token_ratio, "token"),
                             (self.wall_ratio, "wall-clock")):
            if ratio is None:
                continue
            shown = round(ratio, RATIO_DP)
            if shown < 1:
                pct = f"{1 - shown:.0%}"
                # "an 8%", "an 11%", "an 18%", "an 80%" — a report that reads like a
                # typo invites the reader to trust its arithmetic less.
                article = "an" if pct.startswith("8") or pct[:2] in ("11", "18") else "a"
                out.append(f"{article} {pct} {label} saving")
        return out


def cost_move(frm: Cost, to: Cost) -> CostMove:
    """Cost of moving FROM `frm` TO `to`. Never a bare ratio — always a ratio plus the
    word that ratio implies.

    `direction` collapses the two axes: `cheaper` only when neither axis got worse and
    at least one improved, `pricier` only when neither improved and at least one got
    worse, `mixed` when they disagree (which is common — tokens and wall-clock are not
    the same measurement, and the report says so in its own header).
    """
    if not (frm.known and to.known):
        why = frm.reason if not frm.known else to.reason
        return CostMove(False, COST_UNKNOWN,
                        "cost-unknown for at least one side, so the price of this move "
                        "is unmeasured, never assumed", None, None, why)
    t_sign, t_txt = _directed(to.tokens / frm.tokens,
                              "tokens (MORE)", "tokens (FEWER)",
                              "tokens (the same, to 2dp)")
    w_sign, w_txt = _directed(to.wall_ms / frm.wall_ms,
                              "wall (SLOWER)", "wall (FASTER)",
                              "wall (the same, to 2dp)")
    if t_sign == 0 and w_sign == 0:
        direction = "same"
    elif t_sign >= 0 and w_sign >= 0:
        direction = "pricier"
    elif t_sign <= 0 and w_sign <= 0:
        direction = "cheaper"
    else:
        direction = "mixed"
    return CostMove(True, direction, f"{t_txt} and {w_txt}",
                    to.tokens / frm.tokens, to.wall_ms / frm.wall_ms)


def gap_phrase(reference: int, other: int, split: str) -> str:
    """Direction-aware accuracy gap: `other` relative to `reference`, on `split`.

    Same rule as `cost_move`: the word comes from the sign of the number printed
    beside it. A zero gap says LEVEL rather than "0 case(s) BEHIND", and a NEGATIVE
    gap says AHEAD rather than printing a minus sign inside a sentence that has
    already asserted the opposite direction.
    """
    d = reference - other
    if d > 0:
        return f"{d} {split} case(s) BEHIND"
    if d < 0:
        return f"{-d} {split} case(s) AHEAD"
    return f"LEVEL on {split}"


# ---------------------------------------------------------------- corpus

def cohort_key(data: dict) -> tuple:
    """The comparability fingerprint: the exact (case id, split) set that was scored.

    Two runs share a key iff they answered the same questions. Split is part of the
    key because moving a case between splits changes what `heldout` even means.
    """
    return tuple(sorted((str(c.get("id")), str(c.get("split", "train")))
                        for c in data["cases"]))


class Run(NamedTuple):
    """One results file, reduced to what a route decision needs."""
    agent: str
    model: str
    provider: str
    file: str
    train_passed: int
    train_total: int
    heldout_passed: int
    heldout_total: int
    heldout_failed: tuple  # case ids, sorted
    cost: Cost

    @property
    def cost_label(self) -> str:
        if not self.cost.known:
            return COST_UNKNOWN
        return f"{self.cost.tokens:.0f} tok/case, {self.cost.wall_ms:.0f} ms/case"


def to_run(data: dict, file: str) -> Run:
    failed = tuple(sorted(str(c.get("id")) for c in data["cases"]
                          if c.get("split") == "heldout" and not c.get("passed")))
    return Run(
        agent=data["agent"], model=data["model"], provider=data.get("provider", "?"),
        file=file,
        train_passed=data["train"]["passed"], train_total=data["train"]["total"],
        heldout_passed=data["heldout"]["passed"],
        heldout_total=data["heldout"]["total"],
        heldout_failed=failed, cost=cost_per_case(data),
    )


def load_corpus(results_dir: Path) -> list[tuple[tuple, Run]]:
    """[(cohort key, Run)] over every top-level results file. Fails loud on an empty
    or missing directory: an empty policy that reads like a finding is the worst
    possible output of this command."""
    files = taxonomy.find_result_files(results_dir)
    if not files:
        raise ValueError(f"empty results corpus at {results_dir} — nothing to route "
                         f"on. Run `python3 sandbox/runner.py run <agent> --model M` "
                         f"for at least two models per exam first.")
    out = []
    for path in files:
        data = taxonomy.load_result_file(path)
        for key in ("train", "heldout"):
            if not isinstance(data.get(key), dict) or "passed" not in data[key]:
                raise ValueError(f"malformed results file {path}: missing {key} "
                                 f"passed/total — cannot route on it")
        out.append((cohort_key(data), to_run(data, path.name)))
    return out


def resolve_duplicates(runs: list) -> tuple[list, list, list]:
    """(kept, resolved_notes, conflicts) for one cohort.

    `(agent, model)` is NOT unique within a cohort — the corpus carries reruns under
    both the old and the provider-prefixed filename, and they DISAGREE (verified
    2026-07-27: email-triage llama3.1 is train 5/6 in one file and 6/6 in the other).
    Picking arbitrarily would silently decide a route.

    Rule, in order, stated in the output wherever it fires:
      1. Prefer files with a KNOWN cost — independently justified: a run with no
         metrics block cannot participate in a cost comparison anyway.
      2. If that leaves more than one and they AGREE on both splits, take the
         lexicographically first filename (deterministic) and note it.
      3. If they DISAGREE, keep neither. The model is reported as a conflict and
         excluded from ranking — a disagreement between two runs of the same case
         set is exactly the kind of thing a route must not average away.
    """
    by_model: dict[str, list] = {}
    for r in runs:
        by_model.setdefault(r.model, []).append(r)
    kept, notes, conflicts = [], [], []
    for model in sorted(by_model):
        group = sorted(by_model[model], key=lambda r: r.file)
        if len(group) == 1:
            kept.append(group[0])
            continue
        metered = [r for r in group if r.cost.known]
        pool = metered or group
        scores = {(r.train_passed, r.heldout_passed) for r in pool}
        if len(pool) > 1 and len(scores) > 1:
            conflicts.append((model, tuple(
                (r.file, f"train {r.train_passed}/{r.train_total}, "
                         f"heldout {r.heldout_passed}/{r.heldout_total}")
                for r in group)))
            continue
        kept.append(pool[0])
        why = "metered" if metered else "unmetered — no file for it carried metrics"
        dropped = ", ".join(r.file for r in group if r is not pool[0])
        notes.append(f"{model}: {len(group)} files for this case set, kept "
                     f"{pool[0].file} ({why}); dropped {dropped}")
    return kept, notes, conflicts


# ---------------------------------------------------------------- exam staleness

def current_exam_key(agent: str, exams_dir: Path | None = None) -> tuple | None:
    """The CURRENT exam's (case id, split) fingerprint, or None if it isn't on disk."""
    exams_dir = exams_dir or (ROOT / "evals")
    path = exams_dir / agent / "cases.json"
    if not path.exists():
        return None
    exam = json.loads(path.read_text())
    cases = exam["cases"] if isinstance(exam, dict) else exam
    return tuple(sorted((str(c.get("id")), str(c.get("split", "train")))
                        for c in cases))


def staleness(cohort: tuple, current: tuple | None) -> tuple[str, str]:
    """(label, detail). A cohort measured on a retired exam version is a historical
    fact — it is never silently presented as a current recommendation."""
    if current is None:
        return "UNKNOWN-VINTAGE", ("no evals/<agent>/cases.json on disk, so this "
                                   "cohort cannot be dated")
    if cohort == current:
        return "CURRENT", "matches the exam on disk case-for-case"
    gone = len(set(cohort) - set(current))
    added = len(set(current) - set(cohort))
    return "STALE", (f"measured on {len(cohort)} cases; the exam now has "
                     f"{len(current)} ({added} added since, {gone} no longer in it). "
                     f"This is a route for the OLD exam version, not the current one")


# ---------------------------------------------------------------- the policy

class Verdict(NamedTuple):
    agent: str
    status: str                # "routed" | INSUFFICIENT_DATA
    reason: str
    cohort_models: tuple = ()
    cohort_cases: int = 0
    heldout_total: int = 0
    stale_label: str = ""
    stale_detail: str = ""
    accuracy_verdict: str = ""      # CANNOT_DISTINGUISH | "pick"
    accuracy_evidence: str = ""
    contenders: tuple = ()          # model names within the noise band of the leader
    leader: str = ""
    start: str = ""                 # recommended START model, or ""
    start_basis: str = ""           # "cost" | "accuracy" | COST_UNKNOWN
    start_evidence: str = ""
    escalation: str = ""            # "never-escalate" | COST_UNKNOWN | ...
    escalation_evidence: str = ""
    triggers: tuple = ()            # (case_id, passing models) the start model fails
    cost_unknown_models: tuple = ()
    conflicts: tuple = ()
    resolved: tuple = ()
    other_cohorts: tuple = ()
    failure_profile: tuple = ()     # (category, count) for the start model's failures
    current_cohort: tuple = ()      # models measured on the CURRENT cases.json
    current_exam_known: bool = False
    # Whether the CURRENT exam (as opposed to the cohort routed above, which may be a
    # retired case set) has enough measured models to route at all. Its own field, not
    # folded into `status`, because it also selects the cohort (see `cohort_rank`) and
    # because a reader must not see `status: routed` and miss that the route describes
    # a retired exam version.
    current_exam_status: str = ""   # "routable" | INSUFFICIENT_DATA | "unknown"
    champion: str = ""              # agent.yaml's model, for "this is a swap" framing
    champion_note: str = ""         # where the incumbent sits in the measured cohort
    # A3: interval + paired lines, printed under ACCURACY. Annotation only — the
    # noise band above stays the decision rule; these say how wide it really is.
    stats_evidence: tuple = ()


def _pct(n: int, total: int) -> str:
    return f"{n / total:.0%}" if total else "n/a"


def route_agent(agent: str, runs_with_keys: list, current: tuple | None,
                noise_cases: int = NOISE_BAND_CASES,
                failure_categories: dict | None = None,
                champion: str = "") -> Verdict:
    """The whole decision for one exam. Pure function of the corpus rows.

    `noise_cases` is injectable so a test can set it to 0 and prove the noise guard —
    not some other branch — is what turns a pick into `cannot-distinguish`.
    """
    mine = [(k, r) for k, r in runs_with_keys if r.agent == agent]
    if not mine:
        return Verdict(agent, INSUFFICIENT_DATA,
                       "no results files for this exam in the corpus",
                       current_exam_known=current is not None,
                       current_exam_status=("unknown" if current is None
                                            else INSUFFICIENT_DATA),
                       champion=champion)

    by_cohort: dict[tuple, list] = {}
    for key, run in mine:
        by_cohort.setdefault(key, []).append(run)

    # Reported unconditionally, even when the route below comes from a bigger but
    # older cohort: "how much of the CURRENT exam has actually been measured across
    # models" is the question that decides whether the route is actionable today.
    current_models = tuple(sorted({r.model for r in by_cohort.get(current, [])})) \
        if current is not None else ()
    cur_status = ("unknown" if current is None else
                  "routable" if len(current_models) >= 2 else INSUFFICIENT_DATA)

    # Cohort choice, in order: (1) the CURRENT exam's case set whenever two or more
    # models have been measured on it — a route for the exam you actually ship beats
    # a wider route for a retired one; (2) otherwise the cohort with the most
    # comparable models, which is a historical finding and is labelled STALE. Ties go
    # to the larger case set, then to the fingerprint, so the choice is deterministic.
    def cohort_rank(item):
        key, runs = item
        is_current = int(cur_status == "routable" and key == current)
        return (is_current, len({r.model for r in runs}), len(key), key)

    chosen_key, chosen_runs = max(by_cohort.items(), key=cohort_rank)
    kept, resolved, conflicts = resolve_duplicates(chosen_runs)
    others = tuple(sorted(
        (len(k), len({r.model for r in rs}), tuple(sorted({r.model for r in rs})))
        for k, rs in by_cohort.items() if k != chosen_key))
    label, detail = staleness(chosen_key, current)
    heldout_total = kept[0].heldout_total if kept else 0

    if len(kept) < 2:
        why = (f"the chosen cohort ({len(chosen_key)} cases) holds only "
               f"{len(kept)} usable model(s) — routing is a COMPARISON, and there is "
               f"nothing to compare against")
        if conflicts:
            why += (f"; {len(conflicts)} model(s) excluded as conflicting reruns: "
                    + ", ".join(m for m, _ in conflicts))
        if len(by_cohort) > 1:
            why += (f". The corpus holds {len(by_cohort)} incompatible case sets for "
                    f"this exam, which is why they could not be pooled")
        return Verdict(agent, INSUFFICIENT_DATA, why,
                       cohort_models=tuple(sorted(r.model for r in kept)),
                       cohort_cases=len(chosen_key), heldout_total=heldout_total,
                       stale_label=label, stale_detail=detail,
                       conflicts=tuple(conflicts), resolved=tuple(resolved),
                       other_cohorts=others, current_cohort=current_models,
                       current_exam_known=current is not None,
                       current_exam_status=cur_status, champion=champion)
    if not heldout_total:
        return Verdict(agent, INSUFFICIENT_DATA,
                       "the comparable cohort has ZERO heldout cases — a route "
                       "chosen on train scores would be tuned-to-fit",
                       cohort_models=tuple(sorted(r.model for r in kept)),
                       cohort_cases=len(chosen_key), stale_label=label,
                       stale_detail=detail, other_cohorts=others,
                       current_cohort=current_models,
                       current_exam_known=current is not None,
                       current_exam_status=cur_status, champion=champion)

    ranked = sorted(kept, key=lambda r: (-r.heldout_passed, -r.train_passed, r.model))
    leader = ranked[0]
    # THE primary bar: a model is indistinguishable from the leader only if NEITHER
    # split can separate them by more than the noise band. Heldout is the reporting
    # split, but a model that is measurably worse on TRAIN is not indistinguishable —
    # dropping train would let a saturated heldout split hand a cost win to a model
    # the corpus already shows to be worse (email-triage: eight models tie at 4/4
    # heldout while three of them are 4/6 on train).
    train_total = leader.train_total
    contenders = [r for r in ranked
                  if leader.heldout_passed - r.heldout_passed <= noise_cases
                  and leader.train_passed - r.train_passed <= noise_cases]
    one_case = _pct(1, heldout_total)
    # A3 — the width behind the verdict. One interval line per model in the band (the
    # leader first), then a PAIRED line per contender against the leader: only the
    # cases where the two verdicts differ carry information, and the exact sign test
    # on those is the honest p. With one runner-up outside the band (a "pick"), the
    # same paired line is printed for the pick so a 2-case lead on n=18 is never read
    # as more than it is.
    stats_lines = [f"{r.model} {r.heldout_passed}/{heldout_total} heldout "
                   f"[{stats.fmt_ci(r.heldout_passed, heldout_total)}]"
                   for r in contenders]
    stats_lines += [stats.fmt_paired(leader.model, r.model,
                                     set(leader.heldout_failed), set(r.heldout_failed))
                    for r in contenders if r.model != leader.model]
    if len(contenders) == 1:
        runner_up = next(r for r in ranked if r.model != leader.model)
        stats_lines.append(f"{runner_up.model} {runner_up.heldout_passed}/{heldout_total} "
                           f"heldout [{stats.fmt_ci(runner_up.heldout_passed, heldout_total)}]")
        stats_lines.append(stats.fmt_paired(leader.model, runner_up.model,
                                            set(leader.heldout_failed), set(runner_up.heldout_failed)))
        gap = leader.heldout_passed - runner_up.heldout_passed
        train_gap = leader.train_passed - runner_up.train_passed
        acc_verdict = "pick"
        # Which split actually cleared the band is DERIVED, not assumed to be heldout.
        # The leader is the top of the heldout ranking, but a contender can be
        # excluded by the TRAIN arm alone — and then the leader may be level on
        # heldout, or even behind on train, while still being the only contender.
        # Saying "leads by 0 heldout / -3 train cases" would be a comparative clause
        # contradicting its own numbers, which is the defect class this lane exists
        # to close.
        separating = [s for s, d in (("heldout", gap), ("train", train_gap))
                      if d > noise_cases]
        acc_evidence = (f"{leader.model} is the only model outside the "
                        f"{noise_cases}-case noise band of itself: the runner-up "
                        f"{runner_up.model} is "
                        f"{gap_phrase(leader.heldout_passed, runner_up.heldout_passed, 'heldout')}"
                        f" and {gap_phrase(leader.train_passed, runner_up.train_passed, 'train')}"
                        f" ({leader.model} {leader.heldout_passed}/{heldout_total} "
                        f"heldout, {leader.train_passed}/{train_total} train vs "
                        f"{runner_up.model} {runner_up.heldout_passed}/{heldout_total} "
                        f"and {runner_up.train_passed}/{train_total}) — the band is "
                        f"cleared on "
                        + (" and ".join(separating) if separating else "neither split")
                        + f" ({one_case} per heldout case)")
    else:
        spread = leader.heldout_passed - min(r.heldout_passed for r in contenders)
        acc_verdict = CANNOT_DISTINGUISH
        acc_evidence = (f"{len(contenders)} models sit within {spread} heldout case(s) "
                        f"of the leader ({leader.heldout_passed}/{heldout_total}) — "
                        f"one case is {one_case} here, so this instrument CANNOT rank "
                        f"them: " + ", ".join(
                            f"{r.model} {r.heldout_passed}/{heldout_total} heldout, "
                            f"{r.train_passed}/{train_total} train"
                            for r in contenders))

    priced = [r for r in contenders if r.cost.known]
    unpriced = tuple(r.model for r in contenders if not r.cost.known)
    start = start_basis = start_evidence = ""
    if acc_verdict == "pick":
        start, start_basis = leader.model, "accuracy"
        start_evidence = acc_evidence
    elif not priced:
        start_basis = COST_UNKNOWN
        start_evidence = (f"accuracy cannot distinguish these models and NONE of them "
                          f"has a usable cost total, so there is no sound basis for a "
                          f"pick. cost-unknown: " + ", ".join(unpriced))
    else:
        cheapest = min(priced, key=lambda r: (r.cost.tokens, r.cost.wall_ms, r.model))
        dearest = max(priced, key=lambda r: (r.cost.tokens, r.cost.wall_ms, r.model))
        fastest = min(priced, key=lambda r: (r.cost.wall_ms, r.model))
        ratio = dearest.cost.tokens / cheapest.cost.tokens
        # The token ratio is >= 1 by construction here (`dearest` is the max), but the
        # WALL ratio is not — the token-dearest model is routinely the faster one
        # (expense-categorization: 1.08x tokens, 0.60x wall). Printing a bare `0.60x`
        # inside a sentence framed as "the call is made on COST" is the same
        # undirected-comparative defect, so both axes go through `cost_move`.
        spread = cost_move(cheapest.cost, dearest.cost)
        spread_txt = (f"{cheapest.model} at {cheapest.cost_label} vs {dearest.model} "
                      f"at {dearest.cost_label} — moving to {dearest.model} would be "
                      f"{spread.text}")
        if cheapest.model == dearest.model:
            start, start_basis = cheapest.model, "cost"
            start_evidence = (f"only one indistinguishable model carries a usable cost "
                              f"total ({cheapest.model}, {cheapest.cost_label}); the "
                              f"rest are cost-unknown, so it wins by default, not by "
                              f"measurement")
        elif spread.direction == "same":
            # Both axes identical to the printed precision. Naming a "cheapest" here
            # would be a coin flip wearing a number — and the sentence would carry a
            # comparative word next to a 1.00x figure. `diff`'s tiebreak already
            # refuses this exact shape; the policy refuses it the same way.
            start_basis = CANNOT_DISTINGUISH
            start_evidence = (
                f"cost cannot decide either: {spread_txt}. The indistinguishable "
                f"models cost the SAME to {RATIO_DP}dp on both axes, so there is "
                f"nothing to break the accuracy tie with — no start model is "
                f"recommended between them. Grow heldout (E7) before revisiting; see "
                f"the champion line for whether the incumbent is nonetheless beaten")
        elif fastest.model != cheapest.model and ratio < COST_FLOOR_RATIO:
            # Cheapest on tokens, SLOWER on the clock, and the token saving is under
            # the declared floor. Recommending a swap here would trade a measured 7%
            # against an unmeasured 70% — so nothing is recommended, loudly.
            start_basis = CANNOT_DISTINGUISH
            # "saving" only when the printed figure is actually above 1.00 — a 1.00x
            # ratio is a difference of nothing and must not be called a saving.
            gap_word = "saving" if round(ratio, RATIO_DP) > 1 else "difference"
            start_evidence = (
                f"cost cannot decide either. {spread_txt}: the token {gap_word} "
                f"({ratio:.2f}x) is under the declared {COST_FLOOR_RATIO}x floor AND "
                f"the token-cheapest model is NOT the fastest ({fastest.model} runs "
                f"at {fastest.cost.wall_ms:.0f} ms/case vs {cheapest.cost.wall_ms:.0f})"
                f". Accuracy cannot separate these models and neither can cost — no "
                f"start model is recommended between them. Grow heldout (E7) before "
                f"revisiting; see the champion line for whether the incumbent is "
                f"nonetheless beaten")
        else:
            start, start_basis = cheapest.model, "cost"
            start_evidence = (
                f"equal accuracy within the noise band, so the call is made on COST: "
                f"{spread_txt}. Equal-accuracy-cheaper is a sound call; "
                f"equal-accuracy-better is not, which is why no accuracy pick is made "
                f"here")
            if fastest.model != cheapest.model:
                # Tokens and wall time do not always agree. Saying "cheapest" while
                # a peer is faster would hide half of the tradeoff being made.
                start_evidence += (
                    f". TRADEOFF: cheapest-by-tokens is NOT the fastest — "
                    f"{fastest.model} runs at {fastest.cost.wall_ms:.0f} ms/case vs "
                    f"{cheapest.cost.wall_ms:.0f}; the {ratio:.2f}x token saving clears "
                    f"the declared {COST_FLOOR_RATIO}x floor, so the pick optimises "
                    f"tokens with that tradeoff accepted")
        if unpriced:
            start_evidence += (f". NOT ranked on cost (cost-unknown): "
                               + ", ".join(unpriced))

    # The escalation question. `contenders` always contains the accuracy leader, so
    # when the start model is chosen from it the accuracy headroom is bounded by the
    # noise band BY CONSTRUCTION — and that is the finding, not a bug.
    start_run = next((r for r in kept if r.model == start), None)
    peers = [r for r in kept if r.model != start]
    if start_run is None:
        escalation = CANNOT_DISTINGUISH
        esc_evidence = ("no start model was recommended, so there is no baseline to "
                        "escalate FROM — see the START line above for why")
    elif start_run.model == leader.model:
        # Nothing in this cohort scores above the start model, so "escalate" has no
        # measured destination. Name the best alternative and what it would cost, so
        # the claim is checkable rather than an assertion.
        escalation = "no-escalation-target"
        if not peers:
            esc_evidence = (f"{start} is the only usable model in this cohort — there "
                            f"is nothing to escalate to")
        else:
            # Deterministic: `max` alone would resolve a (heldout, train) tie by list
            # position. Same rule as `ranked` — best scores first, then model name.
            best_peer = min(peers, key=lambda r: (-r.heldout_passed, -r.train_passed,
                                                  r.model))
            behind = start_run.heldout_passed - best_peer.heldout_passed
            move = cost_move(start_run.cost, best_peer.cost)
            # THE defect that round-tripped PR #24 was here: "escalating would pay more
            # for no measured gain" was appended as a FIXED string, so on crm-followup
            # — where the alternative is 0.65x tokens and 5x faster — the sentence
            # contradicted the ratios it had just printed. The conclusion is now
            # selected by `move.direction`, which is itself derived from those printed
            # figures. The cheaper case is a real routing call (a DE-ESCALATION trade)
            # and is named as one rather than deleted.
            head = (f"{start} is the measured accuracy leader of this cohort "
                    f"({start_run.heldout_passed}/{heldout_total} heldout), so no model "
                    f"here scores above it and there is nothing to escalate TO. The "
                    f"best alternative, {best_peer.model}, is "
                    f"{gap_phrase(start_run.heldout_passed, best_peer.heldout_passed, 'heldout')}"
                    f" ({best_peer.heldout_passed}/{heldout_total}) and "
                    f"{gap_phrase(start_run.train_passed, best_peer.train_passed, 'train')}"
                    f" ({best_peer.train_passed}/{train_total})")
            if not move.known:
                tail = (f", and its cost cannot be compared with {start}'s "
                        f"({COST_UNKNOWN}: {move.reason}) — so neither direction of "
                        f"this trade is priced, and none is claimed")
            elif move.direction == "pricier":
                # `behind` is >= 0 by construction here (`start` IS the leader), so
                # "no measured accuracy gain" is safe — but it is the *direction*
                # clause that had to be earned, and it now is.
                tail = (f", and moving to it would cost {move.text} — i.e. escalating "
                        f"would pay MORE for no measured accuracy gain")
            elif move.direction == "cheaper":
                tail = (f", and moving to it would be {move.text}. That is a "
                        f"DE-ESCALATION trade, not an escalation: it buys "
                        + " and ".join(move.savings)
                        + " at the price of "
                        + (f"{behind} heldout case(s) ({_pct(behind, heldout_total)})"
                           if behind > 0 else
                           f"a train-split regression ({best_peer.train_passed}/"
                           f"{train_total} vs {start_run.train_passed}/{train_total})")
                        + f". NOT recommended here — accuracy is the primary axis and "
                          f"the loss is outside the {noise_cases}-case noise band — but "
                          f"priced so the trade is visible rather than hidden")
            elif move.direction == "mixed":
                tail = (f", and moving to it is a MIXED trade: {move.text}. The axes "
                        f"disagree, so no single direction is claimed; there is still "
                        f"no measured accuracy gain to escalate FOR")
            else:  # "same"
                tail = (f", and it costs the SAME to {RATIO_DP}dp ({move.text}) — "
                        f"there is nothing to gain on either axis")
            esc_evidence = head + tail
    else:
        delta = leader.heldout_passed - start_run.heldout_passed
        # Same treatment as the branch above. The TOKEN ratio is >= 1 here by
        # construction (`start` is the token-cheapest priced contender and the leader
        # is a priced contender) but the WALL ratio is not: escalating can be faster.
        # "and costs 0.6x wall" would be another undirected comparative.
        move = cost_move(start_run.cost, leader.cost)
        if not move.known:
            cost_txt = (f"{COST_UNKNOWN} on at least one side, so the price of "
                        f"escalating is unmeasured, not assumed ({move.reason})")
        else:
            verb = {"pricier": "costs MORE", "cheaper": "is CHEAPER",
                    "mixed": "is a MIXED trade", "same": "costs the SAME"}[move.direction]
            cost_txt = (f"the move {verb}: {move.text} ({leader.model} "
                        f"{leader.cost_label} vs {start} {start_run.cost_label})")
        escalation = "never-escalate"
        esc_evidence = (f"escalating from {start} to the accuracy leader "
                        f"{leader.model} buys "
                        + (f"+{delta} heldout case(s) of {heldout_total} "
                           f"({_pct(delta, heldout_total)})" if delta > 0 else
                           f"NOTHING on heldout (both at {leader.heldout_passed}/"
                           f"{heldout_total})")
                        + f" — inside the {noise_cases}-case noise band, i.e. not a "
                          f"measured gain — and {cost_txt}")

    # Candidate per-case escalation triggers: heldout cases the start model FAILS that
    # some other model in the same cohort PASSES. Reported separately from the verdict
    # and never allowed to become a pick — n is tiny by construction.
    triggers = []
    if start_run is not None:
        for case_id in start_run.heldout_failed:
            passers = tuple(sorted(r.model for r in kept
                                   if r.model != start
                                   and case_id not in r.heldout_failed))
            if passers:
                triggers.append((case_id, passers))

    # Where the incumbent sits in the measured cohort. This is the one place the
    # report can say "staying put is itself a measured loss" — without it, a
    # `cannot-distinguish` verdict reads as "stay on today's champion" even when the
    # corpus shows that champion beaten by more than the noise band.
    champ_run = next((r for r in kept if r.model == champion), None) if champion else None
    champion_note = ""
    if champion and champ_run is None:
        champion_note = (f"the incumbent {champion} was NOT measured on this case set, "
                         f"so nothing here compares to it")
    elif champ_run is not None:
        behind = leader.heldout_passed - champ_run.heldout_passed
        if champ_run in contenders:
            champion_note = (f"the incumbent {champion} is inside the noise band "
                             f"({champ_run.heldout_passed}/{heldout_total} heldout vs "
                             f"leader {leader.heldout_passed}/{heldout_total}) — this "
                             f"corpus does not show it beaten")
        else:
            # The champion falls out of `contenders` if EITHER split beats it by more
            # than the band, so neither "N heldout cases behind" nor "every contender
            # is ahead of it" may be asserted — both are derived. Pre-fix, a champion
            # excluded by the TRAIN arm alone printed "is 0 heldout cases behind the
            # leader (4/4 vs 4/4, 0%) — OUTSIDE the noise band", which is a sentence
            # arguing against its own figures.
            behind_train = leader.train_passed - champ_run.train_passed
            axes = [name for name, d in (("heldout", behind),
                                         ("train", behind_train)) if d > noise_cases]
            ahead = [r.model for r in contenders
                     if r.heldout_passed > champ_run.heldout_passed]
            level = [r.model for r in contenders
                     if r.heldout_passed == champ_run.heldout_passed]
            under = [r.model for r in contenders
                     if r.heldout_passed < champ_run.heldout_passed]
            parts = []
            if ahead:
                parts.append(f"{len(ahead)} of {len(contenders)} contender(s) are "
                             f"ahead of it on heldout ({', '.join(ahead)})")
            if level:
                parts.append(f"{len(level)} are level with it on heldout and separated "
                             f"only on train ({', '.join(level)})")
            if under:
                parts.append(f"{len(under)} are BELOW it on heldout and in the band "
                             f"only because the leader is ({', '.join(under)})")
            champion_note = (
                f"MEASURED LOSS: the incumbent {champion} is "
                f"{gap_phrase(leader.heldout_passed, champ_run.heldout_passed, 'heldout')}"
                f" and "
                f"{gap_phrase(leader.train_passed, champ_run.train_passed, 'train')} "
                f"versus the leader "
                f"({champ_run.heldout_passed}/{heldout_total} heldout, "
                f"{champ_run.train_passed}/{train_total} train vs "
                f"{leader.heldout_passed}/{heldout_total} and "
                f"{leader.train_passed}/{train_total} for {leader.model}; "
                f"{_pct(behind, heldout_total)} of the heldout split) — beaten by more "
                f"than the {noise_cases}-case noise band on "
                + (" and ".join(axes) if axes else "neither split alone")
                + f", so staying on it is not a neutral default. "
                + "; ".join(parts)
                + f": the actionable call is MOVE OFF the incumbent, even where the "
                  f"data cannot say which contender to move to")

    profile = ()
    if failure_categories and start_run is not None:
        counts = failure_categories.get((agent, start_run.file), {})
        profile = tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    return Verdict(
        agent, "routed", "", tuple(sorted(r.model for r in kept)), len(chosen_key),
        heldout_total, label, detail, acc_verdict, acc_evidence,
        tuple(r.model for r in contenders), leader.model, start, start_basis,
        start_evidence, escalation, esc_evidence, tuple(triggers), unpriced,
        tuple(conflicts), tuple(resolved), others, profile, current_models,
        current is not None, cur_status, champion, champion_note,
        stats_evidence=tuple(stats_lines))


def failure_categories(results_dir: Path) -> dict:
    """{(agent, filename) -> {category: count}} from E9's classifier.

    Reuses `taxonomy.case_findings` rather than re-deriving why a model failed — the
    route's "why" column and the taxonomy report must never be able to disagree.
    """
    out: dict = {}
    for path in taxonomy.find_result_files(results_dir):
        data = taxonomy.load_result_file(path)
        counts: Counter = Counter()
        for case in data["cases"]:
            if case.get("passed") or case.get("split") != "heldout":
                continue
            for finding in taxonomy.case_findings(data, case, path.name):
                counts[finding.category] += 1
        out[(data["agent"], path.name)] = dict(counts)
    return out


def champion_model(agent: str, agents_dir: Path | None = None) -> str:
    """agent.yaml's model, or "" if it cannot be read.

    Decoration, not a decision input: it only lets the report say "this recommends
    moving OFF your current champion". A missing or unreadable agent.yaml therefore
    degrades to an empty string and the report says `champion: unknown`, rather than
    aborting a read-only report over a cosmetic field.
    """
    path = (agents_dir or (ROOT / "agents")) / agent / "agent.yaml"
    if not path.exists():
        return ""
    try:
        import yaml
        return str(yaml.safe_load(path.read_text()).get("model") or "")
    except (OSError, UnicodeDecodeError, ImportError, AttributeError):
        return ""


def route_all(results_dir: Path, agent: str | None = None,
              noise_cases: int = NOISE_BAND_CASES) -> list[Verdict]:
    corpus = load_corpus(results_dir)
    cats = failure_categories(results_dir)
    agents = sorted({r.agent for _, r in corpus}) if not agent else [agent]
    return [route_agent(a, corpus, current_exam_key(a), noise_cases, cats,
                        champion_model(a))
            for a in agents]


# ---------------------------------------------------------------- report

def report_lines(verdicts: list, results_dir: Path,
                 noise_cases: int = NOISE_BAND_CASES) -> list[str]:
    """The whole report, as lines. Pure function of the verdicts — no clock, no
    environment, every loop over a sorted sequence, so it is byte-stable."""
    try:
        where = results_dir.resolve().relative_to(ROOT)
    except ValueError:
        where = results_dir.resolve()
    out = [
        "ESCALATION ROUTING (E12) — read-only report over recorded results. NOT a "
        "gate:",
        "it scores nothing, is not part of check-all, and never calls a model.",
        f"source: {where}/*.json   (results/ is GITIGNORED — this policy describes "
        f"the corpus",
        "on THIS box, and says so rather than implying a universal result)",
        f"noise band: {noise_cases} heldout case. Any accuracy difference at or below "
        f"it is reported",
        f"as {CANNOT_DISTINGUISH} — never as a pick. Cost may still decide: "
        f"equal-accuracy-CHEAPER",
        "is a sound call, equal-accuracy-BETTER is not.",
        "cost caveat: tok/case is deterministic at temp 0 and directly comparable; "
        "ms/case is a",
        "SINGLE run and includes cold model-load, so latency ratios are indicative, "
        "not measured.",
    ]
    for v in sorted(verdicts, key=lambda v: v.agent):
        out += ["", "=" * 78, f"{v.agent}"]
        if v.status == INSUFFICIENT_DATA:
            out += [f"  VERDICT: {INSUFFICIENT_DATA} — {v.reason}"]
            if v.cohort_models:
                out.append(f"  usable models in that cohort: "
                           f"{', '.join(v.cohort_models)}")
            if v.stale_label:
                out.append(f"  cohort vintage: {v.stale_label} — {v.stale_detail}")
            out += _cohort_notes(v)
            continue
        out += [
            f"  cohort: {len(v.cohort_models)} models over {v.cohort_cases} shared "
            f"cases ({v.heldout_total} heldout)",
            f"  vintage: {v.stale_label} — {v.stale_detail}",
            f"  models: {', '.join(v.cohort_models)}",
            "",
            f"  ACCURACY: {v.accuracy_verdict}",
            f"    {v.accuracy_evidence}",
            *[f"    · {line}" for line in v.stats_evidence],
            "",
            f"  START ON: {v.start or '(none — nothing here decides)'}"
            + (f"   [basis: {v.start_basis}]" if v.start_basis else ""),
            f"    {v.start_evidence}",
            _champion_line(v),
            "",
            f"  ESCALATE? {v.escalation}",
            f"    {v.escalation_evidence}",
        ]
        if v.cost_unknown_models:
            out.append(f"  {COST_UNKNOWN}: "
                       f"{', '.join(sorted(v.cost_unknown_models))} — excluded from "
                       f"every cost comparison above, never counted as 0")
        if v.failure_profile:
            prof = ", ".join(f"{c} x{n}" for c, n in v.failure_profile)
            out.append(f"  why the start model still fails (E9 categories, heldout): "
                       f"{prof}")
        if v.triggers:
            out.append(f"  candidate escalation triggers — heldout cases {v.start} "
                       f"fails that a cohort peer passes:")
            for case_id, passers in v.triggers:
                out.append(f"    {case_id:<32} passed by: {', '.join(passers)}   "
                           f"[n=1, single run, INSIDE the noise band — a trigger to "
                           f"replicate, not a route]")
        elif v.start:
            out.append(f"  candidate escalation triggers: none — no cohort peer "
                       f"passes a heldout case {v.start} fails")
        out += _cohort_notes(v)
    return out


def _champion_line(v) -> str:
    """Name the incumbent next to the recommendation. A route that reads "start on X"
    is a very different proposition depending on whether X is already the champion —
    without this the reader cannot tell a confirmation from a proposed swap."""
    if not v.champion:
        return "    champion (agent.yaml): unknown — could not read agents/…/agent.yaml"
    if not v.start:
        return (f"    champion (agent.yaml): {v.champion} — no swap is recommended"
                + (f"\n      {v.champion_note}" if v.champion_note else ""))
    if v.start == v.champion:
        head = (f"    champion (agent.yaml): {v.champion} — the recommendation "
                f"CONFIRMS the incumbent")
    else:
        head = (f"    champion (agent.yaml): {v.champion} — the recommendation is a "
                f"SWAP away from the incumbent, on the evidence above")
    return head + (f"\n      {v.champion_note}" if v.champion_note else "")


def _current_cohort_line(v) -> list[str]:
    """How much of the CURRENT exam has been measured across models — printed even
    when the route above came from a bigger, older cohort. Without it a STALE route
    reads as if it applied to the exam as it stands today."""
    if not v.current_exam_known:
        return ["  current-exam cohort: UNKNOWN — no evals/<agent>/cases.json on disk"]
    if len(v.current_cohort) >= 2:
        return [f"  current-exam cohort: routable — {len(v.current_cohort)} models "
                f"({', '.join(v.current_cohort)})"]
    who = ", ".join(v.current_cohort) if v.current_cohort else "none"
    return [f"  current-exam cohort: {len(v.current_cohort)} model ({who}) — "
            f"{INSUFFICIENT_DATA} to route the exam AS IT STANDS TODAY. Any route "
            f"above describes a retired case set;",
            f"    to route the current exam, run at least two models against it: "
            f"`python3 sandbox/runner.py run {v.agent} --model <M>`"]


def _cohort_notes(v) -> list[str]:
    out = _current_cohort_line(v)
    for note in v.resolved:
        out.append(f"  duplicate-resolved: {note}")
    for model, files in v.conflicts:
        out.append(f"  CONFLICT (excluded): {model} has disagreeing reruns of the "
                   f"same case set —")
        for name, score in files:
            out.append(f"      {name}: {score}")
    for n_cases, n_models, models in v.other_cohorts:
        out.append(f"  other cohort NOT pooled: {n_cases} cases, {n_models} model(s) "
                   f"({', '.join(models)}) — different case set, not comparable")
    return out


# ---------------------------------------------------------------- entry point

def run(args) -> int:
    results_dir = Path(args.results) if getattr(args, "results", None) else RESULTS_DIR
    verdicts = route_all(results_dir, getattr(args, "agent", None))
    print("\n".join(report_lines(verdicts, results_dir)))
    return 0


def add_arguments(sp) -> None:
    sp.add_argument("--agent", help="only this exam")
    sp.add_argument("--results", help="results directory (default: ./results)")
    # Deliberately NO --json: nothing consumes it, and scope-adherence flagged it as
    # surface built ahead of a caller. The report is the deliverable.
    # Deliberately NO --noise-cases flag: the band is injectable in code so tests can
    # isolate the guard, but exposing it on the CLI would make "set it to 0" the
    # obvious way to manufacture a confident-looking route out of thin data.


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(p)
    return run(p.parse_args())


if __name__ == "__main__":
    sys.exit(main())
