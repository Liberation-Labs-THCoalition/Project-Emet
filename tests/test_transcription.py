"""Tests for A/V transcription adapter — Sprint 12.

Tests transcription config, result types, FtM conversion, NER extraction,
SRT export, and client behavior.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from emet.ftm.external.transcription import (
    TranscriptionConfig,
    TranscriptSegment,
    TranscriptionResult,
    TranscriptionFtMConverter,
    TranscriptionClient,
    SUPPORTED_EXTENSIONS,
    _format_time,
    _format_srt_time,
)


# ===========================================================================
# Config
# ===========================================================================


class TestTranscriptionConfig:
    def test_defaults(self):
        cfg = TranscriptionConfig()
        assert cfg.model_size == "base"
        assert cfg.device == "auto"
        assert cfg.vad_filter is True
        assert cfg.diarize is False

    def test_custom_config(self):
        cfg = TranscriptionConfig(
            model_size="large-v3",
            device="cuda",
            compute_type="float16",
            language="en",
            diarize=True,
            hf_token="hf_abc123",
        )
        assert cfg.model_size == "large-v3"
        assert cfg.diarize is True


# ===========================================================================
# Segment
# ===========================================================================


class TestTranscriptSegment:
    def test_duration(self):
        seg = TranscriptSegment(start=10.0, end=15.5, text="hello")
        assert seg.duration == pytest.approx(5.5)

    def test_timestamp_str(self):
        seg = TranscriptSegment(start=3661.0, end=3725.0, text="test")
        assert seg.timestamp_str() == "[01:01:01 - 01:02:05]"

    def test_default_speaker(self):
        seg = TranscriptSegment(start=0, end=1, text="hi")
        assert seg.speaker == ""


# ===========================================================================
# TranscriptionResult
# ===========================================================================


class TestTranscriptionResult:
    def _make_result(self, diarized=False) -> TranscriptionResult:
        segments = [
            TranscriptSegment(start=0.0, end=5.0, text="Hello world.", speaker="SPEAKER_00" if diarized else ""),
            TranscriptSegment(start=5.5, end=10.0, text="This is a test.", speaker="SPEAKER_01" if diarized else ""),
            TranscriptSegment(start=10.5, end=15.0, text="Goodbye.", speaker="SPEAKER_00" if diarized else ""),
        ]
        return TranscriptionResult(
            source_path="/tmp/test.mp3",
            segments=segments,
            language="en",
            language_probability=0.95,
            duration_seconds=15.0,
            model_size="base",
            diarized=diarized,
            speaker_count=2 if diarized else 0,
        )

    def test_full_text(self):
        result = self._make_result()
        assert result.full_text == "Hello world. This is a test. Goodbye."

    def test_segment_count(self):
        result = self._make_result()
        assert result.segment_count == 3

    def test_speakers_empty_when_not_diarized(self):
        result = self._make_result(diarized=False)
        assert result.speakers() == []

    def test_speakers_when_diarized(self):
        result = self._make_result(diarized=True)
        assert result.speakers() == ["SPEAKER_00", "SPEAKER_01"]

    def test_text_by_speaker(self):
        result = self._make_result(diarized=True)
        by_speaker = result.text_by_speaker()
        assert "SPEAKER_00" in by_speaker
        assert "Hello world." in by_speaker["SPEAKER_00"]
        assert "Goodbye." in by_speaker["SPEAKER_00"]
        assert "SPEAKER_01" in by_speaker

    def test_to_srt(self):
        result = self._make_result()
        srt = result.to_srt()
        assert "1\n" in srt
        assert "00:00:00,000 --> 00:00:05,000" in srt
        assert "Hello world." in srt

    def test_to_srt_with_speakers(self):
        result = self._make_result(diarized=True)
        srt = result.to_srt()
        assert "[SPEAKER_00]" in srt
        assert "[SPEAKER_01]" in srt


# ===========================================================================
# FtM Converter
# ===========================================================================


class TestTranscriptionFtMConverter:
    def _make_result(self) -> TranscriptionResult:
        return TranscriptionResult(
            source_path="/tmp/interview.mp3",
            segments=[
                TranscriptSegment(
                    start=0.0, end=30.0,
                    text=(
                        "John Smith from Acme Corporation told us about the "
                        "$5 million deal. Contact him at john@acme.com. "
                        "Maria Garcia confirmed the details."
                    ),
                ),
            ],
            language="en",
            language_probability=0.97,
            duration_seconds=30.0,
            model_size="base",
        )

    def test_produces_document_entity(self):
        converter = TranscriptionFtMConverter()
        entities = converter.convert(self._make_result())
        docs = [e for e in entities if e["schema"] == "Document"]
        assert len(docs) == 1
        assert "interview.mp3" in docs[0]["properties"]["title"][0]
        assert docs[0]["properties"]["language"] == ["en"]

    def test_document_provenance(self):
        converter = TranscriptionFtMConverter()
        entities = converter.convert(self._make_result())
        doc = entities[0]
        prov = doc["_provenance"]
        assert prov["source"] == "transcription"
        assert prov["model"] == "faster-whisper-base"
        assert prov["duration_seconds"] == 30.0

    def test_extracts_names(self):
        converter = TranscriptionFtMConverter()
        entities = converter.convert(self._make_result())
        names = [
            e["properties"]["name"][0]
            for e in entities
            if e["schema"] == "LegalEntity"
        ]
        assert "John Smith" in names
        assert "Acme Corporation" in names
        assert "Maria Garcia" in names

    def test_extracts_emails(self):
        converter = TranscriptionFtMConverter()
        entities = converter.convert(self._make_result())
        emails = [e for e in entities if e["schema"] == "Email"]
        assert len(emails) == 1
        assert emails[0]["properties"]["address"] == ["john@acme.com"]

    def test_extracts_money(self):
        converter = TranscriptionFtMConverter()
        entities = converter.convert(self._make_result())
        notes = [e for e in entities if e["schema"] == "Note"]
        money_notes = [n for n in notes if "Financial" in n["properties"].get("title", [""])[0]]
        assert len(money_notes) >= 1
        assert "$5 million" in money_notes[0]["properties"]["title"][0]

    def test_deduplicates_names(self):
        result = TranscriptionResult(
            source_path="/tmp/test.mp3",
            segments=[
                TranscriptSegment(start=0, end=5, text="John Smith said hello. John Smith agreed."),
            ],
            language="en",
            duration_seconds=5.0,
            model_size="base",
        )
        converter = TranscriptionFtMConverter()
        entities = converter.convert(result)
        names = [e for e in entities if e["schema"] == "LegalEntity"]
        name_values = [e["properties"]["name"][0] for e in names]
        assert name_values.count("John Smith") == 1

    def test_speaker_entities_from_diarization(self):
        result = TranscriptionResult(
            source_path="/tmp/test.mp3",
            segments=[
                TranscriptSegment(start=0, end=5, text="Hello.", speaker="SPEAKER_00"),
                TranscriptSegment(start=5, end=10, text="Hi.", speaker="SPEAKER_01"),
            ],
            language="en",
            duration_seconds=10.0,
            model_size="base",
            diarized=True,
        )
        converter = TranscriptionFtMConverter()
        entities = converter.convert(result)
        speakers = [e for e in entities if e["schema"] == "Person" and "Speaker" in e["properties"].get("description", [""])[0]]
        assert len(speakers) == 2

    def test_empty_transcript(self):
        result = TranscriptionResult(
            source_path="/tmp/silence.mp3",
            segments=[],
            language="en",
            duration_seconds=5.0,
            model_size="base",
        )
        converter = TranscriptionFtMConverter()
        entities = converter.convert(result)
        assert len(entities) == 1  # Just the document entity
        assert entities[0]["schema"] == "Document"


# ===========================================================================
# Client
# ===========================================================================


class TestTranscriptionClient:
    @pytest.mark.asyncio
    async def test_file_not_found(self):
        client = TranscriptionClient()
        with pytest.raises(FileNotFoundError):
            await client.transcribe("/nonexistent/file.mp3")

    @pytest.mark.asyncio
    async def test_unsupported_format(self, tmp_path):
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("not audio")
        client = TranscriptionClient()
        with pytest.raises(ValueError, match="Unsupported format"):
            await client.transcribe(str(bad_file))

    @pytest.mark.asyncio
    async def test_transcribe_calls_faster_whisper(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.start = 0.0
        mock_segment.end = 5.0
        mock_segment.text = "Hello world"
        mock_segment.avg_logprob = -0.3
        mock_segment.words = None

        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95
        mock_info.duration = 5.0

        mock_model.transcribe.return_value = ([mock_segment], mock_info)

        with patch("emet.ftm.external.transcription.TranscriptionClient._transcribe_faster_whisper") as mock_fw:
            mock_fw.return_value = TranscriptionResult(
                source_path=str(audio_file),
                segments=[TranscriptSegment(start=0, end=5, text="Hello world", confidence=-0.3)],
                language="en",
                language_probability=0.95,
                duration_seconds=5.0,
                model_size="base",
            )

            client = TranscriptionClient()
            result = await client.transcribe(str(audio_file))

            assert result.language == "en"
            assert result.segment_count == 1
            assert "Hello world" in result.full_text

    @pytest.mark.asyncio
    async def test_transcribe_to_ftm(self, tmp_path):
        audio_file = tmp_path / "interview.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        with patch.object(TranscriptionClient, "transcribe") as mock_transcribe:
            mock_transcribe.return_value = TranscriptionResult(
                source_path=str(audio_file),
                segments=[
                    TranscriptSegment(start=0, end=10, text="John Smith discussed the contract."),
                ],
                language="en",
                language_probability=0.95,
                duration_seconds=10.0,
                model_size="base",
            )

            client = TranscriptionClient()
            result = await client.transcribe_to_ftm(str(audio_file))

            assert result["transcription"]["language"] == "en"
            assert result["entity_count"] > 0
            assert result["srt"]  # SRT output present

    @pytest.mark.asyncio
    async def test_diarize_flag_routes_to_whisperx(self, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        config = TranscriptionConfig(diarize=True, hf_token="hf_test")
        client = TranscriptionClient(config)

        with patch.object(client, "_transcribe_whisperx") as mock_wx:
            mock_wx.return_value = TranscriptionResult(
                source_path=str(audio_file),
                segments=[],
                language="en",
                duration_seconds=5.0,
                model_size="base",
                diarized=True,
            )

            result = await client.transcribe(str(audio_file))
            mock_wx.assert_called_once()
            assert result.diarized is True


# ===========================================================================
# Helpers
# ===========================================================================


class TestHelpers:
    def test_supported_extensions(self):
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert ".mp4" in SUPPORTED_EXTENSIONS
        assert ".wav" in SUPPORTED_EXTENSIONS
        assert ".pdf" not in SUPPORTED_EXTENSIONS

    def test_format_time(self):
        assert _format_time(0) == "00:00:00"
        assert _format_time(61) == "00:01:01"
        assert _format_time(3661) == "01:01:01"

    def test_format_srt_time(self):
        assert _format_srt_time(0) == "00:00:00,000"
        assert _format_srt_time(1.5) == "00:00:01,500"
        assert _format_srt_time(3661.123) == "01:01:01,123"
