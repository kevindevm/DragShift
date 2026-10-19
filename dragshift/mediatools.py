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
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = os.path.join(sys._MEIPASS, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
            if os.path.exists(bundled):
                return bundled
        from imageio_ffmpeg import get_ffmpeg_exe
        return get_ffmpeg_exe()
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
