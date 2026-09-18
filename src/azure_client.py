"""Azure AI Foundry client wrapper for speech and text services."""

import re
from typing import Iterable, Optional

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


def sanitize_azure_error(error: BaseException, secrets: Iterable[Optional[str]] = ()) -> str:
    """Return an Azure error message with credential material removed."""
    message = str(error) or error.__class__.__name__

    for secret in secrets:
        if secret and len(secret) >= 8:
            message = message.replace(secret, REDACTED)

    for pattern in _KEY_PATTERNS:
        if pattern.groups:
            message = pattern.sub(lambda m: m.group(1) + REDACTED, message)
        else:
            message = pattern.sub(REDACTED, message)

    return message


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

    def transcribe_file(self, audio_file_path: str, language: str = "en-US") -> str:
        """Transcribe audio file to text."""
        try:
            audio_config = self.speechsdk.audio.AudioConfig(filename=audio_file_path)
            recognizer = self.speechsdk.SpeechRecognizer(
                speech_config=self.speech_config,
                audio_config=audio_config
            )

            result = recognizer.recognize_once()

            if result.reason == self.speechsdk.ResultReason.RecognizedSpeech:
                return result.text
            elif result.reason == self.speechsdk.ResultReason.NoMatch:
                raise ValueError("Could not understand the audio")
            elif result.reason == self.speechsdk.ResultReason.Canceled:
                raise ValueError(f"Recognition failed: {result.cancellation_details.error_details}")
        except Exception as e:
            raise Exception(f"Transcription error: {str(e)}")


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

    def extract_summary(self, text: str, language: str = "en") -> str:
        """Extract summary from text."""
        try:
            # For MVP, we'll use a simple extractive summarization approach
            # Split text into sentences and take key ones
            sentences = text.split('. ')

            if len(sentences) <= 3:
                return text

            # Simple heuristic: take first and last sentence + longest sentence
            summary_sentences = [sentences[0]]
            longest_idx = 0
            longest_len = len(sentences[0])

            for i, sent in enumerate(sentences[1:-1], 1):
                if len(sent) > longest_len:
                    longest_len = len(sent)
                    longest_idx = i

            if longest_idx not in [0, len(sentences) - 1]:
                summary_sentences.append(sentences[longest_idx])

            summary_sentences.append(sentences[-1])
            summary = '. '.join(summary_sentences)

            if not summary.endswith('.'):
                summary += '.'

            return summary
        except Exception as e:
            raise Exception(f"Summarization error: {str(e)}")


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

    def transcribe_and_summarize(self, audio_file_path: str,
                                 language: str = "en-US") -> tuple[str, str]:
        """Transcribe audio file and generate summary."""
        try:
            # Step 1: Transcribe
            transcript = self.speech_client.transcribe_file(audio_file_path, language)

            # Step 2: Summarize
            summary = self.text_client.extract_summary(transcript, language[:2])

            return transcript, summary
        except Exception as e:
            raise Exception(f"Processing failed: {str(e)}")
