"""Rule-based fit scoring: hard filters, then nine factors (0-100 each) blended with text similarity.

Pure functions, no database: `score_job` takes what the service gathered and returns a verdict. A factor
the job says nothing about (no salary, no skills, an alert with only a title) is left out and the remaining
weights are scaled up, so a thin alert is judged on what it does say. The result is marked provisional
until the full description is in.
"""

import re
from dataclasses import dataclass, field, replace

from app.modules.matching import requirements as rq
from app.modules.matching import skills as sk
from app.modules.matching import taxonomy as tx
from app.modules.profiles.schemas import DEFAULT_WEIGHTS, FACTORS, SENIORITY

# Cosine similarity (Voyage) mapped to 0-100: below LOW reads as unrelated, above HIGH as a close fit.
SIM_LOW, SIM_HIGH = 0.40, 0.65  # calibrated on real resumes vs alert jobs: unrelated ~0.42, close ~0.62+
SIM_WEIGHT = 0.35  # share of the final score that similarity carries when an embedding is available
# Another line of work, a primary skill the resumes don't show (SAP, Oracle Apps, Salesforce, embedded…) or a
# different domain: at most 40 (user, 2026-11-11; were 45, 55 and 65).
CLASH_CAP = 40  # highest score for a job in an unrelated family (see family_clash)
SPECIALISM_CAP = 40  # highest score for a specialist job the resumes don't show (see specialism_clash)
INDUSTRY_CAP = 40  # highest score for a job asking for industry experience no resume shows (industry_gap)
NOT_A_FIT_CAP = 40  # highest score for a job the user marked not a fit
TRACK_ROLE = 40  # highest Role factor for a hands-on role when the candidate leads teams (see other_track)
# Each skill the job asks for that no resume or the profile shows costs this much, up to MISSING_SKILLS_MAX
# (user feedback 2026-11-06: two missing skills on a 15%-weight factor cost under a point, so the job showed 100).
MISSING_SKILL_POINTS = 3
MISSING_SKILLS_MAX = 15
# Must-haves (user feedback 2026-11-16): each requirement under a requirements heading the resume doesn't show costs
# MUST_POINTS (half when partly shown), up to MUST_MAX; a PhD the job requires and no resume shows caps the score.
MUST_POINTS = 4
MUST_MAX = 20
DEGREE_CAP = 55


@dataclass
class JobInput:
    title: str
    company: str | None
    location: str | None
    work_model: str | None
    experience: str | None
    salary: str | None
    skills: list[str]
    text: str  # everything known about the job, for themes and domains
    full_description: bool
    not_a_fit: bool = False  # the user marked the job not a fit (a gap they can't close)
    learned: str | None = None  # a learned preference it falls under ("Jobs at Okta"): feedback/learning.py
    years_short: float = (
        0  # share taken off: a job at the user's level asking for fewer years (learning.years_cut)
    )
    # The description's requirements by section (requirements.read): must-haves score, preferred ones don't.
    must: list[rq.Item] = field(default_factory=list)
    preferred: list[rq.Item] = field(default_factory=list)


@dataclass
class Candidate:
    years: int | None
    level: int | None  # seniority of the current role (1-9)
    families: set[str]
    locations: list[str]  # current location, when no search profile names any
    expected_ctc_lakh: float | None
    domains: list[str]
    track: str | None = None  # "lead" or "ic", from the current role (taxonomy.track)


@dataclass
class ProfileInput:
    id: str | None
    name: str
    target_roles: list[str]
    locations: list[str]
    work_models: list[str]
    min_seniority: int
    excluded_companies: list[str]
    weights: dict[str, int]
    threshold: int
    skills: list[str] = field(
        default_factory=list
    )  # the profile's key skills: the resume's and the added ones
    resume_id: str | None = None  # a resume's own match profile; None: matched with every resume
    added_skills: list[str] = field(default_factory=list)  # added by the user: skills they have


@dataclass
class ResumeInput:
    id: str
    label: str
    text: str  # lower-cased
    skills: set[str]
    similarity: float | None  # cosine with the job, when both have embeddings


@dataclass
class ResumeScore:
    resume_id: str
    label: str
    score: int
    factors: dict[str, int]
    reason: str
    lost: dict[str, int] = field(default_factory=dict)  # see points_lost
    skills_have: list[str] = field(default_factory=list)
    skills_missing: list[str] = field(default_factory=list)
    key_skills_found: list[str] = field(default_factory=list)  # the profile's key skills the job asks for
    profile_id: str | None = None  # the match profile the resume was judged with
    must: list[rq.Check] = field(default_factory=list)  # each must-have, shown or not
    preferred: list[rq.Check] = field(default_factory=list)  # preferred only: never cost points


@dataclass
class Verdict:
    band: str  # strong | good | low | filtered
    score: int
    profile_id: str | None
    filter_reason: str | None
    ranking: list[ResumeScore]
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    provisional: bool = True


DEFAULT_PROFILE = ProfileInput(
    id=None,
    name="Your profile",
    target_roles=[],
    locations=[],
    work_models=[],
    min_seniority=1,
    excluded_companies=[],
    weights=dict(DEFAULT_WEIGHTS),
    threshold=85,
)


# --- Parsing the job's facts ------------------------------------------------------------------------------


def years_range(experience: str | None) -> tuple[int, int] | None:
    nums = [int(n) for n in re.findall(r"\d{1,2}", experience or "")]
    if not nums:
        return None
    return (nums[0], nums[1]) if len(nums) > 1 else (nums[0], nums[0] + 5)


def lakh(amount: str | None) -> float | None:
    """'₹5M-₹6M / year' → 60.0, '85 LPA' → 85.0, '1.1 Cr' → 110.0: the top of a range, in lakh a year."""
    s = (amount or "").lower().replace(",", "")
    best = None
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(cr|crore|m|mn|million|l|lakh|lakhs|lpa|k)?\b", s):
        v = float(num)
        if unit in ("cr", "crore"):
            v *= 100
        elif unit in ("m", "mn", "million"):
            v *= 10
        elif unit == "k":
            v /= 100
        elif unit not in ("l", "lakh", "lakhs", "lpa"):
            v = v / 100_000 if v >= 100_000 else v
        best = v if best is None else max(best, v)
    return round(best, 1) if best is not None else None


# --- Hard filters ---------------------------------------------------------------------------------------


def hard_filter(job: JobInput, p: ProfileInput) -> str | None:
    """Why this profile rules the job out, or None. Unknown facts never rule a job out."""
    company = (job.company or "").lower()
    for ex in p.excluded_companies:
        if ex.strip() and ex.strip().lower() in company:
            return f"{job.company} is on your excluded list"
    if p.locations:
        wanted = {c for loc in p.locations for c in tx.cities(loc)[0]}
        remote_ok = "Remote" in p.work_models or any(tx.is_remote(loc) for loc in p.locations)
        found, truncated = tx.cities(job.location)
        remote_job = tx.is_remote(job.location) or (job.work_model or "").lower() == "remote"
        if found and not (found & wanted) and not truncated and not (remote_job and remote_ok):
            return f"{job.location} isn't one of your locations"
    level = tx.seniority(job.title)
    if level is not None and level < p.min_seniority - 1:
        return f"Below your seniority ({SENIORITY.get(level, level)})"
    return None


# --- Factors --------------------------------------------------------------------------------------------


def _role(job: JobInput, cand: Candidate, p: ProfileInput) -> int | None:
    job_fam = tx.title_families(job.title)
    parts: list[tuple[float, float]] = []  # (score, weight)
    if job_fam and cand.families:
        if job_fam & cand.families:
            fam = 100
        elif any(frozenset({a, b}) in tx.ADJACENT for a in job_fam for b in cand.families):
            fam = 55
        else:
            fam = 5
        parts.append((fam, 0.6))
    level = tx.seniority(job.title)
    mine = cand.level or (p.min_seniority + 1 if p.id else None)
    if level is not None and mine is not None:
        diff = level - mine
        lv = {0: 100, 1: 85, -1: 85, 2: 60, -2: 55}.get(diff, 30 if diff > 0 else 20)
        parts.append((lv, 0.4))
    title = job.title.lower()
    if any(all(w in title for w in r.lower().split()) for r in p.target_roles if r.strip()):
        parts.append((100, 0.4))
    if not parts:
        return None
    score = round(sum(s * w for s, w in parts) / sum(w for _, w in parts))
    return min(score, TRACK_ROLE) if other_track(job, cand) else score


def other_track(job: JobInput, cand: Candidate) -> bool:
    """A hands-on role (Principal Engineer, Architect…) for someone who leads teams. The other way round is a
    step up, not a mismatch."""
    return cand.track == "lead" and tx.track(job.title) == "ic"


def _experience(job: JobInput, cand: Candidate) -> int | None:
    rng = years_range(job.experience)
    if rng is None or cand.years is None:
        return None
    lo, hi = rng
    if lo <= cand.years <= hi:
        return 100
    if cand.years > hi:  # more experience than asked: mildly over-qualified
        return max(45, 100 - 5 * (cand.years - hi))
    return max(0, 100 - 20 * (lo - cand.years))


def _theme(theme: str, job: JobInput, resume: ResumeInput) -> int | None:
    words = tx.THEMES[theme]
    if tx.count(job.text, words) == 0:
        return None
    covered = tx.count(resume.text, words)
    return 100 if covered >= 4 else 80 if covered >= 2 else 55 if covered == 1 else 10


def _domain(job: JobInput, cand: Candidate, resume: ResumeInput) -> int | None:
    job_domains = set(tx.domains(f"{job.company or ''} {job.text}"))
    if not job_domains:
        return None
    mine = set(cand.domains) | set(tx.domains(resume.text))
    return 100 if job_domains & mine else 30


def _location(job: JobInput, cand: Candidate, p: ProfileInput) -> int | None:
    found, truncated = tx.cities(job.location)
    remote_job = tx.is_remote(job.location) or (job.work_model or "").lower() == "remote"
    wanted_locs = p.locations or cand.locations
    if remote_job and ("Remote" in p.work_models or not p.work_models):
        return 100
    if not found:
        return None
    wanted = {c for loc in wanted_locs for c in tx.cities(loc)[0]}
    if not wanted:
        return None
    if found & wanted:
        return 100
    return None if truncated else 20


def _job_text(job: JobInput) -> str:
    return f"{job.title.lower()} {job.text} {' '.join(job.skills).lower()}"


def skill_split(
    job: JobInput, resume: ResumeInput, key_skills: list[str] | None = None
) -> tuple[list[str], list[str]]:
    """The skills the job asks for (listed, named in its text, or the profile's key skills it names) that the
    resume or profile shows, and the ones it doesn't, as the job (or the user) words them."""
    have, missing = [], []
    mine = {sk.norm(s) for s in key_skills or []}
    for s in sk.asked_for(_job_text(job), job.skills, key_skills or []):
        shown = sk.shows(resume.text, resume.skills, s, by_meaning=sk.norm(s) in mine)
        (have if shown else missing).append(s)
    return have, missing


def profile_skill_hits(job: JobInput, p: ProfileInput) -> list[tuple[str, float]]:
    """The profile's key skills the job asks for, by meaning (see skills.match), with the match strength."""
    return sk.key_skill_hits(_job_text(job), p.skills)


KEY_SKILLS_FOR_FULL_MARKS = 6  # with many key skills, a job needn't ask for all of them


def _skills(job: JobInput, resume: ResumeInput, p: ProfileInput) -> int | None:
    """Skills: the share of the profile's key skills the job asks for (60%; full marks at 6, or all of them
    when fewer) and the share of the skills the job asks for that the resume shows (40%). A job that says too
    little to tell (a title-only alert: no description, no skills listed) is left out rather than marked down;
    its title can't name six key skills (user feedback 2026-11-05)."""
    parts: list[tuple[float, float]] = []  # (score, weight)
    have, missing = skill_split(job, resume, p.skills)
    if have or missing:
        parts.append((100 * len(have) / (len(have) + len(missing)), 0.4))
    if p.skills:
        hits = profile_skill_hits(job, p)
        if job.full_description or job.skills:
            found = sum(m for _, m in hits)
            parts.append((100 * min(1.0, found / min(len(p.skills), KEY_SKILLS_FOR_FULL_MARKS)), 0.6))
    if not parts:
        return None
    return round(sum(s * w for s, w in parts) / sum(w for _, w in parts))


def _comp(job: JobInput, cand: Candidate) -> int | None:
    offered = lakh(job.salary)
    if offered is None or not cand.expected_ctc_lakh:
        return None
    ratio = offered / cand.expected_ctc_lakh
    return 100 if ratio >= 1 else max(0, round(100 - (1 - ratio) * 200))


def factors(job: JobInput, cand: Candidate, p: ProfileInput, resume: ResumeInput) -> dict[str, int]:
    """The factors the job gives evidence for; missing ones are absent, not zero."""
    raw = {
        "role": _role(job, cand, p),
        "exp": _experience(job, cand),
        "core": _theme("core", job, resume),
        "cloud": _theme("cloud", job, resume),
        "ai": _theme("ai", job, resume),
        "domain": _domain(job, cand, resume),
        "loc": _location(job, cand, p),
        "skills": _skills(job, resume, p),
        "comp": _comp(job, cand),
    }
    return {k: v for k, v in raw.items() if v is not None}


def similarity_score(cos: float | None) -> int | None:
    if cos is None:
        return None
    return round(100 * min(1.0, max(0.0, (cos - SIM_LOW) / (SIM_HIGH - SIM_LOW))))


def combine(f: dict[str, int], weights: dict[str, int], sim: int | None) -> int:
    used = {k: weights.get(k, 0) for k in f if weights.get(k, 0) > 0}
    total = sum(used.values())
    rules = sum(f[k] * w for k, w in used.items()) / total if total else None
    if rules is None and sim is None:
        return 0
    if rules is None:
        return int(sim or 0)
    if sim is None:
        return round(rules)
    return round((1 - SIM_WEIGHT) * rules + SIM_WEIGHT * sim)


def points_lost(
    f: dict[str, int],
    weights: dict[str, int],
    sim: int | None,
    score: int,
    capped_by: str = "clash",
    missing_skills: float = 0,
    must_have: float = 0,
) -> dict[str, int]:
    """Where the points between `score` and 100 went: per factor, "similarity" for wording, "missing_skills"
    for skills the resumes don't show, and `capped_by` for a cap ("clash": another line of work; "title_only":
    no description yet). Rounded; the parts add up to 100 - score."""
    used = {k: weights.get(k, 0) for k in f if weights.get(k, 0) > 0}
    total = sum(used.values())
    if not total and sim is None:
        return {}  # nothing to judge the job on
    rules_share = 0.0 if not total else (1 - SIM_WEIGHT if sim is not None else 1.0)
    raw = {k: rules_share * w / total * (100 - f[k]) for k, w in used.items()}
    if sim is not None:
        raw["similarity"] = (SIM_WEIGHT if total else 1.0) * (100 - sim)
    if missing_skills:
        raw["missing_skills"] = missing_skills
    if must_have:
        raw["must_have"] = must_have
    uncapped = 100 - sum(raw.values())
    if uncapped - score > 0.5:
        raw[capped_by] = uncapped - score
    out = {k: round(v) for k, v in raw.items()}
    # Rounding can leave the sum a point off; settle it on the largest part.
    drift = (100 - score) - sum(out.values())
    if drift and out:
        top = max(out, key=lambda k: out[k])
        out[top] += drift
    return {k: v for k, v in sorted(out.items(), key=lambda kv: -kv[1]) if v > 0}


# --- The verdict ----------------------------------------------------------------------------------------


def _band(score: int, threshold: int) -> str:
    if score >= threshold:
        return "strong"
    return "good" if score >= min(70, threshold) else "low"


def _reason(
    job: JobInput, f: dict[str, int], resume: ResumeInput, best_sim: bool, hits: list[tuple[str, float]]
) -> str:
    covered = [FACTORS[k] for k in ("ai", "cloud", "core") if f.get(k, 0) >= 80]
    parts = []
    if hits:
        names = [s for s, _ in hits]
        shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
        parts.append(f"asks for {len(names)} of your key skills ({shown})")
    if covered:
        parts.append("covers " + ", ".join(covered))
    if best_sim and resume.similarity is not None:
        parts.append("closest in wording to this job")
    text = "; ".join(parts) or "fits on role and location"
    return text[:1].upper() + text[1:]  # not capitalize(): it would lower-case skill names


def family_clash(job: JobInput, cand: Candidate) -> bool:
    """The title is in a job family unrelated to the candidate's (a CFO role for an engineering leader)."""
    job_fam = tx.title_families(job.title)
    if not job_fam or not cand.families or job_fam & cand.families:
        return False
    return not any(frozenset({a, b}) in tx.ADJACENT for a in job_fam for b in cand.families)


def specialism_clash(job: JobInput, cand: Candidate, resumes: list[ResumeInput]) -> bool:
    """The description is about a specialism (manufacturing and hardware, SAP / Oracle / Salesforce…) that no
    resume shows, whatever the title says ("MCCB Product Engineering" is switchgear manufacturing)."""
    return any(
        s not in cand.families and not any(tx.has_specialism(r.text, s) for r in resumes)
        for s in tx.specialisms(f"{job.title}\n{job.text}", job.company) | tx.title_specialisms(job.title)
    )


def industry_gap(job: JobInput, resumes: list[ResumeInput]) -> bool:
    """The job asks for experience in an industry with its own vocabulary (EV charging, core banking…) that no
    resume shows. The work itself may fit, so the cap is gentler than for another line of work."""
    return any(not any(tx.has_specialism(r.text, i) for r in resumes) for i in tx.industries(job.text))


def _notes(f: dict[str, int]) -> tuple[list[str], list[str]]:
    strengths = [FACTORS[k] for k, v in f.items() if v >= 80]
    gaps = [FACTORS[k] for k, v in f.items() if v < 45]
    return strengths, gaps


def _rank_key(s: ResumeScore) -> tuple[int, int, int]:
    return (-s.score, sum(1 for c in s.must if c.status != rq.MET), len(s.skills_missing))


def _requirement_gaps(top: ResumeScore) -> list[str]:
    """ "Asks for a PhD", "3 must-haves not shown": for the gaps list."""
    out = [
        f"Asks for a {deg[1]}" for c in top.must if c.status == rq.MISSING and (deg := rq.degree_in(c.text))
    ][:1]
    short = sum(1 for c in top.must if c.status == rq.MISSING and not rq.degree_in(c.text))
    if short:
        out.append(f"{short} must-have{'s' if short > 1 else ''} not shown")
    return out


def score_job(
    job: JobInput, cand: Candidate, profiles: list[ProfileInput], resumes: list[ResumeInput]
) -> Verdict:
    """Score the job against every active profile and every resume; keep the best verdict. A resume's own match
    profile judges only that resume, and those profiles' results are one ranking (user feedback 2026-11-13); a
    profile with no resume judges every resume."""
    profiles = profiles or [DEFAULT_PROFILE]
    passing = [(p, hard_filter(job, p)) for p in profiles]
    candidates = [p for p, why in passing if why is None]
    best_sim = max((r.similarity for r in resumes if r.similarity is not None), default=None)

    cap, cap_reason = 100, "clash"
    if job.not_a_fit:  # the user's word beats any rule
        cap, cap_reason = NOT_A_FIT_CAP, "not_a_fit"
    elif job.learned:  # like a job the user said wasn't for them (milestone 13 A)
        cap, cap_reason = NOT_A_FIT_CAP, "learned"
    elif family_clash(job, cand):
        cap = CLASH_CAP
    elif specialism_clash(job, cand, resumes):
        cap = SPECIALISM_CAP
    elif industry_gap(job, resumes):
        cap, cap_reason = INDUSTRY_CAP, "industry"

    def rank(p: ProfileInput) -> list[ResumeScore]:
        out = []
        hits = profile_skill_hits(job, p)
        added = {s.lower() for s in p.added_skills}
        for r in resumes:
            if p.resume_id is not None and r.id != p.resume_id:
                continue
            if added:  # skills the user said they have count as shown by this profile's resume
                r = replace(r, skills=r.skills | added)
            f = factors(job, cand, p, r)
            # A title alone always reads as far from a whole resume (about 27 points lost on every title-only
            # alert, 2026-11-05), so wording is compared only once the description is in.
            sim = similarity_score(r.similarity) if job.full_description else None
            # A different line of work: location and experience can't make it a match. A title-only job can be
            # a Good match (Top matches) but not a Strong one, which sends a WhatsApp alert, until its
            # description confirms it.
            have, missing = skill_split(job, r, p.skills)
            penalty = min(MISSING_SKILLS_MAX, MISSING_SKILL_POINTS * len(missing))
            must = [rq.check(i, r.text, r.skills, p.skills) for i in job.must]
            preferred = [rq.check(i, r.text, r.skills, p.skills) for i in job.preferred]
            degree_short = any(c.status == rq.MISSING and rq.degree_in(c.text) for c in must)
            must_penalty = min(
                MUST_MAX,
                sum(
                    MUST_POINTS if c.status == rq.MISSING else MUST_POINTS / 2 if c.status == rq.PARTLY else 0
                    for c in must
                    if not rq.degree_in(c.text)  # a degree is a cap, not points
                ),
            )
            r_cap, capped_by = cap, cap_reason
            if degree_short and DEGREE_CAP < r_cap:
                r_cap, capped_by = DEGREE_CAP, "degree"
            s = max(0, min(round(combine(f, p.weights, sim) - penalty - must_penalty), r_cap))
            # A hands-on role for a leader is a move to weigh, not a Strong match: at most Good.
            if other_track(job, cand) and s >= p.threshold:
                s, capped_by = p.threshold - 1, "track"
            if not job.full_description and s >= p.threshold:
                s, capped_by = p.threshold - 1, "title_only"
            reason = _reason(job, f, r, r.similarity == best_sim, hits)
            lost = points_lost(f, p.weights, sim, s, capped_by, penalty, must_penalty)
            # Fewer years than the user's level calls for: a share off, not a cap (user, 2026-11-11).
            if cut := round(s * job.years_short):
                s -= cut
                lost = {**lost, "years_short": cut}
            out.append(
                # Only the key skills the job names count as "asked for"; a related word gives credit, not a claim.
                ResumeScore(
                    r.id,
                    r.label,
                    s,
                    f,
                    reason,
                    lost,
                    have,
                    missing,
                    [n for n, m in hits if m == 1.0],
                    p.id,
                    must,
                    preferred,
                )
            )
        # Equal scores (both capped): the resume that shows more of what the job asks for first.
        return sorted(out, key=_rank_key)

    def groups(ps: list[ProfileInput]) -> list[list[ResumeScore]]:
        """One ranking per profile with no resume; the resumes' own profiles together make one more."""
        own = sorted((s for p in ps if p.resume_id for s in rank(p)), key=_rank_key)
        return [rank(p) for p in ps if not p.resume_id] + ([own] if own else [])

    by_id = {p.id: p for p in profiles}

    provisional = not job.full_description
    if not candidates:
        p, why = passing[0]
        ranking = next((g for g in groups([q for q, _ in passing]) if g), [])
        return Verdict(
            "filtered", ranking[0].score if ranking else 0, p.id, why, ranking, provisional=provisional
        )

    best_rank: list[ResumeScore] = []
    for g in groups(candidates):
        if g and (not best_rank or g[0].score > best_rank[0].score):
            best_rank = g
    top = best_rank[0] if best_rank else None
    best_p = by_id.get(top.profile_id) if top else candidates[0]
    best_p = best_p or candidates[0]
    score = top.score if top else 0
    strengths, gaps = _notes(top.factors) if top else ([], [])
    if top:
        gaps += _requirement_gaps(top)
    return Verdict(
        _band(score, best_p.threshold), score, best_p.id, None, best_rank, strengths, gaps, provisional
    )
