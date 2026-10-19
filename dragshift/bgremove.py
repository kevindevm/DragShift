"""Background removal: solid-color (always works) + AI u2net (opt-in download).

AI path downloads NOTHING at install time. On first AI use it fetches:
  - u2net.onnx (~176 MB) from the rembg release, once, into the models dir
  - onnxruntime: reused if importable; in dev (non-frozen) auto `pip install onnxruntime`,
    in the frozen portable exe the user is told how to enable it.
Toggle lives in Settings ("Background removal": Off=skip, Solid, AI).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.request import urlretrieve

from .util import UserError, sibling

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
MODEL_NAME = "u2net.onnx"


def models_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    d = base / "DragShift" / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ai_model_present() -> bool:
    return (models_dir() / MODEL_NAME).exists()


def ai_ready() -> bool:
    return ai_status()[0] == "ready"


def onnx_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def rembg_available() -> bool:
    try:
        import rembg  # noqa: F401
        return onnx_available()
    except Exception:
        return False


def ai_status() -> tuple[str, str]:
    """(state, human message). States: ready / no-model / no-onnx / frozen-no-onnx."""
    has_model = ai_model_present()
    has_onnx = onnx_available()
    if has_model and has_onnx:
        return "ready", "AI ready (model downloaded)"
    if not has_onnx:
        if getattr(sys, "frozen", False):
            return ("frozen-no-onnx",
                    "Not available in portable .exe (can't install onnxruntime inside it). "
                    "Use the Python version or Solid background.")
        return ("no-onnx",
                "Needs onnxruntime (auto-installs on first AI use) + model download (~176 MB, once)")
    return "no-model", "Model not downloaded yet (downloads ~176 MB on first AI use)"


def ensure_onnxruntime() -> None:
    """Make onnxruntime importable. Dev: pip-install to user site. Frozen: explain."""
    if onnx_available():
        return
    if getattr(sys, "frozen", False):
        raise UserError(
            "AI background needs onnxruntime, which can't be pip-installed into the portable .exe. "
            "Use the Python version (pip install onnxruntime) or Solid background instead.")
    import subprocess
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "onnxruntime"],
                       check=True, capture_output=True)
    except Exception as e:
        raise UserError(f"Couldn't install onnxruntime: {e}")
    if not onnx_available():
        raise UserError("onnxruntime installed but still not importable. Restart the app.")


def ensure_model(progress=None) -> Path:
    dest = models_dir() / MODEL_NAME
    if dest.exists() and dest.stat().st_size > 10_000_000:
        return dest
    tmp = dest.with_suffix(".part")
    try:
        def _hook(block, size, total):
            if progress and total > 0:
                try:
                    progress(min(99, int(block * size * 100 / total)))
                except Exception:
                    pass
        urlretrieve(MODEL_URL, tmp, reporthook=_hook)
        tmp.replace(dest)
    except Exception as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise UserError(f"Couldn't download the AI model (~176 MB): {e}")
    return dest


def ff_one(p: float) -> Path:
    d = models_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f".dl{p:.0f}"


def remove_solid_background(src: str | Path, tolerance: int = 32, feather: int = 2) -> Path:
    """Flood-fill from the corners: good for product shots on plain backgrounds."""
    from PIL import Image, ImageChops, ImageFilter
    from .convert import flatten, open_image
    im = flatten(open_image(src)).convert("RGB")
    small = im.resize((480, max(1, int(480 * im.height / max(1, im.width)))))
    seed = Image.new("RGB", small.size)
    corners = [small.getpixel((0, 0)), small.getpixel((small.width - 1, 0)),
               small.getpixel((0, small.height - 1)), small.getpixel((small.width - 1, small.height - 1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    diff = ImageChops.difference(small, Image.new("RGB", small.size, bg)).convert("L")
    mask_small = diff.point(lambda v: 0 if v <= tolerance else 255)
    from PIL import ImageDraw
    ImageDraw.floodfill(mask_small, (0, 0), 128)
    ImageDraw.floodfill(mask_small, (mask_small.width - 1, 0), 128)
    ImageDraw.floodfill(mask_small, (0, mask_small.height - 1), 128)
    ImageDraw.floodfill(mask_small, (mask_small.width - 1, mask_small.height - 1), 128)
    mask_small = mask_small.point(lambda v: 0 if v == 128 else 255)
    mask = mask_small.resize(im.size, Image.BILINEAR)
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    out_im = im.convert("RGBA")
    out_im.putalpha(mask)
    out = sibling(src, "No BG", ".png")
    out_im.save(out, "PNG")
    return out


def _u2net_session(model: Path):
    import numpy as np
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    return ort.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])


def remove_ai_background(src: str | Path, progress=None) -> Path:
    """u2net inference. Downloads model on first use. Raises UserError when unavailable."""
    # rembg fast path (dev machines that already have it)
    try:
        import rembg
        from PIL import Image as _I
        im = _I.open(src)
        out_im = rembg.remove(im)
        out = sibling(src, "No BG AI", ".png")
        out_im.save(out, "PNG")
        return out
    except Exception:
        pass
    ensure_onnxruntime()
    model = ensure_model(progress)
    try:
        import numpy as np
        from PIL import Image as _I
    except Exception as e:
        raise UserError(f"AI background needs numpy/Pillow: {e}")
    im = _I.open(src).convert("RGB")
    w, h = im.size
    small = im.resize((320, 320), _I.BILINEAR)
    arr = (np.asarray(small).astype(np.float32) / 255.0 - np.array([0.485, 0.456, 0.406], np.float32)) \
        / np.array([0.229, 0.224, 0.225], np.float32)
    arr = arr.transpose(2, 0, 1)[None]
    try:
        sess = _u2net_session(model)
        pred = sess.run(None, {sess.get_inputs()[0].name: arr})[0][0][0]
    except Exception as e:
        raise UserError(f"AI inference failed: {e}")
    pred = (pred - pred.min()) / max(1e-6, (pred.max() - pred.min()))
    from PIL import Image as _I2
    mask = _I2.fromarray((pred * 255).astype(np.uint8)).resize((w, h), _I2.BILINEAR)
    out_im = im.convert("RGBA")
    out_im.putalpha(mask)
    out = sibling(src, "No BG AI", ".png")
    out_im.save(out, "PNG")
    return out


def remove_background(src: str | Path, mode: str = "solid") -> Path:
    if mode == "ai":
        return remove_ai_background(src)
    return remove_solid_background(src)
