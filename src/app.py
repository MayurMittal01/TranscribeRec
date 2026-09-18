"""Main Streamlit application for TranscribeRec."""

import streamlit as st
import os
import sys

# Add src directory to path
sys.path.insert(0, os.path.dirname(__file__))

from config import APP_NAME, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from database import Database
from azure_client import AzureFoundryClient
from utils import save_uploaded_file, format_timestamp, cleanup_old_files

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

if 'azure_client' not in st.session_state:
    try:
        st.session_state.azure_client = AzureFoundryClient()
    except ValueError as e:
        st.error(f"Azure configuration error: {str(e)}")
        st.info("Please configure Azure credentials in .env file")


def main():
    """Main application."""
    st.title("🎤 " + APP_NAME)
    st.markdown("Transcribe and Summarize Voice Recordings with Azure AI")

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

        if st.button("🚀 Process Recording", type="primary"):
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
        recording = st.session_state.db.get_recording(recording_id)
        transcription = st.session_state.db.get_transcription(recording_id)
        transcription_id = transcription['id']

        # Transcribe and summarize
        progress_bar = st.progress(0, text="Processing audio...")

        try:
            progress_bar.progress(50, text="Transcribing audio...")
            transcript, summary = st.session_state.azure_client.transcribe_and_summarize(
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
            st.session_state.db.update_transcription_error(
                transcription_id,
                str(e)
            )
            st.error(f"❌ Processing failed: {str(e)}")

    except ValueError as e:
        st.error(f"❌ File error: {str(e)}")
    except Exception as e:
        st.error(f"❌ Unexpected error: {str(e)}")


def history_page():
    """History and results page."""
    st.header("📜 Processing History")

    # Cleanup old files periodically
    cleanup_old_files(hours=24)

    recordings = st.session_state.db.get_recordings()

    if not recordings:
        st.info("No recordings yet. Start by uploading an audio file!")
        return

    # Create table
    for recording in recordings:
        recording_id = recording['id']
        transcription = st.session_state.db.get_transcription(recording_id)
        summary = None

        if transcription and transcription['id']:
            summary = st.session_state.db.get_summary(transcription['id'])

        with st.expander(
            f"📁 {recording['filename']} - {format_timestamp(recording['upload_date'])}"
        ):
            col1, col2 = st.columns(2)

            with col1:
                st.write(f"**Upload Date:** {format_timestamp(recording['upload_date'])}")
                st.write(f"**Language:** {recording['language']}")

            with col2:
                st.write(f"**Status:** {transcription['status'].upper()}")

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

            if transcription['error_message']:
                st.error(f"Error: {transcription['error_message']}")


if __name__ == "__main__":
    main()
