"""Compare the analyst's verdicts on calibration fixtures to what they MUST be.
A non-empty result means the analyst cannot reliably distinguish good from bad
(or can't decline) → the run must abort before judging real transcripts."""


def mismatches(results, expected):
    out = []
    for case, want in expected.items():
        got = results.get(case)
        if got != want:
            out.append(f"{case}: expected {want}, got {got!r}")
    return out
