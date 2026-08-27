"""Reject an under-specified conversation brief before it is driven. Mirrors the
base campaign/dogfood/schema.py but (a) adds 'edges' to the dynamic agenda,
(b) requires done_whens to be {target_id, text} objects, and (c) cross-checks
covers + done_when target_ids against the known target universe when given."""

_AGENDA_KEYS = {"goal", "opening", "reactions", "edges", "done_when_turns"}


def validate(spec, target_ids=None):
    errs = []
    if not spec.get("id"):
        errs.append("missing id")
    if spec.get("type") not in ("dynamic", "scripted"):
        errs.append("type must be 'dynamic' or 'scripted'")

    covers = spec.get("covers")
    if not covers:
        errs.append("covers must be a non-empty list of target ids")
    elif target_ids is not None:
        unknown = [c for c in covers if c not in target_ids]
        if unknown:
            errs.append(f"covers references unknown targets: {unknown}")

    dws = spec.get("done_whens")
    if not dws:
        errs.append("done_whens must be a non-empty list")
    else:
        for i, dw in enumerate(dws):
            if not isinstance(dw, dict) or "target_id" not in dw or "text" not in dw:
                errs.append(f"done_whens[{i}] must be an object with target_id + text")
            elif target_ids is not None and dw["target_id"] not in target_ids:
                errs.append(f"done_whens[{i}].target_id unknown: {dw['target_id']}")

    if spec.get("type") == "dynamic":
        agenda = spec.get("agenda")
        if not isinstance(agenda, dict):
            errs.append("dynamic spec must have an 'agenda' object")
        elif not _AGENDA_KEYS.issubset(agenda):
            errs.append(f"agenda missing keys: {_AGENDA_KEYS - set(agenda)}")
    if spec.get("type") == "scripted" and not spec.get("turns"):
        errs.append("scripted spec must have a non-empty 'turns' list")
    return errs
