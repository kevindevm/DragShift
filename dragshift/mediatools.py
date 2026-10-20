"""Audio/video conversions via static ffmpeg (imageio-ffmpeg) + mutagen tags.

No system ffmpeg needed. All functions take a source path and return a list
of output paths next to the source.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .util import UserError, sibling

AUDIO_TARGETS = ["MP3", "WAV", "OGG", "OPUS", "FLAC", "M4A"]
VIDEO_TARGETS = ["MP4", "WEBM", "MKV", "MP3", "WAV", "GIF", "PNG"]


def _ffmpeg() -> str:
    import os
    import sys
    import time
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
            direct = base / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
            if direct.exists():
                return str(direct)
            # imageio-ffmpeg ships versioned names (ffmpeg-win-x86_64-v7.1.exe)
            hits = sorted(base.rglob("ffmpeg*.exe" if sys.platform == "win32" else "ffmpeg*"))
            hits = [h for h in hits if h.is_file()]
            if hits:
                return str(hits[0])
        from imageio_ffmpeg import get_ffmpeg_exe
        # first call downloads the static binary: retry on flaky CI networks
        last: Exception | None = None
        for attempt in range(3):
            try:
                return get_ffmpeg_exe()
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        raise last  # type: ignore[misc]
    except Exception as e:
        raise UserError(f"Audio/video engine missing (imageio-ffmpeg): {e}")


def _run(args: list[str]) -> None:
    try:
        subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"")[-600:].decode("utf-8", "replace")
        raise UserError(f"ffmpeg failed: {err or e}")


def audio_to(src: str | Path, target: str) -> list[Path]:
    target = target.upper()
    from .util import CONFIG
    bitrate = str(CONFIG.get("audio_bitrate", "192k"))
    ff = _ffmpeg()
    ext = "." + ("opus" if target == "OPUS" else target.lower())
    out = sibling(src, ext=ext)
    codec = {"MP3": ["-c:a", "libmp3lame", "-b:a", bitrate],
             "WAV": ["-c:a", "pcm_s16le"],
             "OGG": ["-c:a", "libvorbis", "-b:a", bitrate],
             "OPUS": ["-c:a", "libopus", "-b:a", "96k"],
             "FLAC": ["-c:a", "flac"],
             "M4A": ["-c:a", "aac", "-b:a", bitrate]}[target]
    _run([ff, "-y", "-i", str(src), "-vn", *codec, str(out)])
    return [out]


def audio_voice(src: str | Path) -> Path:
    """Tiny mono 16 kHz MP3, ideal for voice notes."""
    out = sibling(src, "Voice", ".mp3")
    _run([_ffmpeg(), "-y", "-i", str(src), "-vn", "-c:a", "libmp3lame",
          "-b:a", "64k", "-ac", "1", "-ar", "16000", str(out)])
    return out


def audio_sample(src: str | Path, seconds: int = 30) -> Path:
    # re-encode (never -c copy): cutting mp3/aac mid-frame corrupts the file
    out = sibling(src, f"{seconds}s", ".mp3")
    _run([_ffmpeg(), "-y", "-i", str(src), "-t", str(seconds),
          "-vn", "-c:a", "libmp3lame", "-b:a", "128k", str(out)])
    return out


def strip_media_tags(src: str | Path) -> Path:
    """Copy with -map_metadata -1 (no re-encode when possible)."""
    out = sibling(src, "Clean", Path(src).suffix.lower())
    try:
        _run([_ffmpeg(), "-y", "-i", str(src), "-map_metadata", "-1", "-c", "copy", str(out)])
    except UserError:
        # copy failed (e.g. wav) -> plain re-mux without tags
        import mutagen
        data = Path(src).read_bytes()
        out.write_bytes(data)
        try:
            m = mutagen.File(str(out))
            if m is not None:
                m.delete()
                m.save()
        except Exception:
            pass
    else:
        # also drop mutagen tags for formats ffmpeg keeps
        try:
            import mutagen
            m = mutagen.File(str(out))
            if m is not None:
                m.delete()
                m.save()
        except Exception:
            pass
    return out


def video_to(src: str | Path, target: str) -> list[Path]:
    target = target.upper()
    if target in AUDIO_TARGETS:
        return audio_to(src, target)
    if target in ("SRT", "VTT"):
        return [extract_subs(src, target.lower())]
    ff = _ffmpeg()
    if target == "GIF":
        out = sibling(src, ext=".gif")
        pal = out.with_name(out.stem + " palette.png")
        _run([ff, "-y", "-ss", "0", "-t", "5", "-i", str(src), "-vf",
              "fps=10,scale=480:-1:flags=lanczos,palettegen", str(pal)])
        _run([ff, "-y", "-ss", "0", "-t", "5", "-i", str(src), "-i", str(pal),
              "-lavfi", "fps=10,scale=480:-1:flags=lanczos [x];[x][1:v] paletteuse", str(out)])
        try:
            pal.unlink()
        except OSError:
            pass
        return [out]
    if target == "PNG":
        from .util import CONFIG
        out = sibling(src, "Thumb", ".png")
        _run([ff, "-y", "-ss", str(CONFIG.get("thumb_sec", 1)), "-i", str(src),
              "-vframes", "1", str(out)])
        return [out]
    if target == "JPG":
        from .util import CONFIG
        out = sibling(src, "Thumb", ".jpg")
        _run([ff, "-y", "-ss", str(CONFIG.get("thumb_sec", 1)), "-i", str(src),
              "-vframes", "1", str(out)])
        return [out]
    out = sibling(src, ext="." + target.lower())
    from .util import CONFIG
    crf = str(CONFIG.get("video_crf", 23))
    if target == "MP4":
        args = ["-c:v", "libx264", "-crf", crf, "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k"]
    elif target == "WEBM":
        args = ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-c:a", "libopus"]
    else:  # MKV
        args = ["-c", "copy"]
    _run([ff, "-y", "-i", str(src), *args, str(out)])
    return [out]


def video_compress(src: str | Path) -> Path:
    out = sibling(src, "720p", ".mp4")
    _run([_ffmpeg(), "-y", "-i", str(src), "-vf", "scale=-2:720",
          "-crf", "28", "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", str(out)])
    return out


def video_mute(src: str | Path) -> Path:
    # keep the source container: -c:v copy into .mp4 fails for VP9/WebM sources
    ext = Path(src).suffix.lower() or ".mp4"
    out = sibling(src, "Muted", ext)
    if ext == ".mp4":
        _run([_ffmpeg(), "-y", "-i", str(src), "-an", "-c:v", "copy", str(out)])
    else:
        _run([_ffmpeg(), "-y", "-i", str(src), "-an", "-c:v", "libx264",
              "-crf", "23", "-preset", "veryfast", str(out)])
    return out


def concat_same(srcs: list[str | Path]) -> Path:
    """Join same-extension media with the concat demuxer (no re-encode)."""
    import tempfile
    if len(srcs) < 2:
        raise UserError("Select at least 2 files to join.")
    exts = {Path(s).suffix.lower() for s in srcs}
    if len(exts) != 1:
        raise UserError("Join needs the same format for every file (e.g. all .mp3).")
    lst = Path(tempfile.mkdtemp()) / "list.txt"
    lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in srcs), encoding="utf-8")
    out = sibling(srcs[0], "Joined", exts.pop())
    _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)])
    return out


def extract_subs(src: str | Path, fmt: str = "srt") -> Path:
    fmt = "vtt" if str(fmt).lower() == "vtt" else "srt"
    out = sibling(src, "Subs", "." + fmt)
    try:
        _run([_ffmpeg(), "-y", "-i", str(src), "-map", "0:s:0", str(out)])
    except UserError as e:
        raise UserError(f"No subtitles found in this file. ({e})")
    return out


LOUD_PRESETS = {"Podcast": "I=-16:TP=-1.5:LRA=11", "Music": "I=-14:TP=-1:LRA=11",
                "Broadcast": "I=-23:TP=-2:LRA=7"}


def loudnorm(src: str | Path, preset: str = "Podcast") -> Path:
    spec = LOUD_PRESETS.get(preset, LOUD_PRESETS["Podcast"])
    is_audio = Path(src).suffix.lower() in {".mp3", ".wav", ".ogg", ".oga", ".opus",
                                            ".flac", ".m4a", ".aac"}
    out = sibling(src, f"Loud {preset}", ".mp3" if is_audio else ".mp4")
    if is_audio:
        _run([_ffmpeg(), "-y", "-i", str(src), "-af", f"loudnorm={spec}",
              "-c:a", "libmp3lame", "-b:a", "192k", str(out)])
    else:
        _run([_ffmpeg(), "-y", "-i", str(src), "-af", f"loudnorm={spec}",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)])
    return out


def trim_media(src: str | Path, start: float, end: float) -> Path:
    if end <= start or start < 0:
        raise UserError("End must be after start (seconds, e.g. 5 → 20).")
    dur = end - start
    is_audio = Path(src).suffix.lower() in {".mp3", ".wav", ".ogg", ".oga", ".opus",
                                            ".flac", ".m4a", ".aac"}
    out = sibling(src, "Trim", Path(src).suffix.lower())
    if is_audio:
        _run([_ffmpeg(), "-y", "-ss", str(start), "-i", str(src), "-t", str(dur),
              "-c:a", "libmp3lame", "-b:a", "128k", str(out)])
    else:
        _run([_ffmpeg(), "-y", "-ss", str(start), "-i", str(src), "-t", str(dur),
              "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "128k", str(out)])
    return out
