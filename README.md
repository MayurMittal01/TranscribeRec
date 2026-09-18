# Azure AI Foundry Voice Transcription & Summarization Portal

A Streamlit-based web application that leverages Azure AI Foundry to transcribe and summarize voice recordings.

## Features

- 🎤 **Audio Upload**: Easy-to-use interface for uploading voice recordings
- 📝 **Transcription**: Automated speech-to-text conversion using Azure Cognitive Services
- 📊 **Summarization**: Intelligent text summarization using Azure Text Analytics
- 💾 **History**: View and manage your transcriptions and summaries
- 📥 **Export**: Download transcriptions and summaries as text files

## Technology Stack

- **Frontend**: Streamlit
- **Backend**: Python with Azure SDK
- **Database**: SQLite
- **Cloud Services**: Azure Cognitive Services (Speech-to-Text, Text Analytics)

## Prerequisites

- Python 3.8+
- Azure Subscription
- Azure Cognitive Services resources:
  - Speech Services
  - Text Analytics

## Installation

1. Clone the repository:
```bash
git clone https://github.com/MayurMittal01/TranscribeRec.git
cd TranscribeRec
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your Azure credentials
```

## Running the Application

```bash
streamlit run src/app.py
```

The application will be available at `http://localhost:8501`

## Project Structure

```
TranscribeRec/
├── src/
│   ├── app.py                 # Main Streamlit application
│   ├── config.py              # Configuration and constants
│   ├── database.py            # SQLite operations
│   ├── azure_client.py        # Azure SDK wrapper
│   └── utils.py               # Helper functions
├── data/
│   ├── uploads/               # Temporary audio files
│   └── transcribe_rec.db      # SQLite database
├── tests/                     # Unit tests
├── docs/                      # Documentation
└── requirements.txt           # Python dependencies
```

## Documentation

- [Setup Guide](docs/SETUP.md) - Detailed installation and configuration
- [Architecture](docs/ARCHITECTURE.md) - System design and architecture
- [API Integration](docs/API_INTEGRATION.md) - Azure services integration details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions, please open an issue on GitHub or contact the maintainers.
