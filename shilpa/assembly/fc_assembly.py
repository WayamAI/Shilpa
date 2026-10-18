# Runs inside FreeCADCmd (FreeCAD's own Python). Self-contained: no Shilpa imports.
#
# Builds a FreeCAD 1.x Assembly from a placed Shilpa assembly. Each unique part becomes a
# Part::Feature (part-local BREP) in a hidden "Parts" group; each instance is an App::Link
# to it inside the Assembly, carrying the world placement Shilpa computed. Mates become
# Assembly joints whose connectors (JCS) are set directly from the port frames, detached
# from sub-elements: JCS1 = P_a @ M on the first part, JCS2 = P_b on the second, so the
# FreeCAD solver's "make JCS1 and JCS2 coincide" reproduces Shilpa's placement. The script
# then solves and reports every link's placement so the caller can compare.
#
# Job file path comes from SHILPA_FC_JOB; results go to job["result"] as JSON.

import json
import os
import traceback

import FreeCAD as App
import Part

JOB = json.load(open(os.environ["SHILPA_FC_JOB"], encoding="utf-8"))
RESULT = {"ok": False, "joints": "none", "error": None, "placements": {}, "notes": []}
TYPES = {"fixed": "Fixed", "revolute": "Revolute", "cylindrical": "Cylindrical", "slider": "Slider", "ball": "Ball",
         "screw": "Screw"}


def placement(m):
    mat = App.Matrix(*[v for row in m for v in row])
    return App.Placement(mat)


def matrix(plc):
    m = plc.toMatrix()
    return [[m.A11, m.A12, m.A13, m.A14], [m.A21, m.A22, m.A23, m.A24], [m.A31, m.A32, m.A33, m.A34], [0, 0, 0, 1]]


def main():
    doc = App.newDocument("Assembly")
    parts = doc.addObject("App::DocumentObjectGroup", "Parts")
    features = {}
    for key, path in JOB["parts"].items():
        shape = Part.Shape()
        shape.read(path)
        f = doc.addObject("Part::Feature", key)
        f.Shape = shape
        f.Visibility = False
        parts.addObject(f)
        features[key] = f

    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    links = {}
    for inst in JOB["instances"]:
        link = asm.newObject("App::Link", inst["id"])
        link.LinkedObject = features[inst["part"]]
        link.Label = inst["id"]
        link.Placement = placement(inst["matrix"])
        links[inst["id"]] = link

    try:
        import JointObject
    except Exception as exc:  # Assembly workbench missing or unusable headless
        RESULT["notes"].append(f"JointObject unavailable: {exc}")
        JointObject = None

    if JointObject is not None and JOB.get("joints"):
        group = asm.newObject("Assembly::JointGroup", "Joints")
        if JOB.get("ground") in links:
            g = group.newObject("App::FeaturePython", "GroundedJoint")
            JointObject.GroundedJoint(g, links[JOB["ground"]])
        made, skipped = 0, []
        for j in JOB["joints"]:
            jtype = TYPES.get(j["type"])
            if jtype is None:
                skipped.append(j["name"])
                continue
            obj = group.newObject("App::FeaturePython", j["name"])
            JointObject.Joint(obj, JointObject.JointTypes.index(jtype))
            obj.Label = j["name"]
            a, b = links[j["a"]], links[j["b"]]
            # FreeCAD 1.1 references are rooted at the moving part; empty subs mean the whole part.
            obj.Reference1 = [a, ["", ""]]
            obj.Reference2 = [b, ["", ""]]
            obj.Detach1 = True
            obj.Detach2 = True
            obj.Placement1 = placement(j["jcs1"])
            obj.Placement2 = placement(j["jcs2"])
            lim = j.get("limits")
            if lim and j["type"] in ("revolute", "cylindrical") and hasattr(obj, "AngleMin"):
                obj.EnableAngleMin, obj.EnableAngleMax = True, True
                obj.AngleMin, obj.AngleMax = lim[0], lim[1]
            if lim and j["type"] == "slider" and hasattr(obj, "LengthMin"):
                obj.EnableLengthMin, obj.EnableLengthMax = True, True
                obj.LengthMin, obj.LengthMax = lim[0], lim[1]
            if j["type"] == "screw" and hasattr(obj, "ScrewThread"):
                obj.ScrewThread = j.get("pitch") or 1.0
            made += 1
        RESULT["joints"] = "all" if not skipped else "partial"
        RESULT["skipped_joints"] = skipped
        RESULT["joint_count"] = made
        if JOB.get("scramble"):
            # Shift every non-ground part before solving, so matching placements prove the joints work.
            for iid, link in links.items():
                if iid != JOB.get("ground"):
                    link.Placement = App.Placement(link.Placement.Base + App.Vector(*JOB["scramble"]), link.Placement.Rotation)
        doc.recompute()
        try:
            RESULT["solve"] = asm.solve()  # 0 on success
        except Exception as exc:
            RESULT["solve_error"] = str(exc)
    doc.recompute()
    RESULT["placements"] = {iid: matrix(link.Placement) for iid, link in links.items()}
    # Save Shilpa's assembled pose: a free joint may have settled elsewhere after the scramble.
    for inst in JOB["instances"]:
        links[inst["id"]].Placement = placement(inst["matrix"])
    doc.recompute()
    doc.saveAs(JOB["out_fcstd"])
    RESULT["freecad"] = ".".join(App.Version()[:3])
    RESULT["ok"] = True


try:
    main()
except Exception as exc:
    RESULT["error"] = {"message": str(exc), "trace": traceback.format_exc()[-2000:]}
finally:
    with open(JOB["result"], "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh)
