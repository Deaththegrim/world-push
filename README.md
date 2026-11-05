# World Push

An unofficial desktop app for checking and pushing Voyage world JSON through Voyage's Creator API, instead of pasting it into Studio.

It tells you what's wrong before you push, shows exactly what would change, backs up the live draft first, and confirms what landed. It doesn't fix your file for you, and it never publishes: publishing stays in Studio.

## Download

Get the Linux or Windows file from the [Releases](../../releases) page. It's a single file with nothing to install. On Linux, mark it executable first (`chmod +x WorldPush-linux`). These builds aren't code-signed, so Windows may warn you the first time.

## Using it

1. Run the app and paste your API key. In Studio: open any world, then Settings, then API keys. The key stays on your computer in a plain text file in your user folder (not encrypted), and is only sent to Voyage.
2. Pick the world, and drop your JSON on the window (or press Browse).
3. Press **Check**. This writes nothing. You get:
   - **Problems:** Voyage's errors and warnings grouped by type, each with what's wrong and how to fix it. Red stops a save, orange stops publishing, grey is a warning.
   - **What changes:** every field that differs from the live draft, with before and after.
   - **Edits made in Studio:** anything changed in Studio since your last push from this app.
4. Press **Back up and push**. If Studio has edits since your last push, or this computer hasn't pushed this world before, you have to type the world's title to confirm.

## Backups

Before every push, the live draft is saved to `Documents/World Push backups/<world>/`. To go back, open that backup file in the app and push it like any other file. A failed backup stops the push.

A push replaces the world's content. The title, image, tags, description and visibility stay whatever Studio has.

## Limits

- It pushes a whole world, not a piece of one.
- The first push to a world from a computer can't tell Studio edits from your own, so read What changes before you confirm.
- A backup can't be pushed back once Voyage has moved the world to a newer version. Voyage keeps its own revision history for that case.
- Advice covers the problem types we've met. Anything else still shows Voyage's own message.

## Building

Python 3.11+:

    pip install -e ".[dev]"
    python -m world_push
    QT_QPA_PLATFORM=offscreen python -m pytest tests
    pyinstaller packaging/world_push.spec

GitHub Actions builds Linux and Windows on a `v*` tag or by hand. Not made by or affiliated with Voyage or Latitude.

MIT licence (see LICENSE). The builds include Qt and PySide6, which are under the LGPL v3.
