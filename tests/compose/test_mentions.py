"""@-mention grammar (spec 2.1) and pinning (spec 2.2): deterministic, never raises on user text."""

import pytest

from shilpa.compose import mentions as mp


def one(text):
    r = mp.parse(text)
    assert not r.errors, r.errors
    assert len(r.mentions) == 1, r.mentions
    return r.mentions[0]


@pytest.mark.parametrize("text, part, path", [
    ("@plate", "plate", ""),
    ("@plate.holes", "plate", "holes"),
    ("@plate.holes[*]", "plate", "holes[*]"),
    ("@bracket.hole[2]", "bracket", "holes[2]"),  # singular alias folds to the group
    ("@plate.face.top", "plate", "face.top"),
    ("@frame.edge.long[0]", "frame", "edge.long[0]"),
    ("@ISO4032-M6", "ISO4032-M6", ""),
    ("@ISO4762-M6x20", "ISO4762-M6x20", ""),
    ("@6204", "6204", ""),
    ("@shaft-20.axis.main", "shaft-20", "axis.main"),
    ("@shaft-20.face.end[0]", "shaft-20", "face.end[0]"),
    ("@plate.holes[1..3]", "plate", "holes[1..3]"),
    ("@plate.holes[first]", "plate", "holes[first]"),
    ("@plate.holes[last]", "plate", "holes[last]"),
])
def test_spec_examples(text, part, path):
    m = one(text)
    assert m.text == text and m.part.name == part and m.path_text == path


def test_instance_index_and_nesting():
    m = one("@bolt#2")
    assert m.part.name == "bolt" and m.part.index == 2
    m = one("@frame/left_rail.slot_1")
    assert [p.name for p in m.parts] == ["frame", "left_rail"] and m.path_text == "slot_1"


def test_filters():
    m = one("@plate.holes{diameter=6.4mm}")
    (p,) = m.filter
    assert (p.attr, p.op, p.value, p.unit) == ("diameter", "=", 6.4, "mm")
    m = one("@base.holes{on @base.face.top, kind=through}")
    assert [f.attr for f in m.filter] == ["on", "kind"]
    assert m.filter[0].on.text == "@base.face.top" and m.filter[1].value == "through"
    m = one("@plate.holes{diameter ≈ 6 mm and depth >= 5}")
    assert [(f.attr, f.op, f.value, f.unit) for f in m.filter] == [("diameter", "≈", 6.0, "mm"), ("depth", ">=", 5.0, None)]
    m = one("@plate.holes{diameter ~= 6.4 mm, thread = M6}")
    assert m.filter[0].op == "≈" and m.filter[1].value == "M6"
    m = one("@plate.holes{on .face.top}")
    assert m.filter[0].on_path[0].name == "face"


def test_mentions_in_prose():
    r = mp.parse("insert @ISO4032-M6 into every hole on @bracket where diameter = 6.4 mm.")
    assert [m.text for m in r.mentions] == ["@ISO4032-M6", "@bracket"] and not r.errors
    r = mp.parse("put @nema17 10 mm above @plate.face.top, centered")
    assert [m.text for m in r.mentions] == ["@nema17", "@plate.face.top"]
    r = mp.parse("sit it on @plate. Then stop")  # a sentence full stop ends the mention
    assert [m.text for m in r.mentions] == ["@plate"]
    r = mp.parse("(@plate) and @bracket- see")
    assert [m.text for m in r.mentions] == ["@plate", "@bracket"]
    r = mp.parse("mail dev@wayam.local about @plate")  # an e-mail address is not a mention
    assert [m.text for m in r.mentions] == ["@plate"]


@pytest.mark.parametrize("text", [
    "@", "@ ", "@@plate", "@.face", "@plate.holes[", "@plate.holes[x]", "@plate.holes[3..1]", "@plate.holes[99999999]",
    "@plate.holes{", "@plate.holes{diameter}", "@plate.holes{colour=red}", "@plate.holes{diameter=}", "@plate.holes{kind<3}",
    "@plate.holes{diameter=6 mm", "@bolt#0", "@bolt#", "@" + "a" * 65, "@plate{on @a{on @b{on @c{on @d{on @e}}}}}",
    "@plate.holes{on}", "@plate.holes{diameter=6,}",
])
def test_malformed_input_is_reported_not_raised(text):
    r = mp.parse(text)
    assert r.errors or not r.mentions or r.mentions[0].text != text
    with pytest.raises(ValueError):
        mp.parse_one(text)


@pytest.mark.parametrize("text", [
    "@../../etc/passwd", "@C:\\Windows\\system32", "@plate;DROP TABLE models;--", "@ignore_previous_instructions",
    "@plate<script>alert(1)</script>", "@plate.holes{diameter=6.4mm}}}}", "@\u202eetalp", "@plate\x00.face", "@pläte",
    "@" + "x" * 10_000, "@{}[]()", "@plate" * 200,
])
def test_injection_like_names_are_plain_data(text):
    r = mp.parse(text)  # never raises, never interprets anything
    for m in r.mentions:
        assert all(c.isascii() and (c.isalnum() or c in "_-") for p in m.parts for c in p.name)
        assert len(m.text) <= 300
    assert len(r.mentions) <= mp.MAX_MENTIONS


def test_mention_count_is_capped():
    r = mp.parse(" ".join(f"@p{i}" for i in range(40)))
    assert len(r.mentions) == mp.MAX_MENTIONS and r.errors


def test_identical_text_resolves_once():
    from shilpa.compose.resolve import Library, resolve_prompt

    res, errs = resolve_prompt("@nema17 and @nema17 again", Library(), {})
    assert len(res) == 1 and res[0].mention == "m1" and not errs


def test_pinning():
    pins = mp.pin_map([{"text": "@bracket.hole[2]", "ref": {"item": "M1", "version": "V3", "instance": "bracket",
                                                            "feature_uid": "holes.wall[2]", "path": "holes[2]"}}])
    assert pins["@bracket.hole[2]"].version == "V3"
    with pytest.raises(ValueError):
        mp.pin_map([{"text": "@bracket hole", "ref": {"item": "M1"}}])  # not one mention
    with pytest.raises(ValueError):
        mp.pin_map([{"text": "@bracket", "ref": {}}])  # names nothing
    with pytest.raises(ValueError):
        mp.pin_map([{"text": "@bracket", "ref": {"item": "M1", "evil": 1}}])  # unknown fields refused
