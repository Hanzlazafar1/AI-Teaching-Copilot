"""Validate the recert target list. Small on purpose — it makes 'a target has
no yardstick' or 'the id universe drifted' impossible to miss before a drive."""


def validate(targets):
    if not isinstance(targets, list) or not targets:
        return ["targets must be a non-empty list"]
    errs, seen = [], set()
    for t in targets:
        tid = t.get("id")
        if not tid:
            errs.append("target missing id")
        elif tid in seen:
            errs.append(f"duplicate target id {tid}")
        else:
            seen.add(tid)
        for field in ("requirement", "done_when", "source"):
            if not t.get(field):
                errs.append(f"target {tid} missing {field}")
    return errs


def target_ids(targets):
    return [t["id"] for t in targets]
