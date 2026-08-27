from scripts.verify_model_access import verdict


def test_verdict_proceed_when_all_pass():
    r = {"gen": True, "nano_gen": True, "nano_struct": True, "emb": True, "gen_struct": True}
    assert verdict(r) == "PROCEED"


def test_verdict_fallback_when_nano_struct_fails_but_gen_struct_ok():
    r = {"gen": True, "nano_gen": True, "nano_struct": False, "emb": True, "gen_struct": True}
    assert verdict(r) == "FALLBACK"


def test_verdict_blocker_when_generation_model_missing():
    r = {"gen": False, "nano_gen": False, "nano_struct": False, "emb": True, "gen_struct": False}
    assert verdict(r) == "BLOCKER"


def test_verdict_not_fallback_when_embeddings_down():
    # emb down must NOT yield a go-ish FALLBACK even if the rest of the
    # FALLBACK criteria hold — retrieval would be broken.
    r = {"gen": True, "nano_gen": True, "nano_struct": False, "gen_struct": True, "emb": False}
    assert verdict(r) == "MIXED"
