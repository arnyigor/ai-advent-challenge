from evaluation import evaluate_answer, extract_python, validate_candidate


GOOD_CODE = '''
def reconcile_ranges(ranges, exclusions):
    def normalize(items):
        for start, end in items:
            if type(start) is not int or type(end) is not int or start >= end:
                raise ValueError("invalid interval")
        merged = []
        for start, end in sorted(items):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    source = normalize(ranges)
    cuts = normalize(exclusions)
    result = []
    for start, end in source:
        pieces = [(start, end)]
        for cut_start, cut_end in cuts:
            updated = []
            for left, right in pieces:
                if cut_end <= left or cut_start >= right:
                    updated.append((left, right))
                else:
                    if left < cut_start:
                        updated.append((left, cut_start))
                    if cut_end < right:
                        updated.append((cut_end, right))
            pieces = updated
        result.extend(pieces)
    return result
'''


def test_extracts_python_fence():
    assert extract_python(f"```python\n{GOOD_CODE}\n```\nO(n log n)").startswith("def reconcile_ranges")


def test_good_candidate_passes_all_tests():
    result = evaluate_answer(GOOD_CODE)
    assert result["passed"] == result["total"] == 10


def test_rejects_dangerous_candidate():
    safe, reason = validate_candidate("def reconcile_ranges(a, b):\n    return open('x')")
    assert not safe
    assert "open" in reason


def test_allows_relevant_standard_library_imports():
    safe, reason = validate_candidate(
        "from collections import deque\ndef reconcile_ranges(a, b):\n    return []"
    )
    assert safe, reason


def test_missing_function_scores_zero():
    result = evaluate_answer("Я не знаю")
    assert result["score"] == 0
    assert not result["code_found"]
