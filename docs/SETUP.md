# Setup Guide

This guide will help you set up the TranscribeRec application for development and deployment.

## Prerequisites

- Python 3.8 or higher
- Azure Subscription
- Git

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/MayurMittal01/TranscribeRec.git
cd TranscribeRec
```

### 2. Create Virtual Environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Azure Services Setup

#### Create Azure Resources

1. Go to [Azure Portal](https://portal.azure.com)
2. Create a new Resource Group
3. Create the following resources in that Resource Group:
   - **Speech Services**: For speech-to-text transcription
   - **Text Analytics**: For text summarization

#### Get Credentials

For **Speech Services**:
- Navigate to your Speech Services resource
- Go to "Keys and Endpoint" in the left sidebar
- Copy `Key 1` (or `Key 2`)
- Copy the `Region` (e.g., "eastus")

For **Text Analytics**:
- Navigate to your Text Analytics resource
- Go to "Keys and Endpoint" in the left sidebar
- Copy `Key 1` (or `Key 2`)
- Copy the `Endpoint`

### 5. Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit .env with your credentials
# AZURE_SPEECH_KEY=your_speech_key
# AZURE_SPEECH_REGION=eastus
# AZURE_TEXT_ANALYTICS_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
# AZURE_TEXT_ANALYTICS_KEY=your_analytics_key
```

## Running the Application

### Development

```bash
streamlit run src/app.py
```

The application will be available at `http://localhost:8501`

### Deployment (Example: Streamlit Cloud)

1. Push your code to GitHub (with `.env` added to `.gitignore`)
2. Go to [Streamlit Cloud](https://streamlit.io/cloud)
3. Create a new app from your GitHub repository
4. Add secrets in the Streamlit Cloud dashboard matching your `.env` file

## Testing

### Run Unit Tests

```bash
pytest tests/
```

### Manual Testing

1. Upload a test audio file
2. Verify transcription appears correctly
3. Verify summary is generated
4. Check database entries in `data/transcribe_rec.db`

## Troubleshooting

### Azure Authentication Failed
- Verify credentials in `.env` file
- Check that resources exist in Azure portal
- Ensure API keys have sufficient permissions

### File Upload Fails
- Check file size (max 25MB)
- Verify file format is supported (wav, mp3, m4a, flac, ogg)
- Check disk space in `data/uploads/` directory

### Database Errors
- Delete `data/transcribe_rec.db` to reset (will lose all records)
- Check file permissions in `data/` directory

## Project Structure

```
TranscribeRec/
├── src/
│   ├── app.py              # Main Streamlit application
│   ├── config.py           # Configuration
│   ├── database.py         # Database operations
│   ├── azure_client.py     # Azure SDK wrapper
│   └── utils.py            # Utility functions
├── data/
│   └── uploads/            # Temporary audio files
├── tests/                  # Unit tests
├── docs/                   # Documentation
├── requirements.txt        # Python dependencies
└── .env.example            # Environment variable template
```

## Next Steps

- Review [Architecture](ARCHITECTURE.md) for system design details
- Check [API Integration](API_INTEGRATION.md) for Azure service details
- Read the [README](../README.md) for feature overview
