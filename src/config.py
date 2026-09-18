"""Configuration and constants for TranscribeRec application."""

import os
from dotenv import load_dotenv

load_dotenv()

# Azure Configuration. These are the fallback used when the sidebar form is
# left blank; they are never the only source of credentials at runtime.
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
AZURE_TEXT_ANALYTICS_ENDPOINT = os.getenv("AZURE_TEXT_ANALYTICS_ENDPOINT")
AZURE_TEXT_ANALYTICS_KEY = os.getenv("AZURE_TEXT_ANALYTICS_KEY")


def env_credentials() -> dict[str, str]:
    """Return Azure credentials sourced from the environment, blanks where unset."""
    return {
        "speech_key": AZURE_SPEECH_KEY or "",
        "speech_region": AZURE_SPEECH_REGION or "",
        "text_analytics_endpoint": AZURE_TEXT_ANALYTICS_ENDPOINT or "",
        "text_analytics_key": AZURE_TEXT_ANALYTICS_KEY or "",
    }

# Application Configuration
APP_NAME = os.getenv("APP_NAME", "TranscribeRec")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Database Configuration
DATABASE_PATH = "data/transcribe_rec.db"
UPLOADS_PATH = "data/uploads"

# File Upload Configuration
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB

# WAV only: the Speech SDK's AudioConfig(filename=...) decodes WAV/PCM natively,
# and every other container needs GStreamer binaries on PATH.
ALLOWED_AUDIO_FORMATS = ["wav"]
AUDIO_FORMAT_HELP = (
    "WAV only (16 kHz, 16-bit, mono PCM). Azure Speech reads WAV directly; "
    "MP3, M4A, FLAC and OGG need a GStreamer runtime on PATH, so they are "
    "not accepted here. Convert to WAV before uploading."
)

# Processing Configuration
SUPPORTED_LANGUAGES = {
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "es-ES": "Spanish",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
}
DEFAULT_LANGUAGE = "en-US"
