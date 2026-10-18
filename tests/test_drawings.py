"""Drawing intake without the model: untrusted-file handling, provenance, consistency, review (T057-T059, T063-T067)."""

import json
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from shilpa.api.app import app
from shilpa.drawings.extract import confirm, consistency, postprocess, to_requirements
from shilpa.drawings.ingest import Rejected, ingest

DRAWINGS = Path(__file__).resolve().parents[1] / "evals" / "drawings"
DEV = {"Authorization": "Bearer dev:dev@wayam.local"}
VIEWER = {"Authorization": "Bearer dev:viewer@wayam.local"}
OTHER = {"Authorization": "Bearer dev:other@example.com"}


def _pdf(tmp_path, name="d.pdf", js=False, pages=1, encrypt=False) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), "4X Ø6 THRU", fontsize=12)
    path = tmp_path / name
    if js:
        doc.set_xml_metadata("")
        xref = doc.get_new_xref()
        doc.update_object(xref, "<< /S /JavaScript /JS (app.alert(1)) >>")
        doc.xref_set_key(doc.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    kw = dict(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y") if encrypt else {}
    doc.save(path, **kw)
    return path


def test_ingest_vector_drawing_text_layer(tmp_path):
    r = ingest(DRAWINGS / "F01_vector.pdf", tmp_path)
    assert r["ok"] and r["has_text_layer"] and r["media_type"] == "application/pdf"
    texts = [s["text"] for s in r["pages"][0]["spans"]]
    assert "4X Ø10 THRU EQ SP ON Ø70 PCD" in texts  # Unicode symbol and whitespace normalised
    assert (tmp_path / "page-1.png").exists()


def test_ingest_scan_has_no_text_layer(tmp_path):
    r = ingest(DRAWINGS / "F01_scan.pdf", tmp_path)
    assert r["ok"] and not r["has_text_layer"]


@pytest.mark.parametrize("kind", ["js", "encrypted", "pages", "type"])
def test_ingest_rejects_unsafe_inputs(tmp_path, kind):  # T057-T059
    if kind == "js":
        src = _pdf(tmp_path, js=True)
    elif kind == "encrypted":
        src = _pdf(tmp_path, encrypt=True)
    elif kind == "pages":
        src = _pdf(tmp_path, pages=11)
    else:
        src = tmp_path / "x.pdf"
        src.write_bytes(b"MZ\x90\x00 not a drawing")
    with pytest.raises(Rejected):
        ingest(src, tmp_path / "out")


def _extraction(dims, conflicts=None):
    return {"task_class": "engineering_cad", "family": "flange", "summary": "flange",
            "title_block": {"units": "mm", "scale": "1:1", "part_name": "FLANGE", "general_tolerance": "±0.1"},
            "views": ["front", "side"], "dimensions": dims, "features": [], "assumptions": [], "missing": [],
            "conflicts": conflicts or [], "notes": [], "ignored_instructions": [], "unsupported_reason": None}


def _dim(name, value, text, span_ids, kind="length"):
    return {"name": name, "value": value, "unit": "mm" if kind == "length" else None, "kind": kind, "critical": True,
            "meaning": name, "original_text": text, "span_ids": span_ids, "page": 1, "bbox": None, "view": None, "confidence": "high"}


INGESTED = {"has_text_layer": True, "pages": [{"number": 1, "spans": [
    {"id": 0, "text": "Ø100", "bbox": [0.1, 0.1, 0.2, 0.12]},
    {"id": 1, "text": "4X Ø10 THRU EQ SP ON Ø70 PCD", "bbox": [0.3, 0.1, 0.6, 0.12]},
    {"id": 2, "text": "12", "bbox": [0.7, 0.5, 0.72, 0.52]},
    {"id": 3, "text": "±0.1", "bbox": [0.8, 0.9, 0.85, 0.92]}]}]}


def test_provenance_verifies_against_text_layer():
    ex = postprocess(_extraction([
        _dim("outer_diameter", 100, "Ø100", [0]),
        _dim("bolt_count", 4, "4X", [1], kind="count"),
        _dim("bolt_circle_diameter", 70, "Ø70 PCD", [1]),
        _dim("thickness", 21, "12", [2]),            # misread: the text layer says 12
        _dim("general_tolerance", 0.1, "±0.1", [3]),  # title-block value, not geometry
    ]), INGESTED)
    by = {d["name"]: d for d in ex["dimensions"]}
    assert by["outer_diameter"]["verified"] and by["outer_diameter"]["bbox"] == [0.1, 0.1, 0.2, 0.12]
    assert by["bolt_count"]["verified"] and by["bolt_circle_diameter"]["verified"]
    assert by["thickness"]["verified"] is False and by["thickness"]["confidence"] == "low"
    assert "general_tolerance" not in by


def test_consistency_graph():
    ex = _extraction([_dim("outer_diameter", 100, "", []), _dim("bolt_circle_diameter", 120, "", []),
                      _dim("width", 80, "", []), _dim("width", 85, "", [])])
    msgs = consistency(ex)
    assert any("bolt circle" in m for m in msgs) and any("width is given as 80, 85" in m for m in msgs)


def test_drawing_requires_review_then_confirm():
    req = to_requirements(postprocess(_extraction([_dim("outer_diameter", 100, "Ø100", [0]), _dim("thickness", 12, "12", [2])]), INGESTED))
    assert req["status"] == "needs_review" and req["source"] == "drawing"
    done = confirm(req, {"thickness": 15})
    assert done["status"] == "ready"
    assert {d["name"]: d["value"] for d in done["dimensions"]}["thickness"] == 15
    assert {d["name"]: d["review"] for d in done["drawing"]["dimensions"]} == {"outer_diameter": "confirmed", "thickness": "edited"}


def test_upload_endpoint_quarantine_and_isolation():
    with TestClient(app) as c:
        project = c.post("/v1/projects", json={"name": "drawings"}, headers=DEV).json()["id"]
        pdf = (DRAWINGS / "P01_vector.pdf").read_bytes()
        r = c.post(f"/v1/projects/{project}/uploads", files={"file": ("../../evil name.pdf", pdf, "application/pdf")}, headers=DEV)
        assert r.status_code == 201, r.text
        up = r.json()
        assert up["state"] == "ready" and up["has_text_layer"] and ".." not in up["filename"]
        assert c.get(f"/v1/uploads/{up['id']}/pages/1", headers=DEV).headers["content-type"] == "image/png"
        assert c.get(f"/v1/uploads/{up['id']}", headers=OTHER).status_code == 404
        assert c.get(f"/v1/uploads/{up['id']}/pages/1", headers=OTHER).status_code == 404
        bad = c.post(f"/v1/projects/{project}/uploads", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}, headers=DEV)
        assert bad.status_code == 422 and bad.json()["code"] == "upload_rejected"
        assert c.post(f"/v1/projects/{project}/uploads", files={"file": ("d.pdf", pdf, "application/pdf")}, headers=VIEWER).status_code == 403
