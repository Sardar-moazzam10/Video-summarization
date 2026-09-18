import transformers.utils.hub
original_cached_file = transformers.utils.hub.cached_file
def fake_cached_file(*args, **kwargs):
    if "adapter_config.json" in kwargs.get("filename", "") or "adapter_config.json" in args:
        raise EnvironmentError("Offline mode: adapter_config.json not found")
    return original_cached_file(*args, **kwargs)
transformers.utils.hub.cached_file = fake_cached_file
