# Accent

Accent is a local macOS accessibility assistant that lets a user ask what to do on screen, then highlights the correct UI element and speaks a short direction. It is designed for older adults, non-English speakers, and anyone who needs software to feel more learnable in the moment.

[Devpost](https://devpost.com/software/accent-cdw2qi) · Submitted to LA Hacks 2026

# Demo

![Accent demo](assets/accent-demo.gif)

## Awards

- 1st Place Winner, Light The Way Track (Powered by Aramco)
- Winner, Figma Make Challenge

## What It Does

Accent turns voice and screen context into a concrete UI action:

1. Listens to a natural language request, including vague requests like "Why can't they hear me?" or multilingual requests.
2. Captures the current macOS screen.
3. Detects visible UI elements with an RF-DETR-based computer vision model.
4. Builds crop sheets and structured element metadata so an LLM can reason over the interface reliably.
5. Resolves the user's intent with Gemini or Ollama.
6. Highlights the selected UI element and speaks the instruction back with ElevenLabs TTS.

## How It Works

- **Perception:** Swift/AppKit command bar, ElevenLabs realtime speech-to-text, macOS screenshot capture, Gradio detector server, RF-DETR UI element detection.
- **Reasoning:** Python pipeline that normalizes detections, generates crop sheets, labels UI elements, and resolves user intent with structured LLM outputs.
- **Output:** Native macOS overlay highlights the target element while the app displays and speaks the next step.

## Tech Stack

Swift, AppKit, Python, Gradio, PyTorch, RF-DETR, Hugging Face, Gemini, Ollama, ElevenLabs, LangChain, OpenCV, NumPy, Pillow.

The repo has three pieces:

- `detector_server.py`: Gradio detector server for UI element boxes.
- `run_detector.py`, `label_elements.py`, `resolve_intent.py`, `run_pipeline.py`: pipeline scripts that detect elements, label them, resolve the user intent, and write JSON outputs.
- `app/`: native Swift macOS wrapper with the command bar, microphone, waiting animation, and final highlight overlay.

## Fresh Setup

From a fresh clone:

```sh
git clone git@github.com:RyloRiz/accent.git
cd accent
git lfs install
git lfs pull
python3 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Make sure `model.pth` exists in the repo root and is the real model file, not a tiny Git LFS pointer:

```sh
ls -lh model.pth
```

If it is only a few bytes or a few KB, run `git lfs pull` again.

Build the macOS wrapper once:

```sh
cd app
swift build
cd ..
```

## Local Env

Create a local `.env` in the repo root. This file is ignored by Git and should contain your private keys/settings.

Minimal Gemini setup:

```sh
GEMINI_API_KEY=your_gemini_key_here
LLM_PROVIDER=gemini
INTENT_PROVIDER=gemini
GEMINI_MODEL=gemini-3.1-pro-preview
GEMINI_FALLBACK_MODEL=gemini-3.1-pro-preview
CONFIDENCE_THRESHOLD=0.1
```

Optional ElevenLabs voice setup:

```sh
ELEVENLABS_API_KEY=your_elevenlabs_key_here
ELEVENLABS_REALTIME_STT_MODEL=scribe_v2_realtime
ELEVENLABS_STT_MODEL=scribe_v2
ELEVENLABS_TTS_MODEL=eleven_multilingual_v2
ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb
```

Optional Ollama setup:

```sh
LLM_PROVIDER=ollama
INTENT_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma4:e4b
OLLAMA_INTENT_MODEL=gemma4:e4b
```

## Run The App

Terminal 1, from the repo root:

```sh
source env/bin/activate
python3 detector_server.py
```

Keep this running. It serves the detector at `http://127.0.0.1:7860`.

Terminal 2:

```sh
cd app
swift run
```
If you have stale paths do:
```
swift package clean
```

Then press `Command+Shift+Space` and start speaking. The command bar begins recording immediately. You can also type your request and press `Return` or `Go`.

The app will:

1. Hide the command bar.
2. Capture a screenshot.
3. Run `run_pipeline.py`.
4. Show the detective waiting animation while the pipeline works.
5. Highlight the selected element and display `direction_for_user`.

The mic button stops or restarts listening while the command bar is open. During the waiting screen, `Stop` cancels the current pipeline run. On the final result, `Replay` repeats the spoken direction.

## Run The Pipeline Without The Swift App

Add these to `.env`:

```sh
TEST_IMAGE='/absolute/path/to/screenshot.png'
USER_INTENT='Why cant they hear me?'
```

Then run:

```sh
source env/bin/activate
python3 run_pipeline.py
```

Generated outputs are written to `test_outputs/`, including:

- `detections.json`: raw detector boxes and confidence scores.
- `annotated_image.png`: screenshot with element ids.
- `crop_sheet_*.png`: cropped element sheets for visual labeling.
- `llms.json`: `{element_id: semantic_description}`.
- `final_action_buttons.json`: semantic descriptions plus pixel boxes.
- `conflict_resolution.json`: selected element and user-facing direction.

## After Git Pull

When you pull new code:

```sh
git pull
git lfs pull
source env/bin/activate
pip install -r requirements.txt
cd app
swift build
cd ..
```

Then run `python3 detector_server.py` and `swift run` as above.

## Permissions

macOS may ask for:

- Screen Recording permission for the terminal/app that launches Screen Intent.
- Microphone permission when using the mic button.

If screenshots fail, open `System Settings > Privacy & Security > Screen Recording` and enable the terminal you use to run `swift run`.

## Logs And Cache

- Swift wrapper logs: `app/runtime/app.log`
- Pipeline logs from the app: `app/runtime/pipeline.log`
- Pipeline outputs: `test_outputs/`

`run_pipeline.py` reuses detector and LLM semantics when the screenshot content is unchanged. Set this in `.env` to force a full rerun:

```sh
FORCE_FULL_PIPELINE=true
```

## Git Hygiene

Do not commit `.env`. It is already ignored by `.gitignore`.

Check before committing:

```sh
git status --short
git check-ignore -v .env
```

The second command should show `.gitignore` as the reason `.env` is ignored.

Generated files in `test_outputs/`, Swift runtime files in `app/runtime/`, local virtualenvs, and Python bytecode are ignored and should not be committed.
