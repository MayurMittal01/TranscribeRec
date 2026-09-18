# Azure Pipeline Design — Transcription & Summarization

**Status**: Decided. Ready for implementation.
**Owner**: azure-architect
**Implementer**: python-dev
**Blocks**: Issue #7 (Speech-to-Text), Issue #8 (Summarization)
**Date**: 2026-09-18
**Scope**: `src/azure_client.py` only, plus the two handoffs called out in §5.

All Azure API surfaces below were verified against Microsoft Learn and the
Azure SDK for Python repository on 2026-09-18. Claims that could not be
verified from a machine with no Azure credentials are marked
**[VERIFY LIVE]**.

---

## 0. Sizing assumptions this design is built on

These bound every decision below. If they change, revisit the design.

| Assumption | Value | Source |
|---|---|---|
| Concurrent users | 1 | Demo, runs on a laptop |
| Uploads per demo session | ~5–20 | Occasional, manual |
| Audio duration | 2–13 minutes | `MAX_FILE_SIZE = 25 MB` in `src/config.py` |
| Max transcript length | ~10,000 characters | Derived below |
| Languages | 6 locales (`en-US`, `en-GB`, `es-ES`, `fr-FR`, `de-DE`, `it-IT`) | `SUPPORTED_LANGUAGES` in `src/config.py` |

**Derivation of max transcript length.** 25 MB is the hard upload cap. At the
Speech service's native input format (16 kHz, 16-bit, mono PCM = 32,000
bytes/sec), 25 MB is ~780 seconds ≈ 13 minutes of audio. At ~150 words/minute
and ~5 characters/word plus a space, that is roughly **10,000 characters** of
transcript, worst case.

This number matters: it is ~8% of the Language service's 125,000-character
asynchronous document limit. **The character cap is unreachable in this app as
configured.** Chunking is therefore defensive code, not the main path (§2.5).

---

## 1. Decision 1 — Speech-to-Text (Issue #7)

### The decision

**Use continuous recognition (`start_continuous_recognition`) with an
accumulating `recognized` event handler, run synchronously inside the Streamlit
call by blocking on a `threading.Event`.**

### What I rejected, and why

**`recognize_once()` — the current code.** Returns after the first utterance or
the first ~15 seconds of silence-bounded speech. A 5-minute recording yields one
sentence. This is the defect in Issue #7 and is not a candidate.

**Batch Transcription REST API — rejected on three independent grounds:**

1. **Not available on the Free tier.** The Speech quotas doc states batch
   transcription is "Not available for F0." The demo's stated posture is free
   tier where possible. Choosing batch forces an S0 resource before the demo can
   run at all.
2. **It requires storage the demo does not have.** Batch takes a
   `contentUrls` list of publicly reachable or SAS-signed audio URLs, or a
   multipart upload. From a laptop holding a local file in `data/uploads/`, that
   means standing up an Azure Storage account, uploading the blob, minting a SAS,
   submitting the job, polling, then fetching a result JSON from a returned URL.
   That is blob storage plus a polling loop added to a single-user laptop demo —
   strictly more infrastructure for no benefit at this volume.
3. **It is not faster in wall-clock terms.** Batch jobs enter a shared regional
   queue. Microsoft's own guidance notes that raising the batch quota "doesn't
   improve transcription performance" because jobs queue sequentially. For one
   5-minute file, queue wait can exceed the audio duration. Since Streamlit
   blocks either way, batch trades a predictable wait for an unpredictable one.

Batch is cheaper per hour ($0.18/hr vs $1.00/hr real-time) **[VERIFY LIVE]**, but
at demo volume the absolute difference is a few cents (§1.6). Cost is not a
reason to accept the three problems above.

### 1.1 Can continuous recognition work synchronously inside Streamlit?

Yes, and this is the load-bearing point. The Speech SDK runs recognition on its
own background threads and delivers results via callbacks. The Streamlit script
thread calls `start_continuous_recognition()`, then blocks on a
`threading.Event` until the SDK signals `session_stopped` or `canceled`. The
script thread is blocked, the SDK threads are not. When the wait returns, the
accumulated transcript is already in a local list.

**Critical constraint for the implementer:** the `recognized` / `canceled` /
`session_stopped` callbacks execute on **SDK-owned background threads that have
no Streamlit ScriptRunContext**. Do not call any `st.*` API from inside a
callback — in current Streamlit versions those calls are silently dropped and
emit a "missing ScriptRunContext" warning. Callbacks must only append to plain
Python lists and set the event. All rendering happens on the script thread after
the wait returns.

### 1.2 Concrete API surface

```
class AzureSpeechClient:

    def __init__(self) -> None
        # unchanged: reads AZURE_SPEECH_KEY / AZURE_SPEECH_REGION from config
        # speechsdk.SpeechConfig(subscription=..., region=...)

    def transcribe_file(
        self,
        audio_file_path: str,
        language: str = "en-US",
    ) -> str
```

Returns the full transcript as a single space-joined string. Raises on failure
(§1.4). Never returns `None` — the current implementation falls off the end of
the `if/elif` chain and returns `None` when `reason` is anything unexpected.

**Implementation shape** (design guidance, not code to paste):

1. **Set the language.** This is the second half of Issue #7:
   ```
   self.speech_config.speech_recognition_language = language
   ```
   Verified property name on `SpeechConfig`. It takes a BCP-47 locale string
   (`"en-US"`, `"de-DE"`), which is exactly what `SUPPORTED_LANGUAGES` holds.
   Set it per call, not once in `__init__`, so the UI dropdown actually takes
   effect. (Setting it in `__init__` would also work only if a new client is
   built per request — do not rely on that.)

2. **Build the recognizer.**
   ```
   audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)
   recognizer  = speechsdk.SpeechRecognizer(
       speech_config=self.speech_config,
       audio_config=audio_config,
   )
   ```

3. **Accumulate.** Create three locals before connecting handlers:
   `segments: list[str]`, `cancellation: list` (one-element holder for the
   cancellation details), and `done = threading.Event()`.

   - `recognizer.recognized.connect(handler)` — handler receives a
     `SpeechRecognitionEventArgs`. Append `evt.result.text` **only when**
     `evt.result.reason == speechsdk.ResultReason.RecognizedSpeech` **and**
     `evt.result.text` is non-empty.
   - `recognizer.canceled.connect(handler)` — stash
     `evt.result.cancellation_details` (or `evt.cancellation_details`, both are
     reachable on the canceled event args) into the holder, then `done.set()`.
   - `recognizer.session_stopped.connect(lambda evt: done.set())`.

   Do **not** connect `recognizing` (interim hypotheses). It fires many times
   per second and appending from it would duplicate every word.

4. **Run and wait.**
   ```
   recognizer.start_continuous_recognition()
   completed = done.wait(timeout=<see below>)
   recognizer.stop_continuous_recognition_async().get()
   ```

   **Call `stop_*` from the script thread, after the wait — not from inside the
   `session_stopped`/`canceled` callback.** The Microsoft sample calls the
   synchronous `stop_continuous_recognition()` from within the callback; that
   re-enters the SDK from an SDK-owned thread and is a known source of hangs.
   Setting the event in the callback and stopping from the waiting thread avoids
   the question entirely. Use the `_async().get()` form so the call itself
   cannot block forever on a wedged session.

   Wrap steps 4–5 in `try/finally` so `stop_*` and handler disconnection always
   run, even if the wait raises.

5. **Assemble and validate.**
   - If `cancellation` holder is non-empty and its `.reason` is
     `CancellationReason.Error` → raise (§1.4).
   - If `completed` is `False` → timeout, raise (§1.4).
   - `transcript = " ".join(segments).strip()`
   - If `transcript` is empty → raise `TranscriptionError("No speech was
     recognized in this recording...")`. Note: `CancellationReason.EndOfStream`
     is the **normal** end-of-file signal, not an error. Do not treat it as one.

**Timeout value.** Continuous recognition over a local file streams faster than
real time, but design for the worst case. Recommendation:
`timeout = max(120, audio_duration_seconds * 2)`. If the duration is not readily
available, use a flat `900` seconds (covers the 13-minute ceiling with margin).
A timeout is mandatory — without it a wedged session hangs the Streamlit tab
with no recourse but killing the process.

### 1.3 Audio format — the thing that will bite first

**This is the most likely cause of the first failure the implementer sees, and
it is a config problem, not a code problem.**

`speechsdk.audio.AudioConfig(filename=...)` natively handles **WAV/PCM only**
(16 kHz or 8 kHz, 16-bit, mono). `src/config.py` currently declares:

```
ALLOWED_AUDIO_FORMATS = ["wav", "mp3", "m4a", "flac", "ogg"]
```

Four of those five will not work through `AudioConfig(filename=...)`. Per the
Speech docs, MP3, OPUS/OGG, FLAC, ALAW/MULAW-in-WAV and MP4 containers are
supported **only** via GStreamer, and require building a
`PullAudioInputStreamCallback`, wrapping it in
`speechsdk.audio.PullAudioInputStream(stream_format=..., pull_stream_callback=...)`
where the format comes from
`speechsdk.audio.AudioStreamFormat(compressed_stream_format=speechsdk.AudioStreamContainerFormat.MP3)`.
The docs are explicit: "GStreamer binaries must be in the system path so that
they can be loaded by the Speech SDK at runtime." On Windows that is a separate
runtime installer plus a PATH edit — a setup step that will silently break on
any machine that skipped it, with an opaque SDK error.

**Recommendation: for the demo, restrict uploads to WAV.** This is a one-line
config change and removes an entire class of environment-dependent failure from
a demo that has to work on someone else's laptop.

> **HANDOFF → python-dev (config, not my file to change):** narrow
> `ALLOWED_AUDIO_FORMATS` in `src/config.py` to `["wav"]`.
>
> **HANDOFF → streamlit/UI agent:** the upload widget's help text and rejection
> message should say "WAV only (16 kHz, 16-bit, mono PCM)" and explain why,
> rather than just rejecting the file.

If WAV-only is unacceptable to the demo's owner, the fallback is **not**
GStreamer — it is transcoding to WAV on ingest with a bundled `ffmpeg`. That is
a larger change and should be its own issue. Do not implement the
PullAudioInputStream/GStreamer path for this demo; the setup burden is worse
than the restriction.

### 1.4 Failure modes the implementer must handle

Define a `TranscriptionError(Exception)` in `azure_client.py` and raise it for
all of these. The current code's `raise Exception(f"Transcription error: ...")`
is unusable by callers — and worse, its `except Exception` wrapper catches the
`ValueError`s raised inside its own `try` block and re-wraps them, so the
service's real error text gets buried one layer deep in a generic string.

| Failure | How it arrives | Handling |
|---|---|---|
| Bad key or region | `canceled` event, `cancellation_details.reason == CancellationReason.Error`, `error_code == CancellationErrorCode.AuthenticationFailure` | Raise with a message naming the env var, not the raw SDK text |
| Quota exhausted / throttled (F0 5 hrs/month) | `canceled` event, `error_code == CancellationErrorCode.Forbidden` or `TooManyRequests` | Distinct message: "Speech quota exhausted for this month" |
| Network drop mid-stream | `canceled` event, `error_code == ConnectionFailure` or `ServiceTimeout` | Partial transcript is in `segments`. **Decide explicitly**: recommend raising, but include the partial-transcript length in the message so the user knows it was not a total failure |
| Unsupported/corrupt audio container | `canceled` event with `error_details` mentioning the format, *or* an exception at `AudioConfig` construction | Map to the WAV-only guidance from §1.3 |
| File is silent or non-speech | No error at all. `session_stopped` fires with `segments == []` | Empty-transcript check in step 5. This one produces no exception anywhere and will look like success if unchecked |
| Session never terminates | Neither `session_stopped` nor `canceled` fires | The `done.wait(timeout=...)` guard. Mandatory |
| Normal end of file | `canceled` with `reason == CancellationReason.EndOfStream`, then `session_stopped` | **Not an error.** Must be distinguished from `CancellationReason.Error` |
| F0 concurrency (1 request) | Second concurrent call is rejected | Single-user demo, so unlikely — but do not build a client that fires two recognitions in parallel |

`cancellation_details` exposes `.reason`, `.error_code` and `.error_details`.
Include `error_code` and `error_details` in the raised message; `error_details`
carries the actual service diagnostic and is the only thing that makes a live
failure debuggable.

### 1.5 What needs live verification

- That `evt.result.cancellation_details` is populated on the canceled event args
  in SDK 1.51.2 (the attribute has been reachable both as
  `evt.cancellation_details` and `evt.result.cancellation_details`; code
  defensively against both). **[VERIFY LIVE]**
- Actual wall-clock for a 5-minute file, to tune the timeout. **[VERIFY LIVE]**
- Whether the F0 tier is provisioned or S0. Affects quota messaging only.

### 1.6 Cost at demo volume

Real-time speech-to-text, S0: **$1.00 per audio hour**, billed in second
increments **[VERIFY LIVE — pricing page]**.

- One 5-minute recording: **$0.083**
- A 20-recording demo session (~1.7 hrs): **~$1.70**
- F0 free tier allowance: **5 audio hours/month** = ~60 five-minute recordings
  free, which comfortably covers demo usage.

Batch would have cost ~$0.30 for the same session. The ~$1.40 saved does not
justify blob storage, a polling loop, and losing the free tier.

---

## 2. Decision 2 — Summarization (Issue #8)

### The decision

**Keep Azure AI Language (Text Analytics), but use
`begin_abstract_summary()` — abstractive summarization — not extractive, and not
Azure OpenAI.**

### 2.1 Why not extractive

The original plan was extractive. I am overturning that half of it.

Extractive summarization returns **verbatim sentences lifted from the input**,
ranked by relevance. That works well on edited prose. It works badly on a speech
transcript, which is what this app always feeds it: transcripts are disfluent,
run-on, full of filler and restarts, and have machine-inserted sentence
boundaries. Picking the three highest-ranked *verbatim* sentences out of a
rambling meeting recording produces three rambling sentences.

That matters here specifically because summarization quality **is the demo**.
The app's whole pitch is "upload a recording, get a useful summary." An
extractive summary of a transcript looks only marginally better than the local
first/longest/last heuristic it is replacing — which is the exact failure mode
Issue #8 exists to fix. Abstractive generates new, coherent prose and is the
only one of the two that visibly clears the heuristic's bar.

Cost and integration shape are otherwise near-identical: same client, same
long-running-operation flow, same order-of-magnitude billing. There is no reason
to prefer extractive.

### 2.2 Why not Azure OpenAI — and one finding that weakens the original rationale

The project chose Text Analytics over Azure OpenAI "on cost grounds." I checked
that reasoning and it is **partly wrong**, so it is worth recording accurately:

- **The free tier does not apply.** Microsoft's summarization quickstart states
  as a prerequisite: *"To use the Analyze feature, you'll need a Language
  resource with the standard (S) pricing tier."* Summarization runs through the
  async Analyze pipeline. The F0 tier's 5,000 free text records/month therefore
  **cannot be used for summarization**. "Text Analytics is free, Azure OpenAI is
  not" is not a true statement. **[VERIFY LIVE at provisioning time — this
  determines which tier the Language resource must be created in.]**
- On a per-summary basis at this volume, a small Azure OpenAI model would likely
  be *cheaper* than Language summarization, not more expensive.
- Azure Language summarization is **retiring on 2029-03-31**, with Microsoft
  explicitly directing new projects to Foundry models.

So the cost argument does not survive. I am nevertheless keeping Text Analytics,
for reasons that do survive:

1. **Absolute cost at demo volume is noise either way.** Both are fractions of a
   cent per recording (§2.7). A cost argument that resolves to "$0.005 vs
   $0.0003 per summary" is not a decision input for a demo. Since cost does not
   decide it, integration friction does.
2. **Azure OpenAI adds a provisioning step that blocks the demo today.** It
   needs a separate resource, a *model deployment* (name, version, capacity),
   possibly quota approval, two more environment variables, and the `openai`
   package. Nobody on this machine has Azure credentials yet (§4). Adding a
   second resource type with a deployment step to an integration that cannot be
   tested is the wrong trade.
3. **Text Analytics is already wired.** The client, endpoint, key, and env vars
   all exist in `src/config.py` and `AzureTextAnalyticsClient.__init__`. Issue #8
   becomes "call the client you already built." Switching services makes it
   "provision a new resource, change config, change env, change deps, then call
   it." For a demo that is two weeks from working, that is real schedule risk
   for no user-visible gain — abstractive summarization is itself LLM-backed and
   produces comparable output.

**Record this as reversible.** The 2029 retirement plus the cost inversion means
Azure OpenAI is the correct destination eventually; it is just not worth the
churn to get there before the demo works end to end once. If the demo's purpose
shifts to showcasing Foundry model deployment specifically — which, given the
project name, is plausible — reopen this. The swap is contained to
`AzureTextAnalyticsClient.extract_summary()` and two config values.

### 2.3 Concrete API surface

**Package**: `azure-ai-textanalytics==5.4.0` (see §3 — the pinned 5.2.0 **cannot
do this at all**).

```
from azure.ai.textanalytics import TextAnalyticsClient
from azure.core.credentials import AzureKeyCredential

class AzureTextAnalyticsClient:

    def __init__(self) -> None
        # unchanged; already correct

    def extract_summary(
        self,
        text: str,
        language: str = "en",
    ) -> str
```

Keep the method name `extract_summary` so `AzureFoundryClient` and any caller
in `src/app.py` do not change. The name is now slightly inaccurate; a docstring
noting it performs abstractive summarization is enough. Renaming it is churn.

**Verified method signature** (`azure-ai-textanalytics` 5.4.0):

```
poller = self.client.begin_abstract_summary(
    documents,                    # list[str] | list[TextDocumentInput] | list[dict]
    language="en",                # ISO 639-1, NOT the BCP-47 locale
    sentence_count=4,             # approximate sentences in the output summary
    polling_interval=2,           # seconds; SDK default is 5
)
```

Other accepted keywords, verified present but not needed here:
`model_version`, `show_stats`, `string_index_type`, `display_name`,
`disable_service_logs`, `continuation_token`.

**Return shape:**

```
poller  : TextAnalysisLROPoller
result  = poller.result()          # blocks; returns ItemPaged
for doc in result:
    doc.is_error                   # check FIRST
    doc.kind                       # "AbstractiveSummarization"
    doc.summaries                  # list[AbstractiveSummary]
    doc.summaries[0].text          # the generated summary string
```

Join with `" ".join(s.text for s in doc.summaries)` — abstractive returns one
summary per contextual input range, so a long input can yield more than one.

**Language parameter — note the format difference.** `begin_abstract_summary`
takes **ISO 639-1** (`"en"`), while `SpeechConfig.speech_recognition_language`
takes **BCP-47** (`"en-US"`). The existing `AzureFoundryClient` already does
`language[:2]`, which maps all six configured locales correctly
(`en-US`/`en-GB`→`en`, `es-ES`→`es`, `fr-FR`→`fr`, `de-DE`→`de`, `it-IT`→`it`).
Keep it, but make the truncation explicit and commented rather than incidental —
it is only safe because `SUPPORTED_LANGUAGES` is a curated list. All six map to
languages the service supports for abstractive summarization (verified: `ar`,
`zh-hans`, `en`, `fr`, `de`, `he`, `it`, `ja`, `ko`, `pl`, `pt`, `es`).

### 2.4 The long-running operation, from inside a blocking Streamlit call

Summarization is **async-only** on the service side — there is no synchronous
endpoint. The flow is: POST the job → receive an `operation-location` header →
GET-poll until terminal → read results. The Python SDK hides all of that behind
the poller.

For this app the whole thing collapses to: `poller.result()` blocks the
Streamlit script thread until done. That is acceptable, and nothing more
elaborate is warranted.

Two tuning notes:

- **Set `polling_interval=2`.** The default is 5 seconds. Demo documents are
  ~5,000 characters and the job itself finishes in a few seconds, so the default
  can spend more time waiting to poll than the service spends working. Expect
  **~5–15 seconds** end to end with `polling_interval=2` **[VERIFY LIVE]**.
- **Do not use `begin_analyze_actions`.** It works (`AbstractiveSummaryAction`
  exists) but it is the multi-action batching API, and its result shape is
  nested one level deeper — `result[0]` per document per action. The dedicated
  `begin_abstract_summary` is the single-purpose call and has a flatter result.
  Several Microsoft quickstart samples still show the `begin_analyze_actions`
  form; prefer the dedicated method.

> **HANDOFF → streamlit/UI agent (Issue #10):** the pipeline blocks the script
> thread for roughly `transcription_time + 5–15s`. Anything that wants a live
> progress bar needs the SDK callback data, and callbacks have no
> ScriptRunContext (§1.1). The realistic options are a `st.spinner` with staged
> text ("Transcribing…" then "Summarizing…") around two sequential blocking
> calls, or `st.status`. A true percentage progress bar is not available without
> restructuring into a background thread with `add_script_run_ctx`, which I do
> not recommend for this demo. Your call; flagging the constraint.

### 2.5 Character cap and what to do about it

Verified limits for asynchronous (Analyze) operations, which is what
summarization uses:

| Limit | Value |
|---|---|
| Max characters per request | **125,000** across all documents in the request |
| Max documents per request | 25 |
| Max request size | 1 MB |
| Behavior on overflow | **The entire request is rejected with HTTP 400.** Unlike the sync path, it does not skip the oversized document and process the rest |

**At this app's configured limits the cap is unreachable.** Per §0, a 25 MB WAV
yields ~10,000 characters — about 8% of 125,000. The implementer should not
build a summarization pipeline around chunking.

**What to implement instead** — a cheap guard, roughly:

```
MAX_SUMMARY_INPUT_CHARS = 120_000   # margin under the 125,000 service cap

if len(text) > MAX_SUMMARY_INPUT_CHARS:
    chunks = <split on sentence boundaries, each <= MAX_SUMMARY_INPUT_CHARS>
    summarize each chunk in a separate sequential request
    return " ".join(chunk_summaries)
else:
    single request           # <-- always the path taken in practice
```

Note the 120,000 margin: the service measures length in
`StringInfo.LengthInTextElements` (grapheme clusters), not Python `len()`.
Those diverge for combining characters and emoji. The margin absorbs the
difference without needing to replicate the service's counting.

Split on sentence boundaries, not mid-word — a chunk cut mid-sentence produces a
visibly broken summary. Send chunks in **separate sequential requests**, not as
25 documents in one request; the 125,000 cap is across the whole request, so
batching buys nothing.

Rejected alternative: silently truncating at 120,000 characters. Cheaper, but it
discards content without telling the user, and the guard is only ~15 lines.

### 2.6 Failure modes the implementer must handle

Define a `SummarizationError(Exception)`. **Errors arrive by two distinct
mechanisms and both must be handled** — this is the most common mistake with
this SDK.

**(a) Request-level failures raise exceptions** from `azure.core.exceptions`:

| Failure | Exception | Handling |
|---|---|---|
| Bad key | `ClientAuthenticationError` (401) | Name the env var `AZURE_TEXT_ANALYTICS_KEY` |
| Wrong endpoint / wrong resource kind | `HttpResponseError` (403/404) | Name `AZURE_TEXT_ANALYTICS_ENDPOINT` |
| **Language resource is on F0, not S** | `HttpResponseError` — likely 403 | **High-probability first failure** (§2.2). Message must say the resource needs the S tier, or the implementer will chase a key problem that isn't one |
| Input over 125,000 chars | `HttpResponseError` 400, `InvalidDocumentBatch` | Prevented by §2.5 guard; still catch it |
| Rate limited (F0/S0: 100 req/sec, 300 req/min) | `HttpResponseError` 429 | Unreachable at one user. Do not build retry/backoff for it — `azure-core` already retries 429 by default |
| Network failure | `ServiceRequestError` | Generic "could not reach Azure" |
| Region lacks abstractive support | `HttpResponseError` 400 | See §2.7 note on regions |

**(b) Per-document failures do NOT raise.** They come back as `DocumentError`
items inside the successful `ItemPaged`. Code that does
`result[0].summaries` without checking will raise `AttributeError` on a
perfectly normal service response:

```
for doc in poller.result():
    if doc.is_error:
        # doc.error.code, doc.error.message
        raise SummarizationError(...)
```

Common per-document errors: `UnsupportedLanguageCode` (a language code the
service does not support for this action), `InvalidDocument` (empty or malformed
input).

**(c) Empty input.** If the transcript is empty or whitespace, do **not** call
the service — it will return `InvalidDocument` and burn a request. Guard first
and raise a clear error. This is reachable: §1.4 shows a silent audio file
produces an empty transcript.

**(d) Remove the local heuristic entirely.** Do not leave it as a silent
fallback in an `except` branch. A fallback that produces a plausible-looking
summary when Azure failed is exactly the bug Issue #8 is about, and it would be
invisible in a demo. If Azure fails, fail loudly.

### 2.7 Cost at demo volume, and the region constraint

**Billing unit.** Azure Language bills per **text record = 1,000 characters**.
For summarization specifically, the billed length is **input document + output
summary combined**.

Per 5-minute recording: ~4,500 chars in + ~400 chars out ≈ 4,900 chars ≈
**5 text records**.

| Volume | Text records |
|---|---|
| 1 recording | ~5 |
| 20-recording demo session | ~100 |
| 500 recordings | ~2,500 |

The public pricing page renders its S-tier figures dynamically and did not yield
a citable number. Historically the S tier's first band has been on the order of
**$1 per 1,000 text records**, which puts a demo session at well under **$0.01
total** and a single summary at roughly **half a cent**. **[VERIFY LIVE — get
the current per-1,000-text-record rate for your region from the pricing page,
and confirm whether abstractive is billed at a different rate from extractive.]**

Even if abstractive carries a multiple of the extractive rate, demo-volume cost
stays under a dollar. **Cost is not a constraint on this decision at this
volume** — which is precisely why §2.2 decides on integration friction instead.

**Region constraint — check this before provisioning.** Abstractive
summarization is **not available in every region**. Verified supported regions
include: East US, East US 2, West US, West US 2, Central US, North Central US,
South Central US, North Europe, West Europe, UK South, France Central, Germany
West Central, Italy North, Switzerland North, Australia East, Canada Central,
Japan East, Southeast Asia.

`src/config.py` defaults `AZURE_SPEECH_REGION` to `eastus`, which **is**
supported. But note the Language resource is a separate resource with its own
region baked into `AZURE_TEXT_ANALYTICS_ENDPOINT`. If someone provisions it
somewhere unlisted, abstractive returns a 400 and extractive would have worked —
a confusing failure. Document the region requirement in `docs/API_INTEGRATION.md`
at the resource-creation step.

---

## 3. Dependency versions to target

`requirements.txt` as pinned cannot implement this design.

| Package | Pinned | Target | Why |
|---|---|---|---|
| `azure-ai-textanalytics` | `5.2.0` | **`5.4.0`** | **Hard blocker.** `begin_extract_summary` / `begin_abstract_summary` did not exist until 5.3.0. Issue #8 is literally unimplementable on 5.2.0. 5.4.0 is the current stable (2026-02-25) |
| `azure-cognitiveservices-speech` | `1.31.0` | **`1.51.2`** | 1.31.0 is from 2023. 1.51.2 is current (2026-08-20). Wheels are `py3-none-<platform>`, and the SDK supports "Python 3.8 or later" — fine on the local 3.12.5. The 1.31.0-era wheels predate 3.12 and are a risk on this machine |
| `streamlit` | `1.28.0` | `>=1.37,<2` | 1.28.0 is from Oct 2023, before Python 3.12 was broadly supported. Not my call — flagging to whoever owns the UI |
| `python-dotenv` | `1.0.0` | `>=1.0.1` | Minor; no blocker |
| `azure-core` | absent | leave absent | Pulled transitively by `azure-ai-textanalytics`. Do not pin it separately |
| `requests`, `pytest` | — | unchanged | Not used by this design |

Breaking change to be aware of in `azure-ai-textanalytics` 5.4.0: the LRO
**continuation token format changed** and tokens from earlier versions are
incompatible. This design does not persist continuation tokens, so it is not
affected — but do not add token persistence without revisiting it.

Also note 5.3.0 renamed `ExtractSummaryAction` → `ExtractiveSummaryAction` and
`begin_abstractive_summary` → `begin_abstract_summary`. Older blog posts and
Stack Overflow answers use the pre-5.3.0 names and will not work. The
`AttributeError: 'TextAnalyticsClient' object has no attribute
'begin_extract_summary'` that shows up in search results is the 5.2.0 symptom.

---

## 4. What cannot be verified without credentials

No Azure credentials and no `.env` exist on this machine, so none of this has
run against the live service. Everything above is derived from current
Microsoft Learn documentation and the Azure SDK for Python repository. The items
marked **[VERIFY LIVE]** are collected here for whoever gets credentials first:

1. Wall-clock duration of continuous recognition on a 5-minute WAV — tunes the
   §1.2 timeout.
2. Whether `cancellation_details` is reachable as `evt.cancellation_details` or
   `evt.result.cancellation_details` in SDK 1.51.2 — code defensively for both
   until confirmed.
3. That the Language resource must be **S tier** for summarization (§2.2). This
   determines how the resource is provisioned and is the highest-value item on
   this list.
4. End-to-end latency of `begin_abstract_summary` with `polling_interval=2` on a
   ~5,000-character document.
5. Current per-audio-hour and per-text-record prices.
6. That the chosen Language region supports abstractive summarization.

Items 3 and 6 are **provisioning-time** checks — getting them wrong means
creating the wrong resource and finding out at first call. They should be
verified before any resource is created, not after.

---

## 5. Handoffs (changes this design forces outside `src/azure_client.py`)

| # | Owner | Change | Reason |
|---|---|---|---|
| 1 | python-dev | `src/config.py`: `ALLOWED_AUDIO_FORMATS = ["wav"]` | §1.3 — non-WAV needs GStreamer on PATH |
| 2 | python-dev | `requirements.txt`: bump the two Azure pins | §3 — 5.2.0 cannot implement Issue #8 |
| 3 | streamlit/UI agent | Upload widget copy: "WAV only (16 kHz, 16-bit, mono PCM)" with rationale | §1.3 |
| 4 | streamlit/UI agent | Issue #10 progress indicators: use `st.spinner`/`st.status` with staged text, not a percentage bar | §2.4 — callbacks have no ScriptRunContext |
| 5 | docs owner | `docs/API_INTEGRATION.md`: Language resource must be **S tier** and in an abstractive-capable region | §2.2, §2.7 |

**No database schema change is required.** Transcripts stay well under any
practical column limit, `summaries.summary_text` is unchanged in shape, and the
existing `status` / `error_message` columns are sufficient to carry the
`TranscriptionError` / `SummarizationError` messages defined above.

---

## 6. Summary of the two decisions

| | Decision | Rejected | Why |
|---|---|---|---|
| **#7 Speech** | Continuous recognition, blocking on `threading.Event` | `recognize_once()` | Stops after first utterance — the defect itself |
| | | Batch Transcription REST | Not on F0; needs blob storage + SAS; queue latency is unbounded and unpredictable |
| **#8 Summary** | Text Analytics `begin_abstract_summary()` | Extractive summarization | Verbatim sentences from a disfluent transcript barely beat the heuristic it replaces — and summary quality *is* the demo |
| | | Azure OpenAI | Not on cost (cost is noise, and the free-tier rationale turned out to be false) but on integration friction: new resource, model deployment, quota, config and dependency churn, on an integration nobody can test yet. Reversible; revisit before 2029 retirement |
