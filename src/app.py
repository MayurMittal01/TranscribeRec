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
    APP_NAME, ALLOWED_AUDIO_FORMATS, AUDIO_FORMAT_HELP, UPLOAD_LIMIT_HELP,
    SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, env_credentials
)
from src.database import Database
from src.azure_client import AzureFoundryClient, sanitize_azure_error
from src.utils import (
    save_uploaded_file, format_timestamp, format_file_size, cleanup_old_files,
    estimate_wav_duration, format_duration
)

SPEECH_FIELDS = ("speech_key", "speech_region")
TEXT_ANALYTICS_FIELDS = ("text_analytics_endpoint", "text_analytics_key")
CREDENTIAL_FIELDS = SPEECH_FIELDS + TEXT_ANALYTICS_FIELDS

STAGE_LABELS = {
    "transcribing": "Transcribing audio with Azure Speech — this runs the whole "
                    "recording and can take a minute or more...",
    "summarizing": "Summarizing the transcript with Azure Text Analytics...",
}

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

def get_db() -> Database:
    """Return a database handle.

    Deliberately not cached in session state: a cached instance survives
    Streamlit's hot reload and then lacks any method added to the class since
    it was built, which surfaces as a spurious AttributeError mid-run.
    """
    return Database()


get_db()


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


def speech_ready() -> bool:
    """True when Azure Speech credentials are present, so transcription can run."""
    credentials = resolve_credentials()
    return all(credentials[field] for field in SPEECH_FIELDS)


def text_analytics_ready() -> bool:
    """True when Azure Text Analytics credentials are present, so summarization can run."""
    credentials = resolve_credentials()
    return all(credentials[field] for field in TEXT_ANALYTICS_FIELDS)


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

    can_transcribe = speech_ready()
    if not can_transcribe:
        st.warning(
            "Azure Speech credentials are missing, so transcription cannot run. "
            "Enter the Speech key and region in the sidebar (or set them in .env)."
        )
    elif not text_analytics_ready():
        st.info(
            "Transcription is ready. Summarization is unavailable — Azure Text "
            "Analytics is not configured, so recordings will be transcribed and "
            "the summary step skipped. Add Text Analytics credentials in the "
            "sidebar to enable it."
        )

    col1, col2 = st.columns([2, 1])

    with col1:
        uploaded_file = st.file_uploader(
            "Choose an audio file",
            type=ALLOWED_AUDIO_FORMATS,
            help=f"{AUDIO_FORMAT_HELP} {UPLOAD_LIMIT_HELP}"
        )
        st.caption(f"{AUDIO_FORMAT_HELP} {UPLOAD_LIMIT_HELP}")

    with col2:
        language = st.selectbox(
            "Select Language",
            options=list(SUPPORTED_LANGUAGES.keys()),
            format_func=lambda x: SUPPORTED_LANGUAGES[x],
            index=list(SUPPORTED_LANGUAGES.keys()).index(DEFAULT_LANGUAGE)
        )

    if uploaded_file is not None:
        st.success(f"✓ File selected: {uploaded_file.name}")
        render_upload_estimate(uploaded_file)

        if st.button("🚀 Process Recording", type="primary",
                     disabled=not can_transcribe):
            process_recording(uploaded_file, language)

    render_last_run()


def render_upload_estimate(uploaded_file) -> None:
    """Show the selected file's size and approximate audio duration."""
    size_text = format_file_size(len(uploaded_file.getbuffer()))
    duration = estimate_wav_duration(uploaded_file)

    if duration is None:
        st.caption(f"Size: {size_text}. Duration could not be read from the WAV header.")
        return

    st.info(
        f"Size: {size_text} — approximately {format_duration(duration)} of audio. "
        "Azure Speech streams the recording in real time, so transcription takes "
        "roughly as long as the audio itself and is billed for the full duration."
    )


def process_recording(uploaded_file, language: str) -> None:
    """Process the uploaded recording, persisting each stage the moment it completes."""
    st.session_state.pop("last_run", None)
    run: dict[str, object] = {}

    try:
        with st.status("Saving upload...", expanded=True) as status:
            file_path, file_size = save_uploaded_file(uploaded_file)

            recording_id = get_db().add_recording(
                uploaded_file.name,
                file_path,
                file_size,
                language
            )
            transcription_id = get_db().get_transcription(recording_id)['id']
            run = {"recording_id": recording_id, "filename": uploaded_file.name}

            def report_stage(stage: str) -> None:
                """Update the status label as the Azure pipeline moves between stages."""
                status.update(label=STAGE_LABELS.get(stage, stage))

            def save_transcript(transcript: str) -> None:
                """Commit the transcript before summarization is attempted."""
                get_db().update_transcription(
                    transcription_id,
                    transcript,
                    "completed"
                )

            try:
                azure_client = build_azure_client()
                result = azure_client.transcribe_and_summarize(
                    file_path,
                    language,
                    on_stage=report_stage,
                    on_transcript=save_transcript,
                )

                status.update(label="Saving results...")
                summary_id = get_db().add_summary(transcription_id)
                if result.summary_skipped:
                    get_db().update_summary_skipped(
                        summary_id, result.summary_skipped
                    )
                    st.session_state.azure_status = ("ok", "")
                    status.update(
                        label="Transcribed — summarization skipped",
                        state="complete",
                        expanded=False,
                    )
                elif result.summary_error:
                    get_db().update_summary_error(summary_id, result.summary_error)
                    st.session_state.azure_status = ("error", result.summary_error)
                    status.update(
                        label="Transcribed — summary failed",
                        state="error",
                        expanded=False,
                    )
                else:
                    get_db().update_summary(summary_id, result.summary, "completed")
                    st.session_state.azure_status = ("ok", "")
                    status.update(label="Done", state="complete", expanded=False)

                run.update(
                    transcript=result.transcript,
                    summary=result.summary,
                    summary_error=result.summary_error,
                    summary_skipped=result.summary_skipped,
                )

            except Exception as e:
                failure = sanitize_azure_error(e, _secret_values())
                partial = getattr(e, "partial_transcript", "") or ""
                get_db().update_transcription_error(
                    transcription_id, failure, partial or None
                )
                st.session_state.azure_status = ("error", failure)
                status.update(label="Processing failed", state="error", expanded=False)
                run.update(transcript=partial, error=failure)

    except ValueError as e:
        run["error"] = f"File error: {sanitize_azure_error(e, _secret_values())}"
    except OSError as e:
        run["error"] = (
            f"Could not save the upload: {sanitize_azure_error(e, _secret_values())}"
        )
    except Exception as e:
        run["error"] = f"Unexpected error: {sanitize_azure_error(e, _secret_values())}"

    st.session_state.last_run = run


def render_last_run() -> None:
    """Render the most recent processing outcome from session state.

    Results live in session state because st.download_button triggers a rerun, on
    which the Process button is False and locals from the run are gone.
    """
    run = st.session_state.get("last_run")
    if not run:
        return

    recording_id = run.get("recording_id")
    transcript = run.get("transcript")
    summary = run.get("summary")

    if run.get("error"):
        st.error(f"❌ Processing failed: {run['error']}")

    if transcript:
        if not run.get("error") and not run.get("summary_error"):
            st.success("✓ Processing complete!")

        st.subheader("📝 Transcription")
        st.text_area("Transcript", transcript, height=150, disabled=True,
                     key="last_run_transcript")
        st.download_button(
            label="📥 Download Transcript (TXT)",
            data=transcript,
            file_name=f"transcript_{recording_id}.txt",
            mime="text/plain",
            key="last_run_download_transcript",
        )

    if run.get("summary_skipped"):
        st.info(
            f"ℹ️ Summarization was skipped — {run['summary_skipped']}. "
            "The transcript above is complete."
        )
    elif run.get("summary_error"):
        st.warning(
            "⚠️ The transcript was saved, but summarization failed: "
            f"{run['summary_error']}"
        )
    elif summary:
        st.subheader("📊 Summary")
        st.text_area("Summary", summary, height=100, disabled=True,
                     key="last_run_summary")
        st.download_button(
            label="📥 Download Summary (TXT)",
            data=summary,
            file_name=f"summary_{recording_id}.txt",
            mime="text/plain",
            key="last_run_download_summary",
        )


def history_page():
    """History and results page."""
    st.header("📜 Processing History")

    # Cleanup old files periodically
    cleanup_old_files(hours=24)

    recordings = get_db().get_recordings()

    if not recordings:
        st.info("No recordings yet. Start by uploading an audio file!")
        return

    for recording in recordings:
        recording_id = recording['id']
        transcription = get_db().get_transcription(recording_id)
        summary = None

        if transcription:
            summary = get_db().get_summary(transcription['id'])

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

            if summary and summary['status'] == 'skipped':
                st.info(
                    "Summarization skipped — "
                    f"{summary['error_message'] or 'not attempted'}."
                )
            elif summary and summary['error_message']:
                st.warning(
                    "Transcript saved, but summarization failed: "
                    f"{summary['error_message']}"
                )
            elif summary and summary['summary_text']:
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
                if transcription['status'] == 'partial':
                    st.warning(
                        "Partial transcript — transcription did not finish: "
                        f"{transcription['error_message']}"
                    )
                else:
                    st.error(f"Error: {transcription['error_message']}")


if __name__ == "__main__":
    main()
