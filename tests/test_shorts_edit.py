"""Shorts editor: real small renders with ffmpeg; sources are made with lavfi and Pillow."""
import shutil
import subprocess

import pytest
from PIL import Image

from vision.masters import shorts_edit as se

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg missing")


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def tone(path, dur, freq=440):
    ff("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={dur}:sample_rate=24000", "-ac", "1", str(path))
    return path


def clip(path, dur=4):
    ff("-f", "lavfi", "-i", f"testsrc=size=640x360:rate=30:duration={dur}", "-pix_fmt", "yuv420p", str(path))
    return path


def photo(path):
    img = Image.new("RGB", (800, 600), (30, 90, 160))
    for x in range(0, 800, 50):                       # a grid so zoom shows
        for y in range(0, 600, 50):
            if (x // 50 + y // 50) % 2:
                img.paste((220, 220, 220), (x, y, x + 50, y + 50))
    img.save(path)
    return path


def beats(tmp, visuals, dur=1.5):
    out = []
    for i, v in enumerate(visuals):
        out.append({"text": f"hello brave new world {i}", "audio": str(tone(tmp / f"a{i}.wav", dur)), "dur": dur, "visual": v,
                    "kind": "outro" if i == len(visuals) - 1 else "story"})
    return out


def frame(video, t, out):
    ff("-ss", str(t), "-i", str(video), "-frames:v", "1", str(out))
    return Image.open(out).convert("RGB")


def info(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return p.stdout.split()


def diff(a, b):
    return sum(abs(x - y) for p, q in zip(a.getdata(), b.getdata()) for x, y in zip(p, q)) / (a.width * a.height * 3)


def vid(tmp):
    return {"kind": "video", "path": str(clip(tmp / "c.mp4")), "duration": 4}


def test_default_call(tmp_path):
    b = beats(tmp_path, [vid(tmp_path)] * 2)
    r = se.assemble(tmp_path / "w", b, channel="Test")
    assert r["sfx"] == 0 and r["shots"] == 1
    assert "video,1080,1920" in info(r["file"]) and "audio" in info(r["file"])
    assert abs(se.probe(r["file"]) - 3.0) < 0.1


def test_motion_changes_framing(tmp_path):
    v = vid(tmp_path)
    b = beats(tmp_path, [v], dur=3)
    on = se.assemble(tmp_path / "on", b, channel="T", motion=True)["file"]
    off = se.assemble(tmp_path / "off", b, channel="T", motion=False)["file"]
    assert abs(se.probe(on) - se.probe(off)) < 0.1
    # the first frame matches (zoom starts at 1.0), the last is clearly more zoomed in than the unmoved one
    assert diff(frame(on, 0, tmp_path / "a.png"), frame(off, 0, tmp_path / "b.png")) < 6
    assert diff(frame(on, 2.8, tmp_path / "c.png"), frame(off, 2.8, tmp_path / "d.png")) > 8


def test_wide_renders(tmp_path):
    r = se.assemble(tmp_path / "w", beats(tmp_path, [vid(tmp_path)]), channel="T", wide=True)
    assert "video,1920,1080" in info(r["file"])


def test_highlight_style_and_center(tmp_path):
    st = {"fill": "#FFFFFF", "highlight": "#FF0000", "stroke": "#000000"}
    b = beats(tmp_path, [{"kind": "photo", "path": str(photo(tmp_path / "p.png"))}], dur=2)
    r = se.assemble(tmp_path / "w", b, channel="T", style=st)
    f = frame(r["file"], 0.2, tmp_path / "f.png")
    px = f.crop((0, 1110, 1080, 1530)).getdata()
    assert any(p[0] > 200 and p[1] < 60 and p[2] < 60 for p in px)           # highlighted word
    assert any(min(p) > 235 for p in px)                                      # rest stays fill
    # centred caption: pixels of the caption colour sit around the vertical middle, none in the old lower strip
    r2 = se.assemble(tmp_path / "w2", b, channel="T", style={"position": "center", "fill": "#00FF00"})
    g = frame(r2["file"], 0.2, tmp_path / "g.png")
    ys = [y for y in range(g.height) for x in range(0, g.width, 8) if (lambda p: p[1] > 200 and p[0] < 60 and p[2] < 60)(g.getpixel((x, y)))]
    assert ys and 800 < min(ys) and max(ys) < 1200


def test_caption_png_fits_and_font(tmp_path):
    out = tmp_path / "c.png"
    se.caption_png("an extraordinarily long unbroken wordlikethis thing", out, None, se.UPRIGHT, {"font": "/nonexistent.ttf", "highlight": "#ff0", "fill": "#fff"}, 1)
    bb = Image.open(out).getbbox()
    assert bb and bb[0] >= 0 and bb[2] <= 1080


def test_sfx_with_and_without_music(tmp_path):
    music = str(tone(tmp_path / "m.wav", 1, 220))
    s = tone(tmp_path / "s.wav", 0.3, 880)
    for n, mus in enumerate([None, music]):
        b = beats(tmp_path, [vid(tmp_path)] * 2)
        fx = [{"at": 0.5, "path": str(s), "volume": 0.4}, {"at": 1.0, "path": str(tmp_path / "missing.wav")}, {"at": 0.2, "path": str(tmp_path / "c.mp4")[:-4] + ".txt"}]
        r = se.assemble(tmp_path / f"w{n}", b, channel="T", music=mus, sfx=fx)
        assert r["sfx"] == 1 and "audio" in info(r["file"]) and abs(se.probe(r["file"]) - 3.0) < 0.1
    r = se.assemble(tmp_path / "w9", b, channel="T", music=music)
    assert r["sfx"] == 0 and abs(se.probe(r["file"]) - 3.0) < 0.1


def test_sfx_undecodable_skipped(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_text("not audio")
    r = se.assemble(tmp_path / "w", beats(tmp_path, [vid(tmp_path)]), channel="T", sfx=[{"at": 0, "path": str(bad)}])
    assert r["sfx"] == 0


def test_timed_chunks_consistent():
    b = [{"start": 0, "dur": 2.2, "speech": 2.0, "text": "one two three four five six"},
         {"start": 2.2, "dur": 1.0, "text": "a b", "words": [["a", 0.0, 0.3], ["b", 0.4, 0.8]]}]
    tc = se.timed_chunks(b, 16, 3)
    assert [(a, z, t) for a, z, t, _ in tc] == se.chunks(b, 16, 3)
    for a, z, text, ws in tc:
        assert " ".join(w for w, _, _ in ws) == text
        starts = [x for _, x, _ in ws]
        assert starts == sorted(starts)
        assert all(a <= x <= y <= z for _, x, y in ws)


def test_watermark_survives_mixed_shots(tmp_path):
    ph = {"kind": "photo", "path": str(photo(tmp_path / "p.png"))}
    v = vid(tmp_path)
    b = beats(tmp_path, [ph, v, ph, v, v], dur=1.2)
    r = se.assemble(tmp_path / "w", b, channel="WMARK", motion=True)
    assert r["shots"] == 4
    f = frame(r["file"], 5.5, tmp_path / "late.png")
    # the watermark sits top right, white text on a see-through layer: bright pixels in that corner of a non-bright scene
    wm = Image.open(tmp_path / "w" / "build" / "watermark.png")
    box = f.crop((1080 - 40 - wm.width, 70, 1040, 70 + wm.height))
    base = frame(tmp_path / "w" / "build" / "base.mp4", 5.5, tmp_path / "base.png").crop((1080 - 40 - wm.width, 70, 1040, 70 + wm.height))
    assert diff(box, base) > 3
