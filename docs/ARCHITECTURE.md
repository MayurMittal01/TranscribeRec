# System Architecture

## High-Level Overview

```
┌─────────────────────────────────────────────────────────┐
│              User Browser (Streamlit UI)               │
│                                                         │
│  ┌─────────────────────────────────────────────┐      │
│  │         Upload Recording Widget             │      │
│  │  • File picker                              │      │
│  │  • Language selection                       │      │
│  │  • Process button                           │      │
│  └─────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│            Streamlit Application (Python)              │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │  src/app.py                                      │  │
│  │  • File upload handling                          │  │
│  │  • Session management                            │  │
│  │  • UI rendering                                  │  │
│  └──────────────────────────────────────────────────┘  │
│                            ↓                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  src/database.py                                 │  │
│  │  • Recording storage                             │  │
│  │  • Transcription tracking                        │  │
│  │  • Summary persistence                           │  │
│  └──────────────────────────────────────────────────┘  │
│                            ↓                            │
│  ┌──────────────────────────────────────────────────┐  │
│  │  src/azure_client.py                             │  │
│  │  • Azure API communication                       │  │
│  │  • Error handling                                │  │
│  │  • Response processing                           │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
    ↓                                    ↓
┌──────────────────────┐    ┌──────────────────────────┐
│   Azure Cognitive    │    │  SQLite Database         │
│   Services           │    │                          │
├──────────────────────┤    ├──────────────────────────┤
│ • Speech-to-Text     │    │ • recordings table       │
│ • Text Analytics     │    │ • transcriptions table   │
└──────────────────────┘    │ • summaries table        │
                            └──────────────────────────┘
```

## Component Details

### 1. Frontend Layer (Streamlit)

**File**: `src/app.py`

- **Upload Page**: Handles audio file uploads and language selection
- **History Page**: Displays all processed recordings and results
- **UI Components**:
  - File uploader widget
  - Progress indicators
  - Text display areas
  - Download buttons

### 2. Application Layer

#### Configuration (`src/config.py`)
- Environment variable management
- Azure credentials
- Application constants
- File size and format restrictions

#### Database Layer (`src/database.py`)
- SQLite database operations
- Schema initialization
- CRUD operations for:
  - Recordings
  - Transcriptions
  - Summaries
- Foreign key relationships

#### Azure Integration (`src/azure_client.py`)
- **AzureSpeechClient**: Speech-to-Text API wrapper
  - Audio file transcription
  - Language support
  - Error handling

- **AzureTextAnalyticsClient**: Text Analytics API wrapper
  - Text summarization
  - Key phrase extraction (future)
  - Sentiment analysis (future)

- **AzureFoundryClient**: Unified interface
  - Orchestrates transcription and summarization
  - Error propagation

#### Utilities (`src/utils.py`)
- File upload processing
- File system operations
- Data formatting
- Cleanup routines

### 3. Data Layer

#### SQLite Database Schema

**recordings table**
```sql
id              INTEGER PRIMARY KEY
filename        TEXT (original filename)
file_path       TEXT (local storage path)
upload_date     TIMESTAMP
duration        REAL (audio duration in seconds)
file_size       INTEGER (bytes)
language        TEXT (language code)
```

**transcriptions table**
```sql
id              INTEGER PRIMARY KEY
recording_id    INTEGER FOREIGN KEY
transcript      TEXT (transcribed text)
status          TEXT (pending/processing/completed/failed)
created_at      TIMESTAMP
completed_at    TIMESTAMP
error_message   TEXT (if failed)
```

**summaries table**
```sql
id              INTEGER PRIMARY KEY
transcription_id INTEGER FOREIGN KEY
summary_text    TEXT (summarized text)
status          TEXT (pending/processing/completed/failed)
created_at      TIMESTAMP
completed_at    TIMESTAMP
summary_length  INTEGER (character count)
error_message   TEXT (if failed)
```

### 4. Cloud Layer (Azure)

#### Speech-to-Text Service
- Receives audio files from application
- Processes using Azure Cognitive Services
- Returns transcribed text
- Supports multiple languages

#### Text Analytics Service
- Receives transcribed text
- Generates summaries using extractive summarization
- Returns key sentences/summary

## Data Flow

### Transcription Flow

```
1. User uploads audio file
   ↓
2. Streamlit saves file to data/uploads/
   ↓
3. Database creates recording & transcription entries
   ↓
4. AzureSpeechClient.transcribe_file()
   ↓
5. Azure Speech-to-Text processes audio
   ↓
6. Database updates transcription with text
   ↓
7. UI displays transcription
```

### Summarization Flow

```
1. Transcription completed successfully
   ↓
2. Database creates summary entry
   ↓
3. AzureTextAnalyticsClient.extract_summary()
   ↓
4. Azure Text Analytics processes text
   ↓
5. Database updates summary with result
   ↓
6. UI displays summary
```

## Error Handling

### File Upload Errors
- File size validation
- Format validation
- Storage failure handling

### Azure Service Errors
- API authentication failures
- Rate limiting
- Service unavailability
- Network timeouts

### Database Errors
- Connection failures
- Schema conflicts
- Data integrity issues

## Security Considerations

1. **Credentials Management**
   - Store Azure keys in `.env` (never in code)
   - Use environment variables for deployment

2. **File Handling**
   - Validate file types and sizes
   - Store uploads in isolated directory
   - Clean up old files regularly

3. **Database**
   - SQLite file permissions
   - Input validation
   - SQL injection prevention (parameterized queries)

4. **API Communication**
   - HTTPS for Azure API calls
   - Error message sanitization
   - Rate limiting awareness

## Scalability Considerations

### Current Limitations (Single-User MVP)
- Single SQLite database
- No authentication layer
- Local file storage
- Synchronous processing

### Future Improvements
- Queue system (Celery, Azure Queue)
- Multi-user support with authentication
- Cloud storage (Azure Blob Storage)
- Asynchronous task processing
- Caching layer (Redis)
- Load balancing

## Performance Metrics

### Expected Processing Times
- File upload: <5 seconds
- Transcription: 30-120 seconds (depends on audio length)
- Summarization: <5 seconds
- Total: ~1-2 minutes for typical 5-minute audio

### Resource Requirements
- RAM: ~500MB base
- Disk: ~1GB for application + dependencies
- Network: Required for Azure API calls
