from pathlib import Path


def test_player_uses_authenticated_transport_for_protected_job_routes():
    source = Path("src/MergedPodcastPlayer.js").read_text()
    assert "import axios" not in source
    assert "axios.get(`${API_BASE_URL}/api/v1/merge" not in source
    assert "axios.post(`${API_BASE_URL}/api/v1/merge" not in source
    assert "authenticatedFetch(`${API_BASE_URL}/api/v1/merge/${mergeId}`)" in source
    assert "authenticatedFetch(`${API_BASE_URL}/api/v1/merge/${mergeId}/result`)" in source


def test_player_reports_missing_keyword_evidence_honestly():
    source = Path("src/MergedPodcastPlayer.js").read_text()
    assert 'data-testid="keyword-coverage"' in source
    assert "no meaningful supporting evidence found" in source


def test_keyword_ui_preserves_multiple_comma_separated_keywords():
    source = Path("src/SearchByKeywordsPage.js").read_text()
    assert "value.split(',')" in source
    assert "selected_keywords: selectedKeywords" in source
