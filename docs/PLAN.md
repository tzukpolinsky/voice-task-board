# Voice Task Board — Planning Document

> **Status: Option E (Gemini Cloud) was selected.** Sections 2-4 below capture the original tradeoff exploration and the four local-stack alternatives — kept for historical reference and in case the cloud decision is revisited. For what is actually being built, see [BUILD_PLAN.md](BUILD_PLAN.md). For known issues against the implementation, see [CODE_REVIEW.md](CODE_REVIEW.md).
>
> Decisions in Section 2 marked "Foundry Local," "Whisper," "TTL," and "parallel model loading" are **superseded** by the Gemini choice. Hebrew is **no longer a blocker** — Gemini 3 Flash handles it natively.
>
> The pluggable-backend recommendation in Option E is **deferred to v2.** v1 is Gemini-only by explicit decision in BUILD_PLAN.md.

---

## 1. Vision

A Windows desktop task board where the user can create, edit, and delete tasks **using voice**, without leaving their current workflow.

**Core UX loop:**
1. User is doing their daily work in any app.
2. User presses a global hotkey (e.g. `Ctrl+Shift+Space`).
3. App starts listening, captures speech until ~1s of trailing silence (max 30s).
4. AI transcribes speech and extracts intent (`add` / `edit` / `delete` + task content).
5. AI auto-classifies the task into one of the user's existing categories (or a default).
6. Task appears in the board (visible via tray icon).
7. User can later drag-drop to reorder or recategorize.

**Constraints:**
- Free — no paid APIs, no subscriptions.
- Local — everything runs on the user's machine. No cloud calls.
- Easy install — installer that "just works" on Windows.
- Runs on startup, lives in tray.
- Languages: **English + Hebrew** (Hebrew is the hard constraint that drives several decisions below).
- Target RAM: originally 4GB, raised to **8GB total / ~3GB headroom** after research.

---

## 2. Locked decisions

These were debated and decided. Re-open only if a constraint changes.

| Concern | Decision | Why |
|---|---|---|
| Packaging | PyInstaller `--onedir` wrapped in **Inno Setup** | "Double-click to run" promise. Inno Setup also installs Foundry Local as a prerequisite and registers the startup entry in `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. |
| Tray | **pystray** | Standard Windows tray library for Python. App runs from boot. |
| Global hotkey | **Win32 `RegisterHotKey`** via `pywin32` | The `keyboard` library needs admin on some systems; `pynput` conflicts with other apps. `RegisterHotKey` plays nicely with focus stealing and UAC. |
| Audio capture | **sounddevice** (PortAudio binding) | Lightweight, reliable, well-maintained. |
| Endpoint detection (silence) | **Silero VAD** (ONNX, ~15MB) — ~1s of trailing silence, 30s hard cap | webrtcvad (2016) is outdated and trips on keyboard/fan noise. Silero is the modern pick. ~30ms detection latency. |
| Audio handling | Feed full captured audio to Whisper. **Do not manually chunk.** | Whisper internally processes in 30-second windows with prompt conditioning. Manual slicing breaks words at boundaries and loses internal context. Our 30s hard cap fits Whisper's natural window. |
| Model loading strategy | Lazy-load on first use, let Foundry's **TTL** handle unload (default 600s) | Re-call `load_model` after each use to reset TTL clock (true idle-unload is an open feature request, see Foundry-Local issue #284). |
| Parallel model loading | Spawn Whisper load in parallel with audio recording on first hotkey press | User's speech (~2-5s) hides the ~1-2s model load. Only helps the first-after-idle command. |
| DB | **SQLite** with indexed columns for queried fields (`title`, `category_id`, `created_at`, `status`) + a `data JSON` column for flexible/future fields. Migrations via `PRAGMA user_version`. | Schemaless ergonomics for evolving fields, fast indexed queries for the stable ones. No server process needed (unlike MongoDB). |
| UI | **PyWebView + React (Vite build)** | PyWebView embeds WebView2 (already on Windows 11), works with PyInstaller, lets us write the UI in React. Future UI changes = just edit React. Avoids the Rust dependency Tauri would add. |
| Hotkey behavior | Press once → listen until VAD detects ~1s of silence → process | User confirmed. |

---

## 3. The Hebrew question (THE OPEN BLOCKER)

This is the decision that drives the rest of the plan. **It must be answered with user input before building.**

### Background

- **Vanilla OpenAI Whisper** is mediocre at Hebrew, especially on smaller models. `base` multilingual on Hebrew is ~30%+ WER — unusable.
- The community standard for Hebrew STT is **[ivrit.ai](https://www.ivrit.ai/)**, which publishes Hebrew-fine-tuned Whisper checkpoints:
  - `ivrit-ai/whisper-large-v3-turbo` — flagship, best accuracy
  - `ivrit-ai/whisper-v2-d4` — earlier, also good
  - Medium-size fine-tunes — workable, lower accuracy
- **Foundry Local does not ship ivrit.ai models.** Its catalog has OpenAI Whisper variants only. To use ivrit.ai we'd run it via `faster-whisper` (CTranslate2) outside Foundry.
- Hebrew has no `.en`-style small English-only variant. We must use multilingual models. Smallest viable for Hebrew is **medium-class**.
- Phi-3-mini and Phi-4-mini have **mediocre Hebrew capability** — they'll handle transcribed Hebrew text imperfectly, especially for intent extraction with edge cases.

### Why this matters

If the user base is Hebrew-speaking, this single fact reshapes the whole plan:
- Whisper model footprint goes from ~150MB (`base.en`) to ~1.6GB (`ivrit-ai/large-v3-turbo` CT2 INT8).
- Foundry Local's Whisper becomes irrelevant — we'd bypass it and use `faster-whisper` directly.
- The LLM tier becomes questionable — small Phi models are weak in Hebrew, and bigger Hebrew-capable models (Aya, multilingual LLaMA) don't fit in 3GB headroom.

### The four options

Each option assumes the **locked stack above** as the baseline, and varies only the AI layer.

#### Option A — STT only, no LLM (recommended for Hebrew users)

| Component | RAM |
|---|---|
| App (Python + PyWebView + tray + VAD) | ~600 MB |
| `faster-whisper` + `ivrit-ai/whisper-large-v3-turbo` (CT2 INT8) | ~1.6 GB |
| Multilingual sentence-embeddings classifier (`paraphrase-multilingual-MiniLM-L12-v2`, ~120MB) | ~150 MB |
| SQLite | ~10 MB |
| **Total active** | **~2.4 GB** |

**Intent extraction:** regex on transcript for action keywords (Hebrew + English):
- `^(add|create|new|הוסף|תוסיף|תוסף)\s+(.+)$` → ADD
- `^(delete|remove|מחק|תמחק)\s+(.+)$` → DELETE
- `^(edit|change|ערוך|תערוך|שנה)\s+(.+)$` → EDIT
- Default action: ADD (the spoken text becomes the task title).

**Categorization:** embed the task title with multilingual MiniLM, cosine-similarity against pre-embedded category names, pick the best match. If confidence < threshold → default category.

**Pros:** Comfortable RAM headroom. Excellent Hebrew transcription. No flaky LLM Hebrew output. Faster (no LLM inference). Foundry Local can be **dropped entirely** — one less install dependency.

**Cons:** Can't handle compound commands ("delete the dentist task and add a meeting for tomorrow"). No natural-language flexibility — user must use the keyword vocabulary.

#### Option B — Phi-3-mini + smaller Hebrew Whisper

| Component | RAM |
|---|---|
| App | ~600 MB |
| Foundry Local service | ~200 MB |
| `faster-whisper` + ivrit.ai medium fine-tune | ~900 MB |
| Phi-3-mini Q4_K_M | ~2.3 GB |
| **Total active** | **~4.0 GB** |

**Status:** Slightly over the 3GB headroom. Will page on tight machines. Hebrew quality lower than option A on STT side, and Phi-3-mini's Hebrew intent extraction is mediocre.

**Pros:** Natural-language commands possible. Compound commands possible.
**Cons:** Over budget. Worst-of-both for Hebrew quality. Adds Foundry Local install dependency for marginal benefit.

#### Option C — Raise RAM target to 12GB / 5GB headroom

| Component | RAM |
|---|---|
| App | ~600 MB |
| Foundry Local service | ~200 MB |
| `faster-whisper` + ivrit-ai large-v3-turbo | ~1.6 GB |
| Phi-3-mini Q4_K_M | ~2.3 GB |
| **Total active** | **~4.7 GB** |

**Status:** Comfortable on a 12GB machine.

**Pros:** Full stack, best Hebrew STT, LLM intent extraction available.
**Cons:** Raises the minimum spec. Many Windows users still have 8GB.

#### Option E — Cloud (Gemini 3 Flash Preview) — RECOMMENDED for v1

User pastes their own Google AI Studio API key. **One API call replaces both Whisper and the LLM** — Gemini takes raw audio and returns structured intent (`{action, title, category}`) in a single multimodal request. No Foundry Local. No local models. Hebrew handled natively.

##### Pipeline

```
Hotkey → record → Silero VAD endpoint → send raw audio + system prompt to Gemini
       → Gemini returns JSON → SQLite CRUD
```

##### RAM

| Component | RAM |
|---|---|
| Python + app | ~80 MB |
| PyWebView (WebView2) | ~150–250 MB |
| React UI | ~50 MB |
| pystray + Win32 hotkey | ~20 MB |
| Silero VAD | ~15 MB |
| sounddevice + buffers | ~30 MB |
| httpx + SQLite | ~30 MB |
| **Total** | **~400–500 MB** |

Runs on a **2GB machine**. The original 4GB target is back on the table.

##### CPU

- **Idle:** <0.1% — no models running.
- **Recording:** ~2-3% (Silero VAD).
- **API call:** ~0% locally — waiting on network.
- **End-to-end latency:** ~1-2s after speech ends (upload + Gemini response). No model-load delay, ever.

##### Money — per-command cost

Gemini 3 Flash Preview pricing (documented as of Dec 2025 release):
- Audio input: **$1.00 / 1M tokens** (~32 tokens/second of audio)
- Text input: **$0.50 / 1M tokens**
- Text output: **$3.00 / 1M tokens**

Typical 5-second voice command:

| Item | Tokens | Cost |
|---|---|---|
| Audio input (5s × 32) | 160 | $0.00016 |
| System prompt + categories | ~500 | $0.00025 |
| JSON output | ~50 | $0.00015 |
| **Per command** | | **~$0.0006** |

Monthly projections (paid tier):

| Usage | Commands/day | Cost/month |
|---|---|---|
| Light | 10 | ~$0.18 |
| Normal | 30 | ~$0.54 |
| Heavy | 100 | ~$1.80 |
| Very heavy | 300 | ~$5.40 |

##### Free tier — how many tasks per month for free

Google's free tier limits are **per-day** (RPD = requests per day), reset at midnight Pacific time. Exact limits for Gemini 3 Flash Preview are not publicly documented and may shift during the preview period. Best reference points:

- **Gemini 2.5 Flash (stable, reference):** 10 RPM, **250 RPD** free
- **Gemini 2.5 Flash-Lite (stable):** 15 RPM, **1,000 RPD** free
- **Gemini 3 Flash Preview:** reported as "more restrictive than stable 2.5" — likely **~100–250 RPD** during preview

**Practical free-tier capacity for this app:**

| Likely RPD | Tasks/day free | Tasks/month free |
|---|---|---|
| 100 (conservative) | 100 | ~3,000 |
| 250 (likely) | 250 | ~7,500 |
| 1,000 (if uses Flash-Lite-class limits) | 1,000 | ~30,000 |

**One voice command = one API call**, so RPD maps 1:1 to tasks-per-day. RPM (10/min) is irrelevant — no human dictates tasks faster than that.

**Bottom line:** any normal user (10-30 tasks/day) **never pays anything**. Only power users hitting hundreds per day might exceed the free tier and pay <$2/month.

**Important caveat:** free-tier requests may be used by Google for model improvement (per their terms). Paid-tier requests are not. Mention this in the app's setup UI.

##### Tradeoffs vs. local stack

| Concern | Local (Option A: ivrit.ai STT) | Cloud (Option E: Gemini) |
|---|---|---|
| RAM | ~2.4 GB | **~500 MB** |
| Disk | ~2 GB models | **~50 MB app** |
| First-command latency | 8–12s cold | **~1–2s always** |
| Warm latency | 1–2s | ~1–2s |
| Offline | **Yes** | No |
| Hebrew quality | Excellent (STT only) | **Excellent + full reasoning** |
| Compound commands | Hard (regex) | **Trivial** |
| Privacy | **Audio stays local** | Audio sent to Google |
| User cost | Free | $0 for normal use, <$2/mo heavy |
| Install friction | Foundry Local prereq (~3GB) | **Paste API key** |
| Dependency risk | None | Google API, rate limits, preview model deprecation |

##### Recommended architecture: pluggable backend

Don't pick local vs. cloud — **ship both behind one interface.** Define a Python protocol:

```python
class IntentBackend(Protocol):
    def transcribe_and_extract(self, audio_pcm: bytes, categories: list[str]) -> Intent: ...
```

Implementations:
- `GeminiBackend` — default, ships in v1, frictionless
- `LocalBackend` — opt-in in settings, uses ivrit.ai + Phi-3 or Option A regex pipeline
- Future: `OpenAIBackend`, `ClaudeBackend`, `PhiSilicaBackend` (Copilot+ PCs)

Same JSON contract on both sides. Settings UI lets the user pick. Privacy-sensitive users get local; everyone else gets Gemini default.

##### Pros
Smallest footprint. Best Hebrew. Best UX (no first-command lag, compound commands work). Most users pay nothing. Easiest install (no Foundry prereq for the default path).

##### Cons
Requires internet. Requires API key paste step in onboarding. Audio leaves the machine on the default path. Preview model — Google may deprecate/rename; need to track. Free-tier policies subject to change.

---

#### Option D — Hebrew transcription only, manual category

Same as A, but skip even the embeddings classifier. Transcript → task title verbatim. Action via keyword/regex. **No automatic category** — every new task goes to the default category, user drags to assign.

| Component | RAM |
|---|---|
| App | ~600 MB |
| `faster-whisper` + ivrit-ai turbo | ~1.6 GB |
| SQLite | ~10 MB |
| **Total active** | **~2.2 GB** |

**Pros:** Smallest, simplest, fewest moving parts. Easiest to ship a working v0.
**Cons:** Auto-categorization was a stated user value. Without it the value proposition shrinks.

### What to ask users before deciding

1. Native language for daily task entry — Hebrew, English, mixed?
2. RAM available — what does Task Manager show at typical workload?
3. Would they accept a keyword vocabulary ("add", "delete", "edit") for the action verb, or do they want fully natural commands?
4. How important is auto-categorization vs. drag-to-assign?
5. Do they have a Copilot+ PC (NPU available)? Future-proof for Phi Silica path.
6. **Are they OK pasting an API key during setup?** (gates Option E as default)
7. **Are they OK with audio being sent to Google?** (privacy gate for Option E default — local backend remains an opt-in)
8. **Do they typically have internet when working?** (Option E requires it)

---

## 4. Build order (when Hebrew option is chosen)

Regardless of which option, the early steps are the same:

1. **Skeleton:** tray icon (pystray) + global hotkey (Win32 RegisterHotKey) + record fixed 5s → save WAV. Proves the audio path.
2. **STT path:** wire hotkey → record → transcribe → print transcript. Use whichever Whisper the chosen option specifies.
3. **VAD endpoint:** replace fixed 5s with Silero VAD, ~1s trailing silence, 30s hard cap.
4. **Intent extraction:** based on option chosen (regex for A/D, LLM for B/C).
5. **DB + CRUD:** SQLite schema, apply action, return to tray.
6. **Categorization:** embeddings (A) / LLM (B/C) / manual (D).
7. **React UI:** task list view, category columns, opens from tray.
8. **Packaging:** PyInstaller `--onedir` → Inno Setup installer with Foundry Local prerequisite (only B/C) and startup registry entry.
9. **Polish:** TTL tuning, error toasts, model preload on install, parallel model loading on first hotkey.

---

## 5. Reference — explanations for future-me

### What is Foundry Local
Microsoft's local-AI runtime for Windows. Runs LLMs, embeddings, and (since v1.1) Whisper STT entirely on the user's machine via OpenAI-compatible HTTP endpoints. **Free.** Official minimum: 8GB RAM, 3GB disk. Models are downloaded via SDK (not CLI) on first use. Service idle ~200MB.

### What is `faster-whisper`
Third-party Python reimplementation of OpenAI Whisper, built on CTranslate2 (optimized C++ inference). ~4x faster than reference Whisper, lower memory. Supports loading arbitrary Whisper checkpoints (including ivrit.ai's fine-tunes). The pick when not using Foundry's bundled Whisper.

### What is Phi Silica
Microsoft's on-device 3.3B model specifically engineered for **NPU offload** on Copilot+ PCs (40+ TOPS NPU required, 16GB RAM minimum). The reason Copilot feels light on supported hardware — model runs on dedicated AI silicon, not in RAM. **Not available on regular 8GB machines.** Future opt-in path if user has a Copilot+ PC.

### Why we don't manually chunk audio
Whisper processes audio in **30-second internal windows** with prompt conditioning between windows. Slicing at 5s with overlap and aggregating ourselves:
- Breaks words at slice boundaries → garbled tokens
- Loses Whisper's previous-window context → worse accuracy
- Reinvents what Whisper already does, badly

Just feed Whisper the full audio (≤30s due to our hard cap).

### Schema flexibility — SQLite + JSON column
- Stable, queried fields (`title`, `category_id`, `created_at`, `status`) → real columns, indexed.
- Flexible/future fields (notes, tags, priority, etc.) → in a single `data` TEXT column holding JSON.
- Query JSON with `json_extract(data, '$.field')` or shorthand `data->>'field'`.
- For fields that become hot-queried later: add a virtual generated column + index, no migration needed.
- Schema changes to **indexed columns** still require migrations — handled by `PRAGMA user_version` + an ordered list of migration SQL strings in code (~30 lines, no Alembic needed).

### Model lifecycle
Foundry Local default TTL is **600s (10 min)** from load. Currently TTL is from load time, not from last-use time (open feature request: Foundry-Local issue #284). Workaround: call `load_model` again after each use to reset the TTL clock. Configurable per-load via SDK/REST API.

### RAM budget reference (8GB machine, ~3GB headroom)
- Windows 11 idle: 2.0–2.5GB
- Browser + a few apps: +1–2GB
- → Headroom for our app: ~3GB before paging
- Options A and D fit comfortably. Option B is tight. Option C requires 12GB target.

---

## 6. Open questions (besides Hebrew)

- **Hotkey choice** — `Ctrl+Shift+Space`? `Ctrl+Alt+T`? Test for conflicts with common apps (VS Code, Office).
- **Audio feedback** — silent listening vs. subtle "ding" on start/end? Visual indicator on tray icon?
- **Disambiguation UX for delete** — "delete the meeting task" when there are 3 meeting tasks. Defer to post-MVP.
- **Confirm/undo for destructive ops** — toast with 3s undo? Defer to post-MVP.
- **Auto-update mechanism** — Squirrel.Windows? Manual download? Defer to post-MVP.

---

## 7. Sources consulted

- [Foundry Local — Get started (Microsoft Learn)](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/get-started?view=foundry-classic)
- [Foundry Local 1.1 release notes — Live Transcription, Embeddings, Responses API](https://devblogs.microsoft.com/foundry/foundry-local-v1-1/)
- [Foundry Local Whisper voice transcription lab](https://github.com/microsoft-foundry/Foundry-Local-Lab/blob/main/labs/part9-whisper-voice-transcription.md)
- [Foundry Local REST API reference — TTL parameter](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/reference/reference-rest?view=foundry-classic)
- [Foundry Local architecture](https://learn.microsoft.com/en-us/azure/ai-foundry/foundry-local/concepts/foundry-local-architecture?view=foundry-classic)
- [Foundry Local — issue #284: auto-unload idle models](https://github.com/microsoft/Foundry-Local/issues/284)
- [Running Phi-4 Locally with Foundry Local — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/educatordeveloperblog/running-phi-4-locally-with-microsoft-foundry-local-a-step-by-step-guide/4466304)
- [Phi-4 quantization and inference speedup](https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/phi-4-quantization-and-inference-speedup/4360047)
- [Phi-3 Mini 3.8B specs — Local AI Master](https://localaimaster.com/models/phi-3-mini-3.8b)
- [Phi Silica on-device SLM — Windows Experience Blog](https://blogs.windows.com/windowsexperience/2024/12/06/phi-silica-small-but-mighty-on-device-slm/)
- [ivrit.ai — Training Whisper Turbo for Hebrew](https://www.ivrit.ai/en/2025/02/13/training-whisper/)
- [Comparing Whisper, ivrit.ai, and Amazon Transcribe for Hebrew](https://medium.com/@DormanDaniel/comparing-whisper-whisper-ft-and-amazon-transcribe-for-hebrew-e297846bdd24)
- [Whisper Hebrish — code-switching Hebrew/English fine-tune](https://huggingface.co/blog/danielrosehill/whisper-hebrish)
- [Whisper model sizes explained — OpenWhispr](https://openwhispr.com/blog/whisper-model-sizes-explained)
- [faster-whisper — SYSTRAN GitHub](https://github.com/SYSTRAN/faster-whisper)
- [Gemini 3 Flash Preview pricing — pricepertoken.com](https://pricepertoken.com/pricing-page/model/google-gemini-3-flash-preview)
- [Gemini API pricing — Google AI for Developers](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini audio input — generateContent API docs](https://ai.google.dev/gemini-api/docs/audio)
- [Gemini 3.1 Flash Live — native multimodal audio](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-3-1-flash-live/)
- [Gemini API rate limits — Google AI for Developers](https://ai.google.dev/gemini-api/docs/rate-limits)
