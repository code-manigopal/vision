"""Shorts editor: timed beats (one audio file and one visual each) -> one 1080x1920 mp4, with ffmpeg and Pillow.

- Every beat becomes a segment exactly as long as its audio: a clip is sped up or slowed to fit (within limits), cut
  or looped otherwise; a photo gets a slow zoom or pan.
- Captions are drawn with Pillow (Homebrew's ffmpeg has no subtitle filter) and laid over as one timed image stream.
- A small channel watermark sits top right; a subscribe button slides in over the closing beat.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1080, 1920, 30
CAP_H, CAP_Y = 420, 1110          # caption strip: height, top edge
FONTS = ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Supplemental/Impact.ttf",
         "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def run(args: list[str]) -> None:
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{args[0]} failed: {(p.stderr or '').strip()[-400:]}")


def probe(path: Path | str) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        raise RuntimeError(f"ffprobe could not read {Path(path).name}")


def speed(clip_s: float, beat_s: float) -> float:
    """Playback speed for a clip in a beat: the whole clip when that needs 0.6x-1.5x; a longer clip is cut at
    normal speed, a much shorter one is slowed to 0.6x and looped."""
    if clip_s <= 0 or beat_s <= 0:
        return 1.0
    f = clip_s / beat_s
    return 1.0 if f > 1.5 else max(0.6, round(f, 3))


def chunks(beats: list[dict], max_chars: int = 16, max_words: int = 3) -> list[tuple[float, float, str]]:
    """Caption chunks (start, end, text) on the video's clock. Uses the voice's word timings when it gave them,
    otherwise spreads a beat's words over its speech by length."""
    out: list[tuple[float, float, str]] = []
    for b in beats:
        t0, speech = b["start"], b.get("speech") or b["dur"]
        words = [(w, t0 + a, t0 + z) for w, a, z in b.get("words") or []]
        if not words:
            toks = b["text"].split()
            total = sum(len(t) + 1 for t in toks) or 1
            at = 0.0
            for t in toks:
                d = speech * (len(t) + 1) / total
                words.append((t, t0 + at, t0 + at + d))
                at += d
        group: list[tuple[str, float, float]] = []
        mine: list[list] = []
        for w in words:
            if group and (len(group) >= max_words or len(" ".join(x[0] for x in group)) + 1 + len(w[0]) > max_chars):
                mine.append([group[0][1], group[-1][2], " ".join(x[0] for x in group)])
                group = []
            group.append(w)
        if group:
            mine.append([group[0][1], group[-1][2], " ".join(x[0] for x in group)])
        for i, c in enumerate(mine):       # hold each chunk until the next one, so captions don't flicker
            c[1] = mine[i + 1][0] if i + 1 < len(mine) else min(c[1] + 0.15, t0 + b["dur"])
        out += [(a, z, t) for a, z, t in mine if z > a]
    return out


def font(size: int, path: str | None = None):
    for f in [path] + FONTS if path else FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def caption_png(text: str, out: Path, font_path: str | None = None) -> None:
    img = Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    text, size = text.upper(), 96
    while True:
        f = font(size, font_path)
        lines, cur = [], ""
        for w in text.split():
            trial = (cur + " " + w).strip()
            if cur and d.textlength(trial, font=f) > W - 140:
                lines.append(cur)
                cur = w
            else:
                cur = trial
        lines.append(cur)
        if (len(lines) <= 2 and all(d.textlength(l, font=f) <= W - 100 for l in lines)) or size <= 48:
            break
        size -= 8
    d.multiline_text((W / 2, CAP_H / 2), "\n".join(lines), font=f, fill=(255, 255, 255, 255), anchor="mm", align="center",
                     stroke_width=max(6, size // 11), stroke_fill=(0, 0, 0, 255), spacing=10)
    img.save(out)


def watermark_png(out: Path, name: str, logo: str | None = None) -> None:
    """The channel logo (or its name when there is no logo file), small and see-through."""
    if logo and Path(logo).exists():
        img = Image.open(logo).convert("RGBA")
        img.thumbnail((120, 120))
    else:
        f = font(30)
        w = int(ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(name, font=f)) + 16
        img = Image.new("RGBA", (w, 48), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((w / 2, 24), name, font=f, fill=(255, 255, 255, 255), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 255))
    img.putalpha(img.getchannel("A").point(lambda a: int(a * 0.55)))
    img.save(out)


def subscribe_png(out: Path) -> None:
    img = Image.new("RGBA", (540, 136), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, 539, 135), radius=68, fill=(230, 33, 23, 255))
    d.text((270, 68), "SUBSCRIBE", font=font(62), fill=(255, 255, 255, 255), anchor="mm")
    img.save(out)


def segment(visual: dict | None, frames: int, out: Path, i: int) -> None:
    """One beat's picture, `frames` long, no sound."""
    # every segment leaves in the same pixel format and colour range: a change mid-video resets the overlays
    enc = ["-frames:v", str(frames), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-color_range", "tv", str(out)]
    dur = frames / FPS
    if not visual:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0B0C10:s={W}x{H}:r={FPS}", "-vf", "format=yuv420p,setparams=range=limited", *enc])
    elif visual["kind"] == "photo":
        z, x, y = [("1+0.14*on/{n}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"), ("1.14-0.14*on/{n}", "iw/2-iw/zoom/2", "ih/2-ih/zoom/2"),
                   ("1.14", "(iw-iw/zoom)*on/{n}", "ih/2-ih/zoom/2")][i % 3]
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase:out_range=limited,format=yuv420p,crop={W * 2}:{H * 2},"
              f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},setsar=1,setparams=range=limited").replace("{n}", str(max(frames, 1)))
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", str(FPS), "-i", visual["path"], "-vf", vf, *enc])
    else:
        f = speed(visual.get("duration") or probe(visual["path"]), dur)
        vf = f"setpts=PTS/{f},scale={W}:{H}:force_original_aspect_ratio=increase:out_range=limited,format=yuv420p,crop={W}:{H},fps={FPS},setsar=1,setparams=range=limited"
        run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", visual["path"], "-vf", vf, *enc])


def _concat_list(path: Path, entries: list[tuple[str, float | None]]) -> None:
    lines = ["ffconcat version 1.0"]
    for name, dur in entries:
        lines.append(f"file '{name}'")
        if dur is not None:
            lines.append(f"duration {dur:.3f}")
    path.write_text("\n".join(lines) + "\n")


def assemble(work: Path, beats: list[dict], *, channel: str, logo: str | None = None, font_path: str | None = None) -> dict:
    """beats: [{text, audio, dur, speech?, words?, visual?, kind}] in order -> work/final.mp4."""
    build = work / "build"
    build.mkdir(parents=True, exist_ok=True)
    t = 0.0
    for b in beats:
        b["start"] = t
        t += b["dur"]
    total = t

    _concat_list(build / "audio.ffconcat", [(str(Path(b["audio"]).resolve()), None) for b in beats])
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(build / "audio.ffconcat"), "-c", "copy", str(build / "narration.wav")])

    seen = [b.get("visual") for b in beats if b.get("visual")]
    last = None
    segs = []
    for i, b in enumerate(beats):
        last = b.get("visual") or last or (seen[0] if seen else None)     # a beat with no footage reuses its neighbour's
        frames = max(1, round((b["start"] + b["dur"]) * FPS) - round(b["start"] * FPS))
        segment(last, frames, build / f"seg{i:02d}.mp4", i)
        segs.append((f"seg{i:02d}.mp4", None))
    _concat_list(build / "video.ffconcat", segs)
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(build / "video.ffconcat"), "-c", "copy", str(build / "base.mp4")])

    Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0)).save(build / "cap_blank.png")
    caps, entries, at = chunks(beats), [], 0.0
    for n, (a, z, text) in enumerate(caps):
        if a - at > 0.02:
            entries.append(("cap_blank.png", a - at))
            at = a
        if z - at < 0.04:
            continue
        caption_png(text, build / f"cap{n:03d}.png", font_path)
        entries.append((f"cap{n:03d}.png", z - at))
        at = z
    entries += [("cap_blank.png", max(total - at, 0.04)), ("cap_blank.png", None)]
    _concat_list(build / "caps.ffconcat", entries)
    watermark_png(build / "watermark.png", channel, logo)
    subscribe_png(build / "subscribe.png")

    outro = next((b["start"] for b in beats if b.get("kind") == "outro"), None)
    graph = f"[0:v][1:v]overlay=0:{CAP_Y}:eof_action=pass[c];[c][3:v]overlay=W-w-40:70[w]"
    if outro is not None:
        graph += (f";[w][4:v]overlay=x=(W-w)/2:y='H-h-230+max(0,1-(t-{outro:.3f})/0.35)*520-12*abs(sin((t-{outro:.3f})*5))'"
                  f":enable='gte(t,{outro:.3f})'[v]")
    out = work / "final.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-reinit_filter", "0", "-i", str(build / "base.mp4"), "-f", "concat", "-safe", "0", "-i", str(build / "caps.ffconcat"),
         "-i", str(build / "narration.wav"), "-loop", "1", "-i", str(build / "watermark.png"), "-loop", "1", "-i", str(build / "subscribe.png"),
         "-filter_complex", graph, "-map", "[v]" if outro is not None else "[w]", "-map", "2:a", "-t", f"{total:.3f}",
         "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p", "-r", str(FPS),
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
    return {"file": str(out), "seconds": round(total, 1), "captions": len(caps)}
