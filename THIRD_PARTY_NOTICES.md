# Third-party notices

Lanternist builds on code, fonts, tools and models made by other people. This file lists each of them with its
license, and says whether it travels in this repository or is installed or downloaded on your PC.

- **In this repository**: only what its license allows to redistribute (sections 1 and 2).
- **Installed or downloaded at setup**: everything else (sections 3 to 5). It comes from its original source, and
  Lanternist does not redistribute it.

Every license below was checked at its official source on the date shown. Nothing here is legal advice.

## 1. Code derived from faceless-youtube-agents (MIT)

The production skeleton of Lanternist (`pipeline.py`, `lib/state.py`, `lib/youtube_client.py`, `lib/config.py` and
the first skills) comes from [yashaiguy-dev/faceless-youtube-agents](https://github.com/yashaiguy-dev/faceless-youtube-agents),
commit `e92c84537996217dd6fff60da9acc87198022b0b` (30 April 2026). It has been heavily modified since.

The upstream README declares the MIT License («## License — MIT»), and its tree at that commit ships no LICENSE file
(checked on 2026-10-14 at the commit's `README.md` and with the GitHub API). The copyright holder and year below are
the repository owner and the year of that commit. The license text is the SPDX one
(`https://github.com/spdx/license-list-data/blob/main/text/MIT.txt`).

```
MIT License

Copyright (c) 2026 yashaiguy-dev

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial
portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## 2. Fonts in this repository (SIL Open Font License 1.1)

They live in `datos/escena/fuentes/`, each with the full OFL text next to it. Their source, author and sha256 are in
`datos/escena/fuentes/CREDITOS.json`.

| Font | Files | Copyright | License text |
|---|---|---|---|
| Baloo 2 | `baloo-2-latin-700-normal.woff2` | Copyright 2019 The Baloo 2 Project Authors | `OFL-Baloo2.txt` |
| Fredoka | `fredoka-latin-400-normal.woff2`, `fredoka-latin-700-normal.woff2` | Copyright 2016 The Fredoka Project Authors | `OFL-Fredoka.txt` |
| Patrick Hand SC | `PatrickHandSC-Regular.ttf` | Copyright 2012 The Patrick Hand Authors | `OFL-PatrickHandSC.txt` |
| Gelasio | `Gelasio-VariableFont_wght.ttf`, `Gelasio-Italic-VariableFont_wght.ttf` | Copyright 2022 The Gelasio Project Authors | `OFL-Gelasio.txt` |
| Anton | `Anton-Regular.ttf` | Copyright 2020 The Anton Project Authors | `OFL-Anton.txt` |

The OFL texts of Baloo 2, Fredoka and Gelasio come from [google/fonts](https://github.com/google/fonts) (`ofl/<family>/OFL.txt`,
commit `e9678a5385322c63730122ba464765baad83cfd8`, 2026-10-14). Anton and its OFL text come from the same repository
(`ofl/anton/`, commit `cee74d7ca45d66d5c1878c828645c862f2788d2d`, 2026-10-15).

The thumbnail and the channel banner are drawn with a font that the channel profile declares from this folder
(`imagen.fuente_de_la_miniatura` and `marca.banner.fuente`), never with a system font: the font is copied into the run
and listed in its `assets.json` with its license.

## 3. Installed with npm (`cd motor; npm ci`)

| Package | Version | License | What Lanternist does with it |
|---|---|---|---|
| [HyperFrames](https://github.com/heygen-com/hyperframes) | 0.8.78 | Apache-2.0 (its `package.json` and the GitHub API, 2026-10-14) | Renders the HTML composition to video |
| [GSAP](https://gsap.com) | 3.14.2 | GSAP Standard "No Charge" License, [gsap.com/standard-license](https://gsap.com/standard-license) (read on 2026-10-14) | Drives the timeline of every composition. Copied into each run's composition, never into this repository |

**About the GSAP license.** It is not an open source license, and it gives no express right to redistribute GSAP, so
GSAP is installed from npm and is not part of Lanternist's MIT code. Its plain-English summary allows free use «in
commercial or non-commercial apps, web sites, games, components, and other software as long as end users are not
charged a fee of any kind to use your product». It also lists as «Prohibited Uses» tools «that allow users to build
visual animations without code» that compete with Webflow's visual animation builder. Lanternist is free, and its
videos are written as code. If you build a paid product on top of Lanternist, read that license first.

**Sound effects from Pixabay.** The nine sound effects (`datos/escena/sfx/CREDITOS.json`) are from
[Pixabay](https://pixabay.com/sound-effects/) and come inside the HyperFrames package. The
[Pixabay Content License](https://pixabay.com/service/license-summary/) allows commercial use without attribution
inside a work, but not distributing the files on their own (checked on 2026-10-07; on 2026-10-14 the page answered
403 to a script). So they do not travel in this repository: `scripts/instala_efectos.py` copies them from
`motor/node_modules/hyperframes` and refuses any file whose sha256 differs from the one listed.

## 4. Tools installed at setup

| Tool | Version | License | Notes |
|---|---|---|---|
| [ComfyUI](https://github.com/Comfy-Org/ComfyUI) | 0.33.0, commit `de6b062` | GPL-3.0 (`LICENSE` at that commit, 2026-10-14) | Runs as a separate process; Lanternist talks to it over HTTP on `127.0.0.1` and does not include its code |
| [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) | commit `6ea2651` | Apache-2.0 (`LICENSE` at that commit, 2026-10-14) | The only custom node; loads the GGUF image models |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | release `b10850` (commit `f114f91`), CUDA 12.4 build | MIT (`LICENSE`, 2026-10-14; the GitHub API, 2026-10-24) | Runs the Orpheus voice model as a local server |
| CUDA runtime and cuBLAS DLLs | 12.4, the `cudart-llama-bin-win-cuda-12.4-x64.zip` of that llama.cpp release | [NVIDIA CUDA Toolkit EULA](https://docs.nvidia.com/cuda/eula/index.html): `cudart` and `cublas` are in its Attachment A of redistributable files (read on 2026-10-24) | llama-server needs them. `instala.py` downloads them from the llama.cpp release, next to llama-server; Lanternist does not ship them |
| Chrome headless shell | 152.0.7977.30 | The Chromium license (BSD-3-Clause, «Copyright 2015 The Chromium Authors») and the notices of its third-party components, in the `LICENSE.headless_shell` file of the 152.0.7977.30 download (read on 2026-10-24) | Downloaded by HyperFrames (`npx hyperframes browser ensure`); Lanternist does not ship it |
| `dxil.dll`, `dxcompiler.dll` | from [Chrome for Testing](https://googlechromelabs.github.io/chrome-for-testing/) 152.0.7977.30, the version of the headless shell | Microsoft Software License Terms for the DirectX Shader Compiler (`LICENSE-MS.txt` in its [release](https://github.com/microsoft/DirectXShaderCompiler/releases), read on 2026-10-14): use «solely for use on Windows», and redistribution only under its «Distributable Code» conditions | WebGPU needs them and the headless shell lacks them. `instala.py` downloads that Chrome for Testing build from Google, takes only these two files and `scripts/instala_chrome_webgpu.ps1` copies them next to the headless shell. (Google Chrome 155 no longer ships `dxil.dll`, so they can no longer come from your own Chrome.) Lanternist never ships them |
| Voice environment (`.venv-voz`) | `spikes/requirements-voz.txt` | Mostly Apache-2.0 and MIT. `phonemizer-fork` 3.3.2 is GPLv3+ (PyPI, 2026-10-14) and `espeakng-loader` loads eSpeak NG, which is GPL-3.0 (`COPYING`, 2026-10-14) | Installed by pip on your PC. The MIT source code of Lanternist is fine with them; a package or image that bundles `.venv-voz` would have to follow the GPL |
| [AudioSeal](https://github.com/facebookresearch/audioseal) | 0.2.0 | MIT (`LICENSE` of the repository and of the wheel, 2026-10-15) | Puts and reads the audio watermark of the AI mark. Installed by pip in `.venv-escena` |
| [c2pa-python](https://github.com/contentauth/c2pa-python) | 0.38.0 | MIT OR Apache-2.0 (PyPI and the wheel metadata, 2026-10-15) | Signs and reads the C2PA metadata of the AI mark. Installed by pip in `.venv-escena` |
| [PyAV](https://github.com/PyAV-Org/PyAV) | 19.0.1 | BSD-3-Clause (`LICENSE.txt` of the repository and of the wheel, 2026-10-15). Its Windows wheel bundles FFmpeg built with libx264 and libx265 (the `av.libs` folder), which are GPL-2.0 (their `COPYING` files, read on 2026-10-15) | Decodes the video while it is marked. Installed by pip in `.venv-escena` from PyPI; Lanternist does not redistribute it. A package or image that bundles `.venv-escena` would have to follow the GPL |

## 5. Models downloaded at setup

None of these files travel in this repository. Each one is downloaded from its source when you install Lanternist:
`instala.py` takes them from a fixed list, `datos/descargas.json`, with the URL of a fixed revision and the sha256 of
each file, and deletes anything that arrives with another sha256.
Licenses read from each model card (`cardData.license` in the Hugging Face API) or repository on 2026-10-14.

| Model | Source of the file Lanternist uses | License |
|---|---|---|
| Qwen-Image | [city96/Qwen-Image-gguf](https://huggingface.co/city96/Qwen-Image-gguf) (`qwen-image-Q6_K.gguf`), from [Qwen/Qwen-Image](https://huggingface.co/Qwen/Qwen-Image) | Apache-2.0 |
| Qwen-Image-2512 | [unsloth/Qwen-Image-2512-GGUF](https://huggingface.co/unsloth/Qwen-Image-2512-GGUF) (`qwen-image-2512-Q6_K.gguf`), from [Qwen/Qwen-Image-2512](https://huggingface.co/Qwen/Qwen-Image-2512) | Apache-2.0 |
| Qwen-Image-Edit-2511 | [unsloth/Qwen-Image-Edit-2511-GGUF](https://huggingface.co/unsloth/Qwen-Image-Edit-2511-GGUF) (`qwen-image-edit-2511-Q6_K.gguf`), from [Qwen/Qwen-Image-Edit-2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) | Apache-2.0 |
| Qwen-Image-Lightning (8-step LoRA) | [lightx2v/Qwen-Image-Lightning](https://huggingface.co/lightx2v/Qwen-Image-Lightning) (`Qwen-Image-Lightning-8steps-V1.0.safetensors`) | Apache-2.0 |
| Qwen2.5-VL 7B text encoder and Qwen-Image VAE | [Comfy-Org/Qwen-Image](https://huggingface.co/Comfy-Org/Qwen-Image) (`qwen_2.5_vl_7b_fp8_scaled.safetensors`, `qwen_image_vae.safetensors`); base [Qwen/Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct) | Apache-2.0 |
| ACE-Step v1 3.5B | [Comfy-Org/ACE-Step](https://huggingface.co/Comfy-Org/ACE-Step) (`ace_step_v1_3.5b.safetensors`), from [ACE-Step/ACE-Step-v1-3.5B](https://huggingface.co/ACE-Step/ACE-Step-v1-3.5B) | Apache-2.0 |
| Kokoro-82M | [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0 |
| Orpheus TTS 3B 0.1 | [unsloth/orpheus-3b-0.1-ft-GGUF](https://huggingface.co/unsloth/orpheus-3b-0.1-ft-GGUF) (`orpheus-3b-0.1-ft-Q8_0.gguf`) and the tokenizer of [audo/orpheus-3b-0.1-ft](https://huggingface.co/audo/orpheus-3b-0.1-ft), from [canopylabs/orpheus-3b-0.1-ft](https://huggingface.co/canopylabs/orpheus-3b-0.1-ft) | **Llama 3.2 Community License** (see below) |
| SNAC 24 kHz | [hubertsiuzdak/snac_24khz](https://huggingface.co/hubertsiuzdak/snac_24khz) | MIT |
| Whisper small | [openai/whisper-small](https://huggingface.co/openai/whisper-small) | Apache-2.0 |
| SAM 2.1 hiera-large | [facebook/sam2.1-hiera-large](https://huggingface.co/facebook/sam2.1-hiera-large) | Apache-2.0 |
| Real-ESRGAN x4plus anime 6B | [`RealESRGAN_x4plus_anime_6B.pth`](https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth), release v0.2.2.4 of [xinntao/Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) | BSD-3-Clause, the license of the repository that publishes it. The weight has no license of its own: neither the release nor `docs/anime_model.md` gives one |
| Video Seal 1.0 (AI mark: image and video watermark) | [`y_256b_img.jit`](https://dl.fbaipublicfiles.com/videoseal/y_256b_img.jit), the TorchScript of [facebookresearch/videoseal](https://github.com/facebookresearch/videoseal) | MIT, code and weights: «All models… released under MIT» (`README` and `LICENSE`, read on 2026-10-15) |
| AudioSeal 16-bit generator and detector (AI mark: audio watermark) | [`generator_base.pth` and `detector_base.pth`](https://huggingface.co/facebook/audioseal/tree/3c19eba53390776cf2cc9ed5f6c9ac67ce72ecba) of [facebook/audioseal](https://huggingface.co/facebook/audioseal), revision `3c19eba` | MIT, code and weights since 2024-04-02 (`README` and model card, read on 2026-10-15) |

The three AI-mark weights are downloaded at setup too, to `<torch hub dir>/checkpoints/lanternist/`; if one is missing,
Lanternist downloads it the first time it marks or checks a file. Their sha256 is checked when they arrive and every
time they are loaded (`datos/descargas.json`, read by `lib/marca_ia.py → MODELOS`).

### Built with Llama

Orpheus TTS 3B is a derivative of Llama 3.2: every model card above declares `meta-llama/Llama-3.2-3B-Instruct` as its
base model. The cards say `apache-2.0`, but the
[Llama 3.2 Community License](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/LICENSE) governs
derivative works, so Lanternist follows it:

- **Built with Llama.**
- Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.
- Using the voice means accepting that license and the
  [Llama 3.2 Acceptable Use Policy](https://github.com/meta-llama/llama-models/blob/main/models/llama3_2/USE_POLICY.md)
  (both read on 2026-10-14). That policy forbids, among other things, «Representing that the use of Llama 3.2 or
  outputs are human-generated». Lanternist marks every upload as AI-generated content.

### Kokoro's training data

The Kokoro-82M weights are Apache-2.0. Its model card (revision `f3ff357`, read on 2026-10-15) also lists audio under
Creative Commons Attribution that was part of the dataset used to train Kokoro v1.0, and credits it:

| Audio data | License |
|---|---|
| [Koniwa](https://github.com/koniwa/koniwa) `tnc` | [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/deed.ja) |
| [SIWIS](https://datashare.ed.ac.uk/handle/10283/2353) | [CC BY 4.0](https://datashare.ed.ac.uk/bitstream/handle/10283/2353/license_text) |

Lanternist uses Kokoro only to make the reference clip that Orpheus imitates. It does not ship Kokoro, its voices or that
audio.
