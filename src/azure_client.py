"""Azure AI Foundry client wrapper for speech and text services."""

import contextlib
import re
import threading
import wave
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Union

REDACTED = "[redacted]"

# Azure SDK exceptions routinely echo the subscription key back in the message
# (request headers, signed URLs, "Access denied due to invalid subscription key
# ... <key>"). These patterns scrub key-shaped material we were not handed.
_KEY_PATTERNS = (
    re.compile(r"(Ocp-Apim-Subscription-Key\s*[:=]\s*)[^\s&,;\"']+", re.IGNORECASE),
    re.compile(r"(subscription[-_ ]?key\s*[:=]\s*)[^\s&,;\"']+", re.IGNORECASE),
    re.compile(r"([?&](?:subscription-key|key|sig|access_token)=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(Authorization\s*[:=]\s*(?:Bearer|Basic)\s+)\S+", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
)

# Margin under the service's 125,000-character asynchronous request cap. The
# service counts grapheme clusters, not Python characters, so the two diverge.
MAX_SUMMARY_INPUT_CHARS = 120_000
SUMMARY_SENTENCE_COUNT = 4

# Wall-clock ceiling for a recognition session that never signals completion.
MIN_TRANSCRIPTION_TIMEOUT = 120
FALLBACK_TRANSCRIPTION_TIMEOUT = 900

# SDK diagnostics run to hundreds of characters — native call stacks from the
# Speech SDK, whole HTML error pages from azure-core's "Content:" dump. They are
# rendered in st.error and stored in the database, so they are bounded here.
MAX_DIAGNOSTIC_CHARS = 200


class TranscriptionError(Exception):
    """Raised when Azure Speech cannot produce a transcript."""

    def __init__(self, message: str, partial_transcript: str = "") -> None:
        """Record the failure, keeping any text recognized before it."""
        super().__init__(message)
        self.partial_transcript = partial_transcript


class SummarizationError(Exception):
    """Raised when Azure Text Analytics cannot produce a summary."""


@dataclass
class PipelineResult:
    """Outcome of one transcribe-then-summarize run; the summary may be missing."""

    transcript: str
    summary: Optional[str] = None
    summary_error: Optional[str] = None


def sanitize_azure_error(
    error: Union[BaseException, str],
    secrets: Iterable[Optional[str]] = (),
) -> str:
    """Return an Azure error message or diagnostic string with credentials removed."""
    if isinstance(error, BaseException):
        message = str(error) or error.__class__.__name__
    else:
        message = error

    for secret in secrets:
        if secret and len(secret) >= 8:
            message = message.replace(secret, REDACTED)

    for pattern in _KEY_PATTERNS:
        if pattern.groups:
            message = pattern.sub(lambda m: m.group(1) + REDACTED, message)
        else:
            message = pattern.sub(REDACTED, message)

    return message


def brief_diagnostic(
    error: Union[BaseException, str],
    secrets: Iterable[Optional[str]] = (),
    limit: int = MAX_DIAGNOSTIC_CHARS,
) -> str:
    """Return the sanitized first line of an SDK diagnostic, truncated to `limit`."""
    message = sanitize_azure_error(error, secrets).strip()
    if not message:
        return ""

    first_line = message.splitlines()[0].strip()
    if len(first_line) > limit:
        return first_line[:limit].rstrip() + "..."
    return first_line


def _wav_duration_seconds(audio_file_path: str) -> Optional[float]:
    """Duration of a WAV file in seconds, or None if it cannot be read."""
    try:
        with contextlib.closing(wave.open(audio_file_path, "rb")) as handle:
            frame_rate = handle.getframerate()
            if frame_rate <= 0:
                return None
            return handle.getnframes() / float(frame_rate)
    except (wave.Error, OSError, EOFError):
        return None


def _split_for_summary(text: str) -> List[str]:
    """Split text into chunks under the service character cap, on sentence boundaries."""
    if len(text) <= MAX_SUMMARY_INPUT_CHARS:
        return [text]

    chunks: List[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > MAX_SUMMARY_INPUT_CHARS:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        chunks.append(current)
    return chunks


class AzureSpeechClient:
    """Wrapper for Azure Speech-to-Text service."""

    def __init__(self, api_key: str, region: str):
        """Initialize Azure Speech client with explicit credentials."""
        self.api_key = api_key
        self.region = region

        if not self.api_key or not self.region:
            raise ValueError("Azure Speech credentials not configured")

        try:
            import azure.cognitiveservices.speech as speechsdk
            self.speechsdk = speechsdk
            self.speech_config = speechsdk.SpeechConfig(
                subscription=self.api_key,
                region=self.region
            )
        except ImportError:
            raise ImportError("azure-cognitiveservices-speech package required")

    def _brief(self, value: Union[BaseException, str]) -> str:
        """Scrub and shorten an SDK diagnostic for display and storage."""
        return brief_diagnostic(value, (self.api_key,))

    def transcribe_file(self, audio_file_path: str, language: str = "en-US") -> str:
        """Transcribe a whole WAV recording using continuous recognition."""
        speechsdk = self.speechsdk
        self.speech_config.speech_recognition_language = language

        try:
            audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                audio_config=audio_config,
            )
        except Exception as e:
            raise TranscriptionError(
                "Could not open the audio file. Uploads must be WAV "
                f"(16 kHz, 16-bit, mono PCM). ({self._brief(e)})"
            ) from e

        segments: List[str] = []
        cancellation: List[Any] = []
        done = threading.Event()

        # These handlers run on SDK-owned threads with no Streamlit script
        # context, so they may only touch plain Python objects.
        def on_recognized(evt: Any) -> None:
            result = evt.result
            if result.reason == speechsdk.ResultReason.RecognizedSpeech and result.text:
                segments.append(result.text)

        def on_canceled(evt: Any) -> None:
            details = getattr(evt, "cancellation_details", None)
            if details is None:
                details = getattr(getattr(evt, "result", None), "cancellation_details", None)
            if details is not None:
                cancellation.append(details)
            done.set()

        def on_session_stopped(evt: Any) -> None:
            done.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.canceled.connect(on_canceled)
        recognizer.session_stopped.connect(on_session_stopped)

        duration = _wav_duration_seconds(audio_file_path)
        timeout = (
            max(MIN_TRANSCRIPTION_TIMEOUT, int(duration * 2))
            if duration
            else FALLBACK_TRANSCRIPTION_TIMEOUT
        )

        try:
            recognizer.start_continuous_recognition()
            completed = done.wait(timeout=timeout)
        finally:
            # Stopping is done here rather than inside the callbacks: re-entering
            # the SDK from an SDK-owned thread is a known source of hangs.
            try:
                recognizer.stop_continuous_recognition_async().get()
            except Exception:
                pass
            recognizer.recognized.disconnect_all()
            recognizer.canceled.disconnect_all()
            recognizer.session_stopped.disconnect_all()

        transcript = " ".join(segments).strip()

        if cancellation:
            details = cancellation[0]
            # EndOfStream is the normal end-of-file signal, not a failure.
            if details.reason == speechsdk.CancellationReason.Error:
                raise TranscriptionError(
                    self._cancellation_message(details, transcript),
                    partial_transcript=transcript,
                )

        if not completed:
            raise TranscriptionError(
                f"Transcription timed out after {timeout} seconds without Azure "
                "signalling the end of the recording."
                + (
                    f" {len(transcript)} characters recognized before the timeout "
                    "have been kept."
                    if transcript
                    else ""
                ),
                partial_transcript=transcript,
            )

        if not transcript:
            raise TranscriptionError(
                "No speech was recognized in this recording. Check that the file "
                "contains audible speech in the selected language and is WAV "
                "(16 kHz, 16-bit, mono PCM)."
            )

        return transcript

    def _cancellation_message(self, details: Any, transcript: str) -> str:
        """Build a readable message for a cancelled recognition session."""
        speechsdk = self.speechsdk
        # CancellationDetails exposes `code`, not `error_code`; reading the wrong
        # attribute raised inside this handler and masked every message below.
        code = details.code
        code_name = getattr(code, "name", str(code))
        diagnostic = self._brief(details.error_details or "")
        partial = (
            f" The {len(transcript)} characters recognized before the failure "
            "have been kept."
            if transcript
            else ""
        )

        if code == speechsdk.CancellationErrorCode.AuthenticationFailure:
            return (
                "Azure rejected the Speech credentials. Check the Speech key and "
                "region (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION, or the sidebar form)."
            )
        if code in (
            speechsdk.CancellationErrorCode.Forbidden,
            speechsdk.CancellationErrorCode.TooManyRequests,
        ):
            return (
                "Speech quota exhausted or throttled for this resource "
                f"({code_name}). The free F0 tier allows 5 audio hours per "
                f"month.{partial}"
            )
        if code in (
            speechsdk.CancellationErrorCode.ConnectionFailure,
            speechsdk.CancellationErrorCode.ServiceTimeout,
        ):
            return (
                "Lost the connection to Azure Speech mid-recording "
                f"({code_name}: {diagnostic}).{partial}"
            )
        return f"Azure Speech cancelled recognition ({code_name}: {diagnostic}).{partial}"


class AzureTextAnalyticsClient:
    """Wrapper for Azure Text Analytics service."""

    def __init__(self, endpoint: str, api_key: str):
        """Initialize Azure Text Analytics client with explicit credentials."""
        self.endpoint = endpoint
        self.api_key = api_key

        if not self.endpoint or not self.api_key:
            raise ValueError("Azure Text Analytics credentials not configured")

        try:
            from azure.ai.textanalytics import TextAnalyticsClient
            from azure.core.credentials import AzureKeyCredential
            self.client = TextAnalyticsClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.api_key)
            )
        except ImportError:
            raise ImportError("azure-ai-textanalytics package required")

    def _brief(self, value: Union[BaseException, str]) -> str:
        """Scrub and shorten an SDK diagnostic for display and storage."""
        return brief_diagnostic(value, (self.api_key,))

    def extract_summary(self, text: str, language: str = "en") -> str:
        """Summarize a transcript with Azure abstractive summarization."""
        if not text or not text.strip():
            raise SummarizationError("There is no transcript text to summarize.")

        # begin_abstract_summary takes ISO 639-1 ("en"); callers hold BCP-47
        # locales ("en-US"). Truncating is only safe because SUPPORTED_LANGUAGES
        # is a curated list whose six locales all map cleanly.
        language_code = (language or "en")[:2].lower()

        summaries = [
            self._summarize_chunk(chunk, language_code)
            for chunk in _split_for_summary(text.strip())
        ]
        summary = " ".join(part for part in summaries if part).strip()

        if not summary:
            raise SummarizationError("Azure returned an empty summary for this transcript.")
        return summary

    def _summarize_chunk(self, chunk: str, language: str) -> str:
        """Run one abstractive summarization request and poll it to completion."""
        from azure.core.exceptions import (
            ClientAuthenticationError,
            HttpResponseError,
            ServiceRequestError,
            ServiceResponseError,
        )

        try:
            poller = self.client.begin_abstract_summary(
                [chunk],
                language=language,
                sentence_count=SUMMARY_SENTENCE_COUNT,
                polling_interval=2,
            )
            # poller.result() returns a lazy ItemPaged whose page extraction can
            # itself raise HttpResponseError, so it must be drained in here.
            documents = list(poller.result())
        except ClientAuthenticationError as e:
            raise SummarizationError(
                "Azure rejected the Text Analytics key (AZURE_TEXT_ANALYTICS_KEY, "
                "or the sidebar form)."
            ) from e
        except (ServiceRequestError, ServiceResponseError) as e:
            # ServiceResponseError is a sibling of ServiceRequestError, not a
            # subclass: read timeout, dropped connection, or an endpoint pasted
            # without its https:// scheme.
            raise SummarizationError(
                "Could not reach Azure Text Analytics. Check the network and that "
                "AZURE_TEXT_ANALYTICS_ENDPOINT starts with https:// "
                f"({self._brief(e)})."
            ) from e
        except HttpResponseError as e:
            raise SummarizationError(self._http_message(e)) from e

        for document in documents:
            if document.is_error:
                raise SummarizationError(
                    "Azure could not summarize this transcript "
                    f"({document.error.code}: {self._brief(document.error.message or '')})."
                )
            return " ".join(
                item.text for item in (document.summaries or []) if item.text
            ).strip()

        raise SummarizationError("Azure returned no summarization result for this transcript.")

    def _http_message(self, error: BaseException) -> str:
        """Map an HTTP failure from the Language service to actionable text."""
        status = getattr(error, "status_code", None)
        diagnostic = self._brief(error)

        if status == 403:
            return (
                "Azure refused the summarization request (403). Abstractive "
                "summarization requires a Language resource on the Standard (S) "
                "pricing tier in a region that supports it; the free F0 tier "
                f"cannot run it. {diagnostic}"
            )
        if status == 404:
            return (
                "Azure Text Analytics endpoint not found (404). Check that "
                "AZURE_TEXT_ANALYTICS_ENDPOINT points at the Language resource. "
                f"{diagnostic}"
            )
        if status == 400:
            return f"Azure rejected the summarization request (400): {diagnostic}"
        return f"Azure Text Analytics failed: {diagnostic}"


class AzureFoundryClient:
    """Unified client for Azure Foundry services."""

    def __init__(self, speech_key: str, speech_region: str,
                 text_analytics_endpoint: str, text_analytics_key: str):
        """Initialize both Azure clients from explicit credentials."""
        self.speech_client = AzureSpeechClient(speech_key, speech_region)
        self.text_client = AzureTextAnalyticsClient(text_analytics_endpoint, text_analytics_key)

    def secrets(self) -> tuple[Optional[str], ...]:
        """Return the secret values held by this client, for error sanitization."""
        return (self.speech_client.api_key, self.text_client.api_key)

    def transcribe_and_summarize(
        self,
        audio_file_path: str,
        language: str = "en-US",
        on_stage: Optional[Callable[[str], None]] = None,
        on_transcript: Optional[Callable[[str], None]] = None,
    ) -> PipelineResult:
        """Transcribe an audio file then summarize it, reporting stages to `on_stage`.

        `on_transcript` is called with the transcript as soon as Speech returns it,
        so the caller can persist billed work before summarization is attempted. A
        summarization failure is reported on the result, not raised: the transcript
        is the expensive half and must survive it.
        """
        if on_stage:
            on_stage("transcribing")
        transcript = self.speech_client.transcribe_file(audio_file_path, language)

        if on_transcript:
            on_transcript(transcript)

        if on_stage:
            on_stage("summarizing")
        try:
            summary = self.text_client.extract_summary(transcript, language)
        except SummarizationError as e:
            return PipelineResult(transcript=transcript, summary_error=str(e))
        except Exception as e:
            return PipelineResult(
                transcript=transcript,
                summary_error=(
                    "Summarization failed unexpectedly: "
                    f"{brief_diagnostic(e, self.secrets())}"
                ),
            )

        return PipelineResult(transcript=transcript, summary=summary)
