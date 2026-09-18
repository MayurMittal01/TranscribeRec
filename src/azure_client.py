"""Azure AI Foundry client wrapper for speech and text services."""

import os
from typing import Optional
from config import (
    AZURE_SPEECH_KEY, AZURE_SPEECH_REGION,
    AZURE_TEXT_ANALYTICS_ENDPOINT, AZURE_TEXT_ANALYTICS_KEY
)

class AzureSpeechClient:
    """Wrapper for Azure Speech-to-Text service."""

    def __init__(self):
        """Initialize Azure Speech client."""
        self.api_key = AZURE_SPEECH_KEY
        self.region = AZURE_SPEECH_REGION

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

    def __init__(self):
        """Initialize Azure Text Analytics client."""
        self.endpoint = AZURE_TEXT_ANALYTICS_ENDPOINT
        self.api_key = AZURE_TEXT_ANALYTICS_KEY

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

    def __init__(self):
        """Initialize Azure Foundry client."""
        self.speech_client = AzureSpeechClient()
        self.text_client = AzureTextAnalyticsClient()

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
