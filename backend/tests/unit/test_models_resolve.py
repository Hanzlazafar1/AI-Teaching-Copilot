from api.models import ModelSet, resolve_models


class _S:
    openai_generation_model = "gpt-4o"
    openai_query_model = "gpt-4o-mini"
    openai_judge_model = "gpt-4o-mini"


def test_known_profile_5_4_maps_all_three():
    assert resolve_models("gpt-5.4", _S()) == ModelSet("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-mini")


def test_known_profile_4o_maps_all_three():
    assert resolve_models("gpt-4o", _S()) == ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini")


def test_none_uses_settings_defaults():
    assert resolve_models(None, _S()) == ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini")


def test_unknown_profile_falls_back_and_warns(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert resolve_models("bogus", _S()) == ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini")
    assert "Unknown model profile" in caplog.text


def test_empty_string_uses_defaults_without_warning(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert resolve_models("", _S()) == ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini")
    assert "Unknown model profile" not in caplog.text
