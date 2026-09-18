# Azure AI Foundry Integration Guide

## Overview

This guide explains how TranscribeRec integrates with Azure Cognitive Services (Speech-to-Text and Text Analytics).

## Prerequisites

- Azure Subscription
- Azure CLI (optional)
- Resource Group created

## Step 1: Create Speech Services Resource

### Via Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Click "Create a resource"
3. Search for "Speech"
4. Select "Speech" (Microsoft)
5. Click "Create"
6. Fill in the details:
   - **Subscription**: Select your subscription
   - **Resource Group**: Select or create one
   - **Region**: Choose closest region (e.g., East US, West US)
   - **Name**: e.g., `transcribe-rec-speech`
   - **Pricing Tier**: Select "Free" (F0) for testing or "Standard" (S0) for production
7. Click "Create"

### Via Azure CLI

```bash
az cognitiveservices account create \
  --name transcribe-rec-speech \
  --resource-group your-rg \
  --kind Speech \
  --sku F0 \
  --location eastus
```

### Get Credentials

```bash
# Get keys
az cognitiveservices account keys list \
  --name transcribe-rec-speech \
  --resource-group your-rg
```

In the portal:
1. Go to your Speech resource
2. Click "Keys and Endpoint" in left sidebar
3. Copy `Key 1` and `Endpoint Region`

## Step 2: Create Text Analytics Resource

### Via Azure Portal

1. Go to [Azure Portal](https://portal.azure.com)
2. Click "Create a resource"
3. Search for "Text Analytics"
4. Select "Text Analytics" (Microsoft)
5. Click "Create"
6. Fill in the details:
   - **Subscription**: Select your subscription
   - **Resource Group**: Same as Speech Services
   - **Region**: Same as Speech Services
   - **Name**: e.g., `transcribe-rec-analytics`
   - **Pricing Tier**: Select "Free" (F0) for testing or "Standard" (S) for production
7. Click "Create"

### Get Credentials

In the portal:
1. Go to your Text Analytics resource
2. Click "Keys and Endpoint" in left sidebar
3. Copy `Key 1` and `Endpoint`

## Step 3: Configure Application

### Update .env File

```bash
# Speech Services
AZURE_SPEECH_KEY=your_key_from_speech_resource
AZURE_SPEECH_REGION=eastus

# Text Analytics
AZURE_TEXT_ANALYTICS_ENDPOINT=https://your-text-analytics-resource.cognitiveservices.azure.com/
AZURE_TEXT_ANALYTICS_KEY=your_key_from_text_analytics_resource
```

### Verify Configuration

```python
from src.azure_client import AzureFoundryClient

try:
    client = AzureFoundryClient()
    print("✓ Azure services configured correctly")
except ValueError as e:
    print(f"✗ Configuration error: {e}")
```

## API Details

### Speech-to-Text API

**Service**: Azure Cognitive Services - Speech

**Endpoint**: `https://{region}.tts.speech.microsoft.com`

**Method**: REST API or SDK

**Supported Languages**:
- English (US, UK, Canada, Australia, India)
- Spanish
- French
- German
- Italian
- Portuguese
- Chinese (Mandarin, Cantonese)
- And 90+ more

**Audio Formats**:
- WAV
- MP3
- OGG
- FLAC

**Request Example**:
```python
import azure.cognitiveservices.speech as speechsdk

speech_config = speechsdk.SpeechConfig(
    subscription="your_key",
    region="eastus"
)
audio_config = speechsdk.audio.AudioConfig(filename="audio.wav")
recognizer = speechsdk.SpeechRecognizer(
    speech_config=speech_config,
    audio_config=audio_config
)
result = recognizer.recognize_once()
```

**Response**:
```python
{
    "text": "The transcribed text from the audio",
    "duration": 12345,  # milliseconds
    "offset": 0
}
```

### Text Analytics API

**Service**: Azure Cognitive Services - Text Analytics

**Endpoint**: `https://{region}.api.cognitive.microsoft.com/`

**Method**: REST API or SDK

**Supported Operations**:
- Summarization (Extractive & Abstractive)
- Key Phrase Extraction
- Sentiment Analysis
- Language Detection

**Request Example**:
```python
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential

client = TextAnalyticsClient(
    endpoint="https://your-resource.cognitiveservices.azure.com/",
    credential=AzureKeyCredential("your_key")
)

response = client.extract_summary(
    documents=["Your text to summarize..."],
    language="en"
)
```

**Response**:
```python
[
    {
        "sentences": [
            {"text": "Summary sentence 1.", "rank_score": 0.95},
            {"text": "Summary sentence 2.", "rank_score": 0.87}
        ]
    }
]
```

## Pricing

### Speech Services (F0 - Free Tier)
- 5 concurrent requests
- 600 minutes of speech-to-text per month
- $0

### Speech Services (S0 - Standard)
- 100 concurrent requests
- $1 per hour of audio processed
- Billed monthly

### Text Analytics (F0 - Free Tier)
- 5,000 records per month
- $0

### Text Analytics (S - Standard)
- $1 per 1,000 records
- Billed monthly

## Rate Limiting

### Speech Services
- Requests per second: Depends on tier
- Maximum audio length: No limit
- Concurrent requests: 5 (F0) / 100 (S0)

### Text Analytics
- Requests per second: 100 (F0) / 1,000 (S0)
- Document size: Max 5,120 characters

## Error Handling

### Common Errors

**401 - Unauthorized**
```
Cause: Invalid API key or region
Solution: Verify AZURE_SPEECH_KEY and AZURE_SPEECH_REGION in .env
```

**403 - Forbidden**
```
Cause: Resource quota exceeded
Solution: Upgrade tier or wait for quota reset
```

**429 - Too Many Requests**
```
Cause: Rate limit exceeded
Solution: Implement retry logic with exponential backoff
```

**500 - Internal Server Error**
```
Cause: Azure service issue
Solution: Retry request, contact Azure support if persistent
```

## Best Practices

1. **Store Credentials Securely**
   - Never commit `.env` file
   - Use Azure Key Vault for production

2. **Implement Retries**
   - Use exponential backoff for transient failures
   - Max 3 retries with 1s, 2s, 4s delays

3. **Monitor Usage**
   - Track API calls and costs in Azure portal
   - Set up budget alerts
   - Use Application Insights for monitoring

4. **Optimize Performance**
   - Cache results when possible
   - Use appropriate audio format
   - Batch requests for text analytics

5. **Handle Errors Gracefully**
   - Provide user-friendly error messages
   - Log detailed errors for debugging
   - Implement fallback mechanisms

## Testing

### Test Speech-to-Text

```bash
python -c "
from src.azure_client import AzureSpeechClient
client = AzureSpeechClient()
result = client.transcribe_file('test_audio.wav')
print(f'Transcription: {result}')
"
```

### Test Text Analytics

```bash
python -c "
from src.azure_client import AzureTextAnalyticsClient
client = AzureTextAnalyticsClient()
text = 'This is a test document that needs summarization.'
summary = client.extract_summary(text)
print(f'Summary: {summary}')
"
```

## Troubleshooting

### Issue: "No module named 'azure.cognitiveservices.speech'"
```bash
pip install azure-cognitiveservices-speech
```

### Issue: "Invalid subscription key"
- Check API key hasn't expired
- Verify region matches resource location
- Ensure key has sufficient permissions

### Issue: "Audio codec not supported"
- Convert audio to supported format (WAV, MP3, OGG, FLAC)
- Use FFmpeg: `ffmpeg -i input.m4a -c:a pcm_s16le -ac 1 output.wav`

### Issue: Timeout during processing
- Check network connectivity
- Verify Azure service is accessible
- Check Azure service status
- Implement longer timeout values

## Resources

- [Speech Services Documentation](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/)
- [Text Analytics Documentation](https://learn.microsoft.com/en-us/azure/cognitive-services/text-analytics/)
- [Azure CLI Documentation](https://learn.microsoft.com/en-us/cli/azure/)
- [Pricing Calculator](https://azure.microsoft.com/en-us/pricing/calculator/)
