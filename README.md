# World Push

An unofficial desktop app for checking and pushing Voyage world JSON through Voyage's Creator API, instead of pasting it into Studio.

It tells you what's wrong before you push, shows exactly what would change, backs up the live draft first, and confirms what landed. It doesn't fix your file for you, and it never publishes: publishing stays in Studio.

## Download

Get the Linux or Windows file from the [Releases](../../releases) page. It's a single file with nothing to install. On Linux, mark it executable first (`chmod +x WorldPush-linux`).

These builds aren't code-signed, so the first time you run it on Windows, a blue "Windows protected your PC" box comes up. Running as administrator doesn't get past it. Press **More info**, then **Run anyway**. Windows remembers after that.

## Using it

1. Run the app and paste your API key. In Studio: open any world, then Settings, then API keys. The key stays on your computer in a plain text file in your user folder (not encrypted), and is only sent to Voyage.
2. Pick the world, and drop your JSON on the window (or press Browse).
3. Press **Check**. This writes nothing. You get:
   - **Problems:** Voyage's errors and warnings grouped by type, each with what's wrong, how to fix it, and how much to cut if it's too long. Red stops a save, orange stops publishing, grey is a warning. Drafts get more room than published worlds, so there are two size limits (an NPC card is 12,000 characters in a draft, 8,000 to publish).
   - **What does this mean?:** the words and rules explained, if you're new to this.
   - **What changes:** a short list first (say, "Abilities: 59 added", "NPCs: 3 changed"), then every field that differs from the live draft. Pick one to see the words taken out struck through and the new words marked, then the whole before and after.
   - **Edits made in Studio:** anything changed in Studio since your last push from this app.

   On Problems, **Show** picks one kind (red, orange or grey) and **Find** narrows it to a name, field or word. **Copy report** puts the whole check on your clipboard as plain text, to paste to someone helping you.

   The app also checks a few things Voyage's own check doesn't: triggers that are copies of each other, AI-judged questions asked more than once, and the AI-judged quest checks Voyage builds when it saves (a file can pass the check and still be over the 500 limit once saved). The banner shows how many AI-judged triggers you've used of the 500.

   After you've checked a file, saving it again in your editor checks it again by itself.
4. Press **Back up and push**. If Studio has edits since your last push, or this computer hasn't pushed this world before, you have to type the world's title to confirm.

The app remembers the last world and file for next time. When it starts, it asks GitHub whether a newer World Push is out, and shows a button if so. That request sends nothing about you or your worlds.

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
