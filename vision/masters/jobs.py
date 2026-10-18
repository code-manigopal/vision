"""Job Hunt (live): Job Scout -> Resume Tailor + Cover Letter Writer -> YOU -> Outreach -> Application Tracker
(reporter) -> Interview Prep.

Sources (no Indeed):
- Job Bank Canada alert emails (set up alerts at jobbank.gc.ca; the Email Manager reads them)
- Adzuna API (ADZUNA_APP_ID / ADZUNA_APP_KEY; 25 test calls free, then £8 a month as of 2026-10)
- Company career pages on Greenhouse, Lever, Ashby, Workable and SmartRecruiters (public job feeds), listed in config
- Free public feeds, no key (`free_sources`): Job Bank's own search feed (Ontario, the last couple of days), Himalayas and
  Jobicy (remote jobs open to Canada). Any of them may change or close; each fails on its own.
- LinkedIn's public job search (`linkedin: true`; Mani's choice, 2026-10-12): the pages anyone sees signed out, asked for
  with a browser's user agent. Never signed in, a few requests a run spaced apart, and a refusal stops it for a day.
- Companies found along the way: a posting whose link sits on one of those career-page boards adds that company to the
  list read on later runs (`discover_companies`, kv `job_companies`).

Before scoring, a posting must pass the gates in `job_match.gate` and must not be a job already seen from another source
(`job_match.same_keys`, kv `job_keys`). A reworded resume must pass `job_facts.unsupported` or it goes in as written.

Resumes: vault/resume/analyst.md, software.md and ai.md, picked by the posting's title (`resume_for`); master.md is the fallback.

VISION never applies for you. It prepares the package; you submit it from the posting's page.
Your master resume lives at vault/resume/master.md; tailored versions never invent experience.
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
import shutil
import time
from html import unescape
from pathlib import Path
from typing import Any

import httpx

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT, secret
from ..services import gdrive, oauth
from ..services.llm import LLMUnavailable
from .job_facts import unsupported
from .job_match import FENCE_RULE, ats_ref, coverage, fence, gate, has, same_keys

UA = {"User-Agent": "VISION job scout (personal use)"}
# LinkedIn turns away anything that doesn't say it is a browser, so its requests (and only its) carry a browser's user agent.
LI_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
         "Accept-Language": "en-CA,en;q=0.9"}
LI = "https://www.linkedin.com/jobs-guest/jobs/api/"


def jid(source: str, key: str) -> str:
    return source + ":" + hashlib.sha1(key.encode()).hexdigest()[:12]


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


# ---------- sources ----------
async def adzuna(c: httpx.AsyncClient, titles: list[str], where: str, days: int) -> list[dict]:
    app_id, key = secret("ADZUNA_APP_ID"), secret("ADZUNA_APP_KEY")
    if not (app_id and key):
        return []
    out = []
    for t in titles:
        r = await c.get("https://api.adzuna.com/v1/api/jobs/ca/search/1", params={
            "app_id": app_id, "app_key": key, "what": t, "where": where, "results_per_page": 30, "max_days_old": days, "content-type": "application/json"})
        if r.status_code != 200:
            continue
        for j in r.json().get("results", []):
            out.append({"id": jid("adzuna", str(j.get("id"))), "source": "Adzuna", "title": j.get("title", ""), "company": (j.get("company") or {}).get("display_name", ""),
                        "location": (j.get("location") or {}).get("display_name", ""), "url": j.get("redirect_url", ""),
                        "description": _text(j.get("description", "")), "salary": j.get("salary_min")})
    return out


async def company_boards(c: httpx.AsyncClient, companies: list[dict]) -> list[dict]:
    out = []
    for co in companies:
        ats, slug, name = co.get("ats", "greenhouse"), co["slug"], co.get("name", co["slug"])
        try:
            if ats == "greenhouse":
                r = await c.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
                jobs = [(j["id"], j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"], _text(j.get("content", ""))) for j in r.json().get("jobs", [])]
            elif ats == "lever":
                r = await c.get(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
                jobs = [(j["id"], j["text"], (j.get("categories") or {}).get("location", ""), j["hostedUrl"], j.get("descriptionPlain", "")) for j in r.json()]
            elif ats == "ashby":
                r = await c.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
                jobs = [(j["id"], j["title"], j.get("location", ""), j["jobUrl"], j.get("descriptionPlain", "")) for j in r.json().get("jobs", [])]
            elif ats == "workable":   # titles and places only: this feed carries no description
                r = await c.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
                jobs = [(j["shortcode"], j["title"], ", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)
                         + (" · Remote" if str(j.get("telecommuting")).lower() == "true" else ""), j["url"], "") for j in r.json().get("jobs", [])]
            elif ats == "smartrecruiters":
                r = await c.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 100, "country": "ca"})
                jobs = [(j["id"], j["name"], ", ".join(x for x in ((j.get("location") or {}).get("city"), (j.get("location") or {}).get("region")) if x)
                         + (" · Remote" if (j.get("location") or {}).get("remote") else ""),
                         f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", "") for j in r.json().get("content", [])]
            else:
                continue
        except Exception:
            continue
        out += [{"id": jid(ats, str(i)), "source": name, "title": t, "company": name, "location": loc, "url": u, "description": d[:6000]} for i, t, loc, u, d in jobs]
    return out


async def jobbank_feed(c: httpx.AsyncClient, titles: list[str], province: str = "ON", pages: int = 12) -> list[dict]:
    """Job Bank's search feed (Atom): the newest postings for each title in one province. It lists only the last couple of
    days and uses Job Bank's own job names, so a search often comes back short or empty; the posting page gives the text."""
    found: dict[str, dict] = {}
    for t in titles:
        try:
            r = await c.get("https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed", params={"searchstring": t, "fprov": province, "sort": "D"})
        except Exception:
            continue
        for e in re.findall(r"<entry>(.*?)</entry>", r.text if r.status_code == 200 else "", re.S):
            url = re.search(r'href="(https://www\.jobbank\.gc\.ca/jobsearch/jobposting/\d+)', e)
            name = re.search(r"<title[^>]*><!\[CDATA\[(.*?)\]\]>", e, re.S)
            if not (url and name):
                continue
            part = lambda label: _text((re.search(label + r":</strong>(.*?)(?:<br|\]\]>)", e, re.S) or [None, ""])[1])
            found.setdefault(url.group(1), {"id": jid("jobbank", url.group(1)), "source": "Job Bank", "title": _text(name.group(1)).title(),
                                            "company": part("Employer"), "location": part("Location"), "url": url.group(1),
                                            "description": "", "salary": part("Salary")})
    for j in list(found.values())[:pages]:
        try:
            j["description"] = _text((await c.get(j["url"])).text)[:6000]
        except Exception:
            pass
    return list(found.values())


async def himalayas(c: httpx.AsyncClient, titles: list[str], days: int, country: str = "Canada") -> list[dict]:
    """Remote jobs open to one country, searched by title."""
    out = []
    for t in titles:
        try:
            r = await c.get("https://himalayas.app/jobs/api/search", params={"q": t, "country": country, "limit": 20})
            jobs = r.json().get("jobs", []) if r.status_code == 200 else []
        except Exception:
            continue
        for j in jobs:
            if float(j.get("pubDate") or 0) < time.time() - days * 86400:
                continue
            url = j.get("applicationLink") or j.get("guid") or ""
            where = ", ".join(j.get("locationRestrictions") or []) or "anywhere"
            out.append({"id": jid("himalayas", url), "source": "Himalayas", "title": j.get("title", ""), "company": j.get("companyName", ""),
                        "location": "Remote · " + where, "url": url, "description": _text(j.get("description") or j.get("excerpt") or "")[:6000],
                        "salary": j.get("minSalary")})
    return out


async def jobicy(c: httpx.AsyncClient, days: int, geo: str = "canada") -> list[dict]:
    """The newest remote jobs open to one country (one request; the scoring sorts out which matter)."""
    from datetime import datetime
    try:
        r = await c.get("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "geo": geo})
        jobs = r.json().get("jobs", []) if r.status_code == 200 else []
    except Exception:
        return []
    out = []
    for j in jobs:
        try:
            if datetime.fromisoformat(j["pubDate"]).timestamp() < time.time() - days * 86400:
                continue
        except (KeyError, ValueError):
            pass
        out.append({"id": jid("jobicy", str(j.get("id"))), "source": "Jobicy", "title": j.get("jobTitle", ""), "company": j.get("companyName", ""),
                    "location": "Remote · " + (j.get("jobGeo") or ""), "url": j.get("url", ""),
                    "description": _text(j.get("jobDescription") or j.get("jobExcerpt") or "")[:6000]})
    return out


async def linkedin(c: httpx.AsyncClient, store, titles: list[str], days: int, where: str = "Ontario, Canada",
                   details: int = 10, delay: float = 4.0) -> list[dict]:
    """LinkedIn's public job search, as a signed-out visitor sees it: one page of results per title, then the text of up to
    `details` postings not seen before. Requests are `delay` seconds apart. Being refused (a 403, 429 or 999, or a redirect to
    the sign-in wall) stops LinkedIn for a day: no retry, no proxy, no sign-in."""
    if (store.kv_get("job_state", "linkedin") or {}).get("paused_until", 0) > time.time():
        return []
    found: dict[str, dict] = {}
    asked = 0

    async def get(path: str, **params):
        nonlocal asked
        if asked:
            await asyncio.sleep(delay)
        asked += 1
        r = await c.get(LI + path, params=params or None, headers=LI_UA)
        if r.status_code in (403, 429, 999) or re.search(r"authwall|/login|/checkpoint", str(r.url)):
            store.kv_put("job_state", "linkedin", {"paused_until": time.time() + 86400, "why": f"refused ({r.status_code})"})
            raise PermissionError("linkedin refused")
        return r.text if r.status_code == 200 else ""

    try:
        for t in titles:
            page = await get("seeMoreJobPostings/search", keywords=t, location=where, f_TPR=f"r{days * 86400}", start=0)
            for card in page.split("<li")[1:]:
                num = re.search(r"jobPosting:(\d+)", card)
                part = lambda cls, tag: unescape(_text((re.search(cls + r"[^>]*>(.*?)</" + tag + ">", card, re.S) or [None, ""])[1]))
                if not num or not part("base-search-card__title", "h3"):
                    continue
                found.setdefault(num.group(1), {
                    "id": jid("linkedin", num.group(1)), "source": "LinkedIn", "title": part("base-search-card__title", "h3"),
                    "company": part("base-search-card__subtitle", "h4"), "location": part("job-search-card__location", "span"),
                    "url": f"https://www.linkedin.com/jobs/view/{num.group(1)}", "description": "",
                    "posted": (re.search(r'datetime="(\d{4}-\d\d-\d\d)"', card) or [None, ""])[1]})
        ends = [t.split()[-1].lower() for t in titles]
        fresh = [n for n, j in found.items() if not store.kv_has("jobs", j["id"]) and any(e in j["title"].lower() for e in ends)]
        for n in fresh[:details]:
            m = re.search(r"show-more-less-html__markup[^>]*>(.*?)</div>", await get(f"jobPosting/{n}"), re.S)
            found[n]["description"] = unescape(_text(m.group(1)))[:6000] if m else ""
    except PermissionError:
        pass
    except Exception:
        pass
    return list(found.values())


async def still_open(c: httpx.AsyncClient, job: dict) -> bool:
    """False only when the posting's own page says it is gone (404 or 410); anything unclear counts as open."""
    url = job.get("url") or ""
    if not url.startswith("http") or "linkedin.com" in url:
        return True
    try:
        return (await c.get(url)).status_code not in (404, 410)
    except Exception:
        return True


def known_companies(store, prof: dict) -> list[dict]:
    """The career pages to read: the ones in config, then the ones found from postings' own links."""
    listed = list(prof.get("target_companies", []))
    have = {(c.get("ats", "greenhouse"), c["slug"].lower()) for c in listed}
    more = [c for c in store.kv_list("job_companies", limit=500) if (c.get("ats"), str(c.get("slug", "")).lower()) not in have]
    return listed + [{"name": c.get("name") or c["slug"], "ats": c["ats"], "slug": c["slug"]} for c in more[:int(prof.get("discover_max", 40))]]


def note_companies(store, jobs: list[dict]) -> int:
    added = 0
    for j in jobs:
        ref = ats_ref(j.get("url", ""))
        if ref and not store.kv_has("job_companies", f"{ref[0]}:{ref[1].lower()}"):
            store.kv_put("job_companies", f"{ref[0]}:{ref[1].lower()}", {"ats": ref[0], "slug": ref[1], "name": j.get("company") or ref[1], "found": time.time()})
            added += 1
    return added


def seen_before(store, job: dict) -> str:
    """The id of an earlier posting that is this same job (another source, another link, or listed again), or "".
    A job not seen before is written down under its keys."""
    keys = same_keys(job)
    for k in keys:
        was = store.kv_get("job_keys", k)
        if was and was.get("id") != job["id"] and was.get("at", 0) > time.time() - 90 * 86400:
            return was["id"]
    for k in keys:
        store.kv_put("job_keys", k, {"id": job["id"], "at": time.time()})
    return ""


async def jobbank_alerts(c: httpx.AsyncClient, store, cfg) -> list[dict]:
    """Job Bank alert emails (categorised 'jobs' by the Email Manager) -> posting links -> posting pages."""
    from ..services import mailcal
    from .email import accounts
    accts = {a["id"]: a for a in accounts(cfg.master("email").options)} if cfg else {}
    out, links = [], []
    for e in store.kv_list("emails", since=time.time() - 3 * 86400):
        if e.get("category") == "jobs" and "jobbank" in (e.get("from", "") + e.get("snippet", "")).lower() and not e.get("scouted"):
            body = e.get("snippet", "")
            if e.get("account") in accts:
                try:
                    body = await mailcal.get_body(accts[e["account"]], e["id"], limit=40000)
                except Exception:
                    pass
            links += re.findall(r"https://www\.jobbank\.gc\.ca/jobsearch/jobposting/\d+", body)
            store.kv_put("emails", e["_key"], {**{k: v for k, v in e.items() if k not in ("_key", "_ts")}, "scouted": True})
    for url in dict.fromkeys(links):
        try:
            r = await c.get(url, headers=UA)
            m = re.search(r"<title>(.*?)</title>", r.text, re.S)
            title = _text(m.group(1)).split(" - ")[0] if m else "Job Bank posting"
            out.append({"id": jid("jobbank", url), "source": "Job Bank", "title": title, "company": "", "location": "", "url": url, "description": _text(r.text)[:6000]})
        except Exception:
            continue
    return out


# Places that mean Ontario when a posting names only the city (names shared with well-known places elsewhere are left out)
ONTARIO_CITIES = ("toronto", "windsor", "leamington", "ottawa", "mississauga", "brampton", "hamilton", "kitchener", "waterloo", "markham",
                  "vaughan", "oakville", "burlington", "guelph", "barrie", "sudbury", "thunder bay", "oshawa", "richmond hill", "scarborough",
                  "north york", "etobicoke", "sarnia", "st. catharines", "niagara", "kanata", "chatham-kent", "greater toronto", "gta")


def in_ontario(job: dict, remote_ok: bool = True) -> bool:
    """Is this job in Ontario? On site or hybrid: the place must be in Ontario. Remote: only with `remote_ok`, and only when
    the posting says it is open to Canada or Ontario (a remote job open to "anywhere" or to other countries does not count)."""
    loc = (job.get("location") or "").lower()
    if not loc.strip():                                   # no place given (a Job Bank alert page): go by the top of the posting
        loc = (job.get("description") or "")[:600].lower()
    ontario = bool(re.search(r"\bontario\b|,\s*on\b|\(on\)", loc)) or any(c in loc for c in ONTARIO_CITIES)
    if "remote" in loc and not ontario:
        return remote_ok and "canada" in loc
    return ontario


def rule_score(job: dict, prof: dict) -> int:
    t, d = job["title"].lower(), (job["title"] + " " + job.get("description", "")).lower()
    title = 40 if any(w.lower() in t for w in prof.get("target_titles", [])) else 15 if any(w.split()[-1].lower() in t for w in prof.get("target_titles", [])) else 0
    skills = min(40, 8 * sum(1 for s in prof.get("skills", []) if has(s, job["title"] + " " + job.get("description", ""))))
    if len(job.get("description") or "") < 200:           # a feed that gives the title only: half marks until the text is known
        skills = max(20, skills)
    locs = [l.split(",")[0].lower() for l in prof.get("locations", [])]
    loc = 20 if any(l in (job.get("location", "") + " " + d[:400]).lower() for l in locs + ["remote"]) else 0
    bad = any(x.lower() in d for x in prof.get("exclude", []))
    return 0 if bad else title + skills + loc


FEEDS = ("Job Bank", "LinkedIn", "Himalayas", "Jobicy", "Adzuna")


# ---------- agents ----------
class JobScout(SubAgent):
    name, tier, note = "Job Scout", "API", "Job Bank · LinkedIn · career pages"

    async def run(self, ctx):
        prof, store, llm = ctx["options"], ctx["store"], ctx.get("llm")
        titles, days = prof.get("target_titles", []), int(prof.get("max_days_old", 3))
        free = prof.get("free_sources", ["jobbank", "himalayas", "jobicy"])
        async with httpx.AsyncClient(timeout=25, headers=UA, follow_redirects=True) as c:
            found = (await adzuna(c, titles[:int(prof.get("adzuna_titles", 4))], prof.get("adzuna_where", "Ontario"), days)
                     + await company_boards(c, known_companies(store, prof)) + await jobbank_alerts(c, store, ctx.get("cfg"))
                     + (await linkedin(c, store, titles[:int(prof.get("linkedin_titles", 4))], days, prof.get("linkedin_where", "Ontario, Canada"),
                                       int(prof.get("linkedin_details", 10)), float(prof.get("linkedin_delay", 4))) if prof.get("linkedin") else [])
                     + (await jobbank_feed(c, titles) if "jobbank" in free else [])
                     + (await himalayas(c, titles, days) if "himalayas" in free else [])
                     + (await jobicy(c, days) if "jobicy" in free else []))
        if not found and not (free or secret("ADZUNA_APP_ID") or prof.get("target_companies") or prof.get("linkedin")):
            return AgentResult("idle", "NOT SET UP", "Job Hunt: add Adzuna keys, target companies, or Job Bank alerts")
        found = list({j["id"]: j for j in found}.values())  # same posting from two searches counts once
        if str(prof.get("region", "")).lower() == "ontario":    # Mani's rule: Ontario only
            found = [j for j in found if in_ontario(j, bool(prof.get("remote_ok", True)))]
        if prof.get("discover_companies", True):
            note_companies(store, found)
        fresh = sorted((j for j in found if not store.kv_has("jobs", j["id"])), key=lambda j: -len(j.get("description") or ""))
        new, again, gated = [], 0, 0
        for j in fresh:
            first = seen_before(store, j)
            if first:                                           # the same job from another source, or listed again
                again += 1
                was = store.kv_get("jobs", first) or {}
                if was and time.time() - was.get("found", time.time()) > 7 * 86400:
                    store.kv_put("jobs", first, {**was, "reposts": was.get("reposts", 0) + 1})
                store.kv_put("jobs", j["id"], {"id": j["id"], "title": j["title"], "company": j["company"], "source": j["source"],
                                               "status": "duplicate", "of": first, "found": time.time()})
                continue
            stop = gate(j, prof)
            if stop:                                            # read from the posting's own wording, before any scoring
                gated += 1
                store.kv_put("jobs", j["id"], {**j, "score": 0, "why": stop, "status": "skipped", "found": time.time()})
                continue
            new.append(j)
        for j in new:
            fit = coverage(j, _master_resume(j["title"]) or "", prof.get("skills", []))
            j.update(score=rule_score(j, prof), why="rules", matched=fit["matched"], gaps=fit["gaps"], provisional=fit["provisional"])
        cand = sorted(new, key=lambda j: -j["score"])[:15]
        if llm and cand:
            try:
                res = await llm.json("Score each job 0-100 for this candidate and give a 10-word reason. " + FENCE_RULE + "\nCandidate: " + str(
                    {k: prof.get(k) for k in ("target_titles", "skills", "locations", "seniority")}) + "\nJobs:\n" + fence(str(
                    [{"i": i, "title": j["title"], "company": j["company"], "location": j["location"], "has": j["matched"], "lacks": j["gaps"],
                      "desc": j["description"][:700]} for i, j in enumerate(cand)]))
                    + "\nReturn [{i, score, why}].", tier="local", max_tokens=1500)
                for r in res or []:
                    if not cand[int(r["i"])]["provisional"]:      # with no text to read, the rules' half marks stand
                        cand[int(r["i"])].update(score=int(r["score"]), why=r.get("why", ""))
            except (LLMUnavailable, Exception):
                pass
        keep = [j for j in new if j["score"] >= int(prof.get("min_match", 70))]
        for j in new:
            store.kv_put("jobs", j["id"], {**j, "status": "match" if j in keep else "skipped", "found": time.time()})
        by: dict[str, int] = {}
        for j in found:
            src = j["source"] if j["source"] in FEEDS else "career pages"
            by[src] = by.get(src, 0) + 1
        paused = prof.get("linkedin") and (store.kv_get("job_state", "linkedin") or {}).get("paused_until", 0) > time.time()
        return AgentResult("done", f"{len(keep)} MATCHES", f"{len(found)} postings scanned"
                           + (" (" + ", ".join(f"{k} {v}" for k, v in by.items()) + ")" if by else "") + f" · {len(keep)} new matches"
                           + (f" · {again} already seen" if again else "") + (f" · {gated} ruled out" if gated else "")
                           + (" · LinkedIn refused a request and rests for a day" if paused else ""),
                           {"matches": [{"title": j["title"], "company": j["company"], "score": j["score"]} for j in keep[:5]]})


def resume_for(title: str = "") -> str:
    """Which of the resumes suits a posting: ai, analyst or software, judged by its title."""
    t = " " + re.sub(r"[^a-z]+", " ", title.lower()) + " "
    if any(w in t for w in (" ai ", " ml ", " llm ", " machine learning ", " automation ", " agent", " genai ", " generative ")):
        return "ai"
    if any(w in t for w in (" analyst", " analytics ", " bi ", " business intelligence ", " data ", " reporting ")):
        return "analyst"
    return "software"


def _master_resume(title: str = "") -> str | None:
    d = ROOT / "vault" / "resume"
    for p in (d / f"{resume_for(title)}.md", d / "master.md"):
        if p.exists():
            return p.read_text()
    return None


def _app_dir(job: dict) -> Path:
    d = ROOT / "data" / "applications" / re.sub(r"[^a-z0-9]+", "-", f"{job['company']}-{job['title']}".lower())[:60]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_docx(path: Path, md: str) -> bool:
    try:
        from docx import Document
    except ImportError:
        return False
    doc = Document()
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            doc.add_heading(s.lstrip("# "), level=min(3, len(s) - len(s.lstrip("#"))))
        elif s.startswith(("- ", "* ")):
            doc.add_paragraph(s[2:], style="List Bullet")
        else:
            doc.add_paragraph(s)
    doc.save(path)
    return True


class ResumeTailor(SubAgent):
    name, tier, note = "Resume Tailor", "CLOUD", "never invents experience"

    async def run(self, ctx):
        store, llm, n = ctx["store"], ctx.get("llm"), int(ctx["options"].get("max_packages_per_cycle", 2))
        master = _master_resume()
        if not master:
            return AgentResult("idle", "NEEDS RESUME", "Put your resume at vault/resume/master.md")
        todo = [j for j in store.kv_list("jobs") if j.get("status") == "match"][:n]
        if not todo:
            return AgentResult("done", "UP TO DATE", "No new matches to tailor")
        opts = ctx["options"]
        tier, wait = opts.get("tailor_tier", "cloud"), float(opts.get("tailor_timeout", 150))
        tailored, gone, notes = 0, 0, []
        async with httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True) as c:
            alive = [await still_open(c, j) for j in todo]
        for j, open_ in zip(todo, alive):
            if not open_:                                       # taken down since it was found: no package for a closed posting
                gone += 1
                j["status"] = "expired"
                store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
                continue
            # The resume for this kind of role is the package's resume as it stands. A model may reorder and reword it for the
            # posting; if it doesn't answer in time, fails, or hands back a cut-down text, the resume goes in as Mani wrote it.
            base = _master_resume(j["title"]) or master
            head, body = split_contact(base)
            md, did, why = base, False, "the model didn't answer in time"
            gaps = j.get("gaps") or []
            if not (j.get("description") or "").strip():
                why = "the posting came with no description"
            elif llm:
                try:
                    out = await asyncio.wait_for(llm.complete(
                        "Tailor this resume to the job. Reorder and reword bullets to bring forward the relevant experience; keep every "
                        "section, role, date and project, and every heading line exactly as it is. Do NOT add any skill, job, degree, number "
                        "or claim that isn't in the original." + (f" The resume does not show these, so never claim them: {', '.join(gaps)}." if gaps else "")
                        + " Return the whole resume in Markdown, nothing else. " + FENCE_RULE + "\n\n"
                        f"JOB: {j['title']} at {j['company']}\n{fence(j['description'][:3500])}\n\nRESUME:\n{body}", tier=tier, max_tokens=3200), wait)
                    wrong = unsupported(body, out) if len(out.split()) >= 0.6 * len(body.split()) else ["comes back cut down"]
                    if wrong:                                   # it says something the resume doesn't: the resume as written goes in
                        why = "the reworded one " + "; ".join(wrong[:3])
                    else:
                        md, did = head + out.strip() + "\n", True
                except Exception:   # no model, a timeout, a refused request: the resume as written still makes a package
                    pass
            tailored += did
            if not did:
                notes.append(why)
            d = _app_dir(j)
            (d / "resume.md").write_text(md)
            _write_docx(d / "resume.docx", md)
            j.update(status="tailored", folder=str(d), resume=resume_for(j["title"]), reworded=did, tailor_note="" if did else why)
            store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
        made = len(todo) - gone
        plain = made - tailored
        return AgentResult("done", f"{made} READY", f"{made} resumes ready: {tailored} reworded for the posting"
                           + (f", {plain} as written ({'; '.join(dict.fromkeys(notes))})" if plain else "")
                           + (f" · {gone} posting(s) taken down since, dropped" if gone else ""))


def split_contact(md: str) -> tuple[str, str]:
    """The name and contact lines at the top of a resume, and the rest. Only the rest goes to a model; the top is put back as is."""
    i = md.find("\n## ")
    return (md[:i + 1], md[i + 1:]) if i > 0 else ("", md)


class CoverLetterWriter(SubAgent):
    name, tier, note = "Cover Letter Writer", "CLOUD", "short and specific"

    async def run(self, ctx):
        store, llm = ctx["store"], ctx.get("llm")
        master = _master_resume()
        await_t = [j for j in store.kv_list("jobs") if j.get("status") in ("match", "tailored") and not j.get("letter")][:3]
        if not master or not llm or not await_t:
            return AgentResult("idle" if not (master and llm) else "done", "WAITING" if not (master and llm) else "UP TO DATE", "nothing to write")
        done = 0
        for j in await_t:
            resume = _master_resume(j["title"]) or master
            ask = (f"Write a 180-word cover letter from {ctx['cfg'].vision.owner} for {j['title']} at {j['company']}. Specific, warm, "
                   "no clichés, only facts from the resume. " + FENCE_RULE + "\n\nJOB:\n" + fence(j["description"][:3000]) + "\n\nRESUME:\n" + resume)
            try:
                letter = await llm.complete(ask, tier="cloud", max_tokens=600)
                wrong = unsupported(resume, letter, structure=False, numbers=False, names=False)
                if wrong:                                       # one more try with the slip named; what still stands is shown to Mani
                    letter = await llm.complete(ask + "\n\nYour last letter " + "; ".join(wrong) + ". Leave those out.", tier="cloud", max_tokens=600)
                    wrong = unsupported(resume, letter, structure=False, numbers=False, names=False)
                j["letter_note"] = "; ".join(wrong)
            except LLMUnavailable:
                break
            d = _app_dir(j)
            (d / "cover_letter.md").write_text(letter)
            _write_docx(d / "cover_letter.docx", letter)
            j.update(letter=True, folder=str(d))
            store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
            done += 1
        return AgentResult("done", f"{done} LETTERS", f"Wrote {done} cover letters")


class Outreach(SubAgent):
    name, tier, note = "Outreach", "CLOUD", "package for your OK"

    async def run(self, ctx):
        store, raised = ctx["store"], 0
        for j in store.kv_list("jobs"):
            if j.get("status") == "tailored" and j.get("letter"):
                request_approval(ctx, self.name, f"Application package: {j['title']} @ {j['company'] or j['source']} (fit {j['score']})",
                                 {"key": f"apply:{j['_key']}", "kind": "job_package", "job": j["_key"], "url": j["url"], "folder": j.get("folder")})
                j["status"] = "awaiting_ok"
                store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
                raised += 1
        waiting = sum(1 for j in store.kv_list("jobs") if j.get("status") == "awaiting_ok")
        return AgentResult("wait" if waiting else "done", f"{waiting} WAITING" if waiting else "CLEAR", f"{waiting} packages waiting for your OK")


class ApplicationTracker(SubAgent):
    name, tier, note = "Application Tracker", "QUICK", "stages from inbox + calendar"

    async def run(self, ctx):
        store, bus, opts, now = ctx["store"], ctx.get("bus"), ctx.get("options") or {}, time.time()
        legacy_approved(store)
        jobs = store.kv_list("jobs", limit=2000)
        mail = store.kv_list("emails", since=time.time() - 14 * 86400)
        wait, most, stale, nudged = float(opts.get("followup_days", 10)) * 86400, int(opts.get("followups", 2)), float(opts.get("stale_days", 60)) * 86400, 0
        for j in jobs:
            if j.get("status") in ("approved", "applied", "interview") and j.get("company"):
                for e in mail:
                    txt = (e.get("subject", "") + " " + e.get("snippet", "")).lower()
                    if j["company"].lower() in txt:
                        if re.search(r"interview|schedule a call|next steps", txt) and j["status"] != "interview":
                            j["status"] = "interview"
                        elif j["status"] == "approved" and re.search(r"application (was )?received|thank you for (applying|your application)", txt):
                            j.update(status="applied", applied_at=e.get("ts") or now)
                            j.setdefault("history", []).append({"status": "applied", "at": now, "by": "email"})
                        elif re.search(r"unfortunately|not moving forward|other candidates", txt):
                            j["status"] = "rejected"
                # No word since applying: a reminder after `followup_days`, at most `followups` of them, then the job is set aside.
                since, sent = j.get("followup_at") or j.get("applied_at") or j.get("found") or now, j.get("followups", 0)
                applied = j.get("applied_at") or j.get("found") or now
                if j["status"] == "approved":
                    pass
                elif j["status"] != "applied":
                    if sent and bus:
                        bus.clear_notice(f"followup:{j['_key']}")
                elif sent < most and now - since >= wait and nudged < 3:
                    nudged += 1
                    j.update(followups=sent + 1, followup_at=now)
                    if bus:
                        bus.notice(f"followup:{j['_key']}", f"No reply in {int((now - applied) / 86400)} days: a follow-up note to "
                                                           f"{j['company']} ({j['title']}) may help", j.get("url"))
                elif sent >= most and now - applied >= stale:
                    j["status"] = "stale"
                    if bus:
                        bus.clear_notice(f"followup:{j['_key']}")
                store.kv_put("jobs", j["_key"], {k: v for k, v in j.items() if k not in ("_key", "_ts")})
        stages = {s: sum(1 for j in jobs if j.get("status") == s) for s in ("match", "tailored", "awaiting_ok", "approved", "applied", "interview", "offer", "rejected")}
        moved = await to_drive(ctx)
        recent = [j for j in jobs if j.get("found", 0) > time.time() - 86400 and j.get("status") != "skipped"]
        parts = [f"{len(recent)} new matches"] + [f"{v} {k.replace('_', ' ')}" for k, v in stages.items() if v and k not in ("match",)] + ([moved] if moved else [])
        scout = ctx["results"].get("Job Scout")
        if scout and scout.status == "idle" and not jobs:
            parts = [scout.summary]
        return AgentResult("done", f"{stages['interview']} INTERVIEW" if stages["interview"] else "TRACKING", " · ".join(parts), {"stages": stages})


class InterviewPrep(SubAgent):
    name, tier, note = "Interview Prep", "DEEP", "research + STAR answers"

    async def run(self, ctx):
        store, llm = ctx["store"], ctx.get("llm")
        todo = [j for j in store.kv_list("jobs") if j.get("status") == "interview" and not j.get("prep")]
        if not todo:
            return AgentResult("idle", "STANDBY", "No interviews to prep")
        if not llm:
            return AgentResult("idle", "NEEDS AI", "Prep needs LM Studio or a cloud model")
        for j in todo[:1]:
            notes = await llm.complete("Prepare interview notes: company snapshot, 8 likely questions, and STAR answers using only this resume.\n\n"
                                       + FENCE_RULE + f"\n\nJOB: {j['title']} at {j['company']}\n{fence(j['description'][:3000])}\n\nRESUME:\n{_master_resume(j['title']) or ''}", tier="cloud", max_tokens=1800)
            p = ROOT / "vault" / "interviews"
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{re.sub(r'[^A-Za-z0-9]+', '-', j['company'])}.md").write_text(notes)
            j["prep"] = True
            store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
        return AgentResult("done", "PREPPED", f"Interview notes ready for {todo[0]['company']}")


# The tracker, like LinkedIn's "My Jobs" (Mani, 2026-10-18): approving a package makes it `approved` (ready, not yet sent);
# Mani marks it applied once he has submitted it, then interview, offer, rejected or archived (dashboard desk, Telegram /jobs).
TRACK = {"approved": "Approved", "applied": "Applied", "interview": "Interview", "offer": "Offer", "rejected": "Rejected", "archived": "Archived"}
NEXT = {"approved": ("applied", "archived"), "applied": ("interview", "offer", "rejected", "archived"), "interview": ("offer", "rejected", "archived"),
        "offer": ("archived",), "rejected": ("archived",), "archived": ("applied",)}
KEPT = ("approved", "applied", "interview", "offer")       # packages of these go to Drive and leave the Mac
DRIVE_ACCOUNT = "drive-backup"                              # the same Google sign-in as the video backups (oauth provider "gdrive")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=120)


def legacy_approved(store) -> int:
    """Before 2026-10-18 approving a package set it `applied`. Such a record (applied, no history, not added by Mani) was only
    approved: it becomes `approved`, its follow-up count cleared, so Mani marks it applied when he has sent it. Returns the count."""
    n = 0
    for j in store.kv_list("jobs", limit=2000):
        if j.get("status") == "applied" and "history" not in j and j.get("source") != "added by you":
            key = j.pop("_key")
            j.update(status="approved", approved_at=j.pop("applied_at", None) or j.get("found"), history=[{"status": "approved", "at": time.time(), "by": "fix"}])
            for k in ("followups", "followup_at"):
                j.pop(k, None)
            store.kv_put("jobs", key, {k: v for k, v in j.items() if k != "_ts"})
            n += 1
    return n


def set_status(store, key: str, status: str, note: str | None = None) -> dict:
    """Mani's move of a tracked job (dashboard or Telegram). ValueError for an unknown job or status."""
    if status not in TRACK:
        raise ValueError(f"status must be one of {', '.join(TRACK)}")
    j = store.kv_get("jobs", key)
    if not j:
        raise ValueError("no such job")
    now = time.time()
    j["status"] = status
    j.setdefault("history", []).append({"status": status, "at": now})
    if status == "applied" and not j.get("applied_at"):
        j["applied_at"] = now                               # follow-up reminders count from here
    if note is not None:
        j["note"] = note.strip()[:500]
    store.kv_put("jobs", key, j)
    return {**j, "_key": key}


async def track(store, url: str, title: str = "", company: str = "", client=None) -> dict:
    """A job Mani applied to outside VISION, added as `applied`. Only its public page is read, for a title if none is given;
    Indeed is never touched."""
    url = (url or "").strip()
    if not re.match(r"https?://", url):
        raise ValueError("give the posting's link (https://...)")
    if re.search(r"(^|\.)indeed\.", url.split("/")[2].lower()):
        raise ValueError("VISION never touches Indeed: add it with a title instead of the link")
    key = "track:" + hashlib.sha1(url.encode()).hexdigest()[:12]
    if store.kv_get("jobs", key):
        raise ValueError("already tracked")
    if not title:
        try:
            async with (client or _client)() as c:
                r = await c.get(url, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', r.text) or re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.I)
            title = unescape(m.group(1)).strip() if m else ""
        except httpx.HTTPError:
            pass
    now = time.time()
    j = {"id": key, "title": (title or url.split("/")[2])[:160], "company": company.strip(), "url": url, "source": "added by you",
         "status": "applied", "found": now, "applied_at": now, "history": [{"status": "applied", "at": now}]}
    store.kv_put("jobs", key, j)
    return {**j, "_key": key}


async def to_drive(ctx: dict, client=None) -> str:
    """Approved and later packages go to Drive, Vision/Jobs/<package folder>; each file is checked by size and MD5, and only
    then is the local folder removed (Mani, 2026-10-18: "not in local"). No sign-in, a full Drive or an error = the files stay
    and the Application Tracker tries again on its next run."""
    store, bus = ctx["store"], ctx.get("bus")
    todo = [j for j in store.kv_list("jobs", limit=2000) if j.get("status") in KEPT and not j.get("drive") and j.get("folder") and Path(j["folder"]).is_dir()]
    if not todo:
        return ""
    try:
        token = await oauth.access_token(DRIVE_ACCOUNT, "gdrive")
    except oauth.AuthNeeded:
        if bus:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice("gdrive-backup", gdrive.SIGN_IN, f"http://127.0.0.1:{port}/auth/gdrive/login?account={DRIVE_ACCOUNT}")
        return "packages wait for a Drive sign-in"
    if bus:
        bus.clear_notice("gdrive-backup")
    done = 0
    try:
        async with (client or _client)() as c:
            for j in todo:
                d = Path(j["folder"])
                fid = await gdrive.vision_path(c, token, "Jobs", d.name)
                files = [await gdrive.upload(c, token, f, f.relative_to(d).as_posix().replace("/", " - "), fid,
                                             mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                         for f in sorted(d.rglob("*")) if f.is_file()]
                j["drive"] = {"id": fid, "url": gdrive.folder_url(fid), "folder": f"{gdrive.TOP}/Jobs/{d.name}", "files": files, "at": time.time()}
                shutil.rmtree(d, ignore_errors=True)        # every file is in Drive and matches
                j["local_removed"] = time.time()
                store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
                done += 1
    except gdrive.DriveFull:
        if bus:
            bus.notice("gdrive-full", "Google Drive is full: job packages stay on the Mac until there is room", None)
        return f"Drive is full; {done} packages moved"
    except (gdrive.DriveError, httpx.HTTPError) as e:
        return f"Drive upload stopped: {e}"[:160]
    return f"{done} packages moved to Drive" if done else ""


async def approve_package(row: dict, decision: str, ctx: dict) -> str:
    store, p = ctx["store"], row["payload"]
    j = store.kv_get("jobs", p["job"])
    if not j:
        return "job not found"
    if decision != "approved":
        j["status"] = "passed"
        store.kv_put("jobs", p["job"], j)
        return "skipped"
    set_status(store, p["job"], "approved")
    note = await to_drive(ctx)
    j = store.kv_get("jobs", p["job"]) or j
    where = f"files in Drive: {j['drive']['folder']}" if j.get("drive") else f"files in {p.get('folder')}"
    ctx["bus"].notice(f"apply:{p['job']}", f"Submit your application: {j['title']} @ {j['company'] or j['source']} ({where}), then mark it applied", p["url"])
    return "approved: open the posting and submit" + (f" ({note})" if note else "")


APPROVAL_HANDLERS = {"job_package": approve_package}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Job Scout": JobScout(), "Resume Tailor": ResumeTailor(), "Cover Letter Writer": CoverLetterWriter(), "Outreach": Outreach(),
            "Application Tracker": ApplicationTracker(), "Interview Prep": InterviewPrep()}
