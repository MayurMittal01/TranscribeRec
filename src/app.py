"""Main Streamlit application for TranscribeRec."""

import os
import sys

# `streamlit run src/app.py` puts src/ on sys.path but not the repo root, so the
# src package is not importable until its parent directory is added.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from src.config import (
    APP_NAME, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, env_credentials
)
from src.database import Database
from src.azure_client import AzureFoundryClient, sanitize_azure_error
from src.utils import save_uploaded_file, format_timestamp, cleanup_old_files

CREDENTIAL_FIELDS = (
    "speech_key",
    "speech_region",
    "text_analytics_endpoint",
    "text_analytics_key",
)

# Page configuration
st.set_page_config(
    page_title=APP_NAME,
    page_icon="🎤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stButton > button {
        width: 100%;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize session state
if 'db' not in st.session_state:
    st.session_state.db = Database()


def _widget_key(field: str) -> str:
    """Session state key holding the sidebar input for a credential field."""
    return f"cred_{field}"


def resolve_credentials() -> dict[str, str]:
    """Merge sidebar credentials over .env values; a blank sidebar field falls back."""
    env = env_credentials()
    resolved = {}
    for field in CREDENTIAL_FIELDS:
        entered = (st.session_state.get(_widget_key(field)) or "").strip()
        resolved[field] = entered or env[field]
    return resolved


def _secret_values() -> tuple[str, ...]:
    """Current secret values, used to scrub them out of Azure error messages."""
    credentials = resolve_credentials()
    return (credentials["speech_key"], credentials["text_analytics_key"])


def credentials_ready() -> bool:
    """True when every credential needed to reach both Azure services is present."""
    return all(resolve_credentials()[field] for field in CREDENTIAL_FIELDS)


def clear_credentials() -> None:
    """Blank every sidebar credential input and drop the cached connection status."""
    for field in CREDENTIAL_FIELDS:
        st.session_state[_widget_key(field)] = ""
    st.session_state.pop("azure_status", None)


def build_azure_client() -> AzureFoundryClient:
    """Construct an Azure client from the credentials currently in effect."""
    credentials = resolve_credentials()
    return AzureFoundryClient(
        speech_key=credentials["speech_key"],
        speech_region=credentials["speech_region"],
        text_analytics_endpoint=credentials["text_analytics_endpoint"],
        text_analytics_key=credentials["text_analytics_key"],
    )


def render_credential_sidebar() -> None:
    """Render the Azure credential form and connection status in the sidebar."""
    st.sidebar.title("🔑 Azure Credentials")
    st.sidebar.caption(
        "Values stay in this browser session only — nothing is written to disk, "
        "to .env, or to the database. Leave a field blank to use the .env value. "
        "For shared or hosted deployments use platform secrets instead of this form."
    )

    with st.sidebar.form("azure_credentials"):
        st.text_input("Speech key", type="password", key=_widget_key("speech_key"))
        st.text_input(
            "Speech region",
            key=_widget_key("speech_region"),
            placeholder="eastus",
        )
        st.text_input(
            "Text Analytics endpoint",
            key=_widget_key("text_analytics_endpoint"),
            placeholder="https://<resource>.cognitiveservices.azure.com/",
        )
        st.text_input("Text Analytics key", type="password",
                      key=_widget_key("text_analytics_key"))
        st.form_submit_button("Apply for this session")

    st.sidebar.button("🧹 Clear credentials", on_click=clear_credentials)
    render_connection_status()


def render_connection_status() -> None:
    """Show which services are configured and the last Azure outcome, without values."""
    credentials = resolve_credentials()

    st.sidebar.subheader("Connection status")

    for label, fields in (
        ("Speech", ("speech_key", "speech_region")),
        ("Text Analytics", ("text_analytics_endpoint", "text_analytics_key")),
    ):
        if any(not credentials[field] for field in fields):
            st.sidebar.warning(f"{label}: not configured")
            continue
        from_session = [
            bool((st.session_state.get(_widget_key(field)) or "").strip())
            for field in fields
        ]
        if all(from_session):
            source = "sidebar"
        elif any(from_session):
            source = "sidebar + environment"
        else:
            source = "environment"
        st.sidebar.success(f"{label}: configured ({source})")

    status = st.session_state.get("azure_status")
    if status:
        state, message = status
        if state == "ok":
            st.sidebar.info("Last Azure call: succeeded")
        else:
            st.sidebar.error(f"Last Azure call failed: {message}")


def main():
    """Main application."""
    st.title("🎤 " + APP_NAME)
    st.markdown("Transcribe and Summarize Voice Recordings with Azure AI")

    render_credential_sidebar()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Upload & Process", "History"]
    )

    if page == "Upload & Process":
        upload_page()
    elif page == "History":
        history_page()


def upload_page():
    """Upload and process page."""
    st.header("📤 Upload Voice Recording")

    ready = credentials_ready()
    if not ready:
        st.warning(
            "Azure credentials are incomplete. Enter them in the sidebar "
            "(or set them in .env) to enable processing."
        )

    col1, col2 = st.columns([2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "Choose an audio file",
            type=["wav", "mp3", "m4a", "flac", "ogg"],
            help="Supported formats: WAV, MP3, M4A, FLAC, OGG"
        )

    with col2:
        language = st.selectbox(
            "Select Language",
            options=list(SUPPORTED_LANGUAGES.keys()),
            format_func=lambda x: SUPPORTED_LANGUAGES[x],
            index=list(SUPPORTED_LANGUAGES.keys()).index(DEFAULT_LANGUAGE)
        )

    if uploaded_file is not None:
        st.success(f"✓ File selected: {uploaded_file.name}")

        if st.button("🚀 Process Recording", type="primary", disabled=not ready):
            process_recording(uploaded_file, language)


def process_recording(uploaded_file, language: str):
    """Process the uploaded recording."""
    try:
        # Save file
        with st.spinner("Saving file..."):
            file_path, file_size = save_uploaded_file(uploaded_file)
            st.success("✓ File saved")

        # Add to database
        recording_id = st.session_state.db.add_recording(
            uploaded_file.name,
            file_path,
            file_size,
            language
        )

        # Get transcription record
        transcription = st.session_state.db.get_transcription(recording_id)
        transcription_id = transcription['id']

        # Transcribe and summarize
        progress_bar = st.progress(0, text="Processing audio...")

        try:
            azure_client = build_azure_client()

            progress_bar.progress(50, text="Transcribing audio...")
            transcript, summary = azure_client.transcribe_and_summarize(
                file_path,
                language
            )

            # Update transcription
            st.session_state.db.update_transcription(
                transcription_id,
                transcript,
                "completed"
            )

            # Add and update summary
            progress_bar.progress(75, text="Generating summary...")
            summary_id = st.session_state.db.add_summary(transcription_id)
            st.session_state.db.update_summary(summary_id, summary, "completed")

            progress_bar.progress(100, text="Complete!")
            st.session_state.azure_status = ("ok", "")
            st.success("✓ Processing complete!")

            # Display results
            st.subheader("📝 Transcription")
            st.text_area("Transcript", transcript, height=150, disabled=True)

            st.subheader("📊 Summary")
            st.text_area("Summary", summary, height=100, disabled=True)

            # Download options
            col1, col2 = st.columns(2)
            with col1:
                st.download_button(
                    label="📥 Download Transcript (TXT)",
                    data=transcript,
                    file_name=f"transcript_{recording_id}.txt",
                    mime="text/plain"
                )
            with col2:
                st.download_button(
                    label="📥 Download Summary (TXT)",
                    data=summary,
                    file_name=f"summary_{recording_id}.txt",
                    mime="text/plain"
                )

        except Exception as e:
            message = sanitize_azure_error(e, _secret_values())
            st.session_state.db.update_transcription_error(transcription_id, message)
            st.session_state.azure_status = ("error", message)
            st.error(f"❌ Processing failed: {message}")

    except ValueError as e:
        st.error(f"❌ File error: {str(e)}")
    except OSError as e:
        st.error(f"❌ Could not save the upload: {str(e)}")
    except Exception as e:
        st.error(f"❌ Unexpected error: {sanitize_azure_error(e, _secret_values())}")


def history_page():
    """History and results page."""
    st.header("📜 Processing History")

    # Cleanup old files periodically
    cleanup_old_files(hours=24)

    recordings = st.session_state.db.get_recordings()

    if not recordings:
        st.info("No recordings yet. Start by uploading an audio file!")
        return

    for recording in recordings:
        recording_id = recording['id']
        transcription = st.session_state.db.get_transcription(recording_id)
        summary = None

        if transcription:
            summary = st.session_state.db.get_summary(transcription['id'])

        with st.expander(
            f"📁 {recording['filename']} - {format_timestamp(recording['upload_date'])}"
        ):
            col1, col2 = st.columns(2)

            with col1:
                st.write(f"**Upload Date:** {format_timestamp(recording['upload_date'])}")
                st.write(f"**Language:** {recording['language']}")

            with col2:
                status = (transcription or {}).get('status') or 'unknown'
                st.write(f"**Status:** {status.upper()}")

            if transcription and transcription['transcript']:
                st.subheader("Transcript")
                st.text_area(
                    "Transcript",
                    transcription['transcript'],
                    height=150,
                    disabled=True,
                    key=f"transcript_{recording_id}"
                )

                st.download_button(
                    label="📥 Download Transcript",
                    data=transcription['transcript'],
                    file_name=f"transcript_{recording_id}.txt",
                    mime="text/plain",
                    key=f"download_transcript_{recording_id}"
                )

            if summary and summary['summary_text']:
                st.subheader("Summary")
                st.text_area(
                    "Summary",
                    summary['summary_text'],
                    height=100,
                    disabled=True,
                    key=f"summary_{recording_id}"
                )

                st.download_button(
                    label="📥 Download Summary",
                    data=summary['summary_text'],
                    file_name=f"summary_{recording_id}.txt",
                    mime="text/plain",
                    key=f"download_summary_{recording_id}"
                )

            if transcription and transcription['error_message']:
                st.error(f"Error: {transcription['error_message']}")


if __name__ == "__main__":
    main()
