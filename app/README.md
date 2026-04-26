# Screen Intent App

Native macOS wrapper for the UI intent pipeline.

## Run

1. Start the detector server from the repo root:

   ```sh
   python3 app.py
   ```

2. In another terminal, start the wrapper:

   ```sh
   cd app
   swift run
   ```

3. Press `Command+Shift+Space`, type what you want and press `Return` / `Go`, or press the microphone button and speak.

The app captures the screen, writes a temporary env file in `app/runtime`, runs `complete_run.py`, dims the screen while the pipeline works, then highlights the selected UI element for 20 seconds or until you click.

While it is thinking, press `Stop` to cancel the current pipeline run. On the final overlay, press `Replay` to hear the spoken direction again.

The thinking animation is a native Swift port of the detective blob SVG animation, so the wrapper does not need a React dev server at runtime.

## Notes

- macOS may ask for Screen Recording permission for the terminal or Codex app that launches this process.
- Add `ELEVENLABS_API_KEY` to the repo `.env` to use ElevenLabs speech-to-text and text-to-speech.
- Optional `.env` settings: `ELEVENLABS_REALTIME_STT_MODEL=scribe_v2_realtime`, `ELEVENLABS_STT_LANGUAGE_CODE=en`, `ELEVENLABS_STT_MODEL=scribe_v2`, `ELEVENLABS_TTS_MODEL=eleven_multilingual_v2`, `ELEVENLABS_VOICE_ID=JBFqnCBsd6RMkjVDRZzb`.
- macOS may ask for Microphone permission the first time you use the microphone button.
- Runtime logs are written to `app/runtime/complete_run.log`.
- Mic, ElevenLabs, and wrapper logs are written to `app/runtime/app.log`.
- The wrapper reuses the repo `.env`, then overrides `TEST_IMAGE` and `USER_INTENT` for each run.
