"""Configuration and constants for TranscribeRec application."""

import os
from dotenv import load_dotenv

load_dotenv()

# Azure Configuration
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION", "eastus")
AZURE_TEXT_ANALYTICS_ENDPOINT = os.getenv("AZURE_TEXT_ANALYTICS_ENDPOINT")
AZURE_TEXT_ANALYTICS_KEY = os.getenv("AZURE_TEXT_ANALYTICS_KEY")

# Application Configuration
APP_NAME = os.getenv("APP_NAME", "TranscribeRec")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Database Configuration
DATABASE_PATH = "data/transcribe_rec.db"
UPLOADS_PATH = "data/uploads"

# File Upload Configuration
MAX_FILE_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_AUDIO_FORMATS = ["wav", "mp3", "m4a", "flac", "ogg"]

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
