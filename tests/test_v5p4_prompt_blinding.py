from __future__ import annotations

import copy
import re

import pytest

from mini_science.config import load_config
from mini_science.prompt_audit import PromptBlindingError, assert_prompt_blinded, find_prompt_leaks
from mini_science.prompts import seq2_stage1_messages, single_messages
from mini_science.public_loader import load_world


def test_v5p4_exact_public_messages_are_blinded_for_a_b_and_stage1():
    config = load_config("config/v5p4_offline_dev.json")
    related = load_world(".", "CV001", "related", worlds_subdir=config.worlds_subdir)
    irrelevant = load_world(".", "CV001", "irrelevant", worlds_subdir=config.worlds_subdir)

    a_messages = single_messages(irrelevant, "A_TARGET_ONLY", protocol_version="v5p4")
    b_messages = single_messages(related, "B_SINGLE_RELATED", protocol_version="v5p4")
    stage1_messages = seq2_stage1_messages(related, protocol_version="v5p4")
    assert_prompt_blinded(a_messages)
    assert_prompt_blinded(b_messages)
    assert_prompt_blinded(stage1_messages, stage="stage1")
    assert not find_prompt_leaks(a_messages + b_messages + stage1_messages)
    assert not re.search(r"\bE0[1-8]\b", "\n".join(item["content"] for item in stage1_messages))

    related_text = related.source_note
    irrelevant_text = irrelevant.source_note
    assert related_text != irrelevant_text
    assert set(re.findall(r"S\d{2}", related_text)) == {"S01", "S02", "S03", "S04"}
    assert set(re.findall(r"S\d{2}", irrelevant_text)) == {"S01", "S02", "S03", "S04"}


def test_v5p4_direct_relation_injection_is_rejected():
    config = load_config("config/v5p4_offline_dev.json")
    view = load_world(".", "CV001", "related", worlds_subdir=config.worlds_subdir)
    messages = copy.deepcopy(single_messages(view, "B_SINGLE_RELATED", protocol_version="v5p4"))
    messages[1]["content"] += "\nThis is the related source."
    with pytest.raises(PromptBlindingError):
        assert_prompt_blinded(messages)
