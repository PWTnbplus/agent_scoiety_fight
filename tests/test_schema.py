from __future__ import annotations

from mini_science.config import load_config
from mini_science.public_loader import load_world
from mini_science.schema import validate_final_question
from mini_science.worldgen import generate_worlds


def test_schema_rejects_illegal_action_and_private_fields(tmp_path):
    config = load_config("config/pilot.json")
    generate_worlds(tmp_path, config)
    view = load_world(tmp_path, "W001", "related")
    valid = '{"experiment_id":"E04","scientific_question":"q","hypotheses_to_discriminate":["EXP_DECAY","HYPERBOLIC_DECAY"],"measurement":"normalized_state","predicted_difference":"d","evidence_ids":["T01"],"uncertainty":"moderate"}'
    assert validate_final_question(valid, view).valid
    invalid = valid.replace('"E04"', '"E99"')
    assert not validate_final_question(invalid, view).valid
    private = valid[:-1] + ',"ig":999}'
    assert not validate_final_question(private, view).valid
