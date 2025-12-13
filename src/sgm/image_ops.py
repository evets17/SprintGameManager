from __future__ import annotations

from pathlib import Path

import qrcode
from PIL import Image

from sgm.config import Resolution


class ImageProcessError(RuntimeError):
    pass


def pil_from_qimage(qimage) -> Image.Image:
    # qimage is a PySide6.QtGui.QImage
    try:
        from PySide6.QtGui import QImage

        if not isinstance(qimage, QImage):
            raise ImageProcessError("Clipboard does not contain an image")

        img = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
        w = img.width()
        h = img.height()

        nbytes = int(img.sizeInBytes())
        buf = img.bits()

        raw: bytes
        if hasattr(buf, "setsize"):
            buf.setsize(nbytes)
            raw = bytes(buf)
        else:
            if hasattr(buf, "tobytes"):
                raw = buf.tobytes()
            else:
                raw = bytes(buf)
            if len(raw) != nbytes:
                try:
                    raw = bytes(buf[:nbytes])
                except Exception:
                    raw = raw[:nbytes]

        return Image.frombytes("RGBA", (w, h), raw)
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def build_overlay_png(
    blank_overlay_png: Path,
    bottom: Image.Image,
    dest: Path,
    *,
    overlay_resolution: Resolution,
    build_resolution: Resolution,
    position: tuple[int, int],
) -> None:
    try:
        ow, oh = overlay_resolution.width, overlay_resolution.height
        bw, bh = build_resolution.width, build_resolution.height

        if bw > ow or bh > oh:
            raise ImageProcessError(
                f"OverlayBuildResolution {bw}x{bh} exceeds OverlayResolution {ow}x{oh}"
            )

        x, y = position
        if x < 0 or y < 0 or (x + bw) > ow or (y + bh) > oh:
            raise ImageProcessError(
                f"OverlayBuildPosition {x},{y} places image outside overlay bounds"
            )

        with Image.open(blank_overlay_png) as top:
            top = top.convert("RGBA")
            if top.size != (ow, oh):
                top = top.resize((ow, oh), resample=Image.LANCZOS)

        bottom = bottom.convert("RGBA")
        if bottom.size != (bw, bh):
            bottom = bottom.resize((bw, bh), resample=Image.LANCZOS)

        canvas = Image.new("RGBA", (ow, oh), (0, 0, 0, 0))
        canvas.alpha_composite(bottom, dest=(x, y))
        canvas.alpha_composite(top, dest=(0, 0))

        _atomic_png_save(canvas, dest)
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def build_overlay_png_from_file(
    blank_overlay_png: Path,
    bottom_path: Path,
    dest: Path,
    *,
    overlay_resolution: Resolution,
    build_resolution: Resolution,
    position: tuple[int, int],
) -> None:
    try:
        with Image.open(bottom_path) as img:
            bottom = img.convert("RGBA")
        build_overlay_png(
            blank_overlay_png,
            bottom,
            dest,
            overlay_resolution=overlay_resolution,
            build_resolution=build_resolution,
            position=position,
        )
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def get_image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def save_png_resized_from_file(src: Path, dest: Path, *, expected: Resolution) -> None:
    try:
        with Image.open(src) as img:
            img = img.convert("RGBA")
            img = img.resize((expected.width, expected.height), resample=Image.LANCZOS)
            _atomic_png_save(img, dest)
    except Exception as e:
        raise ImageProcessError(str(e))


def save_png_preserve_ratio_centered_on_canvas_from_pil(
    img: Image.Image,
    dest: Path,
    *,
    expected: Resolution,
    canvas_png: Path,
) -> None:
    try:
        ow, oh = expected.width, expected.height

        if not canvas_png.exists():
            raise ImageProcessError(f"Missing canvas image: {canvas_png}")

        with Image.open(canvas_png) as canvas:
            canvas = canvas.convert("RGBA")
            if canvas.size != (ow, oh):
                canvas = canvas.resize((ow, oh), resample=Image.LANCZOS)

        img = img.convert("RGBA")
        iw, ih = img.size
        if iw <= 0 or ih <= 0:
            raise ImageProcessError("Invalid source image size")

        scale = min(ow / iw, oh / ih)
        nw = max(1, int(round(iw * scale)))
        nh = max(1, int(round(ih * scale)))
        fitted = img.resize((nw, nh), resample=Image.LANCZOS)

        x = int((ow - nw) / 2)
        y = int((oh - nh) / 2)

        out = canvas.copy()
        out.alpha_composite(fitted, dest=(x, y))
        _atomic_png_save(out, dest)
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def save_png_preserve_ratio_centered_on_canvas_from_file(
    src: Path,
    dest: Path,
    *,
    expected: Resolution,
    canvas_png: Path,
) -> None:
    try:
        with Image.open(src) as img:
            pil = img.convert("RGBA")
        save_png_preserve_ratio_centered_on_canvas_from_pil(pil, dest, expected=expected, canvas_png=canvas_png)
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def save_png_resized_from_pil(img: Image.Image, dest: Path, *, expected: Resolution) -> None:
    try:
        img = img.convert("RGBA")
        img = img.resize((expected.width, expected.height), resample=Image.LANCZOS)
        _atomic_png_save(img, dest)
    except Exception as e:
        raise ImageProcessError(str(e))


def save_png_resized_from_clipboard_qimage(qimage, dest: Path, *, expected: Resolution) -> None:
    # qimage is a PySide6.QtGui.QImage
    try:
        from PySide6.QtGui import QImage

        if not isinstance(qimage, QImage):
            raise ImageProcessError("Clipboard does not contain an image")

        img = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
        w = img.width()
        h = img.height()

        nbytes = int(img.sizeInBytes())
        buf = img.bits()

        raw: bytes
        if hasattr(buf, "setsize"):
            buf.setsize(nbytes)
            raw = bytes(buf)
        else:
            # PySide6 can return a memoryview-like object with no setsize/setview.
            if hasattr(buf, "tobytes"):
                raw = buf.tobytes()
            else:
                raw = bytes(buf)
            if len(raw) != nbytes:
                try:
                    raw = bytes(buf[:nbytes])
                except Exception:
                    raw = raw[:nbytes]

        pil = Image.frombytes("RGBA", (w, h), raw)
        save_png_resized_from_pil(pil, dest, expected=expected)
    except ImageProcessError:
        raise
    except Exception as e:
        raise ImageProcessError(str(e))


def generate_qr_png(url: str, dest: Path, *, expected: Resolution) -> None:
    try:
        qr_img = qrcode.make(url)
        if not isinstance(qr_img, Image.Image):
            qr_img = qr_img.get_image()
        save_png_resized_from_pil(qr_img, dest, expected=expected)
    except Exception as e:
        raise ImageProcessError(str(e))


def _atomic_png_save(img: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass
    img.save(tmp, format="PNG")
    tmp.replace(dest)
