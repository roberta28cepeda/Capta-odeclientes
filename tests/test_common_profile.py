from src.common.profile import format_profile_for_prompt


def test_format_profile_for_prompt_uses_defaults_for_empty_profile():
    formatted = format_profile_for_prompt({})

    assert formatted["freelancer_name"] == "[freelancer]"
    assert formatted["standard_clauses"] == "nenhuma adicional"
    assert formatted["language"] == "português do Brasil"


def test_format_profile_for_prompt_uses_provided_values():
    profile = {
        "freelancer_name": "Ana Dev",
        "standard_clauses": ["2 rodadas de ajuste", "sem hospedagem inclusa"],
    }

    formatted = format_profile_for_prompt(profile)

    assert formatted["freelancer_name"] == "Ana Dev"
    assert formatted["standard_clauses"] == "2 rodadas de ajuste, sem hospedagem inclusa"
