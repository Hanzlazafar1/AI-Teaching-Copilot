"""Well-formedness of the Brady Protected-Set pack (safety-net layer 0)."""
from tests.protected_set import PROTECTED_SET, INVARIANT_KEYS


def test_pack_nonempty_and_unique_ids():
    assert len(PROTECTED_SET) >= 15
    ids = [c.id for c in PROTECTED_SET]
    assert len(ids) == len(set(ids)), "duplicate case ids"


def test_every_case_has_known_invariants():
    for c in PROTECTED_SET:
        assert c.invariants, f"{c.id} has no invariants"
        unknown = set(c.invariants) - INVARIANT_KEYS
        assert not unknown, f"{c.id} references unknown invariants: {unknown}"


def test_prior_messages_are_nonempty_strings():
    for c in PROTECTED_SET:
        assert all(isinstance(m, str) and m.strip() for m in c.prior_messages)
