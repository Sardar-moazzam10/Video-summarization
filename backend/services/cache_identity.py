"""Content-addressed identities for semantic processing caches."""
import hashlib
import json


def content_key(payload):
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        default=str,
    ).encode("utf-8")).hexdigest()


def model_identity(embedder=None):
    from ..core.config import get_settings
    model = get_settings().EMBEDDING_MODEL
    embedder = getattr(embedder, "wrapped", embedder)
    if embedder is None:
        return model
    return (model, type(embedder).__module__, type(embedder).__qualname__,
            str(getattr(embedder, "model_name_or_path", "")),
            str(getattr(embedder, "revision", "")))


class MeasuredEmbedder:
    """Account for encode time inside segmentation and concept extraction."""
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.elapsed = 0.0

    def encode(self, *args, **kwargs):
        from time import perf_counter
        started = perf_counter()
        try:
            return self.wrapped.encode(*args, **kwargs)
        finally:
            self.elapsed += perf_counter() - started

    def __getattr__(self, name):
        return getattr(self.wrapped, name)
