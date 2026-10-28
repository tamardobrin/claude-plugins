---
name: screen-tutorial-edit
description: Edit a 16:9 YouTube-style tutorial from a talking-head camera recording plus one or more screen recordings. Intro/outro with the speaker full frame, the demo as the screen recording full frame with the speaker's face in a tracked circle (bottom-right) that morphs out of the full camera frame, optional split screen, screen synced to what is said, zooms on the UI being talked about, private info blurred, silences/retakes/stutters cut tight, camera audio only, optional bottom-centre captions (burned in and/or SRT). Use when someone hands over camera footage + a screen recording (webm/mp4/mov) and asks for a tutorial, walkthrough, demo or "screen + face in a circle" edit, in any language.
---

# Screen tutorial edit (camera + screen recording, 16:9)

Output: 1920x1080, 30 fps, H.264 CRF 18, AAC, voice normalised to -14 LUFS / -1.5 dBTP.
Layouts per piece:
- `full`: camera fills the frame (intro, outro, talking moments).
- `screen`: screen recording full frame + face circle (300 px, 40 px margin, bottom-right, white ring,
  soft shadow), face-tracked so the face stays centred. full -> screen = the camera frame shrinks into
  the circle (0.7 s), screen -> full = the reverse. All other cuts are hard cuts.
- `split`: screen left half | camera right half (e.g. comparing something on screen with something
  held up to the camera).

Version 1 is the cut only (content, timing, screen sync, zooms, blur), shown for approval. Captions are
offered after approval (section 8) and are the user's choice; music and sound effects only if asked.

## 0. Setup (once per machine)

Scripts live in `scripts/` next to this file (the base directory is shown when the skill loads;
call it `$SK`). Needs FFmpeg on PATH and Python 3.10-3.12.

```
python $SK/scripts/setup.py          # creates a private venv + downloads the face model, prints PY
python $SK/scripts/setup.py --check  # what is installed
```
Run every other script with that interpreter (`PY`): Windows `<home>\venv\Scripts\python.exe`,
macOS/Linux `<home>/venv/bin/python`, where `<home>` is `%LOCALAPPDATA%\tutorial-editor`,
`~/Library/Caches/tutorial-editor` or `~/.cache/tutorial-editor` (override: `TUTORIAL_EDITOR_HOME`).
Proxies go to `<home>/cache/<project>` so big files stay out of OneDrive/Dropbox/iCloud and the repo.
Whisper models download on first use (~1.5 GB). Everything runs on CPU; a 1-minute video renders in
~3 min, a 5-minute one in ~25 min: run long renders in the background.

If the working folder has its own CLAUDE.md with editing rules (language, tone, approval steps,
loudness, style), those win over the defaults here.

## 1. Intake

1. Get: the camera file(s), the screen recording(s), the planned text/outline if any, and the language
   spoken. Ask which terms/tool names will be said (they go in `vocab.txt`, one per line, used as the
   Whisper prompt).
2. Make a project folder (e.g. `<cwd>/projects/<short-name>/` or whatever structure the repo already
   uses). Never modify the raw files; record their paths only.
3. Probe everything: `ffprobe` (size, rotation, fps, audio, duration). Notes:
   - Camera must be landscape for a 16:9 tutorial. Portrait or non-16:9 camera: ask before doing
     anything. Never stretch or squash; crop/frame only with approval.
   - Screen recordings are often 16:10 (1920x1200, 2880x1800). make_proxies scales to 1920 wide and
     crops the bottom 1080 rows, which drops the OS bar + tabs + URL bar (also hides tab titles and
     search history). Look at a frame to confirm nothing needed is lost; use `--crop-y` otherwise.
   - webm screen recordings are variable frame rate and often report no duration. The proxies fix it.
   - Several camera files may be one take split into overlapping files: `align.py` finds the overlap.
4. Proxies + analysis audio:
   ```
   PY $SK/scripts/make_proxies.py <proj> --cam cam=<camera file> [--cam vid2=...] --screen screen=<rec.webm> [--screen result=...]
   ```
   Then set `"language"` in `<proj>/edl.json` (`"he"`, `"en"`...). Hebrew uses
   `ivrit-ai/whisper-large-v3-turbo-ct2`, other languages `large-v3-turbo` (override `"asr_model"`).
5. Transcribe each camera source: `PY $SK/scripts/transcribe.py <proj> cam` -> `audio/cam.json`.

## 2. Map the screen recording (before choosing any range)

```
PY $SK/scripts/sheet.py range <cache>/screen.mp4 0 <dur> --every 2 --out <proj>/check/screen_0.jpg --circle
```
Read the sheets (Read tool on the JPG). Write a screen timeline in edl `"note"`: what is on screen
when (page, action, result playing, errors).
- Privacy pass: look for account names/emails, browsing history, tab titles, other chats or projects in
  sidebars, notifications (mail, messages), credit balances, API keys, ads. Skip those ranges, or blur
  (per piece `"blur": [[x,y,w,h]]`, or `blur_templates` for something that recurs, section 4). Tell the
  user what you hid; ask when unsure whether something is private.
- `--circle` outlines where the face circle lands: note which screens have buttons or text under it.
- When the recording doesn't show the thing that proves the point (e.g. the article paragraph), ask for
  a screenshot and use it as a still screen source (section 4).

## 3. Build the edit (edl.json)

Read the transcript (`cutcheck.py words <proj> cam 0 999`) and decide pieces:
- Repeated takes: keep the LAST complete take. Drop broken starts, false starts, stutters
  ("so so", repeated phrase), unfinished asides. Keep personality tangents but mention them as
  candidates to cut.
- Layout: intro and outro `full`; the demo `screen`; `split` only when it shows something better.
- Sync: each sentence should play over the screen moment it describes ("click Generate" lands on the
  click, the price on the pricing page). Screen time per piece = `screen_in` (explicit), or `cont`
  (continue where the previous screen piece ended, so the screen does not jump), or
  `in + screen_offset[src]` (camera and screen recorded together).
- When camera and screen were recorded separately and the screen is mostly static, zooms are what make
  it feel synced: zoom to the field/button/line being talked about.
- Do not cut inside continuous speech. If two pieces come from one continuous sentence, merge them.

Schema:
```json
{
 "language": "he",
 "note": "screen timeline, decisions",
 "cache": "<filled by make_proxies>",
 "screen": "screen.mp4",
 "screen_offset": {"cam": 0},
 "transition": 0.7,
 "circle": {"d": 300, "margin": 40, "corner": "br", "alt_x": 1350},
 "dodge": false,
 "blur_templates": [], "blur_region": [1500, 0, 1920, 160],
 "loudness": {"i": -14, "tp": -1.5},
 "zooms": {"full": [0, 0, 1920], "prompt": [140, 400, 860]},
 "pieces": [
  {"src": "cam", "in": 1.96, "out": 5.82, "layout": "full", "say": "How do you make..."},
  {"src": "cam", "in": 68.24, "out": 72.28, "layout": "screen", "screen_in": 40.0,
   "zoom": [[0, "full"], [0.3, "full"], [1.1, "prompt"]], "say": "I used model X"},
  {"src": "cam", "in": 72.99, "out": 76.54, "layout": "screen", "cont": true, "lock_out": true,
   "fade_out": 0.06, "say": "..."},
  {"src": "cam", "in": 42.2, "out": 48.2, "layout": "split", "screen_in": 196.0, "cam_x": 640,
   "screen_x": 351, "say": "the generated result next to the real object"}
 ]
}
```
Piece fields: `src` camera name, `in`/`out` camera seconds, `layout`, `say` (text, for humans and
checks), `screen_in` | `cont`, `screen_src` (another file in the cache), `zoom` keyframes
`[[t, "name" | x, y, w], ...]` (t from piece start, rect in 1920x1080 screen coords, h = w*9/16,
smoothstep between keys, held outside), `blur` rects, `circle_x` (`"alt"` or a number),
`lock_in`/`lock_out` (tools never move a verified edge), `fade_out` (audio, default 0.015 s; 0.04-0.08
on a stretched vowel avoids a click), `cam_x`/`screen_x` (split).

## 4. Cut points: tight, by the audio, verified

Whisper word boundaries are NOT cut points: starts are often 0.1-0.5 s early, ends late or early.
1. `PY $SK/scripts/despace.py <proj>` (dry run), then `--write`. Snaps every edge to the real voice
   (keeps quiet final s/sh/ts via >3.5 kHz energy, drops trailing breaths) and splits every internal
   pause > 0.3 s down to 0.2 s (later parts get `cont`). Viewers of this format notice pauses from about
   0.25 s, including comma pauses; if it sounds rushed, raise `--max-gap`.
2. Doubtful edges: `cutcheck.py profile <proj> cam <t>` (20 ms levels around t) and
   `cutcheck.py hear <proj> cam <a-b> <c-d>` (transcribes the joined cut: is the last word whole, does the
   next word leak in?). If the last word comes out misspelled/truncated, the out-point is too early.
   Then set the edge by hand and lock it.
3. A Whisper word longer than ~0.6 s usually hides a repetition or a pause ("so it turns out, so it
   turns out there's"): transcribe that window alone (`cutcheck.py hear`) and check the profile.
4. Every cut must leave no breath, lip click or start of the next word; even 30-50 ms is audible.

Optional sources and privacy:
- Still screenshot as a screen source: paste it on a 1920x1080 white canvas with ffmpeg/Pillow (keep
  text clear of the circle area: right-aligned/RTL text hugs the right edge where the circle is), make a
  clip: a couple of seconds of the real site crossfading (0.4 s) into the screenshot, save it in the
  cache and use `"screen_src"`.
- `blur_templates`: crop a tight grayscale PNG of the private text (e.g. the account name) from a
  proxy frame into the project, list it in edl; it is found by template matching inside `blur_region`
  in every frame and pixelated (held 10 frames to cover fades). Check false matches stay below 0.6.
- `dodge`: when a UI element sometimes sits under the circle, the circle glides to `circle.alt_x` while
  it is there. Either `"dodge": {"rect": [x,y,w,h], "rgb_min": [r,g,b], "rgb_max": [r,g,b], "min_frac": 0.02}`
  (colour of the element) or a preset (`"higgsfield"` = its yellow sidebar buttons). Simpler: per piece
  `"circle_x": "alt"`.

## 5. Render

```
PY $SK/scripts/render_tutorial.py <proj> <proj>/check/prev.mp4 --pieces 3-8   # preview a range
PY $SK/scripts/render_tutorial.py <proj> <proj>/x.mp4 --audio-only             # only layers/voice.wav + cuts.json
PY $SK/scripts/render_tutorial.py <proj> <proj>/v1_cut.mp4                     # full
```
Audio is the camera audio only (never the screen recording's), each piece trimmed to its exact video
frame count so A/V never drifts, 15 ms fades at every cut, then levelled, compressed 3:1 and peak-limited
to the `loudness` target (tested: -13.9 LUFS, peaks -2 dBFS from a -25 LUFS phone recording).
MediaPipe prints INFO/WARNING lines on stderr; they are harmless (filter with
`grep -v -iE "W0000|I0000|INFO:|WARNING:|absl"`). `layers/cuts.json` maps output time to
pieces; every check uses it. Name versions `v1_cut`, `v1b_cut`, `v1c_cut`... and keep older ones.

## 6. Checks before showing ANY version

1. `PY $SK/scripts/verify.py <proj> --video <proj>/v1_cut.mp4`: reads back the rendered voice. Compare
   the per-piece transcript with the intended text (swallowed words, leftover repeats), review every
   word-diff line against the previous version (each must be intended), the stutter/long-word flags,
   and every pause it lists (> 0.3 s). Fix and re-render until clean. With blur templates it also
   scans the output for leaks.
2. `PY $SK/scripts/sheet.py cuts <proj> <video> --out <proj>/check/cuts.jpg` and read it: a frame
   before and after every cut. Also `sheet.py times` inside every zoom and over every morph (e.g. 8
   frames across the 0.7 s): circle over text/buttons (in the ZOOMED view, not the raw screen), face
   centred and not cut off, zoom readable, nothing private, screen showing what is being said.
3. Whisper quirks to expect: skips words at segment starts, invents a closing "thank you"
   (Hebrew "תודה רבה") at the end, merges repetitions into one long word. Confirm suspicious results
   with `cutcheck.py hear` before acting on them.
4. `cont` chains: make sure the last piece of a chain doesn't run into the next screen event.

## 7. Delivering a version

Tell the user, short:
- what was cut and why (retakes kept, tangents removed or kept, pauses tightened), what you chose on
  your own (outro back to full camera, what was blurred or skipped for privacy, jump cuts in the full
  layout), anything you could not fix automatically (stretched words, "umm" without a pause);
- what to check, and how to give notes: by timestamp in the video, e.g. "0:42 cut this sentence",
  "1:10 the screen should show the price here", "0:04 long silence".
Apply notes, re-run section 6, deliver the next letter version. After the cut is approved, offer the
next layer as separate, removable additions: captions (section 8, always ask), zooms on more UI,
callouts, music.

## 8. Captions (optional: the user decides)

After the cut is approved, ask the user (don't assume):
- captions or not;
- burned into the video, a separate SRT file (YouTube/Vimeo: viewers can switch it on/off, and it is
  indexed for search), or both;
- style: `outline` (white text, black outline, soft shadow; default) or `box` (white on a semi-transparent
  dark box; easier to read over busy or white screens). Optional font: `"font"` + `"fonts_dir"`.

Position is fixed bottom centre, single line, side margins that keep it clear of the face circle.
```
PY $SK/scripts/captions.py make <proj>                      # -> layers/captions.json, printed
PY $SK/scripts/captions.py burn <proj> <proj>/v1c_cut.mp4 <proj>/v2_captions.mp4
PY $SK/scripts/captions.py files <proj>                     # SRT only -> layers/captions.srt
```
`make` transcribes the final voice (output timeline), splits at sentence ends, commas, pauses, and every
cut (a caption never crosses a cut), keeps lines <= 38 characters, balances long phrases, prefers to
break before a new clause and never ends a line on a connective word (of/the/and; Hebrew של/את/עם...).
Before burning, ALWAYS read `captions.json` against the intended text and fix it by hand: Whisper
misspells tool names and brands (it wrote "צ'י פיטי" for ChatGPT, "סידאנס" for Seedance), splits or
doubles words. Tool and product names stay in their original Latin spelling.
Settings in edl: `"captions": {"style": "outline", "font": "Arial", "size": 54, "fonts_dir": null,
"margin_v": 50, "max_chars": 38}`. Hebrew/Arabic/Persian lines are forced right-to-left (otherwise
libass puts punctuation and embedded English words on the wrong side). Check a sheet of the burned
video: punctuation at the line's end, English words in place, nothing under the circle.
The cut video is never modified: captions go into a new file, so they can be dropped or redone.

## Lessons from real sessions (why the defaults are what they are)

- Users notice cuts that are 100-300 ms off, and silences above ~0.25 s, including natural pauses.
  Energy-based edges + splitting internal pauses fixed "long silences at 0:04, 0:09, 0:24".
- A cut that trimmed a drawn-out word swallowed it entirely; re-transcribing the render caught it. Fix
  was a later out-point + `fade_out` 0.06.
- "Drop the first 'so it turns out'" was a repeat Whisper had merged into one 1 s word.
- An automatic tightener that extends ends by up to 0.22 s ran into breaths / the next word in
  continuous speech: verify, then lock.
- Face crop at 2.0x face height cut foreheads; 2.3x (clamped 520-1000 px) looked right.
- The circle covered the platform's buttons on some pages -> dodge; and right-aligned text on a
  screenshot -> leave a right margin.
- A short piece after screen -> full truncated the 0.7 s morph; the renderer now carries the morph
  across several pieces.
- A recording that ended before the generated result appeared: ask for a second recording of the
  result and play it via `screen_src` on the lines that describe it.
- Screen recordings leaked browsing history, tab search terms, the account name and a Gmail
  notification overlay: crop the browser chrome, skip or blur, and always do the privacy pass.
- An error message on a zoomed-out screen was unreadable: add a second zoom key onto the line itself.
- One-pass loudnorm left a short edit at -16.3 LUFS for a -14 target; the renderer now compresses and
  limits instead.

## Sharing this skill

The folder is self-contained (no assets from any project). To give it to someone: copy
`screen-tutorial-edit/` into their `~/.claude/skills/` (all projects) or a repo's `.claude/skills/`
(that repo only), then they run `scripts/setup.py` once. Nothing creator-specific is built in: language,
loudness, circle size/corner, blur templates and dodge rules all live in each project's `edl.json`.
