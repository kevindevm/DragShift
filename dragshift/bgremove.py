"""Background removal: solid-color (always works) + AI u2net (opt-in download).

AI path downloads NOTHING at install time. On first AI use it fetches:
  - onnxruntime wheel (~90 MB) from PyPI (SHA-256 verified) into engines/
  - u2net.onnx (~176 MB) from the rembg release, once, into the models dir
Toggle lives in Settings ("Background removal"). Works in dev, portable and
installed builds alike.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.request import urlretrieve

from .util import UserError, sibling

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx"
MODEL_NAME = "u2net.onnx"


def _rembg_home_models() -> Path:
    # rembg's own cache, e.g. C:\Users\<you>\.rembg\models\isnet-general-use\...
    return Path.home() / ".rembg" / "models"


def find_model() -> tuple[Path, int] | None:
    """Best local AI model: isnet-general-use first (better edges), then u2net.

    Checks rembg's cache (~/.rembg/models/…) and our own models dir.
    Returns (path, input_size) or None.
    """
    cands = [
        (_rembg_home_models() / "isnet-general-use" / "isnet-general-use.onnx", 1024),
        (_rembg_home_models() / "u2net" / "u2net.onnx", 320),
        (_rembg_home_models() / "u2net_human_seg" / "u2net_human_seg.onnx", 320),
        (_rembg_home_models() / "u2net_cloth_seg" / "u2net_cloth_seg.onnx", 320),
        (models_dir() / MODEL_NAME, 320),
    ]
    for p, size in cands:
        try:
            if p.exists() and p.stat().st_size > 10_000_000:
                return p, size
        except OSError:
            continue
    return None


def ai_model_present() -> bool:
    return find_model() is not None


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
    """(state, human message). States: ready / no-model / no-onnx."""
    has_model = ai_model_present()
    has_onnx = onnx_available()
    if has_model and has_onnx:
        found = find_model()
        name = found[0].stem if found else "model"
        return "ready", f"AI ready ({name})"
    if not has_onnx:
        return "no-onnx", "Downloads onnxruntime (~90 MB) + model (~176 MB), once"
    return "no-model", "Model not downloaded yet (downloads ~176 MB on first AI use)"


def ensure_onnxruntime() -> None:
    """Make onnxruntime importable anywhere (dev, portable, installed).

    Order: already importable → engines/ copy → download the official PyPI
    wheel into engines/ (verified by SHA-256 from PyPI metadata). No pip,
    no admin, works frozen.
    """
    if onnx_available():
        return
    from . import engines as _eng
    vendor = _eng.engines_root() / "onnxruntime"
    if _eng.wheel_importable("onnxruntime", vendor):
        return
    _eng.download_wheel("onnxruntime", vendor)
    if not _eng.wheel_importable("onnxruntime", vendor):
        raise UserError("onnxruntime downloaded but still not importable. Restart the app.")
    if not onnx_available():
        raise UserError("onnxruntime downloaded but still not importable. Restart the app.")


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


def _ai_session(model: Path):
    import onnxruntime as ort
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
    return ort.InferenceSession(str(model), sess_options=opts, providers=["CPUExecutionProvider"])


def remove_ai_background(src: str | Path, progress=None) -> Path:
    """u2net/isnet inference. Uses the best local model, downloads u2net if none."""
    from .convert import flatten, open_image
    # rembg fast path (dev machines that already have it): honors EXIF via open_image
    try:
        import rembg
        out_im = rembg.remove(open_image(src))
        out = sibling(src, "No BG AI", ".png")
        out_im.save(out, "PNG")
        return out
    except Exception:
        pass
    ensure_onnxruntime()
    found = find_model()
    if found is None:
        model, size = ensure_model(progress), 320
    else:
        model, size = found
    try:
        import numpy as np
    except Exception as e:
        raise UserError(f"AI background needs numpy: {e}")
    im = flatten(open_image(src)).convert("RGB")  # EXIF-aware: no rotated cutouts
    w, h = im.size
    small = im.resize((size, size), Image.BILINEAR) if (Image := __import__("PIL.Image", fromlist=["Image"])) else None
    arr = (np.asarray(small).astype(np.float32) / 255.0 - np.array([0.485, 0.456, 0.406], np.float32)) \
        / np.array([0.229, 0.224, 0.225], np.float32)
    arr = arr.transpose(2, 0, 1)[None]
    try:
        sess = _ai_session(model)
        pred = sess.run(None, {sess.get_inputs()[0].name: arr})[0][0][0]
    except Exception as e:
        raise UserError(f"AI inference failed: {e}")
    pred = (pred - pred.min()) / max(1e-6, (pred.max() - pred.min()))
    mask = Image.fromarray((pred * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR)
    out_im = im.convert("RGBA")
    out_im.putalpha(mask)
    out = sibling(src, "No BG AI", ".png")
    out_im.save(out, "PNG")
    return out


def remove_background(src: str | Path, mode: str = "solid") -> Path:
    if mode == "ai":
        return remove_ai_background(src)
    return remove_solid_background(src)
