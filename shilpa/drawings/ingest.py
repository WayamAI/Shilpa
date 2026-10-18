"""Untrusted drawing intake: validate, render pages and extract the text layer (blueprint sections 11, 17).

Runs in its own process (``python -m shilpa.drawings.ingest <file> <out_dir>``) with a scrubbed
environment, so a hostile PDF never runs next to credentials. Rejects encrypted files, scripts,
launch actions, embedded files, oversized pages and decompression bombs before any model sees them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 10
MAX_PAGE_SIDE_PT = 2000 * 72 / 25.4  # 2 m: larger is not a drawing sheet
RENDER_LONG_SIDE_PX = 2200
MAX_IMAGE_PIXELS = 40_000_000
FORBIDDEN_PDF_KEYS = ("/JavaScript", "/JS", "/Launch", "/EmbeddedFile", "/RichMedia", "/XFA")


class Rejected(Exception):
    pass


def sniff(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise Rejected("unsupported file type; upload a PDF, PNG or JPEG drawing")


def _check_pdf(doc) -> None:
    if doc.needs_pass or doc.is_encrypted:
        raise Rejected("encrypted PDFs are not accepted")
    if doc.page_count == 0:
        raise Rejected("the PDF has no pages")
    if doc.page_count > MAX_PAGES:
        raise Rejected(f"the PDF has {doc.page_count} pages; the limit is {MAX_PAGES}")
    if doc.embfile_count() > 0:
        raise Rejected("PDFs with embedded files are not accepted")
    for xref in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(xref, compressed=True)
        except Exception:
            continue
        for key in FORBIDDEN_PDF_KEYS:
            if key + " " in obj or key + "/" in obj or key + "<" in obj or key + "(" in obj or obj.rstrip().endswith(key):
                raise Rejected(f"PDFs containing {key[1:]} are not accepted")
    for page in doc:
        if max(page.rect.width, page.rect.height) > MAX_PAGE_SIDE_PT:
            raise Rejected("page size exceeds the drawing sheet limit")


def ingest(src: Path, out: Path) -> dict:
    import pymupdf

    data = src.read_bytes()
    if len(data) > MAX_BYTES:
        raise Rejected(f"file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    media = sniff(data)
    out.mkdir(parents=True, exist_ok=True)
    if media == "application/pdf":
        doc = pymupdf.open(stream=data, filetype="pdf")
        _check_pdf(doc)
    else:
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        import io

        with Image.open(io.BytesIO(data)) as im:
            im.verify()  # raises on truncated or bomb images
        img = pymupdf.open(stream=data, filetype=media.split("/")[1])
        doc = pymupdf.open("pdf", img.convert_to_pdf())

    pages = []
    has_text = False
    for i, page in enumerate(doc):
        w, h = page.rect.width, page.rect.height
        zoom = RENDER_LONG_SIDE_PX / max(w, h)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
        png = out / f"page-{i + 1}.png"
        pix.save(png)
        spans = []
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for sp in line.get("spans", []):
                    # Normalise PDF whitespace (non-breaking and other Unicode spaces are common in CAD exports).
                    text = " ".join(sp.get("text", "").replace(" ", " ").split())
                    if not text:
                        continue
                    x0, y0, x1, y1 = sp["bbox"]
                    spans.append({"id": len(spans), "text": text[:200],
                                  "bbox": [round(x0 / w, 5), round(y0 / h, 5), round(x1 / w, 5), round(y1 / h, 5)]})
        has_text = has_text or bool(spans)
        pages.append({"number": i + 1, "image": png.name, "width_px": pix.width, "height_px": pix.height,
                      "width_mm": round(w * 25.4 / 72, 1), "height_mm": round(h * 25.4 / 72, 1), "spans": spans[:2000]})
    return {"ok": True, "media_type": media, "pages": pages, "has_text_layer": has_text}


def main() -> int:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    try:
        result = ingest(src, out)
    except Rejected as exc:
        result = {"ok": False, "error": str(exc)}
    except Exception as exc:  # malformed input: report, never crash the caller
        result = {"ok": False, "error": f"could not read the file: {type(exc).__name__}"}
    (out / "ingest.json").write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
