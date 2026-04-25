"""
Fetch Lever + Greenhouse jobs, filter by location + AI/ML keywords, optional OpenAI scoring.

Broad mode (default): many companies, no “junior-only” gate — CV-based scorer down-ranks poor fits.
Set STRICT_JUNIOR_FILTERS=1 to restore the previous fellowship/grad-heavy pipeline.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from prompts import SCORING_SYSTEM_ADDENDUM
from sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "jobs.json"
CV_PATH = ROOT / "cv.txt"
ENV_PATH = ROOT / ".env"

MAX_JD_CHARS = 8000
# Cheap default; override with OPENAI_MODEL (e.g. gpt-4.1-mini if your org uses it).
OPENAI_MODEL_DEFAULT = "gpt-4o-mini"


def openai_key() -> str | None:
    k = (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_SECRET_KEY") or "").strip()
    return k or None


def load_env_file(path: Path) -> None:
    """Populate os.environ from a simple KEY=VAL file (no python-dotenv dependency)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def strict_junior_filters() -> bool:
    return os.environ.get("STRICT_JUNIOR_FILTERS", "").lower() in ("1", "true", "yes")


def title_filter_mode() -> str:
    """none | exec (default) | strict — how aggressively to drop roles by title."""
    m = (os.environ.get("TITLE_FILTER_MODE") or "exec").strip().lower()
    if m in ("none", "off", "0"):
        return "none"
    if m in ("strict", "all"):
        return "strict"
    return "exec"


KEYWORD_RE = re.compile(
    r"\b(ai|ml|rl)\b|research|machine learning|reinforcement|artificial intelligence|"
    r"data scientist|applied scientist|deep learning|\bnlp\b|computer vision|\bllm\b|"
    r"generative ai|genai|foundation model|post-?training|alignment|eval|evaluation|"
    r"data analyst|analytics|business analyst|technology consultant|digital consultant",
    re.IGNORECASE,
)

# When the keyword hits only in long boilerplate, require a clearer ML/AI role signal.
STRONG_DOMAIN_RE = re.compile(
    r"machine learning|reinforcement learning|\brl\b|deep learning|\bml\b|"
    r"research engineer|research scientist|applied scientist|ai engineer|"
    r"mle\b|llm|large language model|generative ai|pytorch|tensorflow|jax\b",
    re.IGNORECASE,
)

GENERALIST_EARLY_RE = re.compile(
    r"data analyst|analytics consultant|business analyst|technology consultant|"
    r"digital consultant|operations analyst|strategy analyst|energy analyst|"
    r"graduate (program|scheme)|trainee|early career",
    re.IGNORECASE,
)

LEVER_DESC_STRONG_RE = re.compile(
    r"\brl\b|research|machine learning|reinforcement|\bml\b",
    re.IGNORECASE,
)

UK_HINTS = (
    "united kingdom",
    "london",
    "manchester",
    "edinburgh",
    "bristol",
    "cambridge",
    "oxford",
    "belfast",
    "cardiff",
    "leeds",
    "glasgow",
    ", uk",
    " uk,",
    " england",
    " scotland",
    " wales",
)

EU_HINTS = (
    "ireland",
    "dublin",
    "berlin",
    "munich",
    "frankfurt",
    "hamburg",
    "amsterdam",
    "rotterdam",
    "paris",
    "lyon",
    "madrid",
    "barcelona",
    "lisbon",
    "porto",
    "stockholm",
    "zurich",
    "geneva",
    "brussels",
    "warsaw",
    "krakow",
    "prague",
    "vienna",
    "copenhagen",
    "europe",
    "emea",
    ", eu",
    " eu,",
    " europe",
)

JUNIOR_TAGS = frozenset({"entry", "junior", "graduate", "intern"})

_GH_DETAIL_CACHE: dict[tuple[str, int], dict[str, Any]] = {}


def _blob_for_location(job_location: str) -> str:
    return job_location.lower()


def location_matches(job_location: str) -> bool:
    # Worldwide mode: keep all locations instead of restricting to Lagos/UK/EU/remote.
    return True


def location_tag(job_location: str) -> str:
    L = _blob_for_location(job_location)
    if any(x in L for x in ("remote", "distributed", "anywhere", "fully remote", "work from home")):
        return "remote"
    if "lagos" in L or "nigeria" in L:
        return "lagos"
    if any(h in L for h in UK_HINTS) or L.rstrip().endswith(" uk"):
        return "uk"
    if any(h in L for h in EU_HINTS):
        return "eu"
    return "global"


def keyword_matches(text: str) -> bool:
    return bool(KEYWORD_RE.search(text))


def keyword_pass(title: str, blob: str) -> bool:
    if keyword_matches(title):
        return True
    if keyword_matches(blob) and STRONG_DOMAIN_RE.search(blob):
        return True
    # Keep a broad lane for entry-level generalist roles (consulting/energy/analytics).
    if has_entry_level_signal(f"{title}\n{blob}") and GENERALIST_EARLY_RE.search(f"{title}\n{blob}"):
        return True
    return False


def title_non_stem_noise(title: str) -> bool:
    t = title.lower()
    return any(
        p in t
        for p in (
            "sales development",
            "sales representative",
            "account executive",
            "business development",
            "recruiter",
            "talent partner",
            "people partner",
            "hr ",
            "human resources",
            "marketing",
            "legal counsel",
            "finance manager",
            "office manager",
            "av builds",
            "audio visual",
            "facilities",
        )
    )


def title_exec_rejects(title: str) -> bool:
    """Drop obvious exec / leadership titles; keep IC 'Senior' / 'Lead' / 'Staff' for breadth."""
    t = title.lower()
    if re.search(r"\bvice president\b", t) or re.search(r"\bvp\b", t):
        return True
    if re.search(r"\bchief\b", t) or re.search(r"\bcto\b", t) or re.search(r"\bcio\b", t) or re.search(r"\bcfo\b", t):
        return True
    if re.search(r"\bhead of\b", t):
        return True
    if re.search(r"\bdirector\b", t):
        return True
    return False


def title_auto_rejects(title: str) -> bool:
    t = title.lower()
    if re.search(r"\b(senior|sr\.)\b", t):
        return True
    if re.search(r"\bstaff\b", t):
        return True
    if re.search(r"\bprincipal\b", t):
        return True
    if re.search(r"\blead\b", t) and not re.search(r"lead gen|lead generation", t):
        return True
    if re.search(r"\bhead of\b", t):
        return True
    if re.search(r"\bdirector\b", t):
        return True
    if re.search(r"\bvp\b", t) or "vice president" in t:
        return True
    if re.search(r"\bchief\b", t) or re.search(r"\bcto\b", t) or re.search(r"\bcio\b", t):
        return True
    if "architect" in t and "associate architect" not in t:
        return True
    if re.search(r"\bmanager\b", t) and "associate manager" not in t:
        return True
    if re.search(r"\b5\s*\+\s*years\b", t) or re.search(r"\b7\s*\+\s*years\b", t) or re.search(r"\b10\s*\+\s*years\b", t):
        return True
    return False


def title_filter_rejects(title: str) -> bool:
    mode = title_filter_mode()
    if mode == "none":
        return False
    if mode == "strict":
        return title_auto_rejects(title)
    return title_exec_rejects(title)


def has_entry_level_signal(blob: str) -> bool:
    b = blob.lower()
    if re.search(r"\bintern(ship)?\b", b):
        return True
    if re.search(r"\bgraduate\b", b) or re.search(r"new\s+grad(uate)?", b):
        return True
    if re.search(r"\bjunior\b", b):
        return True
    if "entry-level" in b or "entry level" in b:
        return True
    if "early-career" in b or "early career" in b:
        return True
    if re.search(r"\bapprentice", b) or re.search(r"\btrainee\b", b):
        return True
    if re.search(r"\bresidency\b", b) or re.search(r"research\s+resident", b):
        return True
    if re.search(r"\bfellows?\s+program", b) or re.search(r"\bfellowship\b", b):
        return True
    if "industrial placement" in b or re.search(r"\bplacement\s+(year|student)\b", b):
        return True
    if re.search(r"\bundergraduate\s+researcher\b", b) or re.search(r"\bstudent\s+researcher\b", b):
        return True
    if re.search(r"0\s*[-–]\s*2\s*years", b) or re.search(r"1\s*[-–]\s*2\s*years", b) or re.search(r"1\s*[-–]\s*3\s*years", b):
        return True
    if re.search(r"\b0\s*(?:\+)?\s*years?\b", b) or re.search(r"\bzero\s+years?\b", b):
        return True
    if "no experience required" in b or "no prior experience" in b:
        return True
    if (
        re.search(r"level\s*1\b", b)
        or re.search(r"\bl1\b", b)
        or re.search(r"level\s*i\b", b)
        or re.search(r"i\s*[-–]\s*ii\b", b)
        or re.search(r"level\s*1\s*[-–]\s*2", b)
    ):
        return True
    if re.search(r"\bassociate\b", b):
        if "associate director" in b or "associate partner" in b:
            return False
        return True
    return False


def infer_seniority(title: str, description: str) -> str:
    t = f"{title}\n{description}".lower()
    if re.search(r"\bintern(ship)?\b", t):
        return "intern"
    if (
        re.search(r"\bgraduate\b", t)
        or re.search(r"new\s+grad(uate)?", t)
        or re.search(r"\bresidency\b", t)
        or re.search(r"research\s+resident", t)
        or re.search(r"\bfellows?\s+program", t)
        or re.search(r"\bfellowship\b", t)
    ):
        return "graduate"
    if (
        "entry-level" in t
        or "entry level" in t
        or "early-career" in t
        or "early career" in t
        or re.search(r"\bapprentice", t)
        or re.search(r"\btrainee\b", t)
        or re.search(r"0\s*[-–]\s*2\s*years", t)
        or re.search(r"1\s*[-–]\s*2\s*years", t)
        or re.search(r"1\s*[-–]\s*3\s*years", t)
        or re.search(r"\b0\s*(?:\+)?\s*years?\b", t)
        or re.search(r"\bzero\s+years?\b", t)
        or "no experience required" in t
        or "no prior experience" in t
        or re.search(r"level\s*1\b", t)
        or re.search(r"\bl1\b", t)
        or re.search(r"level\s*i\b", t)
        or re.search(r"i\s*[-–]\s*ii\b", t)
        or re.search(r"level\s*1\s*[-–]\s*2", t)
    ):
        return "entry"
    if re.search(r"\bjunior\b", t):
        return "junior"
    if re.search(r"\bsenior\b", t) or re.search(r"\bstaff\b", t) or re.search(r"\bprincipal\b", t):
        return "mid"
    if re.search(r"\blead\b", t) and not re.search(r"lead gen|lead generation", t):
        return "mid"
    if "industrial placement" in t or re.search(r"\bplacement\s+year\b", t):
        return "entry"
    if re.search(r"\b(student|undergraduate)\s+researcher\b", t):
        return "entry"
    if re.search(r"\bassociate\b", t) and "associate director" not in t and "associate partner" not in t:
        return "mid"
    return "unknown"


def compute_tier(score: int | None, seniority: str) -> str:
    if score is None:
        return "stretch"
    if score < 40 and seniority in JUNIOR_TAGS:
        return "apply_anyway"
    if score >= 80:
        return "high"
    if score >= 65:
        return "medium"
    return "stretch"


def strip_html_to_text(raw_html: str) -> str:
    t = html.unescape(raw_html)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def fetch_greenhouse(session: requests.Session, board: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    url: str | None = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    while url:
        r = session.get(url, timeout=45)
        r.raise_for_status()
        payload = r.json()
        jobs.extend(payload.get("jobs") or [])
        nxt = r.links.get("next")
        url = nxt.get("url") if nxt else None
    return jobs


def greenhouse_detail(session: requests.Session, board: str, job_id: int) -> dict[str, Any]:
    key = (board, job_id)
    if key not in _GH_DETAIL_CACHE:
        u = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
        r = session.get(u, timeout=45)
        r.raise_for_status()
        _GH_DETAIL_CACHE[key] = r.json()
    return _GH_DETAIL_CACHE[key]


def greenhouse_description_plain(session: requests.Session, board: str, job_id: int) -> str:
    d = greenhouse_detail(session, board, job_id)
    c = d.get("content") or ""
    if not isinstance(c, str):
        return ""
    return strip_html_to_text(c)


def fetch_lever(session: requests.Session, slug: str, region: str) -> list[dict[str, Any]]:
    host = "api.eu.lever.co" if region == "eu" else "api.lever.co"
    url = f"https://{host}/v0/postings/{slug}?mode=json"
    r = session.get(url, timeout=45)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return data


def lever_location_string(raw: dict[str, Any]) -> str:
    cats = raw.get("categories") or {}
    loc = cats.get("location")
    if isinstance(loc, list):
        return ", ".join(str(x) for x in loc)
    if loc:
        return str(loc)
    all_l = cats.get("allLocations")
    if isinstance(all_l, list) and all_l:
        return ", ".join(str(x) for x in all_l)
    return ""


def lever_body_text(raw: dict[str, Any]) -> str:
    parts = [
        raw.get("text") or "",
        raw.get("descriptionPlain") or "",
    ]
    return "\n".join(parts)


def _gh_date(pub: str) -> str:
    if not pub:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if len(pub) >= 10 and pub[4] == "-" and pub[7] == "-":
            return pub[:10]
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


_SKILL_PATTERNS = [
    ("Python", re.compile(r"\bpython\b", re.I)),
    ("PyTorch", re.compile(r"\bpytorch\b", re.I)),
    ("TensorFlow", re.compile(r"\btensorflow\b", re.I)),
    ("RL", re.compile(r"\brl\b|reinforcement learning", re.I)),
    ("LLM", re.compile(r"\bllm\b|large language model", re.I)),
    ("PySpark", re.compile(r"\bpyspark\b", re.I)),
]


def _guess_skills(text: str) -> list[str]:
    out: list[str] = []
    for label, rx in _SKILL_PATTERNS:
        if rx.search(text) and label not in out:
            out.append(label)
    return out[:8]


def _truncate_jd(text: str, max_chars: int = MAX_JD_CHARS) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 3] + "..."


def _coerce_score_value(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        s = int(round(float(raw)))
        return max(0, min(100, s))
    if isinstance(raw, str):
        v = raw.strip()
        if v.isdigit():
            return _coerce_score_value(int(v))
        try:
            return _coerce_score_value(float(v))
        except ValueError:
            m = re.search(r"\b(\d{1,3})\b", v)
            if m:
                return _coerce_score_value(int(m.group(1)))
    return None


def _parse_score_json(text: str) -> tuple[int | None, str]:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s*```\s*$", "", t)
    blob = t
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        start, end = blob.find("{"), blob.rfind("}")
        if start == -1 or end <= start:
            return None, "Score unavailable (no JSON object)."
        try:
            data = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return None, "Score unavailable (invalid JSON)."
    if not isinstance(data, dict):
        return None, "Score unavailable (expected a JSON object)."

    raw_score = None
    for key in ("score", "match_score", "fit_score", "overall_score", "match"):
        if key in data:
            raw_score = data.get(key)
            break
    score = _coerce_score_value(raw_score)
    if score is None:
        m = re.search(
            r'"(?:score|match_score|fit_score)"\s*:\s*(\d{1,3})',
            blob,
        )
        if m:
            score = _coerce_score_value(int(m.group(1)))

    reason_raw = data.get("reasoning", data.get("reason", data.get("explanation", "")))
    reason = str(reason_raw or "").strip()
    words = reason.split()
    if len(words) > 20:
        reason = " ".join(words[:20])
    if score is None:
        return None, reason or "Score unavailable (missing numeric score)."
    return score, reason or "No reasoning returned."


def _chat_score_completion(client: Any, model: str, system: str, user_msg: str) -> str:
    kwargs: dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=200,
    )
    try:
        completion = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        err = str(e).lower()
        if any(
            x in err
            for x in (
                "response_format",
                "json_object",
                "not support",
                "unsupported",
                "invalid_parameter",
            )
        ):
            completion = client.chat.completions.create(**kwargs)
        else:
            raise
    return completion.choices[0].message.content or ""


def _mark_jobs_unscored(jobs: list[dict[str, Any]], message: str) -> None:
    for row in jobs:
        row["match_score"] = None
        row["match_reasoning"] = message
        row["tier"] = compute_tier(None, str(row.get("seniority") or "unknown"))


def score_jobs(jobs: list[dict[str, Any]]) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("openai package not installed; skipping scoring")
        _mark_jobs_unscored(
            jobs,
            "Not scored: install the OpenAI SDK (`pip install -r scraper/requirements.txt`).",
        )
        return

    api_key = openai_key()
    if not api_key:
        print("No OpenAI key (OPENAI_API_KEY or OPENAI_SECRET_KEY); skipping scoring")
        _mark_jobs_unscored(
            jobs,
            "Not scored: OpenAI key missing at scoring time (unexpected).",
        )
        return

    if not CV_PATH.is_file():
        print(f"cv.txt not found at {CV_PATH}; skipping scoring")
        _mark_jobs_unscored(
            jobs,
            f"Not scored: add {CV_PATH.name} next to jobs.json (plain text CV).",
        )
        return

    cv_text = CV_PATH.read_text(encoding="utf-8").strip()
    system = (
        "You are scoring job fit for the candidate below.\n\n"
        "--- CANDIDATE CV ---\n"
        f"{cv_text}\n\n"
        "--- SCORING RULES ---\n"
        f"{SCORING_SYSTEM_ADDENDUM}\n\n"
        "Return a JSON object with exactly two keys: "
        '"score" (integer 0-100) and "reasoning" (string, max 20 words).'
    )

    client = OpenAI(api_key=api_key)
    model = (os.environ.get("OPENAI_MODEL") or "").strip() or OPENAI_MODEL_DEFAULT
    max_n_raw = os.environ.get("MAX_SCORE_JOBS", "").strip()
    max_n = int(max_n_raw) if max_n_raw.isdigit() else None
    n_target = len(jobs) if max_n is None else min(max_n, len(jobs))
    print(f"OpenAI scoring: model={model}, jobs={n_target} (of {len(jobs)} matched)")

    ok = fail = 0
    for idx, job in enumerate(jobs):
        if max_n is not None and idx >= max_n:
            break
        jd = _truncate_jd(job.get("_scoring_text") or "")
        user_msg = (
            f"Title: {job.get('title', '')}\n"
            f"Company: {job.get('company', '')}\n"
            f"Location: {job.get('location', '')}\n\n"
            f"Job description (may be truncated):\n{jd}"
        )
        try:
            raw = _chat_score_completion(client, model, system, user_msg)
            score, reason = _parse_score_json(raw)
            if score is None:
                fail += 1
            else:
                ok += 1
        except Exception as exc:
            print(f"[score error] {job.get('title', '')[:50]}: {exc}")
            score, reason = None, f"API error: {exc}"[:280]
            fail += 1

        job["match_score"] = score
        job["match_reasoning"] = reason
        job["tier"] = compute_tier(score, str(job.get("seniority") or "unknown"))
        time.sleep(0.15)

    if max_n is not None:
        lim_msg = (
            "Not scored: row is beyond MAX_SCORE_JOBS (only the first N matched jobs are sent to the API)."
        )
        for job in jobs[max_n:]:
            job["match_score"] = None
            job["match_reasoning"] = lim_msg
            job["tier"] = compute_tier(None, str(job.get("seniority") or "unknown"))

    print(f"OpenAI scoring done: {ok} scored, {fail} failed/unparsed (this batch).")


def _row_common(
    title: str,
    company: str,
    loc: str,
    apply_url: str,
    posted: str,
    full_text: str,
    seniority: str,
    flags: list[str],
    scoring_text: str,
    salary: str = "",
) -> dict[str, Any]:
    tier = compute_tier(None, seniority)
    return {
        "title": title,
        "company": company,
        "location": loc or "—",
        "location_tag": location_tag(loc),
        "salary": salary,
        "skills": _guess_skills(full_text),
        "apply_url": apply_url,
        "posted_at": posted,
        "match_score": None,
        "match_reasoning": "",
        "tier": tier,
        "seniority": seniority,
        "flags": flags,
        "_scoring_text": scoring_text,
    }


def normalize_lever(raw: dict[str, Any], company: str, flags: list[str]) -> dict[str, Any] | None:
    loc = lever_location_string(raw)
    if not location_matches(loc):
        return None
    title = (raw.get("text") or "").strip()
    if title_filter_rejects(title):
        return None
    body = lever_body_text(raw)
    if not (keyword_matches(title) or LEVER_DESC_STRONG_RE.search(body)):
        return None
    if not keyword_pass(title, body):
        return None
    if title_non_stem_noise(title) and not STRONG_DOMAIN_RE.search(body):
        return None
    if strict_junior_filters() and not has_entry_level_signal(body):
        return None
    desc_only = (raw.get("descriptionPlain") or "").strip()
    seniority = infer_seniority(title, desc_only)
    created = raw.get("createdAt")
    if isinstance(created, (int, float)):
        posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        posted = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    apply_url = raw.get("hostedUrl") or raw.get("applyUrl") or ""
    return _row_common(title, company, loc, apply_url, posted, body, seniority, flags, body)


def normalize_greenhouse(
    session: requests.Session,
    board: str,
    raw: dict[str, Any],
    company: str,
    flags: list[str],
) -> dict[str, Any] | None:
    loc_obj = raw.get("location") or {}
    loc = (loc_obj.get("name") or "").strip()
    if not location_matches(loc):
        return None
    title = (raw.get("title") or "").strip()
    if title_filter_rejects(title):
        return None

    jid = raw.get("id")
    if not isinstance(jid, int):
        try:
            jid = int(jid)
        except (TypeError, ValueError):
            return None

    need_detail = not keyword_matches(title)
    if strict_junior_filters() and not has_entry_level_signal(title):
        need_detail = True
    desc_plain = ""
    if need_detail:
        desc_plain = greenhouse_description_plain(session, board, jid)

    blob = f"{title}\n{desc_plain}"
    if not keyword_pass(title, blob):
        return None
    if title_non_stem_noise(title) and not STRONG_DOMAIN_RE.search(blob):
        return None
    if strict_junior_filters() and not has_entry_level_signal(blob):
        return None

    seniority = infer_seniority(title, desc_plain)
    pub = raw.get("first_published") or raw.get("updated_at") or ""
    posted = _gh_date(str(pub) if pub else "")
    apply_url = raw.get("absolute_url") or ""
    return _row_common(title, company, loc, apply_url, posted, blob, seniority, flags, blob)


def dedupe_key(row: dict[str, Any]) -> str:
    return row.get("apply_url") or f"{row.get('company')}|{row.get('title')}|{row.get('location')}"


def run() -> None:
    global _GH_DETAIL_CACHE
    _GH_DETAIL_CACHE = {}

    load_env_file(ENV_PATH)

    print(
        f"Filters: STRICT_JUNIOR_FILTERS={strict_junior_filters()}, "
        f"TITLE_FILTER_MODE={title_filter_mode()}, boards={len(SOURCES)}"
    )

    session = requests.Session()
    session.headers.update({"User-Agent": "job-dashboard-scraper/1.0"})

    all_rows: list[dict[str, Any]] = []
    total_scraped = 0

    for src in SOURCES:
        flags = list(src.get("flags") or [])
        kind = src["kind"]
        try:
            if kind == "lever":
                raw_jobs = fetch_lever(session, src["slug"], src["region"])
                total_scraped += len(raw_jobs)
                for raw in raw_jobs:
                    row = normalize_lever(raw, src["company"], flags)
                    if row:
                        all_rows.append(row)
            elif kind == "greenhouse":
                raw_jobs = fetch_greenhouse(session, src["board"])
                total_scraped += len(raw_jobs)
                for raw in raw_jobs:
                    row = normalize_greenhouse(session, src["board"], raw, src["company"], flags)
                    if row:
                        all_rows.append(row)
        except Exception as exc:
            print(f"[source error] {src.get('company', 'unknown')} ({kind}): {exc}")
            continue

    seen: set[str] = set()
    jobs: list[dict[str, Any]] = []
    for row in all_rows:
        k = dedupe_key(row)
        if k in seen:
            continue
        seen.add(k)
        jobs.append(row)

    skip = os.environ.get("SKIP_SCORING", "").lower() in ("1", "true", "yes")
    no_key_msg = (
        "Not scored: no OPENAI_API_KEY or OPENAI_SECRET_KEY in the environment. "
        "Locally: export the key or add job dash/.env with OPENAI_API_KEY=sk-... "
        "GitHub Actions: Repository Settings → Secrets and variables → Actions → "
        "add OPENAI_API_KEY as a repository secret (workflows that omit `environment:` "
        "do not see Environment-only secrets)."
    )
    if openai_key() and not skip:
        score_jobs(jobs)
    elif skip:
        print("SKIP_SCORING set; skipping OpenAI.")
        _mark_jobs_unscored(jobs, "Not scored: SKIP_SCORING is enabled.")
    elif not openai_key():
        print("OpenAI key not set; jobs will show — instead of a match score.")
        _mark_jobs_unscored(jobs, no_key_msg)

    for row in jobs:
        row.pop("_scoring_text", None)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_scraped": total_scraped,
        "total_matched": len(jobs),
        "jobs": jobs,
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({payload['total_matched']} matched / {total_scraped} scraped)")


if __name__ == "__main__":
    run()
