"""YouTube Manager (live): one Director per channel, each with its own crew.

    YouTube Manager -> <Channel> Director -> Story Scout -> Story Writer -> Screenplay Writer
        -> Keyword Generator + Voice Artist -> Footage Collector -> Footage Generator -> Editor
        -> Uploader (unlisted) -> Analytics Manager (reports to the Director) -> YOU, on YouTube

- Stories: Reddit's official API (REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET, asleep until the keys exist) and .txt files in
  inbox/stories/<channel id>/. Text files and Google Docs in the channel's Drive folder (`drive_folder`) are copied
  into that inbox first. Every story keeps its source URL. Quora is not used (no API, scraping blocked).
- A story is screened (rules, then the model), rewritten in the third person with names and places removed, and
  split into timed beats for a 1-2 minute Short that ends on the channel's subscribe line.
- Footage: Pexels / Pixabay (free stock), one clip or photo per beat; an online AI provider can fill the gaps
  (services/genmedia.py, off until a channel names one).
- The finished Short is a file in data/shorts/<channel id>/... and is uploaded as UNLISTED (Mani's choice: no approval
  before the upload). VISION sends the YouTube Studio link; making it public or deleting it is done by hand on YouTube.
  Sign-in: /auth/youtube/login?account=youtube-<channel id> (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET, YouTube Data API v3).
- The log (kv `yt_videos`) keeps source, script, screenplay, keywords, footage credits and the file for every Short.
"""

from __future__ import annotations

import asyncio
import calendar
import difflib
import random
import re
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..agents import AgentResult, Director, Stage, SubAgent
from ..config import ROOT
from ..services import bgm, fonts, gdrive, genmedia, gutenberg, oauth, reddit, sfx, stock_video, yt_analytics, yt_suggest, yt_trends
from . import shorts_edit

SEEN, LOG, DRIVE, STATE, PREMISES, CLASSICS = "yt_seen", "yt_videos", "yt_drive", "yt_state", "yt_premises", "yt_classics"
WPS = 2.5                 # narration pace used for planning; the real audio sets the final timing
GAP = 0.18                # pause after each beat, seconds
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
VIDEOS = API + "/videos"
CHANNEL = {"id": "knowidk", "name": "Know IDK Things", "director": "Know IDK Things Director",
           "shorts_per_day": 1, "subreddits": ["offmychest", "TrueOffMyChest"], "seconds": [60, 120],
           "voice_engine": "edge", "voice": "en-US-GuyNeural", "voice_speed": 0.95, "pause": 0.32, "outro": "Subscribe to our channel for more interesting stories.",
           "outro_query": "city lights at night", "logo": "", "caption_font": "", "generator": {},
           "privacy": "unlisted", "report_privacy": "approval", "category": "24", "synthetic_flag": True, "uploads_per_run": 4, "drive_folder": "", "voices": {}, "music": True, "music_volume": 0.12, "ending": "hopeful", "originals": False, "original_genres": ["life"],
           "publish_times": ["06:00", "12:00", "18:00", "00:00"], "create_after": "",
           "classics": [], "classics_per_day": 1, "playlists": {}, "viewer_comments": False, "cta": "", "long": {},
           "motion": True, "caption_styles": True, "sfx": True, "sfx_volume": 0.35, "quick": {},
           "double_down": True, "double_down_after": 12, "explore": 0.15, "trends": True, "trend_region": "US",
           "daily_mix": {}, "mix_auto": True, "mix_min_videos": 6, "mix_days": 28,
           "keep_local": False, "backup": False, "backup_folder": "", "diagrams": [], "lessons": False, "lesson_shorts": False, "lesson_channels": [], "transcripts_per_day": 10, "lesson_model": "", "lesson_tamil_model": "qwen/qwen3.8-27b"}
# Original stories: a premise is built from one of each, so no two start from the same place (20 x 12 x 10 x 10 combinations).
THEMES = ["a family secret", "a betrayal by a close friend", "a lie that grew too big", "a second chance that felt undeserved", "a debt never repaid",
          "an inheritance dispute", "a workplace mistake hidden for years", "a kindness kept secret", "a marriage on autopilot", "jealousy of a sibling",
          "a promise made to a dying parent", "taking credit for someone else's work", "walking away from a wedding", "a friendship ended over money",
          "an apology never sent", "pretending to be successful", "a chance meeting with an ex", "a neighbour badly misjudged",
          "quitting a job without telling the family", "a small act of revenge, regretted"]
SETTINGS = ["a small town", "a big-city apartment block", "a family business", "a hospital night shift", "a long-distance bus ride", "a university residence",
            "a wedding reception", "a gathering after a funeral", "an office after hours", "a village festival", "a first job abroad", "a shared taxi home"]
TELLERS = ["a woman in her thirties", "a man in his forties", "a young man just out of college", "a grandmother", "a single father", "a newly married woman",
           "a retired teacher", "a night-shift nurse", "a delivery driver", "an eldest daughter"]
STRUGGLES = ["starting over at fifty after losing a job", "failing the same exam twice", "a small shop a month from closing", "an injury that ended a sport",
             "learning to read as an adult", "the first lonely year in a new country", "a stammer and a job that needs speaking", "a manuscript rejected thirty times",
             "caring for a sick parent while studying at night", "paying off a debt that felt endless", "going back to school with teenagers", "a business partner who walked away",
             "stage fright before a first performance", "training for a race after years of illness", "raising two children on one small wage", "a farm after a ruined harvest"]
LIFTS = ["one sentence from a teacher", "a small habit kept every single day", "a second attempt nobody expected", "help from a stranger", "a letter kept in a wallet",
         "a promise made to a child", "the worst day turning out to be the start", "watching someone older try again", "a plain notebook of small wins", "a neighbour's quiet example"]
SCIENCE = {
    "space": ["how a star is born and how it dies", "why the Moon always shows us the same face", "the journey of the Voyager probes", "what a black hole's edge is",
              "why Mars is red", "what Saturn's rings are made of", "why a day on Venus is longer than its year", "how sunlight reaches Earth", "what causes the auroras",
              "where comets come from and why they grow tails", "how astronauts sleep and eat in orbit", "why we only ever see the past when we look at the stars"],
    "earth": ["how mountains rise", "why volcanoes erupt", "the journey of a single raindrop", "what causes earthquakes", "why the sky is blue and sunsets are red",
              "how lightning forms", "how a river carves a canyon", "how fossils form", "why we have seasons", "how Earth's magnetic field shields us",
              "how deserts form", "what the ice ages left behind"],
    "forests": ["how trees share food through fungi underground", "how a tree lifts water to its top", "why leaves change colour in autumn", "how a forest returns after fire",
                "the journey of a seed", "the layers of a rainforest", "how tree rings record the years", "how bees and flowers depend on each other",
                "what happens to a fallen log", "how mangroves live in salt water", "why old forests store so much carbon", "how a single fig tree feeds a forest"],
    "oceans": ["what happens when a whale dies and sinks", "life around deep-sea vents", "how coral reefs are built", "the great ocean currents", "why some sea creatures glow",
               "what causes the tides", "why the sea is salty", "the midnight zone of the deep sea", "how sea turtles find their way home", "how tiny plankton make the air we breathe",
               "the hidden forests of kelp", "how an octopus thinks and hides"]}
# The new channels' subject banks (Mani, 2026-10-19: Cosmic Roadster = space, Know Body Things = body and mind, Camping on Satellites =
# geography and maps). Each subject is planned once while others are unused, like SCIENCE.
SPACE = {
    "planets": ["why Jupiter has a storm bigger than Earth", "why Uranus spins on its side", "what it would be like to stand on Titan", "why Mercury is not the hottest planet",
                "how Saturn could float in water", "why Mars has the tallest volcano", "what is inside Jupiter", "why Neptune has the fastest winds",
                "how we found Neptune with maths", "why Venus spins backwards", "what makes Earth's Moon unusual", "why Pluto stopped being a planet"],
    "moons": ["Europa's hidden ocean", "Io, the most volcanic world", "why the Moon is drifting away from Earth", "Enceladus and its ice geysers",
              "how the Moon was probably formed", "why we have tides", "Phobos, the moon that will fall", "how many moons Saturn has and why it keeps changing"],
    "stars": ["how big the biggest stars are", "what a neutron star is", "why stars twinkle but planets do not", "what a supernova leaves behind",
              "why the Sun is white, not yellow", "how long sunlight takes to reach us", "what a red dwarf is", "how stars make the elements in our bodies",
              "what a pulsar is", "why some stars are double"],
    "black holes": ["what happens at a black hole's event horizon", "how the first black hole image was made", "spaghettification explained",
                    "the black hole at the centre of our galaxy", "why black holes are not cosmic vacuum cleaners", "how black holes are found when they give no light"],
    "galaxies and the universe": ["how big the Milky Way is", "the Andromeda galaxy coming toward us", "what the cosmic microwave background is",
                                  "why the night sky is dark", "how we measure distances to stars", "what dark matter is thought to be", "how old the universe is and how we know",
                                  "what a light-year really is", "why the universe is expanding"],
    "missions": ["the Apollo 11 landing step by step", "the Voyager Golden Record", "how the James Webb telescope unfolded", "the Mars rovers and what they found",
                 "the Hubble telescope's blurry start", "how the Rosetta probe landed on a comet", "the New Horizons flyby of Pluto", "how the International Space Station was built",
                 "the Apollo 13 rescue", "how a rocket gets to orbit"],
    "life in space": ["what happens to the human body in space", "why astronauts grow taller in orbit", "how astronauts go to the toilet in space", "what space smells like",
                      "why you cannot cry properly in space", "how a spacesuit keeps someone alive", "what astronauts eat", "how sleep works on the ISS"],
    "what if": ["what if the Sun disappeared", "what if Earth had rings like Saturn", "what if you fell into Jupiter", "what if the Moon vanished",
                "what if Earth stopped spinning", "what if you could see all of light", "what if a black hole passed by the Solar System", "what if we lived on Mars"],
}
BODY = {
    "heart and blood": ["how the heart beats without being told", "the journey of one red blood cell", "why blood is red but veins look blue", "how blood clots seal a cut",
                        "how far your blood travels in a day", "what blood pressure actually measures"],
    "lungs and breath": ["what happens in one breath", "why we yawn", "why we hiccup", "how the lungs pass oxygen into blood", "why you cannot hold your breath until you faint"],
    "gut": ["the journey of food through the gut", "why the stomach does not digest itself", "how the gut bacteria help us", "why your stomach growls",
            "how the liver cleans the blood", "what the appendix may be for"],
    "brain": ["how a memory is made", "why we dream", "what happens when you learn something new", "why we forget names", "how the brain sees colours that do not exist",
              "why time feels faster as we get older", "what deja vu is thought to be", "how the brain fills in the blind spot", "why we cannot tickle ourselves"],
    "mind": ["why habits are hard to break", "how fear works in the body", "why we remember embarrassing moments", "what the placebo effect is",
             "why we feel phantom phone vibrations", "how attention works", "why yawns are contagious", "why music gives us chills", "what flow state is"],
    "senses": ["how the eye focuses", "how the ear turns sound into signals", "why food tastes different with a cold", "how smell triggers memories",
               "how many senses we really have", "why we see optical illusions", "how balance works in the inner ear"],
    "bones and muscles": ["why bones are stronger than steel for their weight", "how many bones a baby has", "how muscles grow", "why muscles get sore",
                          "the strongest muscle in the body", "how joints move without wearing out", "why we get goosebumps"],
    "cells and DNA": ["how long DNA is if stretched out", "how cells copy themselves", "why we age", "how the immune system remembers", "what a fever does",
                      "how skin heals a wound", "why fingerprints are unique"],
    "sleep": ["what happens in each stage of sleep", "why we need sleep at all", "why we twitch as we fall asleep", "what sleep paralysis is"],
}
GEOGRAPHY = {
    "countries": ["the country with the most time zones", "countries that have no rivers", "the smallest country in the world", "countries inside other countries",
                  "the country that spans two continents", "why Chile is so long and thin", "the country with the most neighbours",
                  "the only country with a non-rectangular flag", "the most visited countries in the world"],
    "borders": ["the strangest borders on Earth", "where four countries meet at one point", "a town split between two countries", "the longest border in the world",
                "borders drawn along rivers", "why some borders are perfectly straight lines"],
    "rivers and lakes": ["the Amazon, the river with the most water", "why the Nile flows north", "the deepest lake on Earth", "rivers that flow backwards",
                         "where the Amazon begins", "the river that crosses ten countries"],
    "mountains and land": ["why Everest keeps growing", "the tallest mountain from base to peak", "the Sahara was once green", "the driest place on Earth",
                           "the lowest point on land", "how islands are born", "the largest island in the world", "the Ring of Fire"],
    "oceans and seas": ["the deepest point in the ocean", "the sea with no coast", "why the Dead Sea is so salty", "the ocean that is shrinking",
                        "the place furthest from land", "where two oceans meet and seem not to mix"],
    "maps and earth": ["why maps make Greenland look huge", "the true size of Africa", "how the continents were once joined", "where the equator crosses land",
                       "the North Pole and the South Pole compared", "why time zones zigzag", "the centre of the world's population"],
    "cities and people": ["the highest capital city", "cities on two continents", "the most crowded places on Earth", "the coldest inhabited town",
                          "capitals that moved", "why most people live near water"],
}
LEARN_KINDS = ("science", "money", "space", "body", "geography")      # learning videos: patterns, lesson hooks, their own banks
BANKS = {"science": SCIENCE, "space": SPACE, "body": BODY, "geography": GEOGRAPHY}
MONEY = ["how compound interest really grows money", "why an emergency fund comes before investing", "what an index fund is", "how a credit score is built",
         "what a credit card's minimum payment really costs", "the 50/30/20 budget", "paying off debt: smallest balance first or highest interest first",
         "what passive income costs before it pays", "how creators actually get paid for ads", "what it takes for a channel to be monetised",
         "how affiliate marketing pays, and when it doesn't", "the real margins of selling other people's products online", "pricing your first freelance job",
         "why lifestyle creep eats every raise", "what inflation does to savings", "the true cost of owning a car", "what an employer's pension match is worth",
         "how to ask for a raise", "auditing your subscriptions", "opportunity cost: what a purchase really costs", "why spreading money across investments lowers risk",
         "risk and return: why they travel together", "investing the same amount every month", "how banks make money from your deposit", "how insurance works",
         "the signs of a get-rich-quick scam", "why several small incomes take years to build", "skills that keep paying for decades", "renting or buying: what to compare",
         "saving for a known cost a little each month", "what a recession is", "why most small businesses run out of cash, not customers"]
# How a learning video keeps people to the end (Mani's table): each opens a question the viewer stays to have answered.
STRUCTURES = {
    "result_first": "Open with the end result in one sentence. Then say what was done to get it. Then give the lesson as plain steps, promising early that the "
                    "most useful step comes last, and keep it for last.",
    "belief_flip": "Open by stating something most people believe. Contradict it in the very next sentence. Spend the rest on why, and hold the full reason "
                   "until the end.",
    "better_best": "Open with a way that is better than what most people do. Then say there is a best way and that it is coming, to hook again. Deliver the "
                   "best way last.",
    "unless": "Open by saying the usual way will not work unless one thing is done. Do not name it at once: first show why the usual way fails, then give "
              "the one thing and exactly how to do it.",
    "only_if": "Open with the goal. Give the simple answer early, then at once add that it only works if it is done in one specific way. Keep that "
               "specific way for the end, and build towards it.",
    "not_a_not_b": "Open with the goal. Name a first thing people try and say plainly why it was not the answer. Name a second and why that was not it "
                   "either. Then give the third, the one that actually pays off, and why.",
    "most_do_least": "Open with the goal. Say what most people do for it, and that it gets the least results. Ask why. Answer the why last, with what to "
                     "do instead.",
}
# The pattern that loses viewers (first row of Mani's second table): the whole answer in the middle and nothing left to wait for.
HOLD_BACK = ("Never hand over the whole answer before the final third: every part must leave one question open, and the last part closes it.")
# Opening shapes that earn the first two seconds (from the hook sheets Mani collected, reworked for this channel: the
# narrator has no "I", so a story's shape is in the third person and a lesson's speaks to "you"; nothing here claims
# a personal result). A story opens in its shape; a lesson's shape goes to its title, since its script follows a pattern.
HOOKS = {
    "story": {
        "told_it_would_fail": "Everyone told her it would never work. Then it did.",
        "thought_wrong": "He thought ___ would make him happy. He was wrong.",
        "almost_quit": "The day she almost quit ___, and didn't.",
        "no_one_talks": "No one talks about how lonely ___ can feel.",
        "ignored_advice": "For years he ignored one piece of advice. He regrets it still.",
        "failure_taught": "One failure taught her more than every success before it.",
        "wished_known": "There was one thing he wished he had known before ___.",
        "worst_moment": "It was the worst moment of her year. It became the reason for everything after.",
        "quiet_ruin": "Something was quietly ruining ___, and he could not see it.",
        "used_to_think": "She used to think ___ was selfish. Now she sees it differently.",
    },
    "lesson": {
        "doing_it_wrong": "You're probably doing ___ wrong, and don't realise it",
        "not_working": "Why your ___ isn't working, and how to fix it",
        "truth_untold": "The truth no one tells you about ___",
        "new_to": "If you're new to ___, hear this first",
        "myth": "The myth about ___ that keeps most people stuck",
        "do_this_instead": "If you're doing ___, do this instead",
        "beginner_mistake": "The mistake nearly every beginner makes with ___",
        "overcomplicated": "Stop overcomplicating ___: the simple version",
        "start_calm": "How to start ___ without getting overwhelmed",
        "beginner_trap": "The biggest trap for beginners in ___, and how to avoid it",
        "three_mistakes": "Three mistakes that make ___ harder than it needs to be",
        "wish_known": "What most people wish they had known before starting ___",
    },
}
RETAIN_STORY = ("Keep them listening: the first sentence opens a question the listener needs answered; around the middle, one line raises the stakes again "
                "(\"and that was not the worst of it\"); the answer comes only at the end.")
PROMISE = re.compile(r"\b(guarantee\w*|get rich|rich quick|overnight|risk[- ]free|easy money|secret (trick|method)|in \d+ (days?|hours?|weeks?))\b|"
                     r"[$€£₹]\s?\d[\d,.]*\s?k?\s*(a|per|every|/)\s*(day|week|month|hour)\b", re.I)
# In the lesson itself, the thing never said is a promise made to the viewer (a myth being examined may be named freely).
TOLD_PROMISE = re.compile(r"\byou(?:'ll| will| can| could)?\s+(?:easily\s+|quickly\s+)?(?:make|earn|get|bank)\b[^.?!]{0,40}[$€£₹]\s?\d|"
                          r"\bguaranteed\s+(?:income|returns?|profits?|money|results?)\b|\b(?:will|is going to) make you rich\b", re.I)


def promises(title: str) -> bool:
    """A title that states an amount, a speed or a certainty of earning. Asked as an open question it explores the claim, which is allowed."""
    return bool(PROMISE.search(title)) and not title.strip().endswith("?")


ANGLES = ["as a journey followed from start to finish", "as a mystery that people slowly solved", "as a day in the life of one creature or thing",
          "as the answer to a question a child might ask", "as a story of something happening right now, unseen"]
GENRE_ASK = {
    "life": ("Invent premises for short true-to-life stories: an ordinary adult did or hid something, and it comes into the open. One premise per numbered "
                   "line below, using that line's ingredients. Believable everyday life; adults only; no names or real places; nothing sexual, no self-harm, no "
                   "violent crime.", "2-3 sentences: who, what they did or hid, what forces it out, what is at stake"),
    "motivational": ("Invent premises for short motivational stories: an ordinary adult faces a real difficulty and gets through it by their own effort, a step at a "
                     "time, with no luck, miracle or sudden riches. One premise per numbered line below, using that line's ingredients. Believable everyday life; "
                     "no names or real places; no self-harm.", "2-3 sentences: who, what they are up against, the low point, what they do about it"),
    "money": ("Plan short lessons about money that teach one thing well and honestly. One plan per numbered line below, on that line's subject. Use only "
              "established facts and principles that any standard personal-finance textbook gives; show what the thing costs or risks as well as what it "
              "gives; no promise of earnings, no income figures, no named shares, coins or products, nothing speculative.",
              "the question it answers, then the 3-4 established points it will make, in order, ending on the most useful one"),
    "science": ("Plan short science stories that teach one thing well. One plan per numbered line below, on that line's subject and told the way it says. Use only "
                "well-established facts of the kind found in a school textbook or an encyclopedia; no numbers or dates unless they are famous and certain; nothing "
                "speculative.", "the question it answers, then the 3-4 established facts it will tell, in order"),
    "space": ("Plan short space stories that teach one thing well. One plan per numbered line below, on that line's subject and told the way it says. Use only "
              "well-established astronomy of the kind found in a textbook, NASA or ESA; a 'what if' is a thought experiment built on real physics and must say so; "
              "no numbers or dates unless famous and certain; nothing speculative presented as fact.", "the question it answers, then the 3-4 established facts it will tell, in order"),
    "body": ("Plan short stories about how the human body and mind work, each teaching one thing well. One plan per numbered line below, on that line's subject. Use only "
             "well-established anatomy, physiology and well-replicated psychology of the kind found in a textbook; never health advice, treatment, diets, supplements or "
             "diagnosis; no numbers unless famous and certain.", "the question it answers, then the 3-4 established facts it will tell, in order"),
    "geography": ("Plan short stories about the world's geography that teach one thing well. One plan per numbered line below, on that line's subject. Use only "
                  "well-established facts of the kind an atlas or encyclopedia gives; no politics, no disputed borders or territories, no ranking of peoples, "
                  "religions or countries as better or worse; no numbers unless certain.", "the question it answers, then the 3-4 established facts it will tell, in order")}
GENRE_WRITE = {
    "life": ("Write an original, fictional true-to-life story from the premise below",
                   "- Third person, told like something a person carried for years and finally let out (\"she\", \"he\", \"they\"). Do not claim it is real "
                   "and do not say anyone shared or sent it.\n"
                   "- Believable, specific, everyday detail; build the tension step by step to the moment it comes out.\n"
                   "- Adults only. No personal names at all, and no real city, company or school. Nothing sexual, no self-harm, no violent crime.\n"),
    "motivational": ("Write an original, fictional motivational story from the premise below",
                     "- Third person (\"she\", \"he\", \"they\"). Do not claim it is real.\n"
                     "- Show the difficulty honestly, then the small, concrete steps that got them through; earned by effort, never by luck.\n"
                     "- No personal names, no real city, company or school. No self-harm. No preaching and no list of tips: the story carries the lesson.\n"),
    "money": ("Write a short, honest lesson about money from the plan below",
              "- Speak to the viewer as \"you\", plainly, like a friend who knows the subject. Explain any term the moment you use it.\n"
              "- Only established facts and principles. Never promise or suggest an amount, a speed or a certainty of earning; say what it costs, how long "
              "it takes and what can go wrong. No named shares, coins, apps or products, and no advice to buy or sell anything.\n"
              "- One idea, taught well, with one concrete everyday example using small round numbers that are clearly only an illustration.\n"
              "- Explore, do not promise: ask \"how can we...\", \"can you really...\", \"what does it take to...\"; say \"can\" and \"may\", never "
              "\"will\"; be plain that it may or may not work for the viewer, and say what decides it.\n"
              "- The title is an open question in that same spirit.\n"),
    "science": ("Write a true science story from the plan below",
                "- Every statement must be established science, as a good encyclopedia would give it. If you are not certain of a number or a date, leave it out. "
                "Nothing speculative, no myths presented as fact.\n"
                "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows; explain any term you use.\n"
                "- No invented people or dialogue.\n"),
    "space": ("Write a true space story from the plan below",
              "- Every statement must be established astronomy, as NASA, ESA or a good encyclopedia would give it. If you are not certain of a number or a date, leave it out. "
              "A 'what if' is told as a thought experiment from real physics and says so; nothing speculative presented as fact.\n"
              "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows; explain any term you use.\n"
              "- No invented people or dialogue.\n"),
    "body": ("Write a true story about the human body or mind from the plan below",
             "- Every statement must be established anatomy, physiology or well-replicated psychology, as a textbook would give it. If you are not certain of a number, leave it out. "
             "A finding from animal studies is said as such (\"in studies of mice\"), never as fact about people.\n"
             "- Never health advice, treatment, diets, supplements, diagnosis or 'hacks'; do not tell the viewer to do or take anything. Explain how it works, nothing more.\n"
             "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows; explain any term you use.\n"
             "- No invented people or dialogue.\n"),
    "geography": ("Write a true story about the world's geography from the plan below",
                  "- Every statement must be established geography, as an atlas or a good encyclopedia would give it. If you are not certain of a number, leave it out.\n"
                  "- No politics, no disputed borders or territories, nothing that ranks peoples, religions or countries as better or worse.\n"
                  "- Name the countries, rivers and places it is about, so the map can show them.\n"
                  "- Tell it as a story with a beginning, a turn and an end, in plain words a twelve-year-old follows.\n"
                  "- No invented people or dialogue.\n")}
TURNS = ["a message sent to the wrong person", "an old letter found by accident", "an overheard phone call", "a stranger who knew the truth",
         "a photograph that should not exist", "a bank statement left open", "a child's innocent question", "a secret told at the worst possible moment",
         "a reunion after ten years", "a diary returned by mistake"]
MOODS = ("dark", "sad", "warm", "light", "dramatic")
# A long video (wide, several minutes) beside the Shorts: channel option `long`, these are its defaults.
LONG = {"enabled": False, "per_day": 1, "minutes": [6, 9], "publish_time": "20:00", "playlist": "Long Stories", "create_after": "03:00",
        "min_source_words": 1600, "shot_seconds": 8}
# A quick Short (20-35 s) beside the regular ones: only an original story can be one; channel option `quick`.
QUICK = {"per_day": 1, "seconds": [20, 35], "outro": "Your story could be next. Comment it."}
OLD_WORDS = ("The original is old: never repeat a slur or a dated word for a race, nationality, religion or disability; describe the person plainly "
             "(\"a musician\", \"a man on the ferry\") or leave the detail out.")
ENDINGS = {"plain": "End on the outcome or the thought it leaves.",
           "hopeful": "However heavy the story, end on a hopeful, motivating note: what the person learned, or how they found the strength to move "
                      "forward. You may add one or two closing sentences of reflection for that, but no new events."}
UNSAFE = re.compile(r"\b(suicid\w*|kill(?:ed|ing)? (?:myself|himself|herself|him|her|them)|self[- ]harm\w*|rap(?:e|ed|es|ing|ist)|molest\w*|"
                    r"sexual(?:ly)? (?:assault|abus)\w*|incest\w*|underage|pedo\w*|child abuse|overdos\w*|murder\w*)\b", re.I)
# Mani, 2026-10-18 ("no more such contents"): no story about sex, sexual desire or sexual fantasies, real or invented, whatever the source
SEXUAL = re.compile(r"\b(sex(?:ual(?:ly)?|y)?|lust\w*|horny|orgasm\w*|kink\w*|naked|nude|threesome|erotic\w*|porn\w*|foreplay|arous\w*|"
                    r"one[- ]night stand|slept with|sleeping with|hook(?:ed)? up|role[- ]?play\w*|seduc\w*|libido|fantasi(?:es|ze\w*)|in bed together)\b", re.I)
STOP = set("a an and are as at be but by for from had has have he her his i in is it its me my of on or our she so that the their them "
           "they this to was we were what when which who with you your had been not no one would could there then than into out up".split())


def channel(raw: dict | None) -> dict:
    return {**CHANNEL, **(raw or {})}


def long_of(ch: dict) -> dict:
    return {**LONG, **(ch.get("long") or {})}


def quick_of(ch: dict) -> dict:
    return {**QUICK, **(ch.get("quick") or {})}


def parts(text: str, n: int) -> list[str]:
    """The text cut into n consecutive pieces of about equal length, at paragraph ends (at sentence ends when it has few paragraphs)."""
    units = [" ".join(u.split()) for u in re.split(r"\n\s*\n", text) if u.strip()]
    if len(units) < n * 2:
        units = [u for u in re.split(r"(?<=[.!?])[\"'”’)\]]*\s+", " ".join(text.split())) if u.strip()]
    total, out, cur, done = sum(len(u.split()) for u in units), [], [], 0
    for u in units:
        cur.append(u)
        done += len(u.split())
        if len(out) < n - 1 and done >= total * (len(out) + 1) / n:
            out.append(" ".join(cur))
            cur = []
    return [x for x in out + [" ".join(cur)] if x]


def clock(seconds: float) -> str:
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}"


def words(text: str) -> int:
    return len(text.split())


def word_range(ch: dict, quick: bool = False) -> tuple[int, int]:
    q = quick_of(ch)
    lo, hi = q["seconds"] if quick else ch["seconds"]
    out = words(q["outro"] if quick else ch["outro"])
    return int(lo * WPS) - out, int(hi * WPS) - out - 15


def choose(options: list[str], told: dict[str, int], views: dict[str, float], floor: float) -> str:
    """Double down on what performs without starving the rest: every option keeps a share of `floor`, and the remainder
    follows average views (an option with no views yet counts as the mean of the known ones, so it keeps being tried).
    The option told furthest below its target share is next; a tie goes to the earlier. No views, or a floor that
    leaves nothing to share -> the least told."""
    n, total = len(options), sum(told.get(o, 0) for o in options)
    known = [views[o] for o in options if o in views]
    if floor * n >= 1 or not known or sum(known) <= 0:
        return min(options, key=lambda o: told.get(o, 0))
    mean = sum(known) / len(known)
    seen = {o: views.get(o, mean) for o in options}
    gap = lambda o: round(floor + (1 - floor * n) * seen[o] / sum(seen.values()) - (told.get(o, 0) / total if total else 0), 9)
    return max(options, key=gap)


# Sound effects are cues a line asks for, never decoration: the model names one only where the moment calls for it.
CUES = {"riser": "tension building just before something happens", "impact": "a shock or a revelation lands", "heartbeat": "fear, dread, a held breath",
        "drone": "unease, something is wrong", "tick": "waiting, time running out", "ding": "a realisation, an idea, good news",
        "whoosh": "a jump in time or place", "pop": "something light or funny", "coin": "money gained, paid or lost", "notification": "a message or a call arrives"}
CUE_LEVEL = {"impact": 0.9, "riser": 0.8, "heartbeat": 0.8, "ding": 0.8, "notification": 0.8, "pop": 0.7, "coin": 0.7, "drone": 0.6, "tick": 0.6, "whoosh": 0.6}


def sfx_plan(beats: list[dict], *, volume: float, turn: int = 0) -> list[dict]:
    """Where the sound effects go: only on a line that asked for one (`cue` on a beat), at the moment it is spoken; a riser is
    timed to finish as its line ends. Kept sparse whatever was asked: at least 4 seconds apart and about one per 8 seconds
    of video. A cue whose kind has no file in the library is left out. Times follow the beats' own lengths."""
    starts, t = [], 0.0
    for b in beats:
        starts.append(t)
        t += b["dur"]
    out, used, last = [], {}, -99.0
    for i, b in enumerate(beats):
        cue = b.get("cue")
        if cue not in CUES or b["kind"] == "outro" or len(out) >= max(2, int(t // 8)):
            continue
        path = sfx.pick(cue, turn + used.get(cue, 0))
        if not path:
            continue
        at = starts[i]
        if cue == "riser":
            try:
                at = max(at, starts[i] + b["dur"] - shorts_edit.probe(str(path)))
            except RuntimeError:                       # a file that will not decode is no use
                continue
        if at - last < 4:
            continue
        used[cue] = used.get(cue, 0) + 1
        last = at
        out.append({"at": round(at, 2), "path": str(path), "volume": round(volume * CUE_LEVEL[cue], 3)})
    return out


def screenplay(story: str, outro: str, max_words: int = 16) -> list[dict]:
    """Split a story into beats short enough for one picture each, with the time each should take; outro last.
    `end` marks the beat that closes a sentence: the voice speaks sentence by sentence, never fragment by fragment."""
    parts: list[list] = []                                          # [text, closes a sentence]
    # a full stop after an initial or a title ("O. Henry", "Mrs. Dale") does not end a sentence
    for sent in re.split(r"(?<!\b[A-Z]\.)(?<!\bMr\.)(?<!\bMrs\.)(?<!\bDr\.)(?<!\bSt\.)(?<=[.!?…])[\"'”’)\]]*\s+", " ".join(story.split())):
        if words(sent) <= max_words:
            parts.append([sent, True])
            continue
        cur = ""
        for piece in re.split(r"(?<=[,;:—–])\s+", sent):       # a long sentence breaks at its own pauses
            if cur and words(cur) + words(piece) > max_words:
                parts.append([cur, False])
                cur = piece
            else:
                cur = (cur + " " + piece).strip()
        parts.append([cur, True])
    for i in range(len(parts) - 1, -1, -1):                        # still too long with no pause to break at: halve it
        ws = parts[i][0].split()
        if len(ws) > max_words + 6:
            parts[i:i + 1] = [[" ".join(ws[:len(ws) // 2]), False], [" ".join(ws[len(ws) // 2:]), parts[i][1]]]
    beats: list[list] = []
    for text, end in ([t.strip(), e] for t, e in parts if t.strip()):
        if beats and words(beats[-1][0]) < 5 and words(beats[-1][0]) + words(text) <= max_words:
            beats[-1] = [beats[-1][0] + " " + text, end]            # a two-word beat is too short to show
        else:
            beats.append([text, end])
    if beats:
        beats[-1][1] = True
    out = [{"i": i, "text": t, "target_s": round(words(t) / WPS + GAP, 1), "kind": "story", "end": e} for i, (t, e) in enumerate(beats)]
    if outro:
        out.append({"i": len(out), "text": outro, "target_s": round(words(outro) / WPS + GAP, 1), "kind": "outro", "end": True})
    return out


def split_times(texts: list[str], total: float, marks: list | None) -> tuple[list[float], list]:
    """Where one spoken sentence divides between its beats: (seconds per beat, word timings per beat).
    With the voice's word timings the cut falls between two words; without them it follows the length of the text."""
    counts = [len(t.split()) for t in texts]
    if marks and len(marks) == sum(counts):
        cuts, at = [0.0], 0
        for n in counts[:-1]:
            at += n
            cuts.append((marks[at - 1][2] + marks[at][1]) / 2)
        cuts.append(total)
        per, at = [], 0
        for k, n in enumerate(counts):
            per.append([[w, a - cuts[k], z - cuts[k]] for w, a, z in marks[at:at + n]])
            at += n
        return [cuts[k + 1] - cuts[k] for k in range(len(texts))], per
    chars = [len(t) + 1 for t in texts]
    return [total * c / sum(chars) for c in chars], [None] * len(texts)


def align(text: str, heard: list | None, total: float) -> list | None:
    """Timings for every word of the script, from the words a voice engine or the listener reported:
    [[word, start, end]]. Words that match in order take their heard time; a word in between that was heard
    differently (a number, a name) shares the gap between its neighbours. Too little in common -> None."""
    mine = text.split()
    if not heard or not mine:
        return None
    norm = lambda w: re.sub(r"[^a-z0-9]", "", str(w).lower())
    times: list = [None] * len(mine)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, [norm(w) for w in mine], [norm(h[0]) for h in heard], autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (float(heard[j1 + k][1]), float(heard[j1 + k][2]))
    if sum(t is not None for t in times) < len(mine) * 0.6:
        return None
    i = 0
    while i < len(mine):
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < len(mine) and times[j] is None:
            j += 1
        a = times[i - 1][1] if i else 0.0
        z = times[j][0] if j < len(mine) else total
        size = [len(w) + 1 for w in mine[i:j]]
        at = a
        for k in range(i, j):
            d = max(z - a, 0.0) * size[k - i] / sum(size)
            times[k] = (at, at + d)
            at += d
        i = j
    return [[w, t[0], t[1]] for w, t in zip(mine, times)]


def trending_words(trends: dict | None) -> set[str]:
    """The telling words in today's most-watched titles and their tags."""
    text = " ".join(t.get("title", "") + " " + " ".join(t.get("tags") or []) for t in (trends or {}).get("videos") or [])
    return set(re.findall(r"[a-z]{5,}", text.lower())) - STOP


def trend_score(text: str, hot: set[str]) -> int:
    """How many of a subject's own telling words are in what people are watching today."""
    return len((set(re.findall(r"[a-z]{5,}", text.lower())) - STOP) & hot) if hot else 0


def fallback_query(text: str) -> str:
    picks = sorted(dict.fromkeys(w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in STOP), key=len, reverse=True)[:3]
    return " ".join(picks) or "person thinking alone"


def account(ch: dict) -> str:
    return ch.get("account") or f"youtube-{ch['id']}"


def can_manage(ctx: dict, ch: dict) -> bool:
    """Playlists and comments need a wider permission than uploading. Without it, ask for one more sign-in and carry on."""
    if "youtube.force-ssl" in oauth.granted(account(ch)):
        ctx["bus"].clear_notice(f"youtube-scope-{ch['id']}")
        return True
    port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
    ctx["bus"].notice(f"youtube-scope-{ch['id']}", f"Sign in to YouTube again for {ch['name']}: playlists and viewer comments need a wider permission",
                      f"http://127.0.0.1:{port}/auth/youtube/login?account={account(ch)}")
    return False


def kind(job: dict) -> str:
    """classic (a public-domain story), original / motivational / science (written from a premise), viewer (a comment on the channel) or real."""
    if job.get("original"):
        return job["genre"] if job.get("genre") in ("motivational", *LEARN_KINDS) else "original"
    return "classic" if job.get("classic") else "viewer" if job["source"].get("from") == "viewer comment" else "real"


def save_record(store, ch: dict, job: dict) -> None:
    """The log entry for a finished video: where it came from and everything that went into it."""
    store.kv_put(LOG, job["id"], {
        "channel": ch["id"], "status": "ready", "made": time.time(), "title": job["title"], "hashtags": job["hashtags"],
        "source": job["source"], "script": job["script"], "keywords": job["keywords"], "seconds": job["seconds"], "file": job["file"],
        "mood": job.get("mood", ""), "voice": job.get("voice", ""), "music": job.get("music", ""), "original": bool(job.get("original")), "kind": kind(job),
        "classic": job.get("classic"), "seo": job.get("seo"), "structure": job.get("structure", ""), "hook": job.get("hook", ""), "format": job.get("format", "short"), "summary": job.get("summary", ""),
        "caption": job.get("caption", ""), "sfx": job.get("sfx", 0), "quick": bool(job.get("quick")),
        "thumb": job.get("thumb", ""), "thumb_text": job.get("thumb_text", ""),
        "chapters": [{"t": round(sum(x["dur"] for x in job["beats"][:n])), "heading": b["heading"]} for n, b in enumerate(job["beats"]) if b.get("heading")],
        "screenplay": [{"text": b["text"], "seconds": round(b["dur"], 2), "query": b["query"], "footage": (b.get("visual") or {}).get("page", ""),
                        **({"cue": b["cue"]} if b.get("cue") else {})} for b in job["beats"]],
        "credits": sorted({b["visual"]["credit"] for b in job["beats"] if b.get("visual") and b["visual"].get("source") != "diagram"}),     # our own scenes need no credit
        "diagrams": job.get("diagrams", [])})
    store.kv_put(SEEN, job["key"], {"state": "done"})


ON_YOUTUBE = ("scheduled", "public", "private")      # with `on_youtube` (seen by videos.list after the upload), the local copy is not the only one
SCRAPS = ("build", "audio", "footage")   # a run's working folders
SCRAP_AFTER = 2 * 86400                  # a failed run's working folders are kept this long for a look


BACKUP_ACCOUNT = "drive-backup"          # the Google sign-in the backups go to (oauth provider "gdrive"): /auth/gdrive/login?account=drive-backup


def backs_up(ch: dict) -> bool:
    """Posted videos go to Drive: `backup: true`, or (the older way) a `backup_folder` name."""
    return bool(ch.get("backup") or ch.get("backup_folder"))


def backup_name(v: dict) -> str:
    """"2026-10-15 The Devotee by Rabindranath Tagore [abc123]": the day it went up, the title without hashtags, the YouTube id."""
    day = time.strftime("%Y-%m-%d", time.localtime(v.get("uploaded") or v.get("made") or time.time()))
    title = re.sub(r"#\w+", "", v.get("title") or "")
    title = re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)).strip(" .-|")[:90].strip()
    return f"{day} {title} [{v['video_id']}]"


async def backup(ctx: dict, ch: dict, log: list[dict], client) -> str:
    """Copies each video YouTube has confirmed (see free_space) to Drive before its local copy goes: Vision/YouTube/<channel>/Shorts
    or /Videos in the backup sign-in's Drive (`backup: true` switches it on; `backup_folder`, if set, also switches it on and names an older top-level folder moved in there once), the video and its cover, each checked by size and MD5 (Mani, 2026-10-15: "this is for
    backup... no more local saves"). No sign-in, a full Drive or an error = the local files stay and it is tried again next run."""
    if not backs_up(ch) or ch.get("keep_local"):
        return ""
    todo = [v for v in log if v.get("status") in ON_YOUTUBE and v.get("video_id") and v.get("on_youtube", 0) >= (v.get("uploaded") or 0.1)
            and not v.get("drive") and not v.get("local_removed") and v.get("file") and Path(v["file"]).is_file()]
    if not todo:
        return ""
    store, bus = ctx["store"], ctx["bus"]
    try:
        token = await oauth.access_token(BACKUP_ACCOUNT, "gdrive")
    except oauth.AuthNeeded:
        bus.notice("gdrive-backup", gdrive.SIGN_IN,
                   f"http://127.0.0.1:{ctx['cfg'].vision.port if ctx.get('cfg') else 8765}/auth/gdrive/login?account={BACKUP_ACCOUNT}")
        return "Drive backup waits for a sign-in"
    bus.clear_notice("gdrive-backup")
    done = 0
    try:
        async with client() as c:
            # Vision/YouTube/<channel name>; the channel's older top-level `backup_folder` is moved in there the first time
            top = await gdrive.vision_path(c, token, "YouTube", ch["name"], legacy=ch.get("backup_folder") or None)
            subs: dict[str, str] = {}
            for v in todo:
                sub_ = "Videos" if v.get("format") == "long" else "Shorts"
                if sub_ not in subs:
                    subs[sub_] = await gdrive.ensure_folder(c, token, sub_, top)
                name, f = backup_name(v), Path(v["file"])
                saved = {"video": await gdrive.upload(c, token, f, name + f.suffix, subs[sub_], "video/mp4"), "folder": f"{gdrive.TOP}/YouTube/{ch['name']}/{sub_}"}
                thumb = Path(v.get("thumb") or "")
                if v.get("thumb") and thumb.is_file():
                    saved["cover"] = await gdrive.upload(c, token, thumb, name + " cover" + thumb.suffix, subs[sub_], "image/jpeg")
                v["drive"] = {**saved, "at": time.time()}
                store.kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})
                done += 1
    except gdrive.DriveFull:
        bus.notice("gdrive-full", f"Google Drive is full: {ch['name']}'s videos stay on the Mac until there is room", None)
        return f"Drive is full; {done} backed up"
    except (gdrive.DriveError, httpx.HTTPError) as e:
        return f"Drive backup stopped: {e}"[:160] + (f"; {done} backed up" if done else "")
    bus.clear_notice("gdrive-full")
    return f"{done} backed up to Drive" if done else ""


def month_start(now: float | None = None) -> float:
    t = time.localtime(now or time.time())
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, -1))


async def prune_drive(ctx: dict, ch: dict, log: list[dict], client) -> str:
    """Once a month, on its first run of the month (Mani, 2026-10-15: "every month 1st date, check the YT studio videos released
    last month and those videos should be deleted from the drive"): the Drive copies of videos released before this month that
    videos.list has just seen public on YouTube go to the Drive's trash (emptied by Drive after 30 days). A video gone from
    YouTube keeps its copy: it is then the only one. kv `yt_state` `<channel>:drive_prune:<YYYY-MM>` marks the month done."""
    if not backs_up(ch):
        return ""
    store, month = ctx["store"], time.strftime("%Y-%m")
    mark = f"{ch['id']}:drive_prune:{month}"
    if store.kv_get(STATE, mark):
        return ""
    start = month_start()
    old = [v for v in log if v.get("drive") and not v.get("drive_removed") and v.get("status") == "public"
           and (v.get("publish_at") or v.get("uploaded") or 0) < start and v.get("on_youtube", 0) > time.time() - 86400]
    if old:
        try:
            token = await oauth.access_token(BACKUP_ACCOUNT, "gdrive")
        except oauth.AuthNeeded:
            return ""                            # the backup step has already asked for the sign-in
        try:
            async with client() as c:
                for v in old:
                    for part in ("video", "cover"):
                        if (v["drive"].get(part) or {}).get("id"):
                            await gdrive.trash(c, token, v["drive"][part]["id"])
                    v["drive_removed"] = time.time()
                    store.kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})
        except (gdrive.DriveError, httpx.HTTPError) as e:
            return f"Drive clean-up stopped: {e}"[:160]                 # tried again on the next run this month
    unseen = [v for v in log if v.get("drive") and not v.get("drive_removed") and v.get("status") == "public"
              and (v.get("publish_at") or v.get("uploaded") or 0) < start and v.get("on_youtube", 0) <= time.time() - 86400]
    if unseen:                                   # not confirmed on YouTube today: the month stays open and they are looked at again next run
        return f"{len(old)} of last month's backups moved to Drive's trash" if old else ""
    store.kv_put(STATE, mark, {"at": time.time(), "trashed": len(old)})
    return f"{len(old)} of last month's backups moved to Drive's trash" if old else ""


def free_space(store, ch: dict, log: list[dict]) -> str:
    """Deletes the local folder of every video a videos.list call has found on YouTube since its upload (Mani: "check and make sure it is
    there... and then delete it from local"; never on the upload's answer alone; the log record stays), and the working
    folders of a run that failed over two days ago. Only folders inside data/shorts/<channel>/; a video that is waiting, awaiting,
    for review, stale or deleted on YouTube (then the local copy is the only one) keeps its files. `keep_local: true` keeps everything."""
    root = (ROOT / "data" / "shorts" / ch["id"]).resolve()
    if ch.get("keep_local") or not root.is_dir():
        return ""
    gone, used, freed = 0, set(), 0
    for v in log:
        if not v.get("file"):
            continue
        d = Path(v["file"]).resolve().parent
        if d == root or not d.is_relative_to(root) or d.name.startswith("_"):
            continue
        used.add(d)
        if backs_up(ch) and not v.get("drive"):
            continue                           # backups are on: the local copy goes only after Drive holds a checked copy
        if v.get("status") in ON_YOUTUBE and v.get("video_id") and v.get("on_youtube", 0) >= (v.get("uploaded") or 0.1) and not v.get("local_removed"):
            if d.is_dir():
                freed += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                shutil.rmtree(d, ignore_errors=True)
                gone += 1
            v["local_removed"] = time.time()
            store.kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})
    for d in root.iterdir():                   # a failed run: no record points at it and nothing in it has moved for two days
        if not d.is_dir() or d.name.startswith("_") or d in used:
            continue
        parts = [d / p for p in SCRAPS if (d / p).is_dir()]
        if parts and time.time() - max(f.stat().st_mtime for f in [d, *d.rglob("*")]) > SCRAP_AFTER:
            for p in parts:
                freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                shutil.rmtree(p, ignore_errors=True)
    return f"{freed / 1e6:.0f} MB freed" + (f" ({gone} posted videos' local copies)" if gone else "") if freed else ""


def next_slot(store, ch: dict, now: float | None = None, fmt: str = "short") -> float:
    """The publishing time for the next video: the first of the channel's publish_times after the last one already
    scheduled (the releases form one queue, in upload order), and at least half an hour away. Long videos have
    their own queue, one a day at long.publish_time, so they never take a Short's slot. Times are the Mac's local
    time unless the channel names a `timezone`."""
    now = now or time.time()
    taken = [v["publish_at"] for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("publish_at") and v.get("status") != "deleted"
             and (v.get("format") == "long") == (fmt == "long")]
    after = max([now + 1800] + [t + 60 for t in taken])
    if ch.get("timezone"):                         # a channel on another clock (option `timezone`, e.g. Asia/Kolkata): slots are that zone's wall time
        base = datetime.fromtimestamp(after, ZoneInfo(ch["timezone"]))
        for day in range(3):
            for hm in sorted([long_of(ch)["publish_time"]] if fmt == "long" else ch["publish_times"]):
                h, m = (int(x) for x in str(hm).split(":"))
                ts = (base.replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=day)).timestamp()
                if ts > after:
                    return ts
        return after + 86400
    lt = time.localtime(after)
    for day in range(3):
        for hm in sorted([long_of(ch)["publish_time"]] if fmt == "long" else ch["publish_times"]):
            h, m = (int(x) for x in str(hm).split(":"))
            ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day, h, m, 0, 0, 0, -1))
            if ts > after:
                return ts
    return after + 86400


REPORT_KINDS = ("premarket", "postmarket")     # Mani Market Tamil's two Shorts on a trading day (masters/market_crew.py)
REPORT_LEAD = 15 * 60                          # a report is released this long after it is scheduled or approved (YouTube needs a future time; next_slot keeps 30 minutes)


def _now() -> float:
    return time.time()


def report_release(kind: str, day: date, now: float) -> float | None:
    """When a pre-market or post-market Short (made for the Indian date `day`) may go public, as a time stamp; None when it is stale.
    Pre-market: REPORT_LEAD from now, only if that is before 09:10 IST (later it is yesterday's news). Post-market: 21:00 IST that day if still ahead,
    else REPORT_LEAD from now while it is still that same Indian date. Neither touches next_slot, so the long video's 10:00 slot is never taken."""
    ist = ZoneInfo("Asia/Kolkata")
    soon, at = now + REPORT_LEAD, lambda h, m: datetime(day.year, day.month, day.day, h, m, tzinfo=ist).timestamp()
    if kind == "premarket":
        return soon if soon < at(9, 10) else None
    if soon < at(21, 0):
        return at(21, 0)
    return soon if datetime.fromtimestamp(soon, ist).date() == day else None


LESSON_KINDS = ("lesson", "lesson_short")      # Mani Market Tamil's model-written finance lessons: released like the rest since Mani approved the channel (2026-10-14); were always private until approved, whatever the channel's privacy settings say
SHORT_KINDS = (*REPORT_KINDS, "lesson_short")  # Shorts released on the Indian clock, outside next_slot
LESSON_SLOTS = {"premarket": (9, 0), "postmarket": (21, 0)}     # IST: when a lesson Short made in that window goes public (09:00 for the morning window, 21:00 for the evening one)


def lesson_release(window: str, day: date, now: float) -> float | None:
    """When a lesson Short made for the Indian date `day` in the morning (`premarket`) or evening (`postmarket`) window may go public; None when it is stale.
    Its slot (09:00 or 21:00 IST) if that is still ahead by REPORT_LEAD; past it, REPORT_LEAD from now, but only while it is still that same Indian date (a lesson Short that
    misses its day is stale: it stays private). It never touches next_slot."""
    ist = ZoneInfo("Asia/Kolkata")
    h, m = LESSON_SLOTS[window]
    slot, soon = datetime(day.year, day.month, day.day, h, m, tzinfo=ist).timestamp(), now + REPORT_LEAD
    if soon < slot:
        return slot
    return soon if datetime.fromtimestamp(soon, ist).date() == day else None


def short_when(rec: dict, now: float) -> float | None:
    """When a report or lesson Short (a record with `kind`, `date` and, for a lesson, `window`) may go public, or None when it is stale."""
    day = date.fromisoformat(rec["date"])
    return lesson_release(rec["window"], day, now) if rec["kind"] == "lesson_short" else report_release(rec["kind"], day, now)


def made_today(store, ch: dict, fmt: str | None = None, quick: bool = False) -> int:
    # by the day it was made (a later status or stats update re-saves the record); a reset starts the day's count again
    start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
    return sum(v.get("channel") == ch["id"] and (v.get("made") or 0) >= start and (fmt is None or (v.get("format") == "long") == (fmt == "long"))
               and (not quick or bool(v.get("quick"))) for v in store.kv_list(LOG))


# The day's mix (Mani, 2026-10-18: "daily two videos are of science, one from stories and one for finance"): the day's Shorts
# are slots per category; the Analytics Manager re-splits them once a week by how the categories are really watched.
MIX_CATS = ("science", "story", "money", "space", "body", "geography")      # the first three are Know IDK Things'; the rest the new channels' 
SUB_WEIGHT = 50                      # a subscriber gained counts as much as 50 fully watched views


def others_recent(store, ch: dict, days: int = 90) -> list[set[str]]:
    """The telling words of what the OTHER channels made or planned in the last `days`: a new channel does not tell the same subject
    within that time (Mani, 2026-10-19; switched on by `avoid_others`, so Know IDK Things is unchanged)."""
    since, out = time.time() - days * 86400, []
    for v in store.kv_list(LOG, since=since, limit=5000):
        if v.get("channel") != ch["id"] and v.get("title"):
            out.append(set(re.findall(r"[a-z]{4,}", v["title"].lower())) - STOP)
    for p in store.kv_list(PREMISES, since=since, limit=5000):
        if p.get("channel") != ch["id"] and p.get("used"):
            out.append(set(re.findall(r"[a-z]{4,}", (p.get("title") or "").lower())) - STOP)
    return [w for w in out if w]


def told_elsewhere(subject: str, others: list[set[str]]) -> bool:
    """A subject shares two or more telling words with something another channel told recently."""
    mine = set(re.findall(r"[a-z]{4,}", subject.lower())) - STOP
    return any(len(mine & o) >= 2 for o in others)


def category(k: str | None) -> str:
    """A Short's category for the mix: science, money (finance), or story (real, viewer, classic, original, motivational)."""
    return k if k in LEARN_KINDS else "story"


def mix_of(store, ch: dict) -> dict[str, int]:
    """Today's slots per category: the Analytics Manager's latest re-split, else the channel's `daily_mix`; {} = no mix."""
    if not ch.get("daily_mix"):
        return {}
    kept = (store.kv_get(STATE, f"{ch['id']}:mix") or {}).get("mix") if ch.get("mix_auto") else None
    return {c: int(n) for c, n in (kept or ch["daily_mix"]).items() if c in MIX_CATS}


def made_by_category(store, ch: dict) -> dict[str, int]:
    start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
    out = {c: 0 for c in MIX_CATS}
    for v in store.kv_list(LOG):
        if v.get("channel") == ch["id"] and (v.get("made") or 0) >= start and v.get("format") != "long":
            out[category(v.get("kind"))] += 1
    return out


def next_category(mix: dict[str, int], made: dict[str, int]) -> str | None:
    """The category with the most slots still open today (a tie goes to the bigger slot, then MIX_CATS order); None = all filled."""
    open_ = {c: mix[c] - made.get(c, 0) for c in mix if mix[c] - made.get(c, 0) > 0}
    return max(open_, key=lambda c: (open_[c], mix[c], -MIX_CATS.index(c))) if open_ else None


def category_scores(log: list[dict], days: int = 28, now: float | None = None) -> dict[str, dict]:
    """How each category is really watched, from YouTube Analytics: public Shorts released in the last `days` and at least two
    days old (Analytics lags). score = average of views x share watched, plus SUB_WEIGHT per subscriber gained, per Short."""
    now = now or time.time()
    rows: dict[str, list[dict]] = {}
    for v in log:
        a, at = v.get("analytics"), v.get("publish_at") or v.get("uploaded") or 0
        if a and v.get("status") == "public" and v.get("format") != "long" and now - days * 86400 <= at <= now - 2 * 86400:
            rows.setdefault(category(v.get("kind")), []).append(a)
    out = {}
    for c, xs in rows.items():
        n = len(xs)
        out[c] = {"n": n, "views": round(sum(x.get("views", 0) for x in xs) / n), "pct": round(sum(x.get("avg_pct", 0) for x in xs) / n, 1),
                  "subs": sum(x.get("subs", 0) for x in xs),
                  "score": round(sum(x.get("views", 0) * x.get("avg_pct", 0) / 100 + SUB_WEIGHT * x.get("subs", 0) for x in xs) / n, 1)}
    return out


def resplit(mix: dict[str, int], scores: dict[str, dict], least: int) -> dict[str, int]:
    """The same number of slots shared by score: every category keeps at least one; a category with fewer than `least` measured
    Shorts keeps its slots as they are; the rest go to the measured ones in proportion to score (largest remainder)."""
    total = sum(mix.values())
    measured = [c for c in mix if (scores.get(c) or {}).get("n", 0) >= least and scores[c]["score"] > 0]
    if len(measured) < 2:
        return dict(mix)
    out = {c: mix[c] for c in mix if c not in measured}
    pool = total - sum(out.values())
    out.update({c: 1 for c in measured})
    spare = pool - len(measured)
    if spare <= 0:
        return {c: out[c] for c in mix}
    tot = sum(scores[c]["score"] for c in measured)
    share = {c: spare * scores[c]["score"] / tot for c in measured}
    for c in measured:
        out[c] += int(share[c])
    for c in sorted(measured, key=lambda c: (share[c] - int(share[c]), scores[c]["score"]), reverse=True)[:spare - sum(int(x) for x in share.values())]:
        out[c] += 1
    return {c: out[c] for c in mix}


def mix_text(mix: dict[str, int]) -> str:
    return " / ".join(f"{n} {'finance' if c == 'money' else c}" for c, n in mix.items() if n)


def _midnight() -> float:
    lt = time.localtime()
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


class Crew(SubAgent):
    """A channel's crew member. The Scout puts the job in ctx; everyone after it works on that job."""

    def __init__(self, ch: dict, **kw: Any) -> None:
        super().__init__(**kw)
        self.ch = ch

    def client(self) -> httpx.AsyncClient:
        make = self.opts.get("client_factory")
        return make() if make else httpx.AsyncClient(timeout=httpx.Timeout(60.0))

    @staticmethod
    def idle() -> AgentResult:
        return AgentResult("idle", "IDLE", "Nothing to make this run")


class StoryScout(Crew):
    name, tier, note = "Story Scout", "API", "finds one story worth telling"
    _hot: set = set()               # today's most-watched words, set while an original is being chosen

    def _inbox(self) -> list[dict]:
        folder = ROOT / "inbox" / "stories" / self.ch["id"]
        out = []
        for f in sorted(folder.glob("*.txt")) if folder.exists() else []:
            lines = f.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            url = lines.pop(0).strip() if lines and lines[0].strip().startswith("http") else ""   # optional first line: where it came from
            out.append({"id": f"file-{f.stem}", "title": f.stem, "text": "\n".join(lines).strip(), "url": url, "score": 10**9, "sub": "inbox", "nsfw": False})
        return out

    async def _from_drive(self, ctx: dict) -> int:
        """Copy new text files and Google Docs from the channel's Drive folder into the inbox. A problem here is
        reported as a notice and never stops the Scout: the inbox may already hold stories."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        if not ch["drive_folder"]:
            return 0
        acct, note = account(ch), f"youtube-drive-{ch['id']}"
        try:
            token = await oauth.access_token(acct, "youtube")
        except oauth.AuthNeeded:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
            return 0
        inbox = ROOT / "inbox" / "stories" / ch["id"]
        new = 0
        try:
            async with self.client() as c:
                folder = await gdrive.folder_id(c, token, ch["drive_folder"])
                if not folder:
                    bus.notice(note, f"{ch['name']}: no folder named “{ch['drive_folder']}” in the signed-in Google Drive")
                    return 0
                for f in await gdrive.texts(c, token, folder):
                    key = f"{ch['id']}:{f['id']}"
                    if store.kv_has(DRIVE, key):
                        continue
                    text = await gdrive.read(c, token, f)
                    slug = re.sub(r"[^A-Za-z0-9]+", "-", f["name"].rsplit(".txt", 1)[0]).strip("-")[:50] or "story"
                    inbox.mkdir(parents=True, exist_ok=True)
                    (inbox / f"{slug}-{f['id'][:6]}.txt").write_text(text, encoding="utf-8")
                    store.kv_put(DRIVE, key, {"name": f["name"]})
                    new += 1
        except (gdrive.DriveError, httpx.HTTPError) as e:
            bus.notice(note, f"{ch['name']}: Google Drive could not be read ({e})")
            return new
        bus.clear_notice(note)
        return new

    async def run(self, ctx: dict) -> AgentResult:
        ch, store = self.ch, ctx["store"]
        L, now = long_of(ch), time.strftime("%H:%M")
        shorts, longs = made_today(store, ch, "short"), made_today(store, ch, "long")
        if ch.get("writer_model") and ch.get("groq_daily_cap"):      # a new channel: no Short is started without Groq room for a whole one
            from ..services import groq_budget
            stop = groq_budget.why_not(ch["writer_model"], 15000, ch["id"], int(ch["groq_daily_cap"]))
            if stop:
                return AgentResult("idle", "WRITER BUDGET", stop)
        mix = mix_of(store, ch)
        short_due = (next_category(mix, made_by_category(store, ch)) is not None) if mix else shorts < ch["shorts_per_day"]
        long_due = bool(L["enabled"]) and longs < L["per_day"]
        if not short_due and not long_due:
            return AgentResult("idle", "QUOTA MET", f"{shorts} of {sum(mix.values()) if mix else ch['shorts_per_day']} Shorts made today"
                               + (f" ({mix_text(mix)})" if mix else "") + (f", {longs} of {L['per_day']} long" if L["enabled"] else ""))
        waiting = sum(v.get("channel") == ch["id"] and v.get("status") == "ready" for v in store.kv_list(LOG))
        if waiting >= max(1, ch["shorts_per_day"] + (L["per_day"] if L["enabled"] else 0)):    # a day's worth is piling up unsent (YouTube's upload limit)
            return AgentResult("idle", "BACKLOG", f"{waiting} finished videos are waiting to upload; no new ones until they go")
        short_now = short_due and not (ch["create_after"] and now < ch["create_after"])      # neither kind is started before its hour
        long_now = long_due and not (L["create_after"] and now < L["create_after"])
        if not short_now and not long_now:
            return AgentResult("idle", "NOT YET", f"Today's Shorts start at {ch['create_after']}" if short_due else f"Today's long video starts at {L['create_after']}")
        res = None
        if short_now:
            res = await self._short(ctx)
            if ctx.get("job"):
                return res
        if long_now:                                 # the day's long video: a classic rich enough to tell over several minutes
            c = await self._classic(ctx, long=True)
            if c:
                return AgentResult("done", "LONG", f"A long video: “{c['title']}” by {c['author']}", {"source": ctx["job"]["source"]})
        return res or AgentResult("idle", "NOTHING NEW", "No story on the shelf is long enough for a long video")

    async def _trends(self, ctx: dict) -> dict:
        """Today's most-watched list for the channel's region, read at most twice a day and kept; nothing if it can't be read."""
        ch, store = self.ch, ctx["store"]
        kept = store.kv_get(STATE, f"{ch['id']}:trends") or {}
        if not ch["trends"]:
            return {}
        if time.time() - kept.get("at", 0) < 12 * 3600:
            return kept
        try:
            token = await oauth.access_token(account(ch), "youtube")
            async with self.client() as c:
                videos = await yt_trends.popular(c, token, ch["trend_region"])
        except (oauth.AuthNeeded, httpx.HTTPError):
            return kept
        if videos:
            kept = {"at": time.time(), "region": ch["trend_region"], "videos": videos}
            store.kv_put(STATE, f"{ch['id']}:trends", kept)
        return kept

    async def _short(self, ctx: dict) -> AgentResult:
        """Find the next Short's story: viewers' comments and Mani's own stories, then a classic, then an original. With a daily
        mix, the category with the most open slots decides: science and finance are originals of that kind; a story slot
        takes a real story first, then a classic, then an original life story."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        await self._trends(ctx)
        mix = mix_of(store, ch)
        cat = next_category(mix, made_by_category(store, ch)) if mix else None
        if cat in LEARN_KINDS:
            p = await self._original(ctx, cat)
            if p:
                return AgentResult("done", "INVENTED", f"Today's {mix_text({cat: 1}).split(' ', 1)[1]} slot" + (" (a quick one)" if ctx["job"].get("quick") else "")
                                   + f": “{p['title'][:70]}”", {"source": ctx["job"]["source"], "category": cat})
            return AgentResult("idle", "NOTHING NEW", f"No {cat} premise could be made for today's slot")
        await self._from_drive(ctx)
        cands = self._inbox() + await self._from_comments(ctx)
        if reddit.configured():
            async with self.client() as c:
                for sub in ch["subreddits"]:
                    cands += await reddit.top(c, sub)
        elif not cands and not ch["originals"] and not ch["classics"]:
            bus.notice(f"youtube-source-{ch['id']}", f"{ch['name']} needs a story source: add REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET to .env, "
                                                     f"or drop a .txt into inbox/stories/{ch['id']}/" + (f" or a document into the Drive folder “{ch['drive_folder']}”" if ch["drive_folder"] else ""))
            return AgentResult("wait", "NEEDS SOURCE", "No story to work from: nothing in the Drive folder or the inbox, and no Reddit keys")
        bus.clear_notice(f"youtube-source-{ch['id']}")

        checks = 0
        for p in sorted(cands, key=lambda p: p["score"], reverse=True):
            key = f"{ch['id']}:{p['id']}"
            seen = store.kv_get(SEEN, key) or {}
            if seen.get("state") in ("done", "rejected") or seen.get("tries", 0) >= 2 or p["nsfw"] or not 300 <= len(p["text"]) <= 7000:
                continue
            if UNSAFE.search(p["title"] + " " + p["text"]) or SEXUAL.search(p["title"] + " " + p["text"]):
                store.kv_put(SEEN, key, {"state": "rejected", "why": "screened out by rule" + (" (sexual content)" if SEXUAL.search(p["title"] + " " + p["text"]) else "")})
                continue
            if checks >= 4:
                break
            checks += 1
            verdict = await ctx["llm"].json(
                "You screen anonymous personal stories before they are retold in a public video with every name and place removed. Retelling an anonymous "
                "story is fine in itself. Reject it if it involves minors in any sexual or abusive context, self-harm, a serious crime, hate, "
                "or a person who could still be identified after names and places are removed. Also reject it if sex, sexual desire, sexual fantasies "
                "or a sexual encounter is any real part of it (the channel carries no sexual content at all). "
                'Answer as {"ok": true or false, "why": "a few words"}.\n\nStory:\n' + p["text"][:5000], tier="writer", max_tokens=900)
            if not isinstance(verdict, dict) or not isinstance(verdict.get("ok"), bool):    # no answer: not used now, tried once more next run
                store.kv_put(SEEN, key, {"state": "unclear", "tries": seen.get("tries", 0) + 1})
                continue
            if not verdict["ok"]:
                store.kv_put(SEEN, key, {"state": "rejected", "why": str(verdict.get("why") or "")[:200]})
                continue
            store.kv_put(SEEN, key, {"state": "picked", "tries": seen.get("tries", 0) + 1})
            slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40] or p["id"]
            work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{slug}"
            work.mkdir(parents=True, exist_ok=True)
            ctx["job"] = {"id": f"{ch['id']}-{p['id']}", "key": key, "channel": ch["id"], "dir": str(work), "raw": p["text"],
                          "source": {"url": p["url"], "title": p["title"], "from": p["sub"], "score": p["score"] if p["sub"] != "inbox" else None}}
            return AgentResult("done", "FOUND", f"Picked “{p['title'][:70]}” from {p['sub']}", {"source": ctx["job"]["source"]})
        c = await self._classic(ctx)                # then a classic for the playlist, up to the day's number
        if c:
            return AgentResult("done", "CLASSIC", f"“{c['title']}” by {c['author']}", {"source": ctx["job"]["source"]})
        if ch["originals"]:                         # no real story to tell today: an original one, from a premise never used before
            p = await self._original(ctx, "life" if cat == "story" else None)
            if p:
                return AgentResult("done", "INVENTED", f"An original {ctx['job']['genre']} story" + (" (a quick one)" if ctx["job"].get("quick") else "") + f": “{p['title'][:70]}”", {"source": ctx["job"]["source"]})
        return AgentResult("idle", "NOTHING NEW", f"No usable story among {len(cands)} candidates")

    async def _from_comments(self, ctx: dict) -> list[dict]:
        """Stories viewers left under the channel's own Shorts: the stories every video asks for."""
        ch, store = self.ch, ctx["store"]
        vids = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("video_id") and v.get("status") in ("public", "unlisted")][:20]
        if not ch["viewer_comments"] or not vids or not can_manage(ctx, ch):
            return []
        try:
            token = await oauth.access_token(account(ch), "youtube")
        except oauth.AuthNeeded:
            return []
        out = []
        async with self.client() as c:
            for v in vids:
                r = await c.get(API + "/commentThreads", headers={"Authorization": f"Bearer {token}"},
                                params={"part": "snippet", "videoId": v["video_id"], "maxResults": 50, "order": "time", "textFormat": "plainText"})
                if r.status_code != 200:              # comments switched off, or the video has gone
                    continue
                for item in r.json().get("items", []):
                    top = item["snippet"]["topLevelComment"]
                    text = (top["snippet"].get("textOriginal") or top["snippet"].get("textDisplay") or "").strip()
                    out.append({"id": f"comment-{top['id']}", "title": " ".join(text.split())[:60], "text": text, "score": 2 * 10**9, "nsfw": False,
                                "sub": "viewer comment", "url": f"https://www.youtube.com/watch?v={v['video_id']}&lc={top['id']}"})
        return out

    async def _classic(self, ctx: dict, long: bool = False) -> dict | None:
        """The next unused story from the shelf of public-domain books (taking from the least-used book): for a Short at
        most classics_per_day; for a long video only stories with enough in them to fill it. A story is told once, in one form."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        start = max(_midnight(), (store.kv_get(STATE, f"{ch['id']}:quota_reset") or {}).get("at", 0))
        today = sum(v.get("channel") == ch["id"] and v.get("kind") == "classic" and v.get("format") != "long" and (v.get("made") or 0) >= start
                    for v in store.kv_list(LOG))
        if not ch["classics"] or (not long and today >= ch["classics_per_day"]):
            return None
        least = long_of(ch)["min_source_words"] if long else 0
        used = {v["_key"] for v in store.kv_list(CLASSICS, limit=5000)}
        for _ in range(6):                            # a story the rules screen out is marked and the next one is tried
            best = None
            for bid in ch["classics"]:
                try:
                    rows = await gutenberg.shelve(int(bid), self.client() if self.opts.get("client_factory") else None)
                except (RuntimeError, httpx.HTTPError) as e:
                    bus.say(f"⚠ {ch['name']} · book {bid} could not be fetched: {e}")
                    continue
                free = [r for r in rows if f"{ch['id']}:{bid}:{r['n']}" not in used and r["words"] >= least]
                told = sum(f"{ch['id']}:{bid}:{r['n']}" in used for r in rows)
                if free and (best is None or told < best[0]):
                    best = (told, int(bid), free[0])
            if not best:
                return None
            _, bid, row = best
            key = f"{ch['id']}:{bid}:{row['n']}"
            text = gutenberg.read(bid, row["n"])
            safe = not UNSAFE.search(text)
            store.kv_put(CLASSICS, key, {"title": row["title"], "used": safe})
            used.add(key)
            if not safe:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", row["title"].lower()).strip("-")[:40] or f"{bid}-{row['n']}"
            work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{'long-' if long else ''}{slug}"
            work.mkdir(parents=True, exist_ok=True)
            cite = {"title": row["title"], "author": row["author"], "book": row["book"], "url": gutenberg.page(bid)}
            tag = "long" if long else "classic"
            ctx["job"] = {"id": f"{ch['id']}-{tag}-{bid}-{row['n']}", "key": f"{ch['id']}:{tag}-{bid}-{row['n']}", "channel": ch["id"], "dir": str(work),
                          "format": "long" if long else "short", "raw": text, "classic": cite, "source": {"url": cite["url"], "title": row["title"], "from": "classic", "score": None}}
            return cite
        return None

    def _mixes(self, genre: str, bank: list[dict], rng) -> list[tuple[str, str]]:
        """Eight (seed, ingredient line) pairs for a genre. A science subject is not taken twice while others are still unused."""
        if genre in BANKS:
            taken = {p.get("seed") for p in bank}
            subjects = [(d, t) for d, ts in BANKS[genre].items() for t in ts]
            subjects = [x for x in subjects if not told_elsewhere(x[1], self._elsewhere)] or subjects     # (new channels only: see told_elsewhere)
            pool = [x for x in subjects if f"{x[0]}: {x[1]}" not in taken] or subjects
            hot = [x for x in pool if trend_score(x[1], self._hot) > 0][:3]
            rest = [x for x in pool if x not in hot]
            return [(f"{d}: {t}", f"{d}: {t}; told {rng.choice(ANGLES)}") for d, t in hot + rng.sample(rest, min(8 - len(hot), len(rest)))]
        if genre == "money":
            taken = {p.get("seed") for p in bank}
            pool = [t for t in MONEY if t not in taken] or MONEY
            hot = [t for t in pool if trend_score(t, self._hot) > 0][:3]         # subjects that touch what is being watched today go in first
            rest = [t for t in pool if t not in hot]
            return [(t, t) for t in hot + rng.sample(rest, min(8 - len(hot), len(rest)))]
        if genre == "motivational":
            return [("", f"{rng.choice(STRUGGLES)}; about {rng.choice(TELLERS)}; in {rng.choice(SETTINGS)}; it turns on {rng.choice(LIFTS)}") for _ in range(8)]
        return [("", f"{rng.choice(THEMES)}; set in {rng.choice(SETTINGS)}; told about {rng.choice(TELLERS)}; it comes out through {rng.choice(TURNS)}") for _ in range(8)]

    async def _premises(self, ctx: dict, bank: list[dict], genre: str) -> list[dict]:
        """Ask the model for a batch of new premises, each from its own mix of ingredients; keep the ones unlike any before."""
        ch, store = self.ch, ctx["store"]
        self._elsewhere = others_recent(store, ch) if ch.get("avoid_others") else []
        mixes = self._mixes(genre, bank, self.opts.get("rng") or random)
        ask, shape = GENRE_ASK[genre]
        listing = "\n".join(f"{n + 1}. {line}" for n, (_, line) in enumerate(mixes))
        got = None
        for _ in range(2):                            # the model now and then returns a broken list: ask once more
            got = await ctx["llm"].json(
                f"{ask} Each must be clearly different from the others and from these already used: " + "; ".join(p["title"] for p in bank[:40]) + ".\n"
                f'Answer as a JSON list of {len(mixes)} objects: {{"title": "under 60 characters", "premise": "{shape}"}}.\n\n{listing}', tier="writer", max_tokens=3000)
            if isinstance(got, list) and got:
                break
        old = [p["premise"].lower() for p in bank]
        fresh = []
        for n, d in enumerate(got if isinstance(got, list) else []):
            text = " ".join(str((d or {}).get("premise") or "").split()) if isinstance(d, dict) else ""
            if not 60 <= len(text) <= 900 or UNSAFE.search(text) or any(difflib.SequenceMatcher(None, text.lower(), o).ratio() > 0.75 for o in old):
                continue
            rec = {"channel": ch["id"], "genre": genre, "seed": mixes[n][0] if n < len(mixes) else "", "used": False,
                   "title": " ".join(str(d.get("title") or text[:50]).split())[:80], "premise": text}
            key = f"{ch['id']}:{time.time_ns()}-{n}"
            store.kv_put(PREMISES, key, rec)
            old.append(text.lower())
            fresh.append({**rec, "_key": key})
        return fresh

    def _lean(self, options: list[str], told: dict[str, int], views: dict[str, float]) -> str:
        # the floor is held to 70% of the whole, so a long list (seven patterns) still leaves something to lean on
        return choose(options, told, views, min(self.ch["explore"], 0.7 / len(options)))

    async def _original(self, ctx: dict, want: str | None = None) -> dict | None:
        ch, store = self.ch, ctx["store"]
        everything = [p for p in store.kv_list(PREMISES, limit=5000) if p.get("channel") == ch["id"]]
        genres = [g for g in ch["original_genres"] if g in GENRE_ASK] or ["life"]
        told = {g: sum(p.get("used") and p.get("genre", "life") == g for p in everything) for g in genres}
        log = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"]]
        insights = store.kv_get(STATE, f"{ch['id']}:insights") or {}
        learned = ch["double_down"] and insights.get("videos", 0) >= ch["double_down_after"]       # enough results to lean on
        if want and want in GENRE_ASK:             # the day's mix names the kind
            genre = want
        elif learned:
            by_kind = insights.get("views_by_kind") or {}
            genre = self._lean(genres, told, {g: by_kind["original" if g == "life" else g] for g in genres if ("original" if g == "life" else g) in by_kind})
        else:
            genre = min(genres, key=lambda g: told[g])             # the kind told least so far, so the kinds take turns
        bank = [p for p in everything if p.get("genre", "life") == genre]
        self._hot = trending_words(store.kv_get(STATE, f"{ch['id']}:trends")) if ch["trends"] else set()
        fresh = [p for p in bank if not p.get("used")] or await self._premises(ctx, bank, genre)
        if not fresh:
            return None
        p = max(reversed(fresh), key=lambda x: trend_score(x.get("seed") or x["title"], self._hot))    # one that touches today's list, else the oldest waiting
        store.kv_put(PREMISES, p["_key"], {k: v for k, v in p.items() if not k.startswith("_")} | {"used": True})
        tail = p["_key"].split(":", 1)[1]
        slug = re.sub(r"[^a-z0-9]+", "-", p["title"].lower()).strip("-")[:40] or tail
        work = ROOT / "data" / "shorts" / ch["id"] / f"{time.strftime('%Y%m%d')}-{slug}"
        work.mkdir(parents=True, exist_ok=True)
        ctx["job"] = {"id": f"{ch['id']}-orig-{tail}", "key": f"{ch['id']}:orig-{tail}", "channel": ch["id"], "dir": str(work), "raw": p["premise"],
                      "original": True, "genre": genre, "source": {"url": "", "title": p["title"], "from": f"original ({genre})", "score": None}}
        if genre in LEARN_KINDS:                     # a learning video follows one of the watch-to-the-end patterns, the least used so far
            used = [v.get("structure") for v in log]
            shapes = list(STRUCTURES)
            ctx["job"]["structure"] = (self._lean(shapes, {k: used.count(k) for k in shapes}, insights.get("views_by_structure") or {})
                                       if learned else min(shapes, key=used.count))
        group = "lesson" if genre in LEARN_KINDS else "story"      # and an opening shape, likewise the least used (or the best performing)
        told_h = [v.get("hook") for v in log]
        keys = list(HOOKS[group])
        ctx["job"]["hook"] = (self._lean(keys, {k: told_h.count(k) for k in keys}, {k: x for k, x in (insights.get("views_by_hook") or {}).items() if k in keys})
                              if learned else min(keys, key=told_h.count))
        Q = quick_of(ch)
        if Q["per_day"] and made_today(store, ch, quick=True) < Q["per_day"]:      # a short, sharp one among the day's Shorts
            ctx["job"]["quick"] = True
        return p


class StoryWriter(Crew):
    name, tier, note = "Story Writer", "CLOUD", "retells it with a hook, names and places removed"

    async def _long(self, ctx: dict, job: dict) -> AgentResult:
        """A long retelling, written chapter by chapter: each request carries only its own part of the original, so
        the whole stays inside the hosted model's per-minute allowance and no chapter is rushed."""
        L, cite, src = long_of(self.ch), job["classic"], job["raw"]
        total = max(L["minutes"][0] * 150, min(L["minutes"][1] * 150, int(words(src) * 0.55)))      # about 150 spoken words a minute
        pieces = parts(src, max(3, min(6, round(words(src) / 700))))
        per, chapters = total // len(pieces), []
        for k, piece in enumerate(pieces):
            where = ("Open with one sentence that hooks a listener, then begin the story." if k == 0 else
                     "This is the end of the story: keep the author's own ending, and add no moral of your own." if k == len(pieces) - 1 else
                     "Do not wrap anything up: the story goes on in the next part.")
            prev = f"- The part before this one ended: “{' '.join(chapters[-1]['text'].split()[-45:])}” Carry straight on from there; do not repeat it.\n" if chapters else ""
            prompt = (f"You are retelling the classic short story “{cite['title']}” by {cite['author']} for a narrated video, in {len(pieces)} parts. "
                      f"This is part {k + 1}.\n"
                      f"- Retell only this part, faithfully, in {int(per * 0.8)}-{int(per * 1.25)} words: the same characters and events, in order; the turns of the story "
                      "matter more than every line of talk. Add nothing.\n"
                      "- Third person, your own plain spoken sentences, easy to follow by ear; do not copy the author's sentences. Character names may stay.\n"
                      f"- {OLD_WORDS}\n"
                      f"- {where}\n{prev}"
                      'Answer as {"heading": "2-5 words naming this part, giving nothing away", "text": "..."}.\n\n'
                      f"This part of the original:\n{piece}")
            note, best = "", None
            for _ in range(3):                         # a part heavy with dialogue comes back long: ask again, then take the nearest
                d = await ctx["llm"].json(prompt + note, tier="writer", max_tokens=2600)
                text = " ".join(str((d or {}).get("text") or "").split()) if isinstance(d, dict) else ""
                if words(text) >= min(80, per * 0.5) and (best is None or abs(words(text) - per) < abs(words(best["text"]) - per)):
                    best = {"heading": " ".join(str(d.get("heading") or f"Part {k + 1}").split())[:50], "text": text}
                if per * 0.6 <= words(text) <= per * 1.5:
                    break
                note = f"\n\nYour last answer had {words(text)} words. This part must be between {int(per * 0.8)} and {int(per * 1.25)} words, as JSON."
            if not best:
                raise RuntimeError(f"the model did not return part {k + 1} of {len(pieces)}")
            chapters.append(best)
        job["chapters"], job["script"] = chapters, " ".join(c["text"] for c in chapters)
        meta = await ctx["llm"].json(
            f"For a narrated video retelling “{cite['title']}” by {cite['author']}, answer as "
            '{"title": "under 70 characters, built around the story\'s own title", "thumbnail": "2-5 words for the cover image that make someone click, '
            'giving nothing away", "thumbnail_image": "2-4 words: one concrete thing to photograph for the cover", "summary": "two sentences for the '
            f'description, giving nothing away", "hashtags": ["3 to 5 words, no #"], "mood": "one word: {" | ".join(MOODS)}"}}.\n\n'
            f"How it opens:\n{' '.join(job['script'].split()[:260])}", tier="writer", max_tokens=1200)
        meta = meta if isinstance(meta, dict) else {}
        job["title"] = " ".join(str(meta.get("title") or f"{cite['title']}, by {cite['author']}").split())[:90]
        job["thumb_text"] = " ".join(str(meta.get("thumbnail") or cite["title"]).split()[:6])
        job["thumb_query"] = " ".join(str(meta.get("thumbnail_image") or "").split())[:60]
        job["summary"] = " ".join(str(meta.get("summary") or "").split())[:400]
        job["hashtags"] = ["#" + re.sub(r"\W", "", str(h)) for h in (meta.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:5]
        mood = re.sub(r"[^a-z]", "", str(meta.get("mood") or "").lower())
        job["mood"] = mood if mood in MOODS else ""
        return AgentResult("done", "WRITTEN", f"“{job['title']}” · {words(job['script'])} words in {len(chapters)} chapters" + (f" · {job['mood']}" if job["mood"] else ""))

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if job.get("format") == "long":
            return await self._long(ctx, job)
        quick = bool(job.get("quick"))
        lo, hi = word_range(self.ch, quick)
        pad = 3 if quick else 20                                 # a quick story's range is narrow: keep its target inside it
        length = f"a {'-'.join(str(x) for x in quick_of(self.ch)['seconds'])} second video" if quick else "a 1-2 minute video"
        ending = ENDINGS.get(self.ch["ending"], ENDINGS["plain"])
        head, rules = GENRE_WRITE.get(job.get("genre") or "life", GENRE_WRITE["life"])
        science, learning = job.get("genre") in ("science", "space", "body", "geography"), job.get("structure") in STRUCTURES
        shape = f"- Build it exactly like this: {STRUCTURES[job['structure']]}\n- {HOLD_BACK}\n" if learning else f"- {RETAIN_STORY}\n"
        opener = HOOKS["story"].get(job.get("hook") or "")
        if opener and not learning:                 # a story opens in its shape; a lesson's first line belongs to its pattern
            shape += f"- Shape the first sentence like this one, fitted to this story and in the third person: “{opener}”\n"
        close = ("End on the one thing to remember or do." if job.get("genre") == "money" else "End on what it means for us, or the wonder of it." if science else ending)
        prompt = (f"{head}, narrated for {length}, {lo + pad}-{hi - pad} words.\n"
                  "- The first sentence is a hook that makes someone stop scrolling (never say \"stop scrolling\" or speak to the scrolling itself).\n"
                  + shape + rules + ("- It will be read aloud: no brackets, no labels such as \"Step 1:\"; let the story flow from one point to the next.\n"
                                     if job.get("genre") in ("space", "body", "geography") else
                                     "- It will be read aloud: no brackets, no labels such as \"Step 1:\"; say \"first\", \"then\", \"and the most useful one\".\n") +
                  "- Short spoken sentences. " + close + " No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"Premise:\n{job['raw']}") if job.get("original") else (
                  f"Retell the classic short story below for {length}, {lo + pad}-{hi - pad} words.\n"
                  "- Stay faithful: the same characters, events and the author's own ending. Do not modernise it or add a moral of your own.\n"
                  "- Third person, in your own plain spoken sentences; do not copy the author's sentences. Character names from the story may stay.\n"
                  f"- {OLD_WORDS}\n"
                  "- The first sentence is a hook that makes someone stop scrolling. No call to subscribe.\n"
                  f'Answer as {{"title": "under 70 characters, built around the story\'s own title", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"“{job['classic']['title']}” by {job['classic']['author']}:\n{job['raw'][:40000]}") if job.get("classic") else (
                  f"Retell the personal story below as a narrated story for {length}, {lo + pad}-{hi - pad} words.\n"
                  "- Third person, as if retelling something shared anonymously (\"a woman\", \"he\", \"they\").\n"
                  "- The first sentence is a hook that makes someone stop scrolling.\n"
                  "- Keep the real events, feelings and outcome. You may add small build-ups and pauses for suspense, but no new events or facts.\n"
                  "- No personal names at all, and no city, workplace, school or other identifying detail; use generic terms.\n"
                  "- Short spoken sentences. " + ENDINGS.get(self.ch["ending"], ENDINGS["plain"]) + " No call to subscribe.\n"
                  'Answer as {"title": "under 70 characters, no names", "story": "...", "hashtags": ["3 to 5 words, no #"], '
                  f'"mood": "the one word that fits the story best: {" | ".join(MOODS)}"}}.\n\n'
                  f"Story:\n{job['raw'][:6000]}")
        note = ""
        for _ in range(2):
            d = await ctx["llm"].json(prompt + note, tier="writer", max_tokens=2500)
            story = " ".join(str((d or {}).get("story") or "").split()) if isinstance(d, dict) else ""
            n = words(story)
            if job.get("genre") == "money" and (TOLD_PROMISE.search(story) or promises(str((d or {}).get("title") or ""))):
                note = ("\n\nYour last answer promised or suggested an amount, a speed or a certainty of earning. Write it again with no such promise: "
                        "what it costs, how long it takes and what can go wrong, as JSON.")
                continue
            if (job.get("original") and UNSAFE.search(story)) or SEXUAL.search(story):
                note = "\n\nYour last story touched something it must not (sexual content, self-harm or violent crime). Write it again without that, as JSON."
                continue
            if lo <= n <= hi:
                job["title"] = " ".join(str(d.get("title") or job["source"]["title"]).split())[:90]
                job["script"] = story
                mood = re.sub(r"[^a-z]", "", str(d.get("mood") or "").lower())
                job["mood"] = mood if mood in MOODS else ""
                job["hashtags"] = ["#" + re.sub(r"\W", "", str(h)) for h in (d.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:5]
                return AgentResult("done", "WRITTEN", f"“{job['title']}” · {n} words" + (f" · {job['mood']}" if job["mood"] else ""))
            note = f"\n\nYour last answer had {n} words. It must be between {lo} and {hi} words, as JSON."
        raise RuntimeError(f"the model did not return a story of {lo}-{hi} words")


class ScreenplayWriter(Crew):
    name, tier, note = "Screenplay Writer", "QUICK", "splits the story into timed beats"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if job.get("format") == "long":             # chapter by chapter; the picture changes every few sentences, not every one
            beats: list[dict] = []
            for k, chp in enumerate(job["chapters"]):
                mine = screenplay(chp["text"], "")
                if mine:
                    mine[0]["heading"] = chp["heading"]
                beats += [{**b, "chapter": k} for b in mine]
            beats += screenplay(f"This was a retelling of “{job['classic']['title']}”, by {job['classic']['author']}.", self.ch["outro"])
            shot, run, need = 0, 0.0, long_of(self.ch)["shot_seconds"]
            for i, b in enumerate(beats):
                last = i + 1 == len(beats) or beats[i + 1]["kind"] == "outro" or beats[i + 1].get("chapter") != b.get("chapter")
                b["i"], b["shot"] = i, shot
                run += b["target_s"]
                if run >= need or last or b["kind"] == "outro":
                    shot, run = shot + 1, 0.0
            job["beats"] = beats
            plan = sum(b["target_s"] for b in beats)
            return AgentResult("done", "TIMED", f"{len(beats)} beats in {shot} shots, about {clock(plan)}")
        told = job["script"]
        if job.get("classic"):                      # the citation is spoken, as the story's last line
            told += f" A retelling of “{job['classic']['title']}”, by {job['classic']['author']}."
        job["beats"] = screenplay(told, quick_of(self.ch)["outro"] if job.get("quick") else self.ch["outro"])
        for b in job["beats"]:
            b["shot"] = b["i"]                      # in a Short every beat has its own picture
        plan = sum(b["target_s"] for b in job["beats"])
        return AgentResult("done", "TIMED", f"{len(job['beats'])} beats, about {round(plan)} s")


class KeywordGenerator(Crew):
    name, tier, note = "Keyword Generator", "CLOUD", "one footage search per beat"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        groups: dict[int, list[dict]] = {}
        for b in job["beats"]:
            if b["kind"] == "story":
                groups.setdefault(b.get("shot", b["i"]), []).append(b)
        shots, modelled = list(groups.values()), True
        for at in range(0, len(shots), 30):           # a long video has more shots than one request should carry
            batch = shots[at:at + 30]
            listing = "\n".join(f"{n + 1}. {' '.join(x['text'] for x in g)[:320]}" for n, g in enumerate(batch))
            got = None
            try:
                got = await ctx["llm"].json(
                    "For each numbered line of this story give one stock-footage search of 2-4 words: a concrete thing a camera could film that fits the "
                    "line (\"woman staring out rainy window\", not \"sadness\"). No names, no text on screen. "
                    f'Answer as a JSON list of exactly {len(batch)} strings, in order.\n\n{listing}', tier="writer", max_tokens=1800, light=True)
            except Exception:
                pass                              # no model: plain keywords from the line itself
            ok = isinstance(got, list) and len(got) == len(batch)
            modelled = modelled and ok
            for n, g in enumerate(batch):
                q = str(got[n]).strip()[:60] if ok and str(got[n]).strip() else fallback_query(g[0]["text"])
                for x in g:
                    x["query"] = q
        for b in job["beats"]:
            b.setdefault("query", self.ch["outro_query"])
        job["keywords"] = [b["query"] for b in job["beats"]]
        cues = await self._cues(ctx, shots) if self.ch["sfx"] else 0
        return AgentResult("done", "DONE", f"{len(shots) + 1} searches" + ("" if modelled else " (plain keywords where the model gave none)")
                           + (f", {cues} sound cue{'s' if cues != 1 else ''}" if self.ch["sfx"] else ""))

    async def _cues(self, ctx: dict, shots: list[list[dict]]) -> int:
        """Ask which lines call for a sound, and which one. Most get none; a line gets a sound only if the moment needs it."""
        kinds = [k for k in CUES if sfx.tracks(k)]              # only sounds the library actually has
        if not kinds:
            return 0
        given = 0
        for at in range(0, len(shots), 35):
            batch = shots[at:at + 35]
            listing = "\n".join(f"{n + 1}. {' '.join(x['text'] for x in g)[:260]}" for n, g in enumerate(batch))
            got = None
            try:
                got = await ctx["llm"].json(
                    "This narration will have a few sound effects. For each numbered line name the one sound the moment truly calls for, or \"none\". "
                    f"Most lines need none: a sound belongs only where it makes a listener feel that moment more. At most {max(1, len(batch) // 5)} "
                    "lines in all, and never two lines in a row. Choose only from: " + "; ".join(f"{k} ({CUES[k]})" for k in kinds) + ". "
                    f'Answer as a JSON list of exactly {len(batch)} strings, in order.\n\n{listing}', tier="writer", max_tokens=1200, light=True)
            except Exception:
                pass                              # no model: no sound effects, which is always safe
            if not (isinstance(got, list) and len(got) == len(batch)):
                continue
            for g, cue in zip(batch, got):
                cue = re.sub(r"[^a-z]", "", str(cue).lower())
                if cue in kinds:
                    g[0]["cue"] = cue
                    given += 1
        return given


class SEOStrategist(Crew):
    """Packages a video so it can be found and gets the click: the title, the first lines of the description and the
    search tags. It starts from what people really type into YouTube's search box and from the titles that have done
    best on this channel so far, and it never promises what the story doesn't deliver. If it fails, the writer's own
    title stands and the video is made all the same."""
    name, tier, note, blocking = "SEO Strategist", "CLOUD", "title, description and tags from real searches", False

    def seeds(self, job: dict) -> list[str]:
        what = {"science": "science explained", "money": "personal finance tips", "space": "space facts", "body": "human body facts", "geography": "geography facts", "motivational": "motivational story", "classic": "short story", "viewer": "true-to-life story",
                "real": "true-to-life story", "original": "true-to-life story"}[kind(job)]
        mine = " ".join(w for w in re.findall(r"[A-Za-z]{4,}", job.get("title", "")) if w.lower() not in STOP)
        out = [what, " ".join(mine.split()[:3])]
        if job.get("classic"):
            out.append(f"{job['classic']['title']} {job['classic']['author']}")
        if job.get("genre") in LEARN_KINDS:
            out.append(" ".join(job["source"]["title"].split()[:4]))
        return [x for x in dict.fromkeys(out) if x.strip()]

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        ch, before = self.ch, job["title"]
        searched: list[str] = []
        async with self.client() as c:
            for phrase in self.seeds(job)[:3]:
                searched += await yt_suggest.suggest(c, phrase)
        searched = list(dict.fromkeys(searched))[:24]
        learned = (ctx["store"].kv_get(STATE, f"{ch['id']}:insights") or {}).get("top_titles") or []
        today = (ctx["store"].kv_get(STATE, f"{ch['id']}:trends") or {}) if ch["trends"] else {}
        mine = job["title"] + " " + job["script"]     # only the few that share a telling word with this video are worth showing the model
        watching = [t["title"] for t in today.get("videos") or [] if trend_score(mine, trending_words({"videos": [t]})) > 0][:6]
        fixed = (f" It retells “{job['classic']['title']}” by {job['classic']['author']}: the story's title and the author's name must be in the title."
                 if job.get("classic") else "")
        d = await ctx["llm"].json(
            f"You package a {'long video' if job.get('format') == 'long' else 'YouTube Short'} for the channel “{ch['name']}” so that it is found in "
            f"search and people choose to watch it.{fixed}\n"
            "- title: under 60 characters, the strongest words first, plain sentence case, honest: it may only promise what the story delivers. No "
            "capitals for emphasis, no emoji, no \"you won't believe\", and never call fiction true.\n"
            + ("- This is a lesson: the title is an open question that the video explores and does not answer in the title (\"How can we make money "
               "from this?\", \"Can you really live on one income?\", \"Everybody makes money, but at what cost?\"). It asks; it never states an "
               "amount, a speed or a certainty of earning.\n" if job.get("structure") else "")
            + (f"- A title shape to borrow from only if the lesson really shows it, and turned into a question: “{HOOKS['lesson'][job['hook']]}”. "
               "Otherwise keep to a plain open question.\n" if job.get("hook") in HOOKS["lesson"] else "") +
            "- lead: one or two sentences for the top of the description that say what the video is, using the main search phrase early and naturally.\n"
            "- tags: 8 to 12 search phrases of 2-4 words that someone looking for exactly this video would type, the most specific first. Leave out any "
            "that describe a different video: another language, \"for kids\", \"animated\", \"official\", and \"real life\" or \"true\" for fiction.\n"
            "- hashtags: exactly 3 single words, no #.\n"
            + ("Phrases people are typing into YouTube's search right now (use the ones that truly fit, ignore the rest): " + "; ".join(searched) + "\n" if searched else "")
            + ("Titles that have done best on this channel so far (learn their shape, do not copy them): " + "; ".join(learned[:5]) + "\n" if learned else "")
            + ("Being watched most on YouTube today and touching this video's subject (its angle may shape a tag or the title only if it truly "
               "connects; never force it, never name a channel or a person): " + "; ".join(watching) + "\n" if watching else "")
            + 'Answer as {"title": "...", "lead": "...", "tags": ["..."], "hashtags": ["..."]}.\n\n'
            f"Working title: {before}\nKind: {kind(job)}\nHow it opens:\n{' '.join(job['script'].split()[:150])}", tier="writer", max_tokens=900)
        if not isinstance(d, dict):
            return AgentResult("done", "KEPT", f"No packaging from the model; the writer's title stands: “{before}”")
        title = " ".join(str(d.get("title") or "").split()).strip("\"“” ")
        title = title[:1].upper() + title[1:]          # sentence case still starts with a capital
        if 15 <= len(title) <= 70 and not (job.get("original") and re.search(r"\btrue\b", title, re.I)) and not (kind(job) == "money" and promises(title)):
            job["title"] = title
        tags, size = [], 0
        wrong = r"\b(for kids|animated|official|in (hindi|tamil|telugu|urdu|nepali|tagalog|malayalam|punjabi|spanish))\b" + (
            r"|\b(real life|true)\b" if kind(job) in ("original", "motivational") else "") + (
            r"|\b(get rich|rich quick|overnight|guarantee\w*|easy money|free money)\b" if kind(job) == "money" else "")
        wrong += r"|\b(usa|uk|india|canada|australia|philippines)\b"
        mine = set(re.findall(r"[a-z]{4,}", (job["title"] + " " + job["script"]).lower())) - STOP
        seeds = {x.lower() for x in self.seeds(job)}
        for t in d.get("tags") or []:                 # YouTube allows about 500 characters of tags in all
            t = " ".join(re.sub(r"[<>#,]", " ", str(t)).split())
            if not (t.lower() in seeds or mine & set(re.findall(r"[a-z]{4,}", t.lower()))):
                continue                              # a phrase with nothing in common with the video is someone else's search
            if t and len(t) <= 40 and not re.search(wrong, t, re.I) and size + len(t) + 3 <= 430 and t.lower() not in (x.lower() for x in tags):
                tags.append(t)
                size += len(t) + 3
        hashtags = ["#" + re.sub(r"\W", "", str(h)) for h in (d.get("hashtags") or []) if re.sub(r"\W", "", str(h))][:3]
        if len(hashtags) == 3:
            job["hashtags"] = hashtags
        job["seo"] = {"lead": " ".join(str(d.get("lead") or "").split())[:300], "tags": tags, "searched": searched[:12], "title_before": before}
        return AgentResult("done", "PACKAGED", f"“{job['title']}” · {len(tags)} search tags · from {len(searched)} real searches"
                           + (f", {len(learned[:5])} of our best titles" if learned else ""))


class VoiceArtist(Crew):
    """Narrates sentence by sentence (a whole sentence keeps its intonation), then divides each sentence's audio
    between its beats. The voice follows the story's mood (channel option `voices`), else the channel's own voice.
    Engines: edge (online, reports its word timings) and kokoro (VISION's local voices; a local Whisper model then
    listens to each sentence to time its words, so captions never drift)."""
    name, tier, note = "Voice Artist", "API", "a voice for the mood, sentence by sentence"

    def voice_for(self, mood: str) -> dict:
        ch = self.ch
        return {"engine": ch["voice_engine"], "voice": ch["voice"], "speed": ch["voice_speed"], "pause": ch["pause"], **((ch.get("voices") or {}).get(mood) or {})}

    async def _edge(self, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        import edge_tts
        kw = {"rate": f"{round((float(v['speed']) - 1) * 100):+d}%"}
        try:
            com = edge_tts.Communicate(text, v["voice"], boundary="WordBoundary", **kw)
        except TypeError:                         # older edge-tts: word timings are the default
            com = edge_tts.Communicate(text, v["voice"], **kw)
        marks, raw = [], stem.with_suffix(".mp3")
        with open(raw, "wb") as f:
            async for ch in com.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    marks.append([ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7])
        return raw, marks or None

    def _kokoro(self, ctx: dict, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        import soundfile
        from kokoro_onnx import Kokoro
        vc = ctx["cfg"].voice
        if self._model is None:
            self._model = Kokoro(str(ROOT / vc.get("kokoro_model", "models/kokoro-v1.0.onnx")), str(ROOT / vc.get("kokoro_voices", "models/voices-v1.0.bin")))
        if v["voice"] not in self._model.get_voices():
            raise RuntimeError(f"Kokoro has no voice named {v['voice']}")
        samples, rate = self._model.create(text, voice=v["voice"], speed=float(v["speed"]), lang="en-gb" if v["voice"].startswith("b") else "en-us")
        raw = stem.with_suffix(".src.wav")
        soundfile.write(raw, samples, rate)
        try:
            import mlx_whisper
        except ImportError:
            return raw, None                       # no listener: captions are spread over the beat instead
        heard = mlx_whisper.transcribe(str(raw), path_or_hf_repo=vc.get("whisper_model", "mlx-community/whisper-small-mlx"), language="en",
                                       word_timestamps=True, initial_prompt=text)
        return raw, [[w["word"], w["start"], w["end"]] for seg in heard.get("segments", []) for w in seg.get("words", [])] or None

    async def _synth(self, ctx: dict, v: dict, text: str, stem: Path) -> tuple[Path, list | None]:
        if self.opts.get("synth"):
            return await self.opts["synth"](text, stem)
        if v["engine"] == "kokoro":
            return await asyncio.to_thread(self._kokoro, ctx, v, text, stem)
        return await self._edge(v, text, stem)

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        folder = Path(job["dir"]) / "audio"
        folder.mkdir(exist_ok=True)
        v = self.voice_for(job.get("mood", ""))
        job["voice"] = f"{v['engine']} {v['voice']}"
        pause = float(v["pause"])
        self._model = None
        group: list[dict] = []
        timed = total_lines = 0
        try:
            for b in job["beats"]:
                group.append(b)
                if not b.get("end", True):
                    continue
                stem = folder / f"line{group[0]['i']:02d}"
                text = " ".join(x["text"] for x in group)
                raw, heard = await self._synth(ctx, v, text, stem)
                wav = stem.with_suffix(".wav")
                await asyncio.to_thread(shorts_edit.run, ["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", f"apad=pad_dur={pause}",
                                                          "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
                total = await asyncio.to_thread(shorts_edit.probe, wav)
                marks = align(text, heard, total - pause)
                timed, total_lines = timed + bool(marks), total_lines + 1
                durs, per = split_times([x["text"] for x in group], total - pause, marks)
                durs[-1] += pause                                   # the pause after the sentence stays on its last beat
                for x, d, m in zip(group, durs, per):
                    x["audio"], x["dur"], x["words"] = str(wav), d, m
                    x["speech"] = d - (pause if x is group[-1] else 0)
                group = []
        finally:
            self._model = None                                      # the local voice model is large: let it go after the run
        total = sum(b["dur"] for b in job["beats"])
        job["seconds"] = round(total, 1)
        note = "" if timed == total_lines else f"; captions estimated on {total_lines - timed} of {total_lines} sentences"
        return AgentResult("done", "RECORDED", f"{round(total)} s in {v['voice']}" + (f" for a {job['mood']} story" if job.get("mood") else "") + note)


class FootageCollector(Crew):
    name, tier, note = "Footage Collector", "API", "free stock clips and photos, one per beat"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if not stock_video.configured():
            raise RuntimeError("PEXELS_API_KEY or PIXABAY_API_KEY missing in .env")
        folder = Path(job["dir"]) / "footage"
        folder.mkdir(exist_ok=True)
        used: set[str] = set()
        wide = job.get("format") == "long"
        shots: dict[int, dict | None] = {}             # one clip or photo per shot; the beats of a shot share it
        async with self.client() as c:
            for b in job["beats"]:
                sid = b.get("shot", b["i"])
                if sid in shots:
                    b["visual"] = shots[sid]
                    continue
                b["visual"] = shots[sid] = None
                hit = None
                if "nasa" in (self.ch.get("footage_first") or []):        # a space channel: NASA's own public-domain media first (services/nasa_media.py)
                    from ..services import nasa_media
                    hit = await nasa_media.find(c, b["query"], used, wide=wide)
                hit = hit or await stock_video.find(c, b["query"], used, wide=wide) or await stock_video.find(c, fallback_query(b["text"]), used, wide=wide)
                if not hit:
                    continue
                path = folder / f"shot{sid:03d}.{'mp4' if hit['kind'] == 'video' else 'jpg'}"
                try:
                    await stock_video.download(c, hit["url"], path)
                except httpx.HTTPError:
                    continue
                b["visual"] = shots[sid] = {**{k: hit[k] for k in ("kind", "duration", "credit", "page", "source")}, "path": str(path)}
        have = [v for v in shots.values() if v]
        clips = sum(v["kind"] == "video" for v in have)
        return AgentResult("done", "COLLECTED", f"{len(have)} of {len(shots)} shots have footage ({clips} clips, {len(have) - clips} photos)")


class FootageGenerator(Crew):
    """Animated diagram scenes for some lines (scenes.py, channel option `diagrams`: the kinds that may have them), then fills
    beats the stock libraries had nothing for, through an online AI provider (services/genmedia.py)."""
    name, tier, note, blocking = "Footage Generator", "CLOUD", "animated diagrams; AI clip for a beat with no footage", False

    async def _scenes(self, ctx: dict, job: dict) -> str:
        """Asks the model which lines a diagram explains better than footage, keeps the scenes that pass scenes.check, renders
        them in one go and puts each on its beat (`diagram` on the visual: the Editor gives it no zoom). Any trouble: footage stays."""
        from . import scenes
        from ..services import hyperframes
        group = kind(job) if kind(job) in LEARN_KINDS else "story"
        if group not in (self.ch.get("diagrams") or []) or job.get("format") == "long" or not ctx.get("llm"):
            return ""
        beats = [b for b in job["beats"] if b.get("kind") != "outro" and b.get("dur")]
        if len(beats) < 3 or not hyperframes.ready():
            return ""
        most = 2 if group == "story" else max(1, round(len(beats) * 0.4))     # a story keeps its footage: a scene or two at most
        try:
            got = await ctx["llm"].json(scenes.ask([b["text"] for b in beats], {group}, most), tier="writer", max_tokens=1500, light=True)
        except Exception:  # noqa: BLE001 - no answer: footage only
            return ""
        picked, used = [], set()
        for raw in (got or {}).get("scenes", []) if isinstance(got, dict) else []:
            i = raw.get("line") if isinstance(raw, dict) else None
            if not isinstance(i, int) or not 0 < i < len(beats) or i in used or len(picked) >= most:
                continue
            sc = scenes.check(raw, beats[i]["text"], {group})
            if sc and any(sc == x for _, x in picked):                  # the same scene twice says nothing new
                continue
            if sc and any(abs(i - j) == 1 and x["template"] == sc["template"] for j, x in picked):    # nor the same template back to back
                continue
            if sc:
                picked.append((i, sc))
                used.add(i)
        if not picked:
            return "no diagram fits"
        picked.sort()
        work = Path(job["dir"]) / "footage"
        work.mkdir(parents=True, exist_ok=True)
        try:
            clips = await asyncio.to_thread(scenes.render_shots, [(sc, beats[i]["dur"]) for i, sc in picked], work)
        except hyperframes.RenderFailed as e:
            return f"diagrams not rendered: {e}"[:120]
        for (i, sc), clip in zip(picked, clips):
            beats[i]["visual"] = {"kind": "video", "path": str(clip), "duration": beats[i]["dur"], "credit": "Animated diagram (VISION)", "page": "",
                                  "source": "diagram", "diagram": True}
        job["diagrams"] = [{"line": i, "template": sc["template"]} for i, sc in picked]
        return f"{len(picked)} animated diagram{'s' if len(picked) > 1 else ''} ({', '.join(sc['template'] for _, sc in picked)})"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        drawn = await self._scenes(ctx, job)
        missing = [b for b in job["beats"] if not b.get("visual")]
        spec = self.ch.get("generator") or {}
        if not genmedia.ready(spec):
            if job.get("diagrams"):
                return AgentResult("done", "DIAGRAMS", drawn + (f"; {len(missing)} beats reuse the footage beside them" if missing else ""))
            return AgentResult("off", "OFF", (drawn + "; " if drawn else "") + (f"No AI provider set; {len(missing)} beats reuse the footage beside them" if missing else "No AI provider set; not needed this time"))
        kind = spec.get("kind", "image")
        async with self.client() as c:
            for b in missing:
                out = Path(job["dir"]) / "footage" / f"beat{b['i']:02d}.{'mp4' if kind == 'video' else 'png'}"
                await genmedia.generate(c, spec, f"{b['query']}, cinematic, vertical 9:16, no text", out, kind=kind, seconds=b["dur"])
                b["visual"] = {"kind": "video" if kind == "video" else "photo", "duration": 0, "path": str(out),
                               "credit": f"AI generated ({spec['provider']})", "page": "", "source": spec["provider"]}
        return AgentResult("done", "GENERATED", f"{len(missing)} beats filled by {spec['provider']}")


class Editor(Crew):
    name, tier, note = "Editor", "LOCAL", "cuts, captions, watermark, subscribe animation"

    async def run(self, ctx: dict) -> AgentResult:
        job = ctx.get("job")
        if not job:
            return self.idle()
        if not any(b.get("visual") for b in job["beats"]):
            raise RuntimeError("no footage for any beat")
        track = None
        if self.ch["music"] and job.get("mood"):       # a track from the mood's folder, moving on one each time the mood comes up
            used = sum(v.get("mood") == job["mood"] and v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(LOG))
            track = bgm.pick(job["mood"], used)
        job["music"] = (bgm.line(track[1]) or track[0].name) if track else ""
        wide = job.get("format") == "long"
        turn = sum(v.get("mood") == job.get("mood") and v.get("channel") == self.ch["id"] for v in ctx["store"].kv_list(LOG))   # moves the look and the effects on, as the music
        look = fonts.style_for(job.get("mood") or "", kind(job), turn) if self.ch["caption_styles"] else None
        if look and wide:
            look["position"] = "lower"                  # a wide frame keeps its captions low
        job["caption"] = " · ".join(x for x in (look["font_name"], look["fill"], look["highlight"]) if x) if look else ""
        plan = sfx_plan(job["beats"], volume=float(self.ch["sfx_volume"]), turn=turn) if self.ch["sfx"] else None
        out = await asyncio.to_thread(shorts_edit.assemble, Path(job["dir"]), job["beats"], channel=self.ch["name"],
                                      logo=str(ROOT / self.ch["logo"]) if self.ch["logo"] else None, font_path=self.ch["caption_font"] or None,
                                      music=str(track[0]) if track else None, music_volume=float(self.ch["music_volume"]), wide=wide,
                                      motion=bool(self.ch["motion"]), style={k: v for k, v in look.items() if k != "font_name"} if look else None, sfx=plan)
        job["file"], job["seconds"], job["sfx"] = out["file"], out["seconds"], out.get("sfx", 0)
        if wide:
            job["thumb"] = await self._thumbnail(job)
        for part in ("build", "footage", "audio"):            # the downloads and working files are large; the log keeps their sources
            shutil.rmtree(Path(job["dir"]) / part, ignore_errors=True)
        save_record(ctx["store"], self.ch, job)
        what = f"{clock(out['seconds'])} long video, {out['shots']} shots" + (", thumbnail made" if job.get("thumb") else ", no thumbnail") if wide else f"{out['seconds']} s Short"
        font = f" in {look['font_name']}" if look else ""
        return AgentResult("done", "CUT", f"{what}, {out['captions']} captions{font}, {job['sfx']} sound effects" + (", with music" if track else ", no music"))

    async def _thumbnail(self, job: dict) -> str:
        """The cover for a long video: a photo for the story (else a frame of the video itself) with the writer's few words on it."""
        work = Path(job["dir"])
        src, out = work / "thumb_src.jpg", work / "thumb.jpg"
        try:
            hit = None
            if job.get("thumb_query") and stock_video.configured():
                async with self.client() as c:
                    hit = await stock_video.photo(c, job["thumb_query"])
                    if hit:
                        await stock_video.download(c, hit["url"], src)
            if not hit:
                await asyncio.to_thread(shorts_edit.run, ["ffmpeg", "-y", "-v", "error", "-ss", f"{job['seconds'] * 0.15:.1f}", "-i", job["file"], "-frames:v", "1", str(src)])
            await asyncio.to_thread(shorts_edit.thumbnail, out, src, job.get("thumb_text") or job["title"], self.ch["name"], self.ch["caption_font"] or None)
            src.unlink(missing_ok=True)
            return str(out)
        except Exception:
            return ""


class UploadLimit(Exception):
    pass


def channel_for(cfg, channel_id: str) -> dict | None:
    """A channel's settings by id, from the master's options (an approval handler has no channel in hand)."""
    for raw in (cfg.master("youtube").options.get("channels") or [{}]):
        if channel(raw)["id"] == channel_id:
            return channel(raw)
    return None


async def set_thumbnail(c: httpx.AsyncClient, auth: dict, rec: dict) -> str:
    """The record's thumb.jpg as the uploaded video's cover (thumbnails.set). A refusal (an unverified channel, a file over 2 MB) is a note, never an error."""
    r = await c.post("https://www.googleapis.com/upload/youtube/v3/thumbnails/set", params={"videoId": rec["video_id"], "uploadType": "media"},
                     content=Path(rec["thumb"]).read_bytes(), headers={**auth, "Content-Type": "image/jpeg"})
    return "thumbnail set" if r.status_code == 200 else f"thumbnail failed: {_reason(r)}"


async def publish_approved(ctx: dict, ch: dict, key: str, rec: dict, make=None) -> str:
    """Set an approved private video's release time on YouTube (videos.update) and mark it scheduled. No sign-in: it stays awaiting (and
    approved) and the channel's Uploader tries again on its next run."""
    acct, report = account(ch), rec.get("kind") in SHORT_KINDS
    when = short_when(rec, _now()) if report else None
    if report and when is None:                    # too late to be news: it stays private on YouTube, and is not published by approval
        ctx["store"].kv_put(LOG, key, {**{k: v for k, v in rec.items() if not k.startswith("_")}, "status": "stale", "stale": True})
        return f"stale: this {rec['kind']} update is for {rec['date']} and is too late to publish, so it stays private on YouTube (VISION does not delete videos)"
    try:
        token = await oauth.access_token(acct, "youtube")
    except oauth.AuthNeeded:
        port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
        ctx["bus"].notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
        return f"approved, but YouTube is not signed in for {ch['name']}: sign in and it is scheduled on the next run"
    ctx["bus"].clear_notice(f"auth:{acct}")
    when = when or next_slot(ctx["store"], ch, fmt="long" if rec.get("format") == "long" else "short")
    body = {"id": rec["video_id"], "status": {"privacyStatus": "private", "publishAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when)),
                                              "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(ch["synthetic_flag"])}}
    async with (make() if make else httpx.AsyncClient(timeout=httpx.Timeout(60.0))) as c:
        r = await c.put(VIDEOS, params={"part": "status"}, json=body, headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise RuntimeError(f"YouTube would not schedule it ({r.status_code}): {_reason(r)}")
    ctx["store"].kv_put(LOG, key, {**{k: v for k, v in rec.items() if not k.startswith("_")}, "status": "scheduled", "publish_at": when, "approved": True})
    ctx["bus"].clear_notice(f"youtube-review-{rec['video_id']}")
    tz = ZoneInfo(ch["timezone"]) if ch.get("timezone") else None
    return "Scheduled for " + datetime.fromtimestamp(when, tz).strftime("%a %d %b %H:%M") + (f" ({ch['timezone']})" if tz else "")


async def publish_decision(row: dict, decision: str, ctx: dict) -> str:
    """The YOU gate for a private upload (kind yt_publish): approved = scheduled for the next release slot; rejected = it stays private
    on YouTube (VISION never deletes a video)."""
    p, store = row["payload"], ctx["store"]
    rec, ch = store.kv_get(LOG, p["record"]), channel_for(ctx["cfg"], p["channel"])
    if not rec or not ch:
        return "the video is no longer in the log"
    if decision != "approved":
        store.kv_put(LOG, p["record"], {**rec, "status": "private", "rejected": True})
        return "rejected: it stays private on YouTube (VISION does not delete videos)"
    store.kv_put(LOG, p["record"], {**rec, "approved": True})     # an approval is decided once: remember it in case the sign-in is missing now
    return await publish_approved(ctx, ch, p["record"], {**rec, "approved": True}, ctx.get("client_factory"))


class Uploader(Crew):
    """Uploads finished Shorts as unlisted and hands Mani the link. Public or deleted is his move, on YouTube."""
    name, tier, note = "Uploader", "API", "uploads as unlisted, sends you the link"

    @staticmethod
    async def _file(path: Path):
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                yield chunk

    async def _upload(self, ctx: dict, c: httpx.AsyncClient, token: str, rec: dict) -> dict:
        ch = self.ch
        long = rec.get("format") == "long"
        tags = list(dict.fromkeys(rec["hashtags"] + ([] if long else ["#Shorts"])))
        report, lesson = rec.get("kind") in SHORT_KINDS, rec.get("kind") in LESSON_KINDS
        if rec.get("review"):                       # a review upload (Mani Market Tamil): private, never a release time (decided first: it may have no window)
            when = None
        elif report:                                # a report Short never takes a slot: `report_privacy` scheduled = public by itself at report_release, approval = private until approved
            when = short_when(rec, _now()) if ch["report_privacy"] == "scheduled" else None      # lessons too, since Mani approved the channel (2026-10-14)
        else:
            when = next_slot(ctx["store"], ch, fmt="long" if long else "short") if ch["privacy"] == "scheduled" else None     # private now, public by itself at its slot
        marks = rec.get("chapters") or []           # YouTube shows chapters from three or more timestamps starting at 0:00
        chapters = "\n\n" + "\n".join(f"{clock(m['t'])} {m['heading']}" for m in marks) if long and len(marks) >= 3 and marks[0]["t"] == 0 else ""
        seo = rec.get("seo") or {}                  # the strategist's search tags and opening lines, when it gave them
        about = (seo["lead"] + "\n\n" if seo.get("lead") else "") + (rec["summary"] + "\n\n" if long and rec.get("summary") else "") \
            + " ".join(tags) + (f"\n\n{ch['cta']}" if ch["cta"] else "") + _about(rec) + chapters \
            + ("\n\nFootage: " + "; ".join(rec["credits"]) if rec.get("credits") else "") + (f"\nMusic: {rec['music']}" if rec.get("music") else "")
        if rec.get("kind") in ("result", "analysis", *SHORT_KINDS, "lesson"):   # a results, analysis or report video's description is written whole (the source and the disclaimer last)
            about = rec["summary"]
        body = {"snippet": {"title": rec["title"][:100], "categoryId": str(ch["category"]), "tags": seo.get("tags") or [t.lstrip("#") for t in tags], "description": about},
                "status": {"privacyStatus": "private" if when or report or lesson or rec.get("review") or ch["privacy"] == "approval" else ch["privacy"], "selfDeclaredMadeForKids": False, "containsSyntheticMedia": bool(ch["synthetic_flag"]),
                           **({"publishAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(when))} if when else {})}}
        size = Path(rec["file"]).stat().st_size
        auth = {"Authorization": f"Bearer {token}"}
        r = await c.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                         headers={**auth, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        if r.status_code != 200 or "location" not in r.headers:
            if "uploadLimitExceeded" in r.text or "exceeded the number of videos" in r.text:
                raise UploadLimit()
            raise RuntimeError(f"YouTube refused the upload ({r.status_code}): {_reason(r)}")
        r = await c.put(r.headers["location"], content=self._file(Path(rec["file"])), headers={**auth, "Content-Type": "video/mp4", "Content-Length": str(size)})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"YouTube upload failed ({r.status_code}): {_reason(r)}")
        return {**r.json(), "publish_at": when}

    async def _extras(self, ctx: dict, c: httpx.AsyncClient, token: str, rec: dict) -> str:
        """After the upload: the Short joins its playlist and gets the channel's invitation as a comment. Neither can fail the upload."""
        ch, store = self.ch, ctx["store"]
        long = rec.get("format") == "long"
        name = long_of(ch)["playlist"] if long else (ch["playlists"] or {}).get(rec.get("kind") or "")
        thumb = rec.get("thumb") if long and Path(rec.get("thumb") or "-").exists() else ""
        if not (name or ch["cta"] or thumb) or not can_manage(ctx, ch):
            return ""
        auth, notes = {"Authorization": f"Bearer {token}"}, []
        try:
            if thumb:
                notes.append(await set_thumbnail(c, auth, rec))
            if name:
                slot = f"{ch['id']}:playlist:{name}"
                pid = (store.kv_get(STATE, slot) or {}).get("id")
                if not pid:
                    r = await c.get(API + "/playlists", params={"part": "snippet", "mine": "true", "maxResults": 50}, headers=auth)
                    pid = next((p["id"] for p in r.json().get("items", []) if p["snippet"]["title"] == name), None) if r.status_code == 200 else None
                if not pid:
                    r = await c.post(API + "/playlists", params={"part": "snippet,status"}, headers=auth,
                                     json={"snippet": {"title": name}, "status": {"privacyStatus": "public"}})
                    pid = r.json().get("id") if r.status_code == 200 else None
                if pid:
                    store.kv_put(STATE, slot, {"id": pid})
                    for attempt in range(3):          # YouTube now and then answers "the operation was aborted" on a fresh upload: ask again
                        r = await c.post(API + "/playlistItems", params={"part": "snippet"}, headers=auth,
                                         json={"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": rec["video_id"]}}})
                        if r.status_code == 200:
                            break
                        await asyncio.sleep(4)
                notes.append(f"in “{name}”" if pid and r.status_code == 200 else f"playlist failed: {_reason(r)}")
            if ch["cta"] and rec.get("status") in ("public", "unlisted"):     # a private (scheduled) video takes no comments: the Analytics
                if await post_invitation(c, auth, ch, rec["video_id"]):        # Manager posts the invitation once it has gone public
                    rec["cta_done"] = True
                else:
                    notes.append("comment failed")
        except httpx.HTTPError as e:
            notes.append(f"extras failed: {e}")
        return f" ({', '.join(notes)})" if notes else ""

    async def run(self, ctx: dict) -> AgentResult:
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        ready = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"] and v.get("status") == "ready" and Path(v.get("file") or "").exists()]
        if not ready:
            return AgentResult("idle", "IDLE", "Nothing to upload")
        acct = account(ch)
        try:
            token = await oauth.access_token(acct, "youtube")
        except oauth.AuthNeeded:
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"auth:{acct}", f"Sign in to YouTube for {ch['name']}", f"http://127.0.0.1:{port}/auth/youtube/login?account={acct}")
            return AgentResult("wait", "SIGN IN", f"{len(ready)} Short{'s' if len(ready) != 1 else ''} waiting: sign in to YouTube for {ch['name']}")
        bus.clear_notice(f"auth:{acct}")
        if ch["privacy"] == "scheduled":           # know every release already set, Mani's own included, before choosing the next time
            await AnalyticsManager(ch, **self.opts)._refresh(ctx, [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"]])
        done = []
        async with self.client() as c:
            for rec in sorted(ready, key=lambda v: v["made"])[:ch["uploads_per_run"]]:
                try:
                    out = await self._upload(ctx, c, token, rec)
                except UploadLimit:                # YouTube's own cap on uploads per channel per day: not a fault, the Shorts wait
                    left = len(ready) - len(done)
                    bus.notice(f"youtube-limit-{ch['id']}", f"{ch['name']}: YouTube itself is refusing uploads for now (its own cap per channel per day, not VISION's count). "
                                                            f"{left} finished Short{'s' if left != 1 else ''} kept; they upload by themselves on a later run. Nothing to do.")
                    return AgentResult("wait", "UPLOAD LIMIT", (f"Uploaded as {ch['privacy']}: " + "; ".join(done) + ". " if done else "")
                                       + f"YouTube's daily upload limit reached; {left} waiting")
                bus.clear_notice(f"youtube-limit-{ch['id']}")
                key = rec.pop("_key")
                rec.pop("_ts", None)
                rec.update(status=ch["privacy"], video_id=out["id"], url=f"https://youtu.be/{out['id']}", uploaded=time.time(), publish_at=out["publish_at"])
                store.kv_put(LOG, key, rec)
                extras = await self._extras(ctx, c, token, rec)
                store.kv_put(LOG, key, rec)
                when = time.strftime(" for %a %H:%M", time.localtime(out["publish_at"])) if out["publish_at"] else ""
                if when:                                   # no review step: it goes public by itself
                    bus.say(f"{ch['name']} · “{rec['title']}” goes public{when.replace(' for', '')}")
                else:
                    review_notice(bus, ch, rec)
                done.append(rec["title"] + when + extras)
        return AgentResult("done", "UPLOADED", f"Uploaded as {ch['privacy']}: " + "; ".join(f"“{t}”" if " for " not in t else t for t in done))


async def post_invitation(c: httpx.AsyncClient, auth: dict, ch: dict, video_id: str) -> bool:
    """The channel's own comment under a video, inviting viewers' stories. Only a public or unlisted video can take it."""
    try:
        r = await c.post(API + "/commentThreads", params={"part": "snippet"}, headers=auth,
                         json={"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": ch["cta"]}}}})
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def _about(rec: dict) -> str:
    """One line on where the story comes from, for the description."""
    c = rec.get("classic")
    if c:
        return f"\n\nRetold from “{c['title']}” by {c['author']}, in “{c['book']}” (public domain): {c['url']}"
    return {"original": "\n\nThis story is fiction.", "motivational": "\n\nThis story is fiction.",
            "money": "\n\nFor education only. This is not financial advice.",
            "viewer": "\n\nRetold from a viewer's comment."}.get(rec.get("kind"), "")


def review_notice(bus, ch: dict, rec: dict) -> None:
    bus.notice(f"youtube-review-{rec['video_id']}", f"New {rec['status']} Short on {ch['name']}: “{rec['title']}”. Review it, then make it public or delete it.",
               f"https://studio.youtube.com/video/{rec['video_id']}/edit")


def _reason(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"][:200]
    except Exception:
        return r.text[:200]


class AnalyticsManager(Crew):
    """Follows every uploaded Short (public yet? deleted? views, likes, comments), keeps the log current and reports the
    channel to its Director. The master report it feeds goes into the 06:00 and 18:00 briefs."""
    name, tier, note = "Analytics Manager", "API", "follows each Short, reports the channel"

    async def _refresh(self, ctx: dict, log: list[dict]) -> None:
        live = [v for v in log if v.get("video_id") and v.get("status") in ("unlisted", "private", "public", "scheduled", "review")]
        if not live:
            return
        try:
            token = await oauth.access_token(account(self.ch), "youtube")
        except oauth.AuthNeeded:
            return                                 # the Uploader has already asked for the sign-in
        found: dict[str, dict] = {}
        async with self.client() as c:
            for i in range(0, len(live), 50):      # videos.list takes 50 ids a call (1 quota unit each); every video is followed, not just the first 50
                r = await c.get(VIDEOS, params={"part": "status,statistics", "id": ",".join(v["video_id"] for v in live[i:i + 50])},
                                headers={"Authorization": f"Bearer {token}"})
                if r.status_code != 200:
                    raise RuntimeError(f"YouTube stats failed ({r.status_code}): {_reason(r)}")
                found.update({it["id"]: it for it in r.json().get("items", [])})
        invite = bool(self.ch["cta"]) and "youtube.force-ssl" in oauth.granted(account(self.ch))
        for v in live:
            item = found.get(v["video_id"])
            was = v["status"]
            if was == "review":                    # uploaded for Mani to watch: only his deleting it on YouTube changes its status
                v["status"] = "review" if item else "deleted"
                if item:
                    v["stats"] = {k: int(item.get("statistics", {}).get(f"{k}Count", 0)) for k in ("view", "like", "comment")}
                    v["checked"] = time.time()
                ctx["store"].kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})
                continue
            v["status"] = item["status"]["privacyStatus"] if item else "deleted"
            due = (item or {}).get("status", {}).get("publishAt")
            if due:                                # private with a publishing time = scheduled, whether VISION or Mani set it
                v["publish_at"] = calendar.timegm(time.strptime(due[:19], "%Y-%m-%dT%H:%M:%S"))
            if v["status"] == "private" and (due or (v.get("publish_at") or 0) > time.time() - 3600):
                v["status"] = "scheduled"
            if item:
                v["stats"] = {k: int(item.get("statistics", {}).get(f"{k}Count", 0)) for k in ("view", "like", "comment")}
                v["checked"] = v["on_youtube"] = time.time()      # seen by videos.list: only this lets free_space delete the local copy
            if invite and v["status"] == "public" and not v.get("cta_done"):     # it has gone public: now it can take the channel's invitation
                async with self.client() as c2:
                    v["cta_done"] = await post_invitation(c2, {"Authorization": f"Bearer {token}"}, self.ch, v["video_id"])
            if v["status"] in ("public", "deleted", "scheduled") and was != v["status"]:
                ctx["bus"].clear_notice(f"youtube-review-{v['video_id']}")
            ctx["store"].kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})

    async def _analytics(self, ctx: dict, log: list[dict]) -> str:
        """YouTube Analytics for every public Short at least two days out (watch share, duration, subscribers), at most every
        6 hours; kept on each record as `analytics`. Without the permission: a "sign in again" notice, nothing else stops."""
        ch, store, bus = self.ch, ctx["store"], ctx["bus"]
        mark = f"{ch['id']}:analytics_at"
        if time.time() - (store.kv_get(STATE, mark) or {}).get("at", 0) < 6 * 3600:
            return ""
        due = [v for v in log if v.get("video_id") and v.get("status") == "public" and v.get("format") != "long"
               and (v.get("publish_at") or v.get("uploaded") or time.time()) <= time.time() - 2 * 86400]
        if not due:
            return ""
        if yt_analytics.SCOPE not in oauth.granted(account(ch)):
            port = ctx["cfg"].vision.port if ctx.get("cfg") else 8765
            bus.notice(f"youtube-analytics-{ch['id']}", f"Sign in to YouTube again for {ch['name']}: reading YouTube Analytics (watch share, "
                                                        "subscribers) needs one more read-only permission", f"http://127.0.0.1:{port}/auth/youtube/login?account={account(ch)}")
            return "analytics wait for a sign-in"
        bus.clear_notice(f"youtube-analytics-{ch['id']}")
        try:
            token = await oauth.access_token(account(ch), "youtube")
            async with self.client() as c:
                got = await yt_analytics.per_video(c, token, [v["video_id"] for v in due])
        except oauth.AuthNeeded:
            return ""
        except (yt_analytics.AnalyticsError, httpx.HTTPError) as e:
            return f"analytics not read: {e}"[:160]
        for v in due:
            if v["video_id"] in got:
                v["analytics"] = {**got[v["video_id"]], "at": time.time()}
                store.kv_put(LOG, v["_key"], {k: x for k, x in v.items() if not k.startswith("_")})
        store.kv_put(STATE, mark, {"at": time.time(), "videos": len(got)})
        return ""

    def _rebalance(self, ctx: dict, scores: dict[str, dict]) -> str:
        """Once a week the day's slots are re-split by score (resplit: same total, at least one each). A change is logged and
        sent to Telegram with its reason; the re-split is kept in kv `yt_state` `<channel>:mix`."""
        ch, store = self.ch, ctx["store"]
        if not ch.get("daily_mix") or not ch.get("mix_auto"):
            return ""
        kept = store.kv_get(STATE, f"{ch['id']}:mix") or {}
        if time.time() - kept.get("at", 0) < 7 * 86400:
            return ""
        now_mix = mix_of(store, ch)
        new = resplit(now_mix, scores, int(ch["mix_min_videos"]))
        store.kv_put(STATE, f"{ch['id']}:mix", {"mix": new, "at": time.time(), "was": now_mix, "scores": scores})
        if new == now_mix:
            return ""
        why = " · ".join(f"{'finance' if c == 'money' else c} {s['pct']}% watched, {s['views']} views/Short, {s['subs']} subs ({s['n']})" for c, s in scores.items())
        text = f"🎬 {ch['name']}: the daily mix is now {mix_text(new)} (was {mix_text(now_mix)}). YouTube Analytics, last {ch['mix_days']} days: {why}"
        ctx["bus"].say(text)
        ctx["bus"].publish({"type": "reminder", "text": text})              # reminders go to Telegram as they are
        return f"mix now {mix_text(new)}"

    async def run(self, ctx: dict) -> AgentResult:
        ch = self.ch
        log = [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]]
        if not log:
            free_space(ctx["store"], ch, [])
            return AgentResult("done", "LOGGED", f"{ch['name']}: no Shorts made yet", {"channel": ch["id"], "made": 0})
        await self._refresh(ctx, log)
        read = await self._analytics(ctx, [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]])
        saved = await backup(ctx, ch, [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]], self.client)
        pruned = await prune_drive(ctx, ch, [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]], self.client)
        log = [v for v in ctx["store"].kv_list(LOG) if v.get("channel") == ch["id"]]
        freed = "; ".join(x for x in (saved, pruned, free_space(ctx["store"], ch, log)) if x)
        for v in log:                              # notices live in memory: put the reminder back after a restart
            if v["status"] == "unlisted" and v.get("video_id"):
                review_notice(ctx["bus"], ch, v)
        n = {s: sum(v["status"] == s for v in log) for s in ("ready", "unlisted", "scheduled", "private", "public", "deleted")}
        views = sum((v.get("stats") or {}).get("view", 0) for v in log if v["status"] == "public")
        parts = [f"{len(log)} made"]
        if n["ready"]:
            parts.append(f"{n['ready']} waiting for upload")
        if n["unlisted"]:
            parts.append(f"{n['unlisted']} unlisted for your review")
        if n["scheduled"]:
            parts.append(f"{n['scheduled']} scheduled")
        if n["private"]:
            parts.append(f"{n['private']} held private by YouTube")
        if n["public"]:
            parts.append(f"{n['public']} public with {views:,} views")
        if n["deleted"]:
            parts.append(f"{n['deleted']} deleted")
        if freed:
            parts.append(freed)
        seen = [v for v in log if v["status"] == "public" and (v.get("stats") or {}).get("view", 0) > 0]      # what the channel's own results teach
        by_kind: dict[str, list[int]] = {}
        for v in seen:
            by_kind.setdefault(v.get("kind") or "real", []).append(v["stats"]["view"])
        by_shape: dict[str, list[int]] = {}
        for v in seen:
            if v.get("structure"):
                by_shape.setdefault(v["structure"], []).append(v["stats"]["view"])
        by_hook: dict[str, list[int]] = {}
        for v in seen:
            if v.get("hook"):
                by_hook.setdefault(v["hook"], []).append(v["stats"]["view"])
        by_len: dict[str, list[int]] = {}
        for v in seen:
            if v.get("format") != "long":
                by_len.setdefault("quick" if v.get("quick") else "regular", []).append(v["stats"]["view"])
        insights = {"top_titles": [v["title"] for v in sorted(seen, key=lambda v: v["stats"]["view"], reverse=True)[:5]],
                    "views_by_kind": {k: round(sum(x) / len(x)) for k, x in by_kind.items()}, "videos": len(seen)}
        if by_shape:
            insights["views_by_structure"] = {k: round(sum(x) / len(x)) for k, x in by_shape.items()}
        if by_hook:
            insights["views_by_hook"] = {k: round(sum(x) / len(x)) for k, x in by_hook.items()}
        if by_len:
            insights["views_by_length"] = {k: round(sum(x) / len(x)) for k, x in by_len.items()}
        scores = category_scores(log, int(ch["mix_days"]))
        if scores:
            insights["by_category"] = scores
        ctx["store"].kv_put(STATE, f"{ch['id']}:insights", insights)
        moved = self._rebalance(ctx, scores) if scores else ""
        mix = mix_of(ctx["store"], ch)
        if scores:
            parts.append("watched: " + " · ".join(f"{'finance' if c == 'money' else c} {s['pct']}% of {s['views']} views/Short" for c, s in
                                                 sorted(scores.items(), key=lambda x: -x[1]["score"])))
        if mix:
            parts.append(f"daily mix {mix_text(mix)}")
        parts += [x for x in (read, moved) if x]
        latest = max(log, key=lambda v: v.get("made") or 0)            # by when it was made (the store's order follows each save)
        return AgentResult("done", "LOGGED", f"{ch['name']}: {', '.join(parts)}; latest “{latest['title']}” ({round(latest['seconds'])} s)",
                           {"channel": ch["id"], "made": len(log), **n, "views": views,
                            "videos": [{k: v.get(k) for k in ("title", "status", "url", "seconds", "stats", "source")} for v in log[:20]]})


def crew(ch: dict, **opts: Any) -> list[Stage]:
    return [Stage("SOURCE", [StoryScout(ch, **opts)]), Stage("STORY", [StoryWriter(ch)]), Stage("SCREENPLAY", [ScreenplayWriter(ch)]),
            Stage("PREP", [KeywordGenerator(ch), VoiceArtist(ch, **opts), SEOStrategist(ch, **opts)]), Stage("FOOTAGE", [FootageCollector(ch, **opts)]),
            Stage("GENERATE", [FootageGenerator(ch, **opts)]), Stage("EDIT", [Editor(ch, **opts)]), Stage("UPLOAD", [Uploader(ch, **opts)]),
            Stage("REPORT", [AnalyticsManager(ch, **opts)])]


def reset_today(store, channel_id: str) -> None:
    """Start today's count for a channel again: Shorts made before this moment no longer count toward shorts_per_day."""
    store.kv_put(STATE, f"{channel_id}:quota_reset", {"at": time.time()})


def more_today(ch: dict):
    """One pass of the crew makes one Short. Go round again while the last pass made one and the day's number isn't reached."""
    L = long_of(ch)
    def shorts_left(store) -> bool:
        mix = mix_of(store, ch)
        return next_category(mix, made_by_category(store, ch)) is not None if mix else made_today(store, ch, "short") < ch["shorts_per_day"]
    return lambda ctx: bool((ctx.get("job") or {}).get("file")) and (
        shorts_left(ctx["store"]) or (bool(L["enabled"]) and made_today(ctx["store"], ch, "long") < L["per_day"]))


def peer_line(store, ch: dict) -> str:
    """One line on another channel for the master's report: what is waiting on Mani, what is scheduled, what is public."""
    log = [v for v in store.kv_list(LOG) if v.get("channel") == ch["id"]]
    n = {st: sum(v.get("status") == st for v in log) for st in ("ready", "awaiting", "scheduled", "public")}
    views = sum((v.get("stats") or {}).get("view", 0) for v in log if v.get("status") == "public")
    parts = [f"{n['ready']} waiting for upload"] * bool(n["ready"]) + [f"{n['awaiting']} awaiting your approval"] * bool(n["awaiting"]) + [f"{n['scheduled']} scheduled"] * bool(n["scheduled"]) \
        + [f"{n['public']} public with {views:,} views"] * bool(n["public"])
    return f"{ch['name']}: " + (", ".join(parts) or "nothing made yet")


class Lead(Director):
    """The first channel's Director when the master has more than one channel. Only one agent is the master's reporter, so this one
    adds a line for each other channel to its own report (from the log, as the other Directors left it)."""

    def __init__(self, *a: Any, peers: list[dict], **kw: Any) -> None:
        super().__init__(*a, **kw)
        self.peers = peers

    async def run(self, ctx: dict[str, Any]) -> AgentResult:
        res = await super().run(ctx)
        more = [peer_line(ctx["store"], p) for p in self.peers]
        return AgentResult(res.status, res.label, " | ".join([res.summary, *more]), {**res.data, "channels": more})


class OwnWriter:
    """The LLM as a channel with its own Groq model sees it: a "writer" request without a model goes to `model` (each Groq model has its own
    daily allowance, so the new channels do not use up Know IDK Things' writer), counted against the channel's own share `cap` (tokens a UTC
    day, services/groq_budget.py). With `light` ("local"), a small structured step (footage searches, sound cues, diagram picks:
    calls marked light=True) goes to the local model first and to Groq only if that fails (Mani, 2026-10-19: the hybrid). With `first`
    ("openrouter"), every other writer request (premises, scripts) goes to the free OpenRouter model (Nemotron) first and to Groq if that is
    busy, out of its free requests or down."""

    def __init__(self, llm, model: str, who: str = "", cap: int = 0, light: str = "", first: str = "") -> None:
        self._llm, self._model, self._who, self._cap, self._light, self._first = llm, model, who, cap, light, first

    def __getattr__(self, name):
        return getattr(self._llm, name)

    def _kw(self, kw: dict) -> dict:
        if kw.get("tier") == "writer":
            kw.setdefault("model", self._model)
            if kw["model"] is None:
                kw["model"] = self._model
            kw.update(who=self._who, cap=self._cap)
        return kw

    async def json(self, prompt: str, **kw):
        if kw.pop("light", False) and self._light == "local" and kw.get("tier") == "writer":
            try:
                if await self._llm.local_available():
                    got = await self._llm.json(prompt, **{**kw, "tier": "local", "model": None})
                    if got not in (None, [], {}):
                        return got
            except Exception:  # noqa: BLE001 - the local model is a convenience: Groq answers instead
                pass
        if self._first == "openrouter" and kw.get("tier") == "writer" and not kw.get("model"):     # scripts and premises: the better free writer first
            try:
                got = await self._llm.json(prompt, **{**kw, "tier": "openrouter", "who": self._who})
                if got not in (None, [], {}):
                    return got
            except Exception:  # noqa: BLE001 - busy, out of free requests or down: Groq writes it
                pass
        return await self._llm.json(prompt, **self._kw(kw))

    async def complete(self, prompt: str, **kw):
        kw.pop("light", None)
        if self._first == "openrouter" and kw.get("tier") == "writer" and not kw.get("model"):
            try:
                got = await self._llm.complete(prompt, **{**kw, "tier": "openrouter", "who": self._who})
                if got:
                    return got
            except Exception:  # noqa: BLE001
                pass
        return await self._llm.complete(prompt, **self._kw(kw))


class ChannelDirector(Director):
    """A Director whose crew writes with the channel's own Groq model (`writer_model`)."""

    def __init__(self, name: str, writer_model: str = "", who: str = "", cap: int = 0, light: str = "", first: str = "", **kw) -> None:
        super().__init__(name, **kw)
        self.writer_model, self.who, self.cap, self.light, self.first = writer_model, who, cap, light, first

    async def run(self, ctx: dict) -> AgentResult:
        if self.writer_model and ctx.get("llm"):
            ctx = {**ctx, "llm": OwnWriter(ctx["llm"], self.writer_model, self.who, self.cap, self.light, self.first)}
        return await super().run(ctx)


def build_agents(options: dict, cfg) -> dict[str, SubAgent]:
    out: dict[str, SubAgent] = {}
    chs = [channel(raw) for raw in options.get("channels") or [{}]]
    for n, ch in enumerate(chs):
        if ch.get("crew") == "market":                 # a results-video channel with its own crew (masters/market_crew.py)
            from . import market_crew
            d = dict(crew=market_crew.crew(ch), reporter="Market Analytics")
        else:
            d = dict(crew=crew(ch), reporter="Analytics Manager", again=more_today(ch))
        out[ch["director"]] = (Lead(ch["director"], peers=chs[1:], note=f"runs {ch['name']}", **d) if n == 0 and len(chs) > 1
                               else ChannelDirector(ch["director"], writer_model=ch.get("writer_model") or "", who=ch["id"], cap=int(ch.get("groq_daily_cap") or 0),
                                                    light=ch.get("light_tier") or "", first=ch.get("script_writer") or "", note=f"runs {ch['name']}", **d) if ch.get("writer_model")
                               else Director(ch["director"], note=f"runs {ch['name']}", **d))
    return out


APPROVAL_HANDLERS = {"yt_publish": publish_decision}
