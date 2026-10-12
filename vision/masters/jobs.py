"""Job Hunt (live): Job Scout -> Resume Tailor + Cover Letter Writer -> YOU -> Outreach -> Application Tracker
(reporter) -> Interview Prep.

Sources (no LinkedIn, no Indeed):
- Job Bank Canada alert emails (set up alerts at jobbank.gc.ca; the Email Manager reads them)
- Adzuna API (ADZUNA_APP_ID / ADZUNA_APP_KEY; 25 test calls free, then £8 a month as of 2026-10)
- Company career pages on Greenhouse, Lever, Ashby, Workable and SmartRecruiters (public job feeds), listed in config
- Free public feeds, no key (`free_sources`): Job Bank's own search feed (Ontario, the last couple of days), Himalayas and
  Jobicy (remote jobs open to Canada). Any of them may change or close; each fails on its own.

Resumes: vault/resume/analyst.md, software.md and ai.md, picked by the posting's title (`resume_for`); master.md is the fallback.

VISION never applies for you. It prepares the package; you submit it from the posting's page.
Your master resume lives at vault/resume/master.md; tailored versions never invent experience.
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

import httpx

from ..agents import AgentResult, SubAgent, request_approval
from ..config import ROOT, secret
from ..services.llm import LLMUnavailable

UA = {"User-Agent": "VISION job scout (personal use)"}


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
    skills = min(40, 8 * sum(1 for s in prof.get("skills", []) if s.lower() in d))
    locs = [l.split(",")[0].lower() for l in prof.get("locations", [])]
    loc = 20 if any(l in (job.get("location", "") + " " + d[:400]).lower() for l in locs + ["remote"]) else 0
    bad = any(x.lower() in d for x in prof.get("exclude", []))
    return 0 if bad else title + skills + loc


# ---------- agents ----------
class JobScout(SubAgent):
    name, tier, note = "Job Scout", "API", "Job Bank · Adzuna · career pages"

    async def run(self, ctx):
        prof, store, llm = ctx["options"], ctx["store"], ctx.get("llm")
        titles, days = prof.get("target_titles", []), int(prof.get("max_days_old", 3))
        free = prof.get("free_sources", ["jobbank", "himalayas", "jobicy"])
        async with httpx.AsyncClient(timeout=25, headers=UA, follow_redirects=True) as c:
            found = (await adzuna(c, titles[:int(prof.get("adzuna_titles", 4))], prof.get("adzuna_where", "Ontario"), days)
                     + await company_boards(c, prof.get("target_companies", [])) + await jobbank_alerts(c, store, ctx.get("cfg"))
                     + (await jobbank_feed(c, titles) if "jobbank" in free else [])
                     + (await himalayas(c, titles, days) if "himalayas" in free else [])
                     + (await jobicy(c, days) if "jobicy" in free else []))
        if not found and not (free or secret("ADZUNA_APP_ID") or prof.get("target_companies")):
            return AgentResult("idle", "NOT SET UP", "Job Hunt: add Adzuna keys, target companies, or Job Bank alerts")
        found = list({j["id"]: j for j in found}.values())  # same posting from two searches counts once
        if str(prof.get("region", "")).lower() == "ontario":    # Mani's rule: Ontario only
            found = [j for j in found if in_ontario(j, bool(prof.get("remote_ok", True)))]
        new = [j for j in found if not store.kv_has("jobs", j["id"])]
        for j in new:
            j["score"], j["why"] = rule_score(j, prof), "rules"
        cand = sorted(new, key=lambda j: -j["score"])[:15]
        if llm and cand:
            try:
                res = await llm.json("Score each job 0-100 for this candidate and give a 10-word reason.\nCandidate: " + str(
                    {k: prof.get(k) for k in ("target_titles", "skills", "locations", "seniority")}) + "\nJobs: " + str(
                    [{"i": i, "title": j["title"], "company": j["company"], "location": j["location"], "desc": j["description"][:700]} for i, j in enumerate(cand)])
                    + "\nReturn [{i, score, why}].", tier="local", max_tokens=1500)
                for r in res or []:
                    cand[int(r["i"])].update(score=int(r["score"]), why=r.get("why", ""))
            except (LLMUnavailable, Exception):
                pass
        keep = [j for j in new if j["score"] >= int(prof.get("min_match", 70))]
        for j in new:
            store.kv_put("jobs", j["id"], {**j, "status": "match" if j in keep else "skipped", "found": time.time()})
        return AgentResult("done", f"{len(keep)} MATCHES", f"{len(found)} postings scanned · {len(keep)} new matches",
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
        if not llm:
            return AgentResult("idle", "NEEDS AI", "Tailoring needs LM Studio or a cloud model")
        for j in todo:
            try:
                md = await llm.complete("Tailor this resume to the job. Reorder and reword to highlight relevant experience. "
                                        "Do NOT add any skill, job, degree, number or claim that isn't in the original. Keep it to one page in Markdown.\n\n"
                                        f"JOB: {j['title']} at {j['company']}\n{j['description'][:3500]}\n\nRESUME:\n{_master_resume(j['title'])}", tier="cloud", max_tokens=1800)
            except LLMUnavailable:
                return AgentResult("idle", "NEEDS AI", "Tailoring needs LM Studio or a cloud model")
            d = _app_dir(j)
            (d / "resume.md").write_text(md)
            _write_docx(d / "resume.docx", md)
            j.update(status="tailored", folder=str(d), resume=resume_for(j["title"]))
            store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
        return AgentResult("done", f"{len(todo)} TAILORED", f"Tailored {len(todo)} resumes")


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
            try:
                letter = await llm.complete(f"Write a 180-word cover letter from {ctx['cfg'].vision.owner} for {j['title']} at {j['company']}. Specific, warm, "
                                            "no clichés, only facts from the resume.\n\nJOB:\n" + j["description"][:3000] + "\n\nRESUME:\n" + (_master_resume(j["title"]) or master), tier="cloud", max_tokens=600)
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
        store = ctx["store"]
        jobs = store.kv_list("jobs", limit=2000)
        mail = store.kv_list("emails", since=time.time() - 14 * 86400)
        for j in jobs:
            if j.get("status") in ("applied", "interview") and j.get("company"):
                for e in mail:
                    txt = (e.get("subject", "") + " " + e.get("snippet", "")).lower()
                    if j["company"].lower() in txt:
                        if re.search(r"interview|schedule a call|next steps", txt) and j["status"] != "interview":
                            j["status"] = "interview"
                        elif re.search(r"unfortunately|not moving forward|other candidates", txt):
                            j["status"] = "rejected"
                store.kv_put("jobs", j["_key"], {k: v for k, v in j.items() if k not in ("_key", "_ts")})
        stages = {s: sum(1 for j in jobs if j.get("status") == s) for s in ("match", "tailored", "awaiting_ok", "applied", "interview", "rejected")}
        recent = [j for j in jobs if j.get("found", 0) > time.time() - 86400 and j.get("status") != "skipped"]
        parts = [f"{len(recent)} new matches"] + [f"{v} {k.replace('_', ' ')}" for k, v in stages.items() if v and k not in ("match",)]
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
                                       f"JOB: {j['title']} at {j['company']}\n{j['description'][:3000]}\n\nRESUME:\n{_master_resume(j['title']) or ''}", tier="cloud", max_tokens=1800)
            p = ROOT / "vault" / "interviews"
            p.mkdir(parents=True, exist_ok=True)
            (p / f"{re.sub(r'[^A-Za-z0-9]+', '-', j['company'])}.md").write_text(notes)
            j["prep"] = True
            store.kv_put("jobs", j.pop("_key"), {k: v for k, v in j.items() if k != "_ts"})
        return AgentResult("done", "PREPPED", f"Interview notes ready for {todo[0]['company']}")


async def approve_package(row: dict, decision: str, ctx: dict) -> str:
    store, p = ctx["store"], row["payload"]
    j = store.kv_get("jobs", p["job"])
    if not j:
        return "job not found"
    if decision != "approved":
        j["status"] = "passed"
        store.kv_put("jobs", p["job"], j)
        return "skipped"
    j["status"] = "applied"
    store.kv_put("jobs", p["job"], j)
    ctx["bus"].notice(f"apply:{p['job']}", f"Submit your application: {j['title']} @ {j['company'] or j['source']} (files in {p.get('folder')})", p["url"])
    return "package ready: open the posting and submit"


APPROVAL_HANDLERS = {"job_package": approve_package}


def build_agents(options: dict[str, Any], cfg=None) -> dict[str, SubAgent]:
    return {"Job Scout": JobScout(), "Resume Tailor": ResumeTailor(), "Cover Letter Writer": CoverLetterWriter(), "Outreach": Outreach(),
            "Application Tracker": ApplicationTracker(), "Interview Prep": InterviewPrep()}
