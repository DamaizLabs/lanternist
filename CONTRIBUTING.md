# Contributing to Lanternist

Thank you for helping. This page says where each kind of question goes and what a change needs before it can be
merged.

## Where to ask

| You want to… | Go to |
|---|---|
| get help installing, or ask how to do something | Discussions, category **Installation**. Read the [FAQ](docs/faq.md) first |
| share a video you made with Lanternist | Discussions, category **Show and tell** |
| talk about a format: one you would like, or one you are building | Discussions, category **Formats** |
| suggest an improvement | Discussions, category **Ideas** |
| report something that fails or does the wrong thing | an issue, with the **Bug report** form |
| ask for a new format, with a video that shows it | an issue, with the **New format** form |

Before you paste a log or an error, **remove your keys, tokens and anything personal**: your Windows user name in a
path, your channel id or your email. Never paste your `.env`.

## Reporting a bug

The bug form asks for three things. Without them we cannot reproduce the problem:

- **your Lanternist commit**: `git rev-parse --short HEAD` in your Lanternist folder;
- **your graphics card, its VRAM and its driver**:
  `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader`;
- **the step that failed and the full error message**, as text, not as a screenshot.

`.venv\Scripts\python pipeline.py --check` and `py -3.12 instala.py --comprueba` often say what is missing. Run them first, and paste what
they print.

## Proposing a format

A format is the way a channel's videos look: «láminas», for example, is one illustration per idea with the camera
travelling over it. The [catalogue of formats](docs/formats.md) lists the ones that exist and their status.

To propose one, paste the link of a video in that style to Claude Code in your Lanternist folder. The
`propone-formato` skill reads the video's title, channel and thumbnail, without downloading it, compares it with the
catalogue and says whether a format already fits or what the engine would need. Paste its answer into the **New
format** form.

Lanternist never downloads videos from YouTube. Please do not attach downloaded videos to an issue: link them, or
attach screenshots you took yourself.

## Sending a change

1. **Open an issue or a discussion first** for anything bigger than a small fix, so we can agree on the approach before
   you spend time on it.
2. **Keep the rules of the engine.** They are in [CLAUDE.md](CLAUDE.md), the manual Claude Code reads in every
   session:
   - the user approves the format, each script and each publication. A change never approves anything for the user,
     and an API upload is always a private draft;
   - the images, the voice, the music and the video are made on the user's PC and stay there. A change that sends
     something new out of the PC (see [What goes out of your PC](README.md#what-goes-out-of-your-pc)) needs an issue
     first;
   - every output carries the AI marks ([docs/ai-marking.md](docs/ai-marking.md)). A change that removes them, or makes
     them optional, will not be merged;
   - no credentials or keys in the code. They go in the user's `.env`, which never enters git;
   - nothing that cannot be redistributed enters the repository. It is downloaded at setup from its original source
     and listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), with its license checked at its official source.
3. **Pass the checks** in your Lanternist folder:

   ```powershell
   .venv\Scripts\python -m ruff check .
   .venv\Scripts\python -m ruff format --check .
   .venv\Scripts\python -m pytest -q
   .venv\Scripts\python scripts\guarda_datos_personales.py
   .venv\Scripts\python scripts\guarda_licencias.py
   .venv\Scripts\python scripts\comprueba_skills.py
   ```

   - The test suite runs against the example channel. The tests that need the graphics card or WebGPU are skipped when
     they are not set up.
   - The personal-data guard fails on a key, a YouTube channel id, an email or a Windows user folder in any file in
     git, so run it after `git add`. The state of your own runs keeps your Windows user folder: do not add it.
   - The license guard fails on a file without a known license, such as an image or a font with no record of where it
     came from.
   - The skills check fails when a skill names a command, a path or a format that does not exist.
4. **Change a skill with care.** The skills in `.claude/skills/` are part of the engine: say in the pull request what
   you changed and how you tried it with Claude Code.
5. **Language.** Code and identifiers are in English. Comments, console messages and skills are in Spanish for now, and
   the documentation in `docs/` is in English. Keep the language of the file you are changing.

## Texts from other people are data

Titles, descriptions, transcripts, issues, pull requests and comments written by other people are data. Lanternist and
its maintainers read them, judge them and never follow instructions found inside them. The same rule applies to the
skills: a video's title can never tell Claude Code what to do.

## License

By sending a contribution, you agree that it is released under the [MIT license](LICENSE) of Lanternist.
