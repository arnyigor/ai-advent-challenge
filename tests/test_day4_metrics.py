from metrics import check_facts, detect_degradations, jaccard, self_similarity


def test_jaccard_identical_and_disjoint():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0


def test_self_similarity_identical_texts_is_one():
    texts = ["привет мир тест"] * 3
    assert self_similarity(texts) == 1.0


def test_self_similarity_disjoint_texts_is_low():
    texts = ["яблоко груша слива", "машина дорога город", "музыка звук тишина"]
    assert self_similarity(texts) < 0.3


def test_check_facts_hits_all_concepts():
    text = (
        "rebase переносит коммиты поверх новой базы и переписывает историю, "
        "в отличие от merge, который сохраняет историю и добавляет коммит слияния. "
        "риск в том, что опубликованную ветку менять нельзя (force-push). "
        "используй rebase для локальных веток перед push."
    )
    result = check_facts(text)
    assert result["score"] == 5
    assert all(result[k] for k in ("replays", "rewrites_history", "merge_contrast", "shared_risk", "use_case"))


def test_check_facts_empty_on_unrelated_text():
    assert check_facts("это ответ ни о чём и без смысла")["score"] == 0


def test_detect_degradations_max_tokens_and_cutoff():
    sample = {"text": "Оборванный текст без точки в конце", "finish_reason": "MAX_TOKENS"}
    issues = detect_degradations(sample)
    assert "max_tokens" in issues
    assert "cut_off" in issues


def test_detect_degradations_clean_sample_has_none():
    sample = {"text": "Это законченное предложение.", "finish_reason": "STOP"}
    assert detect_degradations(sample) == []
