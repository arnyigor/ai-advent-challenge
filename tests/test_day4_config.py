from experiment import TEMPERATURES, build_generation_config, prompt_sha256


def test_only_temperature_differs():
    cfgs = [build_generation_config(t) for t in TEMPERATURES]
    diff = {
        key
        for key in cfgs[0]
        if any(cfg[key] != cfgs[0][key] for cfg in cfgs[1:])
    }
    assert diff == {"temperature"}


def test_no_sampling_params_leak():
    cfg = build_generation_config(0.7)
    assert not ({"topP", "topK", "seed", "stopSequences"} & cfg.keys())


def test_prompt_hash_is_deterministic():
    assert prompt_sha256() == prompt_sha256()
    assert len(prompt_sha256()) == 8
