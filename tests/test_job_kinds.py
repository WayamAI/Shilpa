"""Assembly, sheet-metal and product jobs through the API, queue, coordinator and CAD worker (no LLM).

Assembly jobs publish a version even when design checks fail (an interference is a
finding the engineer must see), with every check tied to the instances it involves.
"""

import base64
import copy
import csv
import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from shilpa.api.app import app
from shilpa.api.starters import assembly_starters, sheet_metal_starters
from shilpa.assembly.build import build_assembly
from shilpa.workers import kinds

from .test_workflow import DEV, OTHER, VIEWER, pump

GOLDEN = {s["id"]: s for s in assembly_starters()}
SHEET = {s["id"]: s for s in sheet_metal_starters()}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def project(client):
    r = client.post("/v1/projects", json={"name": "Job kinds"}, headers=DEV)
    return r.json()["id"]


def run_assembly(client, project, name, **kw):
    r = client.post(f"/v1/projects/{project}/assemblies", json={"spec": GOLDEN[name]["spec"], "starter": name, **kw}, headers=DEV)
    assert r.status_code == 202, r.text
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    return client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()


def artifact(client, version, fmt):
    a = next(a for a in version["artifacts"] if a["format"] == fmt)
    r = client.get(f"/v1/artifacts/{a['id']}/download", headers=DEV)
    assert r.status_code == 200
    return r


def test_starters_listed(client):
    r = client.get("/v1/starters", headers=DEV).json()
    assert len(r["assemblies"]) == 10 and {"hinge", "interfering", "lid_hits_wall"} <= {a["id"] for a in r["assemblies"]}
    assert len(r["sheet_metal"]) >= 4
    assert r["products_available"] is (kinds.product_runner() is not None)
    assert client.get("/v1/starters").status_code == 401


def test_hinge_assembly_job(client, project):
    v = run_assembly(client, project, "hinge")
    assert v["kind"] == "assembly" and v["validation_passed"] and v["validation_state"] == "geometry_validated"
    formats = {a["format"] for a in v["artifacts"]}
    assert {"STEP", "BOM_CSV", "BOM_JSON", "PLACEMENTS", "MESHES", "VIEWER", "VALIDATION", "RECIPE"} <= formats
    viewer = v["viewer"]
    assert [i["id"] for i in viewer["instances"]] == ["base", "pin", "lid"]
    assert viewer["instances"][2]["color"] == "#ffa500"  # orange, carried from the spec
    assert viewer["dof"]["computed"] == 1
    names = {c["name"] for c in viewer["checks"]}
    assert {"interference", "dof", "sweep[hinge]", "clearance[lid+pin]"} <= names
    assert all(c["passed"] for c in viewer["checks"])
    (joint,) = viewer["joints"]
    assert joint["name"] == "hinge" and joint["moving"] == ["lid"] and joint["limits"] == [0, 100]

    # STEP keeps one labelled child per instance; the BOM has one line per part.
    step = artifact(client, v, "STEP")
    assert step.headers["content-disposition"].endswith('.step"') and b"lid" in step.content
    rows = list(csv.DictReader(io.StringIO(artifact(client, v, "BOM_CSV").text)))
    assert sorted(r["part_number"] for r in rows) == ["base", "lid", "pin"]

    # Per-instance meshes decode to finite triangles in part-local coordinates.
    meshes = artifact(client, v, "MESHES").json()["parts"]
    lid = meshes["lid"]
    pos = np.frombuffer(base64.b64decode(lid["positions"]), dtype=np.float32).reshape(-1, 3)
    idx = np.frombuffer(base64.b64decode(lid["indices"]), dtype=np.uint32)
    assert len(idx) % 3 == 0 and idx.max() < len(pos)
    assert np.allclose(pos.min(axis=0), [-30, -20, 0], atol=1e-3) and np.allclose(pos.max(axis=0), [30, 20, 3], atol=1e-3)

    # Tenant isolation holds for the new artifacts too.
    a = next(a for a in v["artifacts"] if a["format"] == "MESHES")
    assert client.get(f"/v1/artifacts/{a['id']}/download", headers=OTHER).status_code == 404


def test_interfering_assembly_publishes_findings(client, project):
    v = run_assembly(client, project, "interfering")
    assert v["validation_passed"] is False and v["validation_state"] == "checks_failed"
    failed = {c["name"]: c for c in v["viewer"]["checks"] if not c["passed"]}
    assert set(failed) == {"interference[block+plate]", "interference"}
    assert sorted(failed["interference[block+plate]"]["instances"]) == ["block", "plate"]
    assert failed["interference[block+plate]"]["actual"] == pytest.approx(800, rel=1e-6)


def test_sweep_failure_names_the_wall(client, project):
    v = run_assembly(client, project, "lid_hits_wall")
    (sweep,) = [c for c in v["viewer"]["checks"] if not c["passed"]]
    assert sweep["name"] == "sweep[hinge]" and {"lid", "wall"} <= set(sweep["instances"])


@pytest.mark.parametrize("name", ["slider_rail", "hinge", "shaft_bearings"])
def test_joint_frames_reproduce_pose(name):
    """The studio scrubs joints with J @ motion @ inv(J); it must equal re-placing the assembly."""
    for reverse in (False, True):
        spec = copy.deepcopy(GOLDEN[name]["spec"])
        if reverse:  # place the joint from the child side: the moving side becomes mate.a
            for m in spec["mates"]:
                if m["type"] != "fixed":
                    m["a"], m["b"] = m["b"], m["a"]
        build = build_assembly(spec)
        for j in kinds.joint_frames(build):
            for value in (j["limits"][0], j["limits"][1], sum(j["limits"]) / 2):
                T = build.pose({j["name"]: {j["param"]: value}})
                W = kinds.joint_motion(j, value)
                for mv in j["moving"]:
                    assert np.abs(W @ build.matrices[mv] - T[mv]).max() < 1e-9


def test_floating_part_is_reported(client, project):
    v = run_assembly(client, project, "floating")
    failed = {c["name"]: c for c in v["viewer"]["checks"] if not c["passed"]}
    assert set(failed) == {"spec_valid", "all_placed"}
    assert "spare" in failed["all_placed"]["instances"]
    spare = next(i for i in v["viewer"]["instances"] if i["id"] == "spare")
    assert spare["placed"] is False and spare["matrix"] is None


def test_invalid_assembly_rejected_before_job(client, project):
    bad = copy.deepcopy(GOLDEN["hinge"]["spec"])
    bad["instances"][0]["id"] = "Bad Id"
    r = client.post(f"/v1/projects/{project}/assemblies", json={"spec": bad}, headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "invalid_schema"
    assert client.post(f"/v1/projects/{project}/assemblies", json={"spec": GOLDEN["hinge"]["spec"]}, headers=VIEWER).status_code == 403


def test_assembly_restore_and_no_param_edits(client, project):
    v1 = run_assembly(client, project, "standoff_stack")
    r = client.post(f"/v1/models/{v1['model_id']}/edits", json={"base_version_id": v1["id"], "parameters": {"w": 90}}, headers=DEV)
    assert r.status_code == 422 and r.json()["code"] == "unsupported_operation"
    r = client.post(f"/v1/models/{v1['model_id']}/edits", json={"base_version_id": v1["id"], "restore_version_id": v1["id"]}, headers=DEV)
    assert r.status_code == 202, r.text
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    v2 = client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()
    assert v2["number"] == 2 and v2["kind"] == "assembly" and v2["recipe_hash"] == v1["recipe_hash"]


def test_sheet_metal_job(client, project):
    r = client.post(f"/v1/projects/{project}/sheet-metal", json={"spec": SHEET["l_bracket"]["spec"], "starter": "l_bracket"}, headers=DEV)
    assert r.status_code == 202, r.text
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    v = client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()
    assert v["kind"] == "sheet_metal" and v["validation_passed"]
    assert {"STEP", "DXF", "MESHES", "VIEWER", "VALIDATION", "RECIPE"} <= {a["format"] for a in v["artifacts"]}
    flat = v["viewer"]["flat"]
    # Flat length = depth + BA + leg - (R + T) with DIN 6935 K: same oracle as the sheet-metal suite.
    assert flat["size"][0] == pytest.approx(100) and len(flat["bends"]) == 1
    assert sum(lp["outer"] for lp in flat["loops"]) == 1 and len(flat["loops"]) == 3  # outline + two holes
    assert v["viewer"]["bend_table"][0]["id"] == "leg"
    dxf = artifact(client, v, "DXF")
    assert dxf.headers["content-disposition"].endswith('_flat.dxf"') and b"BEND" in dxf.content


def test_sheet_metal_rule_violation_is_a_finding(client, project):
    r = client.post(f"/v1/projects/{project}/sheet-metal", json={"spec": SHEET["hole_near_bend"]["spec"]}, headers=DEV)
    job = pump(client, r.json()["id"])
    assert job["state"] == "succeeded", job["error"]
    v = client.get(f"/v1/versions/{job['result_version_id']}", headers=DEV).json()
    assert not v["validation_passed"]
    assert {c["name"].split(":")[0] for c in v["viewer"]["checks"] if not c["passed"]} == {"hole_to_bend"}


def test_sheet_metal_examples_match_expectations():
    for s in sheet_metal_starters():
        from shilpa.sheetmetal import SheetMetalSpec, build
        from shilpa.sheetmetal.checks import check

        report = check(build(SheetMetalSpec.model_validate(s["spec"])))
        assert report.passed is s["expected"]["passed"], (s["id"], report.failed)


def test_product_job_without_templates(client, project, monkeypatch):
    monkeypatch.setattr(kinds, "product_runner", lambda: None)
    r = client.post(f"/v1/projects/{project}/products", json={"request": "a road bike for a 180 cm rider"}, headers=DEV)
    assert r.status_code == 501 and r.json()["code"] == "product_templates_not_installed"
    assert "not installed" in r.json()["message"]


def test_product_job_with_a_runner(client, project, monkeypatch, tmp_path):
    """Once shilpa.product.run_product exists, a product job publishes its assembly like an assembly job."""
    def fake_run_product(spec_or_request, out_dir):
        build = build_assembly(GOLDEN["slider_rail"]["spec"])
        return {"ok": True, "request": spec_or_request, "build": build,
                "report": {"checks": [{"name": "frame_fit", "passed": True, "note": "fits"}]}}

    monkeypatch.setattr(kinds, "product_runner", lambda: fake_run_product)
    r = client.post(f"/v1/projects/{project}/products", json={"request": "slider product"}, headers=DEV)
    assert r.status_code == 202, r.text
    # The geometry runs in a subprocess that cannot see the monkeypatch, so execute in-process here.
    res = kinds.execute_product({"request": "slider product"}, tmp_path)
    assert res["ok"] and res["validation"]["passed"]
    viewer = json.loads((tmp_path / "viewer.json").read_text())
    assert viewer["kind"] == "product" and any(c["name"] == "product[frame_fit]" for c in viewer["checks"])
    assert (tmp_path / "product.json").exists() and (tmp_path / "assembly.step").exists()
    client.post(f"/v1/jobs/{r.json()['id']}/cancel", headers=DEV)


def test_execute_product_reports_missing_templates(tmp_path, monkeypatch):
    monkeypatch.setattr(kinds, "product_runner", lambda: None)
    res = kinds.execute_product({"request": "bike"}, tmp_path)
    assert not res["ok"] and res["error"]["code"] == "unsupported_operation" and "not installed" in res["error"]["message"]


@pytest.mark.skipif(not __import__("shilpa.adapters.freecad_adapter", fromlist=["available"]).available(), reason="FreeCAD not installed")
def test_assembly_freecad_export(client, project):
    v = run_assembly(client, project, "hinge")
    e = client.post(f"/v1/versions/{v['id']}/exports", json={"format": "FCSTD"}, headers=DEV)
    assert e.status_code == 202, e.text
    job = pump(client, e.json()["job"]["id"], limit=120)
    assert job["state"] == "succeeded", job["error"]
    v2 = client.get(f"/v1/versions/{v['id']}", headers=DEV).json()
    assert artifact(client, v2, "FCSTD").content[:2] == b"PK"
