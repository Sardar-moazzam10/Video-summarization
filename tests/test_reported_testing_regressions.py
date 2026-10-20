import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from backend.services.knowledge_plan import filter_candidate_concepts
from backend.services.summarization_service import SummarizationService
from backend.services.text_normalization import topic_keyphrase
from backend.services.transcript_service import TranscriptService
from backend.services.whisper_recovery import recover_audio


def test_broad_search_title_does_not_erase_source_subtopics():
    concepts = [SimpleNamespace(name=name, embedding=np.array([0., 1.]))
                for name in ('email', 'laptop', 'spam', 'body language')]
    kept = filter_candidate_concepts(concepts, query='Computer technology course',
                                     query_embedding=np.array([1., 0.]))
    assert kept == concepts


def test_unpunctuated_captions_are_bounded_without_losing_words():
    text = ' '.join(f'word{i}' for i in range(1500))
    chunks = SummarizationService._split_into_chunks(text, 400)
    assert max(len(c.split()) for c in chunks) <= 400
    assert ' '.join(chunks) == text


def test_source_boundaries_survive_cleaning():
    assert SummarizationService._clean_text('First clip here\n\nSecond clip here') == 'First clip here\n\nSecond clip here'


def test_final_compression_keeps_later_sections_and_complete_sentences():
    sections = ['Memory stores active programs. Extra detail about memory usage.',
                'Keyboards need careful cleaning. Extra detail about cleaning equipment.',
                'Phishing emails steal passwords. Extra detail about suspicious messages.']
    result = SummarizationService._balance_chunk_summaries(sections, 15)
    assert result == ('Memory stores active programs. Keyboards need careful cleaning. '
                      'Phishing emails steal passwords.')


def test_topic_is_a_content_phrase_not_opening_fragment():
    topic = topic_keyphrase(['Looks good to me. Just protect against malware attacks. '
                            'Malware attacks can steal account passwords.'])
    assert topic == 'malware attacks'


@pytest.mark.asyncio
async def test_last_waiter_cancels_acquisition_but_shared_waiter_survives():
    service = TranscriptService({'transcripts': None})
    started, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def acquire(*args, **kwargs):
        started.set()
        try:
            await release.wait()
            return {'ok': True}
        finally:
            stopped.set()
    service._get_transcript_impl = acquire
    first = asyncio.create_task(service.get_transcript('0FVoMm6qrwM'))
    await started.wait()
    second = asyncio.create_task(service.get_transcript('0FVoMm6qrwM'))
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert not stopped.is_set()
    second.cancel()
    await asyncio.gather(second, return_exceptions=True)
    assert stopped.is_set()
    assert not service._inflight_waiters


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel', [False, True])
async def test_worker_is_reaped_and_slot_freed_on_timeout_or_cancel(monkeypatch, cancel):
    service = SimpleNamespace()
    killed = asyncio.Event()
    class Worker:
        pid = 123456
        returncode = None
        stdout = asyncio.StreamReader()
        async def wait(self):
            await killed.wait()
            self.returncode = -9
            return self.returncode
    worker = Worker()
    monkeypatch.setattr('backend.core.config.get_settings', lambda: SimpleNamespace(TRANSCRIPT_SOURCE_TIMEOUT_SECONDS=.03))
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', AsyncMock(return_value=worker))
    monkeypatch.setattr('backend.services.whisper_recovery.os.killpg', lambda *args: killed.set())
    progress = AsyncMock()
    task = asyncio.create_task(recover_audio(service, '0FVoMm6qrwM', 'hi', progress))
    if cancel:
        await asyncio.sleep(.01)
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert killed.is_set()
    assert worker.returncode == -9
    assert not service._whisper_slot.locked()


@pytest.mark.asyncio
async def test_cancelled_queue_waiter_does_not_release_active_slot():
    service = SimpleNamespace(_whisper_slot=asyncio.Lock())
    await service._whisper_slot.acquire()
    task = asyncio.create_task(recover_audio(service, '0FVoMm6qrwM'))
    await asyncio.sleep(.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert service._whisper_slot.locked()
    service._whisper_slot.release()
