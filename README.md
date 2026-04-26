# Screen Intent

Screen Intent is a local macOS assistant that lets you press a keyboard shortcut, ask what you want to do on screen, and get a highlighted UI element plus a short direction.

The repo has three pieces:

- `app.py`: Gradio detector server for UI element boxes.
- `test.py`, `llm.py`, `intent_resolver.py`, `complete_run.py`: pipeline scripts that detect elements, label them, resolve the user intent, and write JSON outputs.
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
python3 app.py
```

Keep this running. It serves the detector at `http://127.0.0.1:7860`.

Terminal 2:

```sh
cd app
swift run
```

Then press `Command+Shift+Space` and start speaking. The command bar begins recording immediately. You can also type your request and press `Return` or `Go`.

The app will:

1. Hide the command bar.
2. Capture a screenshot.
3. Run `complete_run.py`.
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
python3 complete_run.py
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

Then run `python3 app.py` and `swift run` as above.

## Permissions

macOS may ask for:

- Screen Recording permission for the terminal/app that launches Screen Intent.
- Microphone permission when using the mic button.

If screenshots fail, open `System Settings > Privacy & Security > Screen Recording` and enable the terminal you use to run `swift run`.

## Logs And Cache

- Swift wrapper logs: `app/runtime/app.log`
- Pipeline logs from the app: `app/runtime/complete_run.log`
- Pipeline outputs: `test_outputs/`

`complete_run.py` reuses detector and LLM semantics when the screenshot content is unchanged. Set this in `.env` to force a full rerun:

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
