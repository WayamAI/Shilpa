"""Template products (roadmap stage S4): skeleton -> product tree -> assembly -> checks -> rollback router.

Entry point for the studio and scripts::

    from shilpa.product import run_product
    result = run_product("medium road bike for a 178 cm rider, 700c", "out/bike")
    result = run_product("4:1 gearbox, 20 Nm input at 1500 rpm", "out/gearbox")

``run_product(spec_or_request, out_dir, *, planner="offline", freecad=None, renders=True,
max_iter=4, steps=9, log=None) -> dict``

``spec_or_request`` is one of:

* request text: parsed by the rule-based ``parse_request_offline`` (default, no LLM) or, with
  ``planner="llm"``, by the structured-output product planner;
* a ``BicycleChoices`` or a choices dict (``{"use_case": "gravel", "wheel_size": "650b"}``);
* a ``GearboxChoices`` or a dict with ``product_class="gearbox"`` (``{"product_class": "gearbox",
  "ratio": 4, "input_torque_nm": 20}``);
* a ``ProductSpec`` or its JSON dict (``template`` and ``assembly`` keys), e.g. an edited spec.

``freecad=None`` exports ``assembly.FCStd`` only when FreeCAD is found (``tools/freecad`` or
``SHILPA_FREECAD_CMD``); ``True`` tries and reports the error, ``False`` skips it.

The result is JSON-serialisable (plain dicts, lists, numbers and strings):

* ``status``: ``passed`` (first build passed), ``repaired`` (the router fixed it), ``unresolved``
  (checks still fail; see ``router.unresolved``), ``unsupported`` (not a product a template makes)
  or ``rejected`` (the parsed choices failed validation). ``passed`` (bool) and ``message``.
* ``request``, ``product`` (name), ``template``, ``planner`` (parser / planner output or None).
* ``spec``: the final ``ProductSpec`` (requirements, skeleton with provenance, product tree,
  derived ``AssemblySpec``, targets, derived numbers, router ``history``).
* ``placements``: instance id -> 4x4 part-to-world matrix (mm), the solved assembly.
* ``bom``: one line per part number with quantity, make / buy / standard, tree node, standard,
  source, generator, mass and volume.
* ``checks``: the product report (``checks`` list with name, passed, actual, target, unit,
  severity, level, responsible, note), ``summary`` name -> pass / warn / FAIL, ``failed``,
  ``warnings``, the generic ``assembly`` report and ``timings_s``.
* ``router``: iterations (failed checks and actions each round), ``history`` (every change with
  old / new value, level, triggering check and reason), ``unresolved``, ``suggestions``.
* ``exports``: paths of ``step``, ``bom_csv``, ``bom_json``, ``product_bom_csv``,
  ``product_bom_json``, ``fcstd`` (when exported), ``spec_json``, ``report_json``.
* ``renders``: ``side`` and ``iso`` PNG paths. ``freecad``: the FreeCAD export result or None.
* ``timings_s``: plan, build-check-route, exports, renders, FreeCAD, total.

The same dict is written to ``out_dir/report.json``.
"""

from __future__ import annotations


def run_product(spec_or_request, out_dir, **kwargs) -> dict:
    """See the module docstring. Imported lazily so ``shilpa.product`` stays light to import."""
    from .run import run_product as _run

    return _run(spec_or_request, out_dir, **kwargs)


__all__ = ["run_product"]
