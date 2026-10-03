"""Stylesheet for sitekit pages, in chunks: BASE is always sent, the rest only when a page uses that variant.

Colours come from role variables (see color.py); a section's tone class (t-bg, t-alt, t-band, t-ink) maps them to
--sbg/--fg/--mut/--hl/--cta so every component is written once and stays readable on any panel.
A recipe's look is carried by the skin variables on :root plus a few body classes (eyebrow, image, pattern, divider).
"""

from __future__ import annotations

import re

BASE = """
*,*::before,*::after{box-sizing:border-box}
*{margin:0}
html{scroll-behavior:smooth;scroll-padding-top:5rem;-webkit-text-size-adjust:100%}
body{background:var(--bg);color:var(--text);font:400 var(--fs)/1.65 var(--body);-webkit-font-smoothing:antialiased;overflow-wrap:break-word;counter-reset:sec}
img{max-width:100%;display:block}
a{color:inherit}
ul,ol.steps{list-style:none;padding:0}
:focus-visible{outline:3px solid var(--fg);outline-offset:3px}
.skip{position:absolute;left:-999rem;top:.75rem;z-index:99;padding:.6rem 1rem;background:var(--surface);color:var(--text);border-radius:var(--rb)}
.skip:focus{left:.75rem}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
h1,h2,h3{font-family:var(--display);font-weight:var(--hw);line-height:var(--hlh);letter-spacing:var(--hls);text-transform:var(--hcase);text-wrap:balance;overflow-wrap:anywhere}
h3{line-height:1.2}
p{text-wrap:pretty}
.wrap{width:min(var(--wrap),100% - 2.5rem);margin-inline:auto}

body,.t-bg,.t-alt{--sbg:var(--bg);--fg:var(--text);--mut:var(--muted);--hl:var(--p);--card:var(--surface);--ln:var(--line);--cta:var(--a);--on-cta:var(--on-a)}
.t-alt{--sbg:var(--alt)}
.t-band{--sbg:var(--band);--fg:var(--on-band);--mut:var(--band-muted);--hl:var(--ia);--card:transparent;--ln:color-mix(in srgb,var(--on-band) 26%,transparent);--cta:var(--ia);--on-cta:var(--on-ia)}
.t-ink{--sbg:var(--ink);--fg:var(--on-ink);--mut:var(--ink-muted);--hl:var(--ia);--card:transparent;--ln:color-mix(in srgb,var(--on-ink) 24%,transparent);--cta:var(--ia);--on-cta:var(--on-ia)}
.sec{position:relative;padding-block:var(--sp);background:var(--sbg);color:var(--fg)}
.div-line main>.sec+.sec{border-top:1px solid var(--ln)}
.div-double main>.sec+.sec{border-top:4px double var(--ln)}
.div-thick main>.sec+.sec{border-top:var(--bw1) solid var(--fg)}

.eyebrow{font:600 .78rem/1.3 var(--body);letter-spacing:.16em;text-transform:uppercase;color:var(--hl)}
.eb-rule .eyebrow{display:flex;align-items:center;gap:.8rem}
.eb-rule .eyebrow::before{content:"";flex:none;width:2.25rem;border-top:2px solid currentColor}
.eb-num .sec:not(.hero) .eyebrow::before{counter-increment:sec;content:counter(sec,decimal-leading-zero) "  /  "}
.eb-plain .eyebrow{font:italic 400 1.2rem/1.3 var(--display);letter-spacing:0;text-transform:none}
.eb-wide .eyebrow{font-weight:500;font-size:.72rem;letter-spacing:.32em}
.head{max-width:44rem;margin-bottom:clamp(2rem,5vw,3.25rem)}
.head h2{font-size:var(--h2);margin-top:.7rem}
.head p:not(.eyebrow){margin-top:1rem;color:var(--mut);font-size:1.08em}
.ha-center .head{margin-inline:auto;text-align:center}
.ha-center .eb-c,.ha-center .head .eyebrow{justify-content:center}

.btn{display:inline-flex;align-items:center;justify-content:center;gap:.55rem;min-height:3rem;padding:.7rem 1.4rem;border-radius:var(--rb);border:var(--bbw) solid transparent;font:var(--bwt) var(--bfs)/1.2 var(--body);letter-spacing:var(--bls);text-transform:var(--bcase);text-decoration:none;text-align:center;transition:transform .2s,box-shadow .2s,background-color .2s}
.btn svg{width:1.05em;height:1.05em;flex:none}
.btn-main{background:var(--cta);color:var(--on-cta);border-color:var(--cta);box-shadow:var(--bsh)}
.btn-main:hover{transform:translateY(-2px)}
.btn-line{border-color:currentColor;color:var(--fg)}
.btn-line:hover{background:color-mix(in srgb,currentColor 10%,transparent)}
.hard .btn-main{box-shadow:4px 4px 0 var(--fg)}
.hard .btn-main:hover{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--fg)}
.tlink{color:var(--fg);text-decoration-color:var(--hl);text-decoration-thickness:2px;text-underline-offset:.22em}

.ph{position:relative;overflow:hidden;margin:0;border-radius:var(--ri);background:var(--alt)}
.ph img{width:100%;height:100%;object-fit:cover;border-radius:inherit}
.img-frame .fr{padding:.45rem;background:var(--surface);border:1px solid var(--line)}
.img-frame .fr img{border-radius:max(0px,calc(var(--ri) - .3rem))}
.img-arch .fr.port{border-radius:999px 999px var(--ri) var(--ri)}
.img-blob .fr.port{border-radius:61% 39% 45% 55%/52% 45% 55% 48%}
.img-blob .fr.land{border-radius:calc(var(--ri)*2.2) var(--ri) calc(var(--ri)*2.2) var(--ri)}
.img-offset .fr{overflow:visible;box-shadow:.85rem .85rem 0 var(--hl)}
.img-soft .fr{box-shadow:0 34px 60px -38px rgb(0 0 0/.5)}
.img-mono .ph img{filter:grayscale(1) contrast(1.08)}
.img-duo .ph img{filter:grayscale(1) contrast(1.05)}
.img-duo .ph:not(.bgph)::after{content:"";position:absolute;inset:0;border-radius:inherit;background:var(--band);mix-blend-mode:color;opacity:.75;pointer-events:none}

.bgp-dots{background-image:radial-gradient(color-mix(in srgb,var(--text) 11%,transparent) 1px,transparent 1.6px);background-size:22px 22px}
.bgp-grid{background-image:linear-gradient(color-mix(in srgb,var(--text) 6%,transparent) 1px,transparent 1px),linear-gradient(90deg,color-mix(in srgb,var(--text) 6%,transparent) 1px,transparent 1px);background-size:72px 72px}
.bgp-grad{background-image:radial-gradient(70rem 42rem at 105% -5%,color-mix(in srgb,var(--a) 13%,transparent),transparent 62%),radial-gradient(56rem 40rem at -10% 38%,color-mix(in srgb,var(--p) 8%,transparent),transparent 62%);background-repeat:no-repeat}
.bgp-lines{background-image:repeating-linear-gradient(0deg,color-mix(in srgb,var(--text) 4%,transparent) 0 1px,transparent 1px 7px)}
.bgp-dots .sec.t-bg,.bgp-grid .sec.t-bg,.bgp-grad .sec.t-bg,.bgp-lines .sec.t-bg{background:none}

.hero{overflow:hidden;padding-block:0}
.hero h1{font-size:var(--h1)}
.hero .eyebrow{margin-bottom:1.1rem}
.hero-txt{position:relative;min-width:0}
.lede{font-size:clamp(1.08rem,1.5vw,1.25rem);line-height:1.55;color:var(--mut);max-width:40ch;margin-top:1.25rem}
.ctas{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:1.9rem}
.rating{display:flex;flex-wrap:wrap;align-items:center;gap:.3rem .7rem;margin-top:1.6rem;font-size:.95rem;color:var(--mut)}
.stars{color:var(--hl);letter-spacing:.12em;white-space:nowrap}
.deco{position:absolute;right:-7rem;top:50%;translate:0 -50%;width:min(34rem,58vw);aspect-ratio:1;border-radius:50%;border:1px solid var(--ln);box-shadow:0 0 0 3.5rem color-mix(in srgb,var(--hl) 5%,transparent),0 0 0 8rem color-mix(in srgb,var(--hl) 3%,transparent);pointer-events:none}

.card{background:var(--card);border:var(--bw1) solid var(--ln);border-radius:var(--r);box-shadow:var(--shadow)}
.t-band .card,.t-ink .card{box-shadow:none}
.hard .t-bg .card,.hard .t-alt .card{box-shadow:5px 5px 0 var(--fg);border-color:var(--fg)}

.hours{width:100%;border-collapse:collapse}
.hours th,.hours td{padding:.62rem 0;border-bottom:1px solid var(--ln);text-align:left;font-weight:400}
.hours td{text-align:right;color:var(--mut)}
.hours tr.today th,.hours tr.today td{font-weight:700;color:var(--fg)}
.hours tr.today th::after{content:" \\2022  today";color:var(--hl);font-size:.82em}
.where{display:flex;gap:.8rem;align-items:flex-start}
.where svg{width:1.2rem;height:1.2rem;flex:none;margin-top:.28rem;color:var(--hl)}
.map{border-radius:var(--ri);overflow:hidden;border:var(--bw1) solid var(--ln);background:var(--alt)}
.map iframe{display:block;width:100%;height:100%;border:0}

.foot{padding:2.25rem 0 calc(2.25rem + env(safe-area-inset-bottom,0px));border-top:1px solid var(--line);font-size:.82rem;color:var(--muted)}
.foot .fname{font:var(--hw) 1.05rem/1.2 var(--display);letter-spacing:var(--hls);text-transform:var(--hcase);color:var(--text);margin-bottom:.6rem}
.foot p+p{margin-top:.45rem}
.callbar{display:none}
@media (max-width:600px){
.has-callbar .foot{padding-bottom:6.25rem}
.callbar{display:flex;position:fixed;inset:auto 0 0 0;z-index:30;padding:.6rem .75rem calc(.6rem + env(safe-area-inset-bottom,0px));background:color-mix(in srgb,var(--bg) 94%,transparent);backdrop-filter:blur(10px);border-top:1px solid var(--line)}
.callbar .btn{flex:1}
.ctas .btn{flex:1 1 100%}
.deco{display:none}
}
.js .rise{opacity:0;transform:translateY(16px);transition:opacity .7s ease,transform .7s ease}
.js .rise.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.js .rise{opacity:1;transform:none;transition:none}.btn{transition:none}.btn-main:hover{transform:none}}
@media print{.js .rise{opacity:1;transform:none}.callbar,.fab{display:none}}
"""

CHUNKS = {
    # ---------- navigation
    "nav": """
.top{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 90%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top,0px)}
.bar{display:flex;align-items:center;justify-content:space-between;gap:1.25rem;min-height:4.25rem}
.brand{flex:0 1 auto;min-width:0;font:var(--hw) 1.22rem/1.15 var(--display);letter-spacing:var(--hls);text-transform:var(--hcase);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.links{display:flex;align-items:center;gap:1.6rem;flex:none}
.links a.link{font-size:.94rem;text-decoration:none;color:var(--muted);white-space:nowrap}
.links a.link:hover{color:var(--text)}
.top .btn{min-height:2.6rem;padding:.45rem 1.05rem;font-size:.9rem;white-space:nowrap;box-shadow:none}
@media (max-width:920px){.links a.link{display:none}}
@media (max-width:600px){.nav-call{display:none}}
""",
    "nav.center": """
.nav-center .bar{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);min-height:5rem}
.nav-center .brand{text-align:center;font-size:1.4rem;max-width:min(24rem,46vw)}
.nav-center .r{justify-content:flex-end}
@media (max-width:920px){.nav-center .bar{grid-template-columns:minmax(0,1fr) auto;min-height:4.25rem}.nav-center .l{display:none}.nav-center .brand{text-align:left;max-width:none;font-size:1.22rem}}
""",
    "nav.minimal": """
.nav-min{position:static;background:none;backdrop-filter:none;border-bottom:0}
.nav-min .bar{min-height:5rem}
.nav-min .links{gap:1.4rem}
.nav-min .tel{font-weight:600;font-size:.98rem;white-space:nowrap}
.fab{position:fixed;right:max(1rem,env(safe-area-inset-right,0px));bottom:calc(1rem + env(safe-area-inset-bottom,0px));z-index:30;min-height:3.4rem;padding-inline:1.35rem;box-shadow:0 14px 30px -12px rgb(0 0 0/.55)}
.has-fab .foot{padding-bottom:6rem}
@media (max-width:600px){.nav-min .tel{display:none}.fab{left:1rem;right:1rem}}
""",
    # ---------- heroes
    "hero.split": """
.h-split .hero-in{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);gap:clamp(2rem,5vw,4.5rem);align-items:center;padding-block:clamp(3rem,7vw,6rem)}
.h-split .ph{aspect-ratio:4/5;width:min(26rem,100%);justify-self:end}
.h-split.noimg .hero-in{grid-template-columns:minmax(0,46rem);padding-block:clamp(3.5rem,9vw,7.5rem)}
@media (max-width:860px){.h-split .hero-in{grid-template-columns:minmax(0,1fr)}.h-split .ph{aspect-ratio:4/3;width:100%}.img-arch .h-split .ph,.img-blob .h-split .ph{aspect-ratio:1;width:min(22rem,100%);justify-self:center}}
""",
    "hero.full": """
.h-full{display:flex;align-items:flex-end;min-height:min(86vh,46rem)}
.h-full .bgph{position:absolute;inset:0;border-radius:0}
.h-full .bgph::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,color-mix(in srgb,var(--ink) 38%,transparent),color-mix(in srgb,var(--ink) 66%,transparent) 42%,color-mix(in srgb,var(--ink) 95%,transparent))}
.h-full .hero-in{position:relative;padding-block:clamp(6rem,15vh,9rem) clamp(2.75rem,6vw,4.5rem)}
.h-full .hero-txt{max-width:46rem}
.h-full.noimg{min-height:0}
.h-full.noimg .hero-in{padding-block:clamp(3.5rem,9vw,7.5rem)}
""",
    "hero.type": """
.h-type .hero-in{padding-block:clamp(2.75rem,7vw,5.5rem) clamp(2.5rem,6vw,4.5rem)}
.h-type h1{font-size:clamp(2.5rem,9.6vw,7.75rem);line-height:.98;max-width:15ch;hyphens:auto}
.hero-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:1.75rem 4rem;align-items:end;margin-top:clamp(1.75rem,4vw,3rem);padding-top:clamp(1.5rem,3vw,2.25rem);border-top:var(--bw1) solid var(--fg)}
.hero-row .lede,.hero-row .ctas{margin-top:0}
.hero-row .rating{margin-top:1rem}
.h-type .ph{aspect-ratio:21/9;margin-top:clamp(2rem,5vw,3.5rem)}
@media (max-width:820px){.hero-row{grid-template-columns:minmax(0,1fr)}.h-type .ph{aspect-ratio:3/2}}
""",
    "hero.collage": """
.h-collage .hero-in{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(2rem,5vw,4rem);align-items:center;padding-block:clamp(3rem,7vw,5.5rem)}
.stack{position:relative;aspect-ratio:1;width:min(32rem,100%);justify-self:end}
.stack .ph{position:absolute}
.stack .s1{inset:0 20% 12% 0}
.stack .s2{right:0;bottom:0;width:46%;aspect-ratio:1;box-shadow:0 0 0 .5rem var(--sbg)}
.stack .s3{right:5%;top:5%;width:29%;aspect-ratio:3/4;box-shadow:0 0 0 .5rem var(--sbg)}
.stack.n1 .s1{inset:0}
.stack.n2 .s1{inset:0 14% 10% 0}
.h-collage.noimg .hero-in{grid-template-columns:minmax(0,46rem);padding-block:clamp(3.5rem,9vw,7.5rem)}
@media (max-width:860px){.h-collage .hero-in{grid-template-columns:minmax(0,1fr)}.stack{justify-self:start;width:min(26rem,100%)}}
""",
    "hero.card": """
.h-card .bgph{height:clamp(20rem,58vh,36rem);width:min(calc(var(--wrap) + 7rem),100% - 1.5rem);margin:.75rem auto 0}
.h-card.noimg .hcard{margin-top:-6.5rem}
.h-card div.bgph{height:clamp(13rem,30vh,18rem);border-radius:var(--ri);background:var(--band) repeating-linear-gradient(135deg,color-mix(in srgb,var(--on-band) 9%,transparent) 0 2px,transparent 2px 16px)}
.hcard{position:relative;max-width:41rem;margin-top:clamp(-11rem,-15vw,-5rem);margin-bottom:clamp(2.5rem,6vw,4.5rem);padding:clamp(1.6rem,4vw,3rem);background:var(--surface);color:var(--fg);border:var(--bw1) solid var(--ln);border-radius:var(--r);box-shadow:0 34px 60px -40px rgb(0 0 0/.55)}
.hard .hcard{box-shadow:6px 6px 0 var(--fg);border-color:var(--fg)}
""",
    "hero.diagonal": """
.h-diag .hero-in{display:grid;grid-template-columns:minmax(0,1.12fr) minmax(0,.88fr);align-items:center;min-height:clamp(26rem,68vh,40rem)}
.h-diag .hero-txt{padding-block:clamp(3rem,7vw,5.5rem);z-index:1}
.h-diag .dph{position:absolute;inset:0 0 0 55%;border-radius:0;clip-path:polygon(17% 0,100% 0,100% 100%,0 100%)}
.h-diag div.dph{background:color-mix(in srgb,var(--fg) 9%,var(--sbg)) repeating-linear-gradient(135deg,color-mix(in srgb,var(--fg) 13%,transparent) 0 3px,transparent 3px 18px)}
.h-diag::before{content:"";position:absolute;inset:0 0 0 calc(55% - 1.1rem);clip-path:polygon(17% 0,100% 0,100% 100%,0 100%);background:var(--cta)}
@media (max-width:860px){
.h-diag .hero-in{grid-template-columns:minmax(0,1fr);min-height:0}
.h-diag .hero-txt{padding-bottom:2.5rem}
.h-diag .dph{position:relative;inset:auto;height:clamp(13rem,52vw,20rem);clip-path:polygon(0 16%,100% 0,100% 100%,0 100%)}
.h-diag div.dph{height:6rem}
.h-diag::before{display:none}
}
""",
    "hero.centered": """
.h-center .hero-in{padding-block:clamp(3rem,7vw,5.5rem) clamp(2.5rem,6vw,4.5rem);text-align:center}
.h-center .hero-txt{max-width:50rem;margin-inline:auto}
.h-center .eyebrow,.h-center .ctas,.h-center .rating{justify-content:center}
.h-center .lede{margin-inline:auto;max-width:46ch}
.h-center .ph{aspect-ratio:16/7;margin-top:clamp(2.25rem,5vw,3.75rem)}
.img-arch .h-center .ph{border-radius:clamp(8rem,22vw,20rem) clamp(8rem,22vw,20rem) var(--ri) var(--ri)}
.h-center.noimg .hero-in{padding-block:clamp(4rem,10vw,8rem)}
.h-center .deco{right:50%;translate:50% -50%}
@media (max-width:700px){.h-center .ph{aspect-ratio:4/3}}
""",
    "hero.strip": """
.h-strip .hero-in{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(2rem,5vw,4rem);align-items:center;padding-block:clamp(2.75rem,6vw,5rem)}
.h-strip .ph{aspect-ratio:5/4}
.h-strip.noimg .hero-in{grid-template-columns:minmax(0,46rem);padding-block:clamp(3.5rem,9vw,7rem)}
.hstrip{position:relative;background:var(--sbg);color:var(--fg)}
.hstrip ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(14rem,1fr))}
.hstrip li{display:flex;gap:.8rem;align-items:baseline;padding:1.3rem 1.5rem 1.3rem 0;font-weight:600;line-height:1.35}
.hstrip li::before{content:"";flex:none;width:.5rem;height:.5rem;rotate:45deg;background:var(--hl);translate:0 -.1rem}
@media (max-width:860px){.h-strip .hero-in{grid-template-columns:minmax(0,1fr)}.h-strip .ph{aspect-ratio:3/2}.hstrip li{padding-block:.8rem}.hstrip ul{padding-block:.6rem}}
""",
    # ---------- services
    "svc.cards": """
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(18rem,100%),1fr));gap:1.25rem}
.cards .card{padding:1.75rem}
.cards .n{font:700 .85rem/1 var(--body);letter-spacing:.14em;color:var(--hl)}
.cards h3{font-size:1.3rem;margin:.95rem 0 .5rem}
.cards p{color:var(--mut)}
""",
    "svc.menu": """
.menu{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 clamp(2rem,6vw,5rem)}
.menu li{padding:1.5rem 0;border-top:1px solid var(--ln)}
.menu h3{display:flex;align-items:baseline;gap:.8rem;font-size:1.4rem}
.menu h3::after{content:"";flex:1;min-width:1.5rem;border-bottom:2px dotted var(--ln);translate:0 -.3rem}
.menu p{margin-top:.45rem;color:var(--mut);max-width:46ch}
@media (max-width:760px){.menu{grid-template-columns:minmax(0,1fr)}}
""",
    "svc.index": """
.index{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 clamp(2rem,6vw,5rem)}
.index li{display:grid;grid-template-columns:clamp(3.4rem,7vw,5.2rem) minmax(0,1fr);gap:.25rem 1rem;padding:1.6rem 0 1.75rem;border-top:var(--bw1) solid var(--fg)}
.index .n{grid-row:span 2;font:var(--hw) clamp(2.4rem,5vw,3.6rem)/.9 var(--display);color:var(--hl);font-variant-numeric:tabular-nums}
.index h3{font-size:1.35rem}
.index p{color:var(--mut)}
@media (max-width:760px){.index{grid-template-columns:minmax(0,1fr)}}
""",
    "svc.rows": """
.rows{display:grid;gap:clamp(2.5rem,6vw,4.5rem)}
.srow{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(1.75rem,5vw,4.5rem);align-items:center}
.srow .ph{aspect-ratio:5/4}
.srow.flip{grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr)}
.srow.flip .ph{order:2}
.srow li{padding:1.15rem 0;border-top:1px solid var(--ln)}
.srow li:last-child{border-bottom:1px solid var(--ln)}
.srow h3{font-size:1.3rem}
.srow p{margin-top:.3rem;color:var(--mut)}
.srow.solo{grid-template-columns:minmax(0,1fr)}
.srow.solo li{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.6fr);gap:.4rem 2.5rem;align-items:baseline}
.srow.solo p{margin-top:0}
@media (max-width:820px){.srow,.srow.flip,.srow.solo li{grid-template-columns:minmax(0,1fr)}.srow.flip .ph{order:0}}
""",
    "svc.tiles": """
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(13.5rem,100%),1fr));gap:.85rem}
.tiles li{padding:1.15rem 1.25rem 1.25rem;background:var(--card);border:var(--bw1) solid var(--ln);border-radius:var(--r)}
.tiles h3{display:flex;gap:.6rem;align-items:baseline;font-size:1.08rem}
.tiles h3::before{content:"";flex:none;width:.55rem;height:.55rem;border-radius:min(var(--r),50%);background:var(--cta);translate:0 -.08rem}
.tiles p{margin-top:.4rem;font-size:.95rem;line-height:1.5;color:var(--mut)}
""",
    # ---------- about
    "about": """
.about .body{font-size:1.12em;margin-top:1.1rem;max-width:60ch}
.about h2{font-size:var(--h2);margin-top:.7rem}
.facts{display:flex;flex-wrap:wrap;gap:1.5rem 3rem;margin-top:2rem;padding-top:1.5rem;border-top:1px solid var(--ln)}
.facts b{display:block;font:var(--hw) 2.2rem/1 var(--display);color:var(--hl)}
.facts span{font-size:.9rem;color:var(--mut)}
""",
    "about.media": """
.ab-media{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.1fr);gap:clamp(2rem,6vw,4.5rem);align-items:center}
.ab-media .ph{aspect-ratio:4/3}
.ab-media .ph.port{aspect-ratio:4/5;width:min(24rem,100%)}
.ab-media.solo{grid-template-columns:minmax(0,46rem)}
@media (max-width:860px){.ab-media{grid-template-columns:minmax(0,1fr)}}
""",
    "about.quote": """
.ab-quote{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:clamp(2rem,6vw,5rem);align-items:start}
.pull{position:relative;padding-top:2.75rem}
.pull::before{content:"\\201C";position:absolute;top:-1.4rem;left:-.2rem;font:var(--hw) 6rem/1 var(--display);color:var(--hl)}
.pull blockquote{font:var(--hw) clamp(1.45rem,3vw,2.2rem)/1.28 var(--display);letter-spacing:var(--hls);text-wrap:balance}
.pull figcaption{margin-top:1.2rem;font-size:.92rem;color:var(--mut)}
.ab-quote.solo{grid-template-columns:minmax(0,48rem)}
.ab-quote.solo .body{font-size:1.25em}
@media (max-width:860px){.ab-quote{grid-template-columns:minmax(0,1fr)}}
""",
    "about.stats": """
.ab-stats{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,.85fr);gap:clamp(2rem,6vw,5rem);align-items:center}
.statband{display:grid;gap:0}
.statband div{display:flex;align-items:baseline;justify-content:space-between;gap:1.5rem;padding:1.15rem 0;border-top:var(--bw1) solid var(--ln)}
.statband div:last-child{border-bottom:var(--bw1) solid var(--ln)}
.statband b{font:var(--hw) clamp(2.2rem,5vw,3.4rem)/1 var(--display);letter-spacing:var(--hls);color:var(--hl);overflow-wrap:anywhere}
.statband b.w{font-size:clamp(1.4rem,3vw,2rem)}
.statband span{font-size:.92rem;color:var(--mut);text-align:right}
.ab-stats.solo{grid-template-columns:minmax(0,48rem)}
@media (max-width:860px){.ab-stats{grid-template-columns:minmax(0,1fr)}}
""",
    # ---------- gallery
    "gal": """
.gal .ph{height:100%}
.g-one .ph{aspect-ratio:21/9}
.g-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--gap)}
.g-two .ph{aspect-ratio:4/3}
@media (max-width:640px){.g-one .ph{aspect-ratio:3/2}}
""",
    "gal.mosaic": """
.mosaic{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:clamp(9rem,17vw,14rem);gap:var(--gap)}
.mosaic .ph:first-child{grid-column:span 2;grid-row:span 2}
.mosaic.n3 .ph:not(:first-child),.mosaic.n4 .ph:last-child{grid-column:span 2}
@media (max-width:760px){.mosaic{grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:9.5rem}.mosaic.n4 .ph:not(:first-child){grid-column:span 1}.mosaic.n4 .ph:last-child{grid-column:span 2}}
""",
    "gal.grid": """
.ggrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--gap)}
.ggrid.n4{grid-template-columns:repeat(4,minmax(0,1fr))}
.ggrid .ph{aspect-ratio:1}
@media (max-width:760px){.ggrid,.ggrid.n4{grid-template-columns:repeat(2,minmax(0,1fr))}.ggrid.n3 .ph:last-child{grid-column:span 2;aspect-ratio:2}}
""",
    "gal.strip": """
.film{display:flex;gap:var(--gap);overflow-x:auto;scroll-snap-type:x mandatory;padding-bottom:1rem;padding-inline:max(1.25rem,calc((100% - var(--wrap))/2));scroll-padding-inline:max(1.25rem,calc((100% - var(--wrap))/2));scrollbar-width:thin;scrollbar-color:var(--ln) transparent}
.film .ph{flex:0 0 min(74vw,24rem);aspect-ratio:4/5;height:auto;scroll-snap-align:start}
.film .ph:nth-child(even){aspect-ratio:1;align-self:end}
""",
    "gal.feature": """
.feat{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);grid-template-rows:repeat(2,clamp(9rem,19vw,15.5rem));gap:var(--gap)}
.feat .ph:first-child{grid-row:span 2}
@media (max-width:700px){.feat{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:13rem 8.5rem}.feat .ph:first-child{grid-row:auto;grid-column:span 2}}
""",
    # ---------- reviews
    "rev": """
.rev-top{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:end;gap:1.5rem;margin-bottom:clamp(2rem,5vw,3rem)}
.rev-top .head{margin:0}
.score{display:flex;align-items:baseline;gap:.75rem}
.score b{font:var(--hw) 3.4rem/1 var(--display)}
.rev blockquote{font-size:1.03rem}
.rev footer,.rev figcaption{font-size:.9rem;color:var(--mut)}
.rev-more{margin-top:2rem}
.ha-center .rev-top{flex-direction:column;align-items:center}
.ha-center .rev-more{text-align:center}
""",
    "rev.wall": """
.wall{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(17rem,100%),1fr));gap:1.25rem}
.wall .rev{padding:1.75rem}
.wall blockquote{margin:.8rem 0 1rem}
""",
    "rev.lead": """
.rlead{display:grid;grid-template-columns:minmax(0,1fr);gap:clamp(2rem,5vw,3.5rem)}
.rlead .big blockquote{font:var(--hw) clamp(1.5rem,3.4vw,2.5rem)/1.25 var(--display);letter-spacing:var(--hls);max-width:26ch;text-wrap:balance}
.rlead .big{max-width:60rem}
.rlead .big figcaption{margin-top:1.3rem;font-size:.95rem}
.rsmall{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(18rem,100%),1fr));gap:1.5rem clamp(2rem,5vw,4rem);padding-top:clamp(1.5rem,4vw,2.5rem);border-top:1px solid var(--ln)}
.rsmall blockquote{margin:.6rem 0 .7rem}
.ha-center .rlead .big{margin-inline:auto;text-align:center}
.ha-center .rlead .big blockquote{margin-inline:auto}
""",
    "rev.badge": """
.rbadge{display:grid;grid-template-columns:minmax(0,19rem) minmax(0,1fr);gap:clamp(2rem,6vw,5rem);align-items:start}
.badge{padding:2rem 1.75rem;text-align:center;position:sticky;top:6rem}
.badge b{display:block;font:var(--hw) clamp(3.5rem,8vw,5rem)/1 var(--display)}
.badge .stars{display:block;margin:.6rem 0 .3rem;font-size:1.2rem}
.badge p{font-size:.92rem;color:var(--mut)}
.badge .btn{margin-top:1.25rem;width:100%}
.rquotes .rev{padding:1.5rem 0;border-top:1px solid var(--ln)}
.rquotes .rev:first-child{border-top:0;padding-top:0}
.rquotes blockquote{margin:.55rem 0 .7rem;font-size:1.12rem}
.rbadge.solo{grid-template-columns:minmax(0,48rem)}
@media (max-width:820px){.rbadge{grid-template-columns:minmax(0,1fr)}.badge{position:static}}
""",
    # ---------- extras
    "x.hl": """
.hl{padding-block:clamp(1.75rem,4vw,2.75rem)}
.hl ul{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(15rem,100%),1fr));gap:1rem clamp(1.5rem,4vw,3rem)}
.hl li{display:flex;gap:.85rem;align-items:flex-start;font-weight:600;line-height:1.4}
.hl svg{flex:none;width:1.35rem;height:1.35rem;margin-top:.1rem;color:var(--hl)}
""",
    "x.steps": """
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(13.5rem,100%),1fr));gap:2rem clamp(1.5rem,3vw,2.5rem);counter-reset:step}
.steps li{position:relative;padding-top:1.4rem;border-top:var(--bw1) solid var(--ln);counter-increment:step}
.steps li::before{content:counter(step);display:grid;place-items:center;width:2.4rem;height:2.4rem;margin:-2.6rem 0 1rem;border-radius:min(var(--r),50%);background:var(--hl);color:var(--sbg);font:700 1rem/1 var(--body)}
.steps h3{font-size:1.2rem}
.steps p{margin-top:.4rem;color:var(--mut)}
""",
    "x.faq": """
.faq{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:clamp(1.5rem,6vw,5rem);align-items:start}
.faq .head{margin-bottom:0}
.faq details{border-top:1px solid var(--ln)}
.faq details:last-child{border-bottom:1px solid var(--ln)}
.faq summary{display:flex;justify-content:space-between;gap:1.25rem;align-items:baseline;padding:1.15rem 0;cursor:pointer;list-style:none;font:600 1.08rem/1.35 var(--body)}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"+";flex:none;font:400 1.5rem/1 var(--body);color:var(--hl)}
.faq details[open] summary::after{content:"\\2212"}
.faq details p{padding:0 2.5rem 1.3rem 0;color:var(--mut)}
.ha-center .faq .head{margin-inline:0;text-align:left}
@media (max-width:820px){.faq{grid-template-columns:minmax(0,1fr)}}
""",
    "x.cta": """
.cta{text-align:center}
.cta h2{font-size:var(--h2);max-width:22ch;margin-inline:auto}
.cta p{max-width:46ch;margin:1rem auto 0;color:var(--mut);font-size:1.1em}
.cta .ctas{justify-content:center}
""",
    "x.area": """
.area{padding-block:clamp(2rem,5vw,3.25rem)}
.area .wrap{display:flex;flex-wrap:wrap;align-items:baseline;gap:.5rem 1.5rem}
.area p.big{font:var(--hw) clamp(1.3rem,3vw,2rem)/1.25 var(--display);letter-spacing:var(--hls);text-transform:var(--hcase);text-wrap:balance}
""",
    # ---------- visit
    "visit": """
.visit .where+.where{margin-top:.9rem}
.visit .hours{margin-top:1.5rem}
.visit h3.sm{font:600 .78rem/1.3 var(--body);letter-spacing:.16em;text-transform:uppercase;color:var(--mut);margin-bottom:.8rem}
""",
    "visit.split": """
.v-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:clamp(2rem,6vw,4.5rem);align-items:start}
.v-split .head{margin-bottom:1.75rem}
.v-split .map{aspect-ratio:4/3.4;min-height:20rem}
.ha-center .v-split .head{margin-inline:0;text-align:left}
@media (max-width:860px){.v-split{grid-template-columns:minmax(0,1fr)}.v-split .map{aspect-ratio:4/3;min-height:0}}
""",
    "visit.stack": """
.v-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(16rem,100%),1fr));gap:1.25rem}
.v-cards .card{padding:1.6rem 1.75rem}
.v-cards .hours{margin-top:0}
.v-cards .ctas{margin-top:1.25rem}
.v-stack .map{aspect-ratio:21/8;margin-top:1.25rem}
@media (max-width:760px){.v-stack .map{aspect-ratio:4/3}}
""",
}


def minify(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s*\n\s*", "", css)
    return re.sub(r"\s*([{};])\s*", r"\1", css).replace(";}", "}")


def sheet(used: list) -> str:
    """BASE plus the chunks a page used (a variant pulls in its family chunk, e.g. svc.cards -> none, rev.wall -> rev)."""
    keys = []
    for k in used:
        fam = k.split(".")[0]
        for x in (fam, k):
            if x in CHUNKS and x not in keys:
                keys.append(x)
    return minify(BASE + "".join(CHUNKS[k] for k in keys))
