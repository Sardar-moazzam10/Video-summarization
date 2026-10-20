"""Regression checks for the Ollama-free VidFusion production path."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_backend_lifespan_does_not_probe_unavailable_ollama():
    from backend.main import app, lifespan

    database = MagicMock()
    database.__getitem__.return_value = MagicMock()

    with (
        patch("backend.services.summarization_service._get_pipeline"),
        patch("backend.services.fusion_engine.get_sentence_transformer"),
        patch("backend.services.rights_service.ensure_rights_indexes", new_callable=AsyncMock),
        patch("backend.services.acquisition_service.ensure_acquisition_indexes", new_callable=AsyncMock),
        patch("backend.core.database.get_database", new_callable=AsyncMock, return_value=database),
        patch("backend.services.job_recovery.recover_orphaned_jobs", new_callable=AsyncMock, return_value={}),
        patch("backend.core.database.close_database", new_callable=AsyncMock),
        patch("httpx.get", side_effect=httpx.ConnectError("Ollama unavailable")) as http_get,
    ):
        async with lifespan(app):
            pass

    http_get.assert_not_called()


def test_local_tfidf_enrichment_produces_structured_output():
    from backend.api.merge import _generate_local_enrichment

    summary = (
        "The research team measured changes in sleep quality across the study. "
        "Participants reported stronger focus after following the new routine. "
        "Consistent daylight exposure improved their daily energy levels. "
        "The authors recommend gradual changes rather than strict schedules. "
        "Future trials will compare these results across different age groups."
    )
    output = _generate_local_enrichment(summary, "informative")

    assert output.tldr
    assert output.key_takeaways
    assert output.chapters


@pytest.mark.asyncio
async def test_standard_quality_evaluation_skips_ollama(monkeypatch):
    import evaluate_summary

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("standard evaluation attempted the Ollama judge")

    monkeypatch.setattr(evaluate_summary, "ollama_judge", fail_if_called)
    monkeypatch.setattr(
        evaluate_summary,
        "semantic_coverage",
        lambda *args, **kwargs: {
            "score": 80.0,
            "covered": 1,
            "total": 1,
            "unit": "chunk",
            "threshold": 0.5,
            "least_covered": [],
        },
    )

    report = await evaluate_summary.evaluate(
        transcript_segments=[{"text": "The speaker explains the study findings."}],
        summary_text="The speaker explains the study findings.",
        use_llm=False,
    )

    assert report["check_a"]["score"] is not None
    assert report["check_a"]["llm_judge"]["error"] == "disabled (--no-llm)"