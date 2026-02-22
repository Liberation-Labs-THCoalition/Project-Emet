"""Audio/Video transcription adapter for investigative journalism.

Integrates faster-whisper (4x faster than OpenAI Whisper) and optionally
WhisperX (word-level timestamps + speaker diarization) to transcribe
media files into text, then extract named entities and convert to FtM.

Pipeline:
  media file → transcription → segments with timestamps
  → NER extraction → FtM Document + Person/Organization entities
  → optional speaker diarization (WhisperX)

Supported formats: mp3, mp4, wav, m4a, ogg, flac, webm, mkv, avi
Models: tiny, base, small, medium, large-v3 (via faster-whisper)

Reference:
  faster-whisper: https://github.com/SYSTRAN/faster-whisper (MIT)
  WhisperX: https://github.com/m-bain/whisperX (BSD)
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Supported media extensions
SUPPORTED_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".flac",
    ".webm", ".mkv", ".avi", ".wma", ".aac",
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class TranscriptionConfig:
    """Configuration for the transcription pipeline."""
    model_size: str = "base"          # tiny, base, small, medium, large-v3
    device: str = "auto"              # auto, cpu, cuda
    compute_type: str = "int8"        # float16, int8, float32
    language: str | None = None       # Auto-detect if None
    beam_size: int = 5
    vad_filter: bool = True           # Voice Activity Detection filtering
    min_silence_duration: float = 0.5 # Seconds of silence to split segments
    word_timestamps: bool = False     # Word-level timestamps (slower)
    diarize: bool = False             # Speaker diarization (requires WhisperX)
    hf_token: str = ""                # HuggingFace token for diarization model
    batch_size: int = 16              # WhisperX batch size


# ---------------------------------------------------------------------------
# Transcription result types
# ---------------------------------------------------------------------------


@dataclass
class TranscriptSegment:
    """A single segment of transcribed audio."""
    start: float           # Start time in seconds
    end: float             # End time in seconds
    text: str
    speaker: str = ""      # Speaker label (if diarized)
    confidence: float = 0.0
    words: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start

    def timestamp_str(self) -> str:
        """Format as [HH:MM:SS - HH:MM:SS]."""
        return f"[{_format_time(self.start)} - {_format_time(self.end)}]"


@dataclass
class TranscriptionResult:
    """Complete transcription of a media file."""
    source_path: str
    segments: list[TranscriptSegment] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration_seconds: float = 0.0
    model_size: str = ""
    diarized: bool = False
    speaker_count: int = 0

    @property
    def full_text(self) -> str:
        """Concatenate all segments into full transcript."""
        return " ".join(seg.text.strip() for seg in self.segments if seg.text.strip())

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def speakers(self) -> list[str]:
        """Unique speaker labels."""
        return sorted({s.speaker for s in self.segments if s.speaker})

    def text_by_speaker(self) -> dict[str, str]:
        """Group transcript text by speaker."""
        result: dict[str, list[str]] = {}
        for seg in self.segments:
            speaker = seg.speaker or "Unknown"
            result.setdefault(speaker, []).append(seg.text.strip())
        return {k: " ".join(v) for k, v in result.items()}

    def to_srt(self) -> str:
        """Export as SRT subtitle format."""
        lines = []
        for i, seg in enumerate(self.segments, 1):
            lines.append(str(i))
            lines.append(f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}")
            prefix = f"[{seg.speaker}] " if seg.speaker else ""
            lines.append(f"{prefix}{seg.text.strip()}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# FtM Converter
# ---------------------------------------------------------------------------


class TranscriptionFtMConverter:
    """Convert transcription results to FtM entities."""

    def __init__(self, source_label: str = "") -> None:
        self._source_label = source_label

    def convert(self, result: TranscriptionResult) -> list[dict[str, Any]]:
        """Convert transcription to FtM entities.

        Produces:
          - 1 Document entity for the transcript itself
          - Person/Organization entities from NER extraction
        """
        entities: list[dict[str, Any]] = []

        # Document entity for the transcript
        doc_id = f"transcript-{uuid.uuid4().hex[:12]}"
        doc_entity = {
            "id": doc_id,
            "schema": "Document",
            "properties": {
                "title": [f"Transcript: {Path(result.source_path).name}"],
                "bodyText": [result.full_text],
                "language": [result.language] if result.language else [],
                "mimeType": ["text/plain"],
            },
            "_provenance": {
                "source": "transcription",
                "source_id": result.source_path,
                "confidence": result.language_probability,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "model": f"faster-whisper-{result.model_size}",
                "duration_seconds": result.duration_seconds,
                "segment_count": result.segment_count,
                "diarized": result.diarized,
            },
        }
        entities.append(doc_entity)

        # Extract named entities from transcript text
        extracted = self._extract_entities(result.full_text)
        entities.extend(extracted)

        # Create speaker entities if diarized
        if result.diarized:
            for speaker in result.speakers():
                speaker_entity = {
                    "id": f"speaker-{doc_id}-{speaker}",
                    "schema": "Person",
                    "properties": {
                        "name": [speaker],
                        "description": [f"Speaker in {Path(result.source_path).name}"],
                    },
                    "_provenance": {
                        "source": "transcription_diarization",
                        "confidence": 0.5,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    },
                }
                entities.append(speaker_entity)

        return entities

    def _extract_entities(self, text: str) -> list[dict[str, Any]]:
        """Simple regex-based NER for transcripts.

        For production, this would use spaCy or the LLM skill chip.
        This provides baseline extraction without heavy dependencies.
        """
        entities: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Capitalized multi-word names (Person/Org heuristic)
        name_pattern = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b')
        for match in name_pattern.finditer(text):
            name = match.group(1)
            if name in seen or len(name) < 4:
                continue
            seen.add(name)

            entity_id = f"ner-{uuid.uuid4().hex[:8]}"
            entities.append({
                "id": entity_id,
                "schema": "LegalEntity",  # Ambiguous — could be person or org
                "properties": {
                    "name": [name],
                },
                "_provenance": {
                    "source": "transcription_ner",
                    "confidence": 0.4,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "method": "regex_capitalized_names",
                },
            })

        # Email addresses
        email_pattern = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b')
        for match in email_pattern.finditer(text):
            email = match.group(0)
            if email in seen:
                continue
            seen.add(email)
            entities.append({
                "id": f"ner-email-{uuid.uuid4().hex[:8]}",
                "schema": "Email",
                "properties": {"address": [email]},
                "_provenance": {
                    "source": "transcription_ner",
                    "confidence": 0.9,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
            })

        # Dollar amounts
        money_pattern = re.compile(r'\$[\d,]+(?:\.\d{2})?(?:\s*(?:million|billion|thousand))?', re.IGNORECASE)
        for match in money_pattern.finditer(text):
            amount = match.group(0)
            if amount in seen:
                continue
            seen.add(amount)
            entities.append({
                "id": f"ner-money-{uuid.uuid4().hex[:8]}",
                "schema": "Note",
                "properties": {
                    "title": [f"Financial reference: {amount}"],
                    "description": [f"Mentioned in transcript: {amount}"],
                },
                "_provenance": {
                    "source": "transcription_ner",
                    "confidence": 0.7,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                },
            })

        return entities


# ---------------------------------------------------------------------------
# Transcription client
# ---------------------------------------------------------------------------


class TranscriptionClient:
    """Async transcription client wrapping faster-whisper / WhisperX.

    Handles model loading, transcription, and optional diarization.
    Falls back gracefully when GPU or diarization dependencies
    are unavailable.
    """

    def __init__(self, config: TranscriptionConfig | None = None) -> None:
        self._config = config or TranscriptionConfig()
        self._model = None
        self._converter = TranscriptionFtMConverter()

    async def transcribe(
        self,
        file_path: str,
        language: str | None = None,
        diarize: bool | None = None,
    ) -> TranscriptionResult:
        """Transcribe a media file.

        Args:
            file_path: Path to audio/video file
            language: Override language detection
            diarize: Override diarization setting

        Returns:
            TranscriptionResult with segments, entities, and metadata
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {file_path}")

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported format: {path.suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        lang = language or self._config.language
        should_diarize = diarize if diarize is not None else self._config.diarize

        logger.info(
            "Transcribing %s (model: %s, language: %s, diarize: %s)",
            path.name, self._config.model_size, lang or "auto", should_diarize,
        )

        # Try faster-whisper first, then WhisperX for diarization
        if should_diarize:
            result = await self._transcribe_whisperx(str(path), lang)
        else:
            result = await self._transcribe_faster_whisper(str(path), lang)

        return result

    async def transcribe_to_ftm(
        self,
        file_path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Transcribe and convert to FtM entities in one call."""
        result = await self.transcribe(file_path, **kwargs)
        entities = self._converter.convert(result)

        return {
            "transcription": {
                "source": file_path,
                "language": result.language,
                "duration_seconds": result.duration_seconds,
                "segment_count": result.segment_count,
                "full_text": result.full_text,
                "diarized": result.diarized,
                "speaker_count": result.speaker_count,
            },
            "entity_count": len(entities),
            "entities": entities,
            "srt": result.to_srt(),
        }

    async def _transcribe_faster_whisper(
        self, file_path: str, language: str | None
    ) -> TranscriptionResult:
        """Transcribe using faster-whisper."""
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. "
                "Install with: pip install faster-whisper"
            )

        if self._model is None:
            self._model = WhisperModel(
                self._config.model_size,
                device=self._config.device,
                compute_type=self._config.compute_type,
            )

        segments_iter, info = self._model.transcribe(
            file_path,
            language=language,
            beam_size=self._config.beam_size,
            vad_filter=self._config.vad_filter,
            word_timestamps=self._config.word_timestamps,
        )

        segments = []
        for seg in segments_iter:
            words = []
            if hasattr(seg, "words") and seg.words:
                words = [
                    {"word": w.word, "start": w.start, "end": w.end, "probability": w.probability}
                    for w in seg.words
                ]
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text,
                confidence=seg.avg_logprob if hasattr(seg, "avg_logprob") else 0.0,
                words=words,
            ))

        return TranscriptionResult(
            source_path=file_path,
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
            duration_seconds=info.duration,
            model_size=self._config.model_size,
        )

    async def _transcribe_whisperx(
        self, file_path: str, language: str | None
    ) -> TranscriptionResult:
        """Transcribe with diarization using WhisperX."""
        try:
            import whisperx
        except ImportError:
            raise ImportError(
                "WhisperX not installed. "
                "Install with: pip install whisperx"
            )

        device = self._config.device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"

        # Load model and transcribe
        model = whisperx.load_model(
            self._config.model_size,
            device,
            compute_type=self._config.compute_type,
            language=language,
        )
        audio = whisperx.load_audio(file_path)
        result = model.transcribe(audio, batch_size=self._config.batch_size)

        detected_language = result.get("language", language or "en")

        # Align timestamps
        model_a, metadata = whisperx.load_align_model(
            language_code=detected_language, device=device
        )
        result = whisperx.align(
            result["segments"], model_a, metadata, audio, device,
            return_char_alignments=False,
        )

        # Diarize
        speaker_count = 0
        if self._config.hf_token:
            diarize_model = whisperx.DiarizationPipeline(
                use_auth_token=self._config.hf_token, device=device
            )
            diarize_segments = diarize_model(audio)
            result = whisperx.assign_word_speakers(diarize_segments, result)
            speakers = {
                seg.get("speaker", "")
                for seg in result.get("segments", [])
                if seg.get("speaker")
            }
            speaker_count = len(speakers)

        # Convert to our format
        segments = []
        for seg in result.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                text=seg.get("text", ""),
                speaker=seg.get("speaker", ""),
                confidence=seg.get("score", 0.0) if "score" in seg else 0.0,
            ))

        duration = segments[-1].end if segments else 0.0

        return TranscriptionResult(
            source_path=file_path,
            segments=segments,
            language=detected_language,
            duration_seconds=duration,
            model_size=self._config.model_size,
            diarized=bool(self._config.hf_token),
            speaker_count=speaker_count,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_srt_time(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm for SRT."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
