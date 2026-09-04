from tools.llm.registry import resolve_provider, split_model_spec


def test_hf_model_spec_keeps_provider_suffix():
    provider, model = split_model_spec("hf:Qwen/Qwen2.5-Coder-7B-Instruct:nscale")
    assert provider == "hf"
    assert model.endswith(":nscale")


def test_hf_provider_is_registered():
    assert resolve_provider("hf").name == "hf"
