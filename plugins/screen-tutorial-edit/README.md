# screen-tutorial-edit

Claude Code plugin that edits a 16:9 tutorial from a camera recording + screen recording(s).

- Intro/outro with the speaker full frame; the demo as the screen recording with the speaker's face in a
  tracked circle that morphs out of the full camera frame; optional split screen.
- Screen synced to what is said, zooms on the UI being talked about, private info blurred.
- Silences, retakes and stutters cut tight by the audio itself; every version re-transcribed and checked.
- Optional captions, bottom centre (burned in and/or SRT), right-to-left languages handled.

## Install

```
/plugin install screen-tutorial-edit --marketplace tamar-solu/my-claude-plugin
```

Requirements: FFmpeg on PATH, Python 3.10-3.12. First run: `python skills/screen-tutorial-edit/scripts/setup.py`
(creates a private venv with faster-whisper, MediaPipe, OpenCV and downloads the face model).
Then ask Claude to edit a tutorial from your camera file and screen recording.
