"""Utility functions for TranscribeRec."""

import os
import shutil
from datetime import datetime
from typing import Optional
from config import UPLOADS_PATH, MAX_FILE_SIZE, ALLOWED_AUDIO_FORMATS


def save_uploaded_file(uploaded_file) -> tuple[str, int]:
    """Save uploaded file to disk and return path and size."""
    if uploaded_file is None:
        raise ValueError("No file provided")

    # Check file size
    file_size = len(uploaded_file.getbuffer())
    if file_size > MAX_FILE_SIZE:
        raise ValueError(f"File size exceeds {MAX_FILE_SIZE / (1024*1024):.0f}MB limit")

    # Check file format
    file_ext = uploaded_file.name.split('.')[-1].lower()
    if file_ext not in ALLOWED_AUDIO_FORMATS:
        raise ValueError(f"Unsupported format. Allowed: {', '.join(ALLOWED_AUDIO_FORMATS)}")

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{uploaded_file.name}"
    file_path = os.path.join(UPLOADS_PATH, filename)

    # Save file
    os.makedirs(UPLOADS_PATH, exist_ok=True)
    with open(file_path, 'wb') as f:
        f.write(uploaded_file.getbuffer())

    return file_path, file_size


def format_timestamp(timestamp_str: str) -> str:
    """Format timestamp for display."""
    if timestamp_str is None:
        return "Pending"
    try:
        dt = datetime.fromisoformat(timestamp_str)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return timestamp_str


def format_file_size(size_bytes: int) -> str:
    """Format file size for display."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        file_size /= 1024
    return f"{size_bytes:.2f} GB"


def cleanup_old_files(hours: int = 24) -> None:
    """Remove uploaded files older than specified hours."""
    import time
    current_time = time.time()
    cutoff_time = current_time - (hours * 3600)

    if not os.path.exists(UPLOADS_PATH):
        return

    for filename in os.listdir(UPLOADS_PATH):
        file_path = os.path.join(UPLOADS_PATH, filename)
        if os.path.isfile(file_path):
            file_time = os.path.getmtime(file_path)
            if file_time < cutoff_time:
                try:
                    os.remove(file_path)
                except Exception as e:
                    print(f"Error removing file {filename}: {e}")
