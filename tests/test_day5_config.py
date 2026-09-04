import importlib.util
from pathlib import Path


DAY05_EXPERIMENT = Path(__file__).resolve().parents[1] / "day05-model-versions" / "experiment.py"
SPEC = importlib.util.spec_from_file_location("day5_experiment", DAY05_EXPERIMENT)
day5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(day5)


def test_three_hf_models_share_provider_and_family():
    assert [model["parameters_b"] for model in day5.HF_MODELS] == [3.0, 7.0, 32.0]
    assert all(model["repo"].startswith("Qwen/Qwen2.5-Coder-") for model in day5.HF_MODELS)
    assert day5.HF_PROVIDER == "nscale"


def test_generation_config_is_locked():
    assert day5.generation_config() == {
        "temperature": 0.1,
        "maxOutputTokens": 1200,
        "thinkingConfig": {"thinkingLevel": "minimal"},
    }


def test_local_small_model_is_locked():
    assert day5.LOCAL_SMALL["repo"] == "qwen3.5:4b"
    assert day5.LOCAL_SMALL["parameters_b"] == 4.66


def test_api_controls_and_cpu_model_are_locked():
    assert [model["repo"] for model in day5.API_MODELS] == [
        "gemini-3.5-flash", "gemini-3.6-flash", "deepseek-v4-flash"
    ]
    assert day5.LOCAL_CPU["parameters_b"] == 1.72


def test_prompt_hash_is_stable_shape():
    assert len(day5.prompt_sha256()) == 8
    assert day5.prompt_sha256() == day5.prompt_sha256()


def test_equal_quality_verdict_uses_overkill_conclusion():
    metrics = {
        "weak": {"label": "3B", "tests_passed_mean": 10, "tests_total": 10, "tokens_per_second_median": 100},
        "strong": {"label": "32B", "tests_passed_mean": 10, "tests_total": 10, "tokens_per_second_median": 20},
    }
    verdict = day5._verdict(metrics)
    assert "одинаковое качество" in verdict
    assert "микроскоп" in verdict


def test_deepseek_cost_uses_cache_hit_and_miss_rates():
    model = next(model for model in day5.API_MODELS if model["id"] == "deepseek")
    price = {
        "input_cache_hit_usd_per_million": 0.01,
        "input_usd_per_million": 0.20,
        "output_usd_per_million": 0.60,
    }
    cost, hit, miss = day5._api_cost(
        model,
        {"prompt_tokens": 100, "output_tokens": 10},
        {"promptCacheHitTokenCount": 80, "promptCacheMissTokenCount": 20},
        price,
    )
    assert (hit, miss) == (80, 20)
    assert cost == (80 * 0.01 + 20 * 0.20 + 10 * 0.60) / 1_000_000
