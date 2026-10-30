"""Serialize a single ComfyUI BHWC IMAGE for a multimodal HTTP request."""

import base64
from io import BytesIO

from .client import ExpansionError


def encode_image(image, max_side=1536):
    import numpy as np
    from PIL import Image

    # PyTorch is supplied by ComfyUI; import is deliberately not required for text-only use.
    if hasattr(image, "detach"):
        image = image.detach().cpu().float().numpy()
    array = np.asarray(image)
    if array.ndim != 4 or array.shape[0] != 1 or array.shape[-1] != 3:
        raise ExpansionError("参考图须为单张 ComfyUI IMAGE [1,H,W,3]；批量图片请先选择一张。")
    if min(array.shape[1:3]) < 1 or not np.isfinite(array).all():
        raise ExpansionError("参考图为空或包含无效像素。")
    if not isinstance(max_side, int) or not 256 <= max_side <= 4096:
        raise ExpansionError("图像最长边须在 256—4096 之间。")
    pixels = np.rint(np.clip(array[0], 0, 1) * 255).astype(np.uint8)
    pil = Image.fromarray(pixels)
    original = list(pil.size)
    pil.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    pil.save(buffer, format="JPEG", quality=92, subsampling=0)
    binary = buffer.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(binary).decode("ascii"), {
        "original_size": original, "sent_size": list(pil.size), "bytes": len(binary),
    }
