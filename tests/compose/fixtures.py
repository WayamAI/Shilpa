"""Fixture library for the composition tests (spec section 7).

``@plate``: 200 x 120 x 10 mm, 4 x Ø6.4 through holes at the corners plus 2 x Ø8.4.
``@bracket``: a flat 80 x 40 x 5 mm bracket with 4 x Ø6.4 holes (the spec's L-bracket, simplified).
Catalog parts come from the real catalog: ``@ISO4032-M6``, ``@6204``, ``@shaft-20``, ``@nema17``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

PLATE = {
    "name": "plate",
    "parameters": {"w": 200, "h": 120, "t": 10, "d6": 6.4, "d8": 8.4, "e": 10, "zero": 0, "px": 100},
    "features": [
        {"id": "plate_profile", "op": "centered_rectangle", "plane": "XY", "width_ref": "w", "height_ref": "h"},
        {"id": "plate", "op": "extrude", "profile_ref": "plate_profile", "distance_ref": "t", "direction": "positive_z"},
        {"id": "corner", "op": "corner_hole_pattern", "body_ref": "plate", "diameter_ref": "d6", "edge_offset_ref": "e"},
        {"id": "mid", "op": "linear_hole_pattern", "body_ref": "corner", "diameter_ref": "d8", "count_x_ref": "2",
         "count_y_ref": "1", "pitch_x_ref": "px", "pitch_y_ref": "zero"},
    ],
}

BRACKET = {
    "name": "bracket",
    "parameters": {"w": 80, "h": 40, "t": 5, "d": 6.4, "e": 8},
    "features": [
        {"id": "p", "op": "centered_rectangle", "plane": "XY", "width_ref": "w", "height_ref": "h"},
        {"id": "base", "op": "extrude", "profile_ref": "p", "distance_ref": "t", "direction": "positive_z"},
        {"id": "holes", "op": "corner_hole_pattern", "body_ref": "base", "diameter_ref": "d", "edge_offset_ref": "e"},
    ],
}


def ref(text: str, mention: str, **sel) -> dict:
    out = {"text": text, "mention": mention}
    if sel:
        out["selector"] = sel
    return out


def qty(value, unit="mm", as_typed=None) -> dict:
    return {"value": value, "unit": unit, "as_typed": as_typed or f"{value:g} {unit}", "provenance": "user"}


# What a well-behaved composer returns for each worked example (mention ids follow first use in the prompt).
E1 = ("use @plate as the base",
      [{"id": "s1", "op": "add", "source": ref("@plate", "m1")}, {"id": "s2", "op": "ground", "source": ref("@plate", "m1")}])
E2 = ("put @nema17 10 mm above @plate.face.top, centered",
      [{"id": "s1", "op": "place", "source": ref("@nema17", "m1"), "target": ref("@plate.face.top", "m2"), "anchor": "center",
        "offset": {"distance": qty(10), "direction": {"normal_of": ref("@plate.face.top", "m2")}}}])
E3 = ("@bracket 10 m away from @plate",
      [{"id": "s1", "op": "place", "source": ref("@bracket", "m1"), "target": ref("@plate", "m2"),
        "offset": {"distance": qty(10, "m"), "direction": {"away_from": ref("@plate", "m2")}}}])
E4 = ("wherever there are holes on @plate, put @ISO4032-M6 inside",
      [{"id": "s1", "op": "insert", "source": ref("@ISO4032-M6", "m2"), "target": ref("@plate", "m1", path="holes[*]"),
        "seat": "exit", "assumptions": [{"field": "target.selector.path", "value": "holes[*]",
                                         "reason": "'wherever there are holes' means every hole"}]}])
E6_BASE = ("use @shaft-20 as the base",
           [{"id": "s1", "op": "add", "source": ref("@shaft-20", "m1")}, {"id": "s2", "op": "ground", "source": ref("@shaft-20", "m1")}])
E6 = ("@6204 coaxial with @shaft-20.axis.main, 15 mm from @shaft-20.face.end[0]",
      [{"id": "s1", "op": "mate", "source": ref("@6204", "m1"), "target": ref("@shaft-20.axis.main", "m2"),
        "mate": {"kind": "coaxial"}, "offset": {"distance": qty(15), "from": ref("@shaft-20.face.end[0]", "m3")}}])


class FakeComposer:
    """A fake model client: replies with queued steps, records requests. Never leaves the process."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        steps = self.replies.pop(0)
        msg = SimpleNamespace(content=json.dumps({"steps": steps}), refusal=None)
        usage = SimpleNamespace(prompt_tokens=900, completion_tokens=150, prompt_tokens_details=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=usage, model=kw["model"] or "fake")


class ExplodingClient:
    """Any model call fails the test: proves a path is LLM-free."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        raise AssertionError("a model call was made on a path that must be LLM-free")
