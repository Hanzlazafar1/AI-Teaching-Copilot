"""Conversation-spec schema + validator. Small on purpose — the value is a
check that rejects an under-specified conversation before it is driven."""

_AGENDA_KEYS = {"goal", "opening", "reactions", "done_when_turns"}


def validate(spec):
    errs = []
    if not spec.get("id"):
        errs.append("missing id")
    if spec.get("type") not in ("scripted", "dynamic"):
        errs.append("type must be 'scripted' or 'dynamic'")
    if not spec.get("covers"):
        errs.append("covers must be a non-empty list of requirement ids")
    if not spec.get("done_whens"):
        errs.append("done_whens must be a non-empty list (what the analyst checks)")
    if spec.get("type") == "scripted":
        if not spec.get("turns"):
            errs.append("scripted spec must have a non-empty 'turns' list")
    if spec.get("type") == "dynamic":
        agenda = spec.get("agenda")
        if not isinstance(agenda, dict):
            errs.append("dynamic spec must have an 'agenda' object")
        elif not _AGENDA_KEYS.issubset(agenda):
            errs.append(f"agenda missing keys: {_AGENDA_KEYS - set(agenda)}")
    return errs
