# Frequently asked questions

The questions that come up when installing and first using Lanternist. If yours is not here, ask in Discussions,
category **Installation**. The messages quoted below are in Spanish, as Lanternist prints them for now.

## Before installing

### Does it work on a Mac, on Linux or with an AMD card?

No on a Mac, and no with an AMD or Intel graphics card: the images, the voice, the music and the render all need an
NVIDIA card with CUDA. Linux has not been tested, and the installer is written for Windows 11.

### Can it work with less than 8 GB of VRAM, or less than 32 GB of RAM?

It has not been tested, and the image model already does not fit whole in 8 GB. The [requirements](../README.md#requirements)
are minimums: Lanternist does not check your VRAM, your RAM or your free disk before downloading.

### Do I need a Google account or a YouTube API key?

Not to make videos. By default Lanternist uploads nothing: each run leaves the video and a page with the steps to upload
it by hand in YouTube Studio. You only need your own Google Cloud project if you want Lanternist to upload drafts for
you ([docs/youtube-upload.md](youtube-upload.md)).

### What does it cost?

Lanternist is free. Everything runs on your PC, so the cost is your electricity and your Claude plan. Claude Code
writes each script with you and puts each episode on scene, and that takes many replies: an entry plan will not
produce a week of videos.

## Installing

### I already have ComfyUI. Can Lanternist use it?

Yes, but tell Lanternist before it installs its own. The order matters:

1. run only `py -3.12 instala.py --paso requisitos` and `py -3.12 instala.py --paso env`, which creates your `.env`;
2. write in your `.env` the path of your ComfyUI in `COMFY_ROOT` (the folder that holds `main.py` and `models\`). If
   your ComfyUI is the portable one, also write the path of its `python_embeded\python.exe` in `COMFY_PYTHON`. The same
   goes for llama.cpp, with `LLAMA_SERVER` and `LLAMA_MODELO_GGUF`;
3. then run the rest: `py -3.12 instala.py`.

If you run the whole installer first, it installs its own ComfyUI in `herramientas\` and downloads about 70 GB of models
there.

With your ComfyUI, the installer does not reinstall it or touch what you have, but:

- it needs the **ComfyUI-GGUF** node in `custom_nodes\`. If it is missing, the installer stops and says so; you install
  it, because that ComfyUI is yours;
- it only reuses model files that are **identical** to the ones on its list: same name, same folder under `models\`
  and same SHA-256. A different quantization is a different file, and the missing ones are downloaded next to yours;
- Lanternist is tested with ComfyUI 0.33.0. Another version may work, but it is not guaranteed.

### The installer says a path is too long

There are two messages, with different fixes:

- **The folder is too long for a DLL** (`…demasiado larga: Windows no carga una DLL…`). Windows cannot load a DLL from
  a path longer than 259 characters, even with long paths turned on, and the environments put DLLs deep inside the
  folder. The only fix is to move your Lanternist folder to a short path, such as `C:\lanternist`, and run the
  installer again.
- **Windows long paths are off** (`…las rutas largas de Windows están apagadas…`). Without them, pip cannot install
  torch in a long folder. Move the folder to a short path, or turn long paths on in an administrator PowerShell: the
  message gives the command.

### The installer asks for Python 3.12

Lanternist's three environments use Python 3.12, even if you have another Python. Install it with
`winget install -e --id Python.Python.3.12` and run `py -3.12 instala.py` again.

If it says that an environment (`.venv`, `.venv-voz` or `.venv-escena`) already exists with another Python version, the
installer did not create it and does not touch it. Delete or rename that folder yourself, and run
`py -3.12 instala.py --paso entornos` again.

### A download stopped

Run the same command again: it resumes where it stopped. Every model and tool on the installer's fixed list
(`datos/descargas.json`) is downloaded to a `.part` file and checked against its SHA-256 when it arrives. A file that
does not match is deleted and never used; if that happens twice, the source has changed, and that is worth an issue.

### Where do the 95 GB go?

About 77 GB are models (images, music, voice, the AI marks), and the rest are the three Python environments, Node
packages and a Chrome build with WebGPU. The Hugging Face and torch caches (about 2.5 GB) always go to `C:`, even if
Lanternist is on another disk.

## Making videos

### The graphics card runs out of memory, or a step says the GPU is busy

Lanternist uses one program at a time on the graphics card, and 8 GB is not enough to share. Close anything else that
uses it (another ComfyUI, a game, a video editor) and run the step again. The render checks first: it stops with
`la GPU tiene N MB libres y el motor de escena pide 4096` when something else is using the card.

### Can Lanternist publish or schedule my videos?

No. Publishing is always your decision, video by video. By default you upload by hand; with the API upload turned on,
each video arrives as a **private draft**, and you publish it in YouTube Studio.

### Can I use my own voice?

Yes: the `crea-canal` skill can build your channel's voice from a recording of yourself, or from Kokoro's catalogue.
Only your own voice: cloning someone else's voice is not allowed ([acceptable use](../README.md#acceptable-use)).

## AI marks

### Why does YouTube show an "AI-generated" label on my videos?

Because the video is declared as synthetic media. An API upload tells YouTube so, and by hand `LEEME.html` tells you
to answer **yes** to Studio's question about altered or synthetic content. The description also carries an AI
disclosure. Expect the label on every video.
[docs/ai-marking.md](ai-marking.md#youtube-may-show-its-own-ai-label) explains it.

### A C2PA validator says "untrusted signer". Is my file broken?

No. Each installation signs with its own certificate, created on your PC, and no public authority issued it, so
validators do not know who signed. "Untrusted" means "I do not know the signer". A file changed after signing shows as
**invalid**, which is different.

### Can I turn the marks off?

No. The EU AI Act asks for them, the upload refuses a file without them, and removing them from Lanternist's outputs is
against its [acceptable use](../README.md#acceptable-use).

## Language

### Why are the messages in Spanish?

Lanternist comes from a Spanish-speaking project. The documentation is in English; the console messages, the skills and
the page with the upload steps are still in Spanish. You can ask Claude Code to explain any of them in your language.
