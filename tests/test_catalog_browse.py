"""Catalog browsing API: listing, one-part previews and STEP downloads."""

import base64

import numpy as np
from fastapi.testclient import TestClient

from shilpa.api.app import app

H = {"Authorization": "Bearer dev:dev@wayam.local"}


def client() -> TestClient:
    return TestClient(app)


def test_catalog_lists_families_and_schemas():
    with client() as c:
        d = c.get("/v1/catalog", headers=H).json()
    fams = {g["family"] for g in d["generators"]}
    assert {"Gears", "V-slot extrusion", "Bicycle parts", "Screws", "Nuts", "Washers", "Bearings"} <= fams
    assert "Other" not in fams
    spur = next(g for g in d["generators"] if g["name"] == "gear.spur")
    assert spur["params"]["properties"]["teeth"]["minimum"] == 10


def test_preview_returns_mesh_ports_and_meta():
    with client() as c:
        r = c.post("/v1/catalog/preview", json={"generator": "vslot.rail", "params": {"profile": "2040", "length": 120}},
                   headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["size"] == [40.0, 20.0, 120.0] and d["family"] == "V-slot extrusion"
    pos = np.frombuffer(base64.b64decode(d["mesh"]["positions"]), dtype=np.float32).reshape(-1, 3)
    idx = np.frombuffer(base64.b64decode(d["mesh"]["indices"]), dtype=np.uint32)
    assert len(pos) == d["mesh"]["vertices"] and len(idx) == 3 * d["mesh"]["triangles"] and idx.max() < len(pos)
    assert all(p["on_geometry"] for p in d["ports"])
    assert {p["kind"] for p in d["ports"]} == {"face", "axis", "point"}
    assert d["meta"]["designation"] == "V-slot 2040 x 120 mm" and d["meta"]["mass_g"] > 0


def test_preview_rejects_bad_params_with_the_reason():
    with client() as c:
        r = c.post("/v1/catalog/preview", json={"generator": "gear.spur", "params": {"teeth": 12, "module": 1,
                                                                                     "bore_d": 9}}, headers=H)
        assert r.status_code == 422 and r.json()["code"] == "invalid_parameter"
        assert "web" in r.json()["message"]
        r = c.post("/v1/catalog/preview", json={"generator": "gear.nope"}, headers=H)
        assert r.status_code == 422 and r.json()["code"] == "unsupported_operation"


def test_step_download():
    with client() as c:
        r = c.post("/v1/catalog/step", json={"generator": "deep_groove_ball_bearing", "params": {"designation": "6204"}},
                   headers=H)
    assert r.status_code == 200 and r.content.startswith(b"ISO-10303-21")
    assert r.headers["content-disposition"].endswith('6204.step"')


def test_lookup_endpoint_and_hidden_generators():
    with client() as c:
        r = c.get("/v1/catalog/lookup", params={"q": "M6x20 socket head"}, headers=H).json()
        assert r["matches"][0]["generator"] == "screw.socket_head" and r["matches"][0]["label"] == "ISO 4762 M6-1 x 20"
        assert c.get("/v1/catalog/lookup", params={"q": ""}, headers=H).json()["matches"] == []
        names = {g["name"] for g in c.get("/v1/catalog", headers=H).json()["generators"]}
        # The template set stays resolvable but is not offered when browsing.
        assert "iso4762_socket_head_cap_screw" not in names and "screw.socket_head" in names
        assert c.post("/v1/catalog/preview", json={"generator": "iso4762_socket_head_cap_screw"}, headers=H).status_code == 200
