from __future__ import annotations

from mini_science.config import load_config
from mini_science.metrics.numeric_ability_split import split_numeric_ability
from mini_science.metrics.public_calculator import calculate_public_predictions
from mini_science.public_loader import load_world


def test_public_calculator_uses_selected_action_and_raw_is_unchanged():
    config = load_config("config/v5p11_main.json")
    view = load_world(".", "IV001", "related", worlds_subdir=config.worlds_subdir)
    raw = {"EXP_DECAY": 0.0}
    expected = calculate_public_predictions(view, "E04")
    split = split_numeric_ability(view, "E04", raw)
    assert split["raw_agent"]["values"] == raw
    assert split["raw_agent"]["accuracy"] == 0.0
    assert split["assisted_calculator"]["accuracy"] == 1.0
    assert split["assisted_calculator"]["calculator_values"] == expected
