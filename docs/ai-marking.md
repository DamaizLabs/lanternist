# AI marking: what Lanternist puts in every video, and how to check it

Every video and thumbnail that Lanternist produces carries **two machine-readable marks** that say it was made with
AI, plus a **signpost** that tells other detectors which detector to use. You do not have to switch them on. They are
added by the pipeline, and the upload refuses a file without them.

Why: Lanternist generates synthetic images, voice and video, so it falls under **Article 50(2) of the EU AI Act**,
which has applied since 2 August 2026. That article asks the provider of such a system to mark its outputs in a
machine-readable way and to make them detectable as AI-generated. The open-source exemption does not cover systems
under Article 50. The way to comply is described in the EU **Code of Practice on marking and labelling of
AI-generated content** (final text, 10 June 2026), whose Section 1 asks for two layers of marking and a free
detector. The last part of this page compares Lanternist with that Section, point by point.

## What gets marked

| File | Layer 1: signed metadata | Layer 2: invisible watermarks |
|---|---|---|
| `subir-al-canal/final.mp4`, picture | a C2PA manifest for the whole file | Video Seal 1.0, a 256-bit message, and a TrustMark signpost that carries the number 59 |
| `subir-al-canal/final.mp4`, sound | the same manifest | AudioSeal, a 16-bit message |
| `subir-al-canal/thumbnail.png` | a C2PA manifest | Video Seal 1.0 and the TrustMark signpost |

- **The watermark** is a pattern hidden in the pixels and in the sound. It carries a fixed message that means
  "made with Lanternist". You cannot see it or hear it, and it survives re-encoding, resizing, cropping and
  screenshots (see [What survives](#what-survives)). Both models are by Meta and are MIT-licensed, code and weights
  ([Video Seal](https://github.com/facebookresearch/videoseal), [AudioSeal](https://github.com/facebookresearch/audioseal)).
- **The signpost** is a second watermark in the picture, made with
  [TrustMark](https://github.com/adobe/trustmark) (by Adobe; MIT-licensed, code and weights). It does not say "AI": it
  carries a number, 59, that points to Lanternist's entry in the C2PA list of watermarking algorithms. A detector that
  has never heard of Lanternist can read it with TrustMark's own decoder and learn which detector to use. That is the
  "interoperability" the EU Code of Practice asks for (Measure 3.4 c). How to read every mark with its authors' tools:
  [For other detectors](#for-other-detectors).
- **The model files** (the Video Seal model, AudioSeal's marker and detector, and TrustMark's configuration, encoder
  and decoder, about 390 MB in all) are downloaded by the installer (`instala.py`, step `marca`), and checked against
  their SHA-256 when they arrive and every time they are loaded. If one is missing, Lanternist downloads it the first
  time it marks or checks a file.
- **The C2PA manifest** (also called *Content Credentials*) is a signed record embedded in the file. It says that the
  content was created by AI (the IPTC value `trainedAlgorithmicMedia`), with which tool (Lanternist and its version)
  and when. It also declares each watermark in the file, with the action `c2pa.watermarked.unbound` and a short
  description. The signature binds the exact bytes of the file, so any change to the file breaks it.
- **The order matters.** The signpost goes in first, Video Seal on top of it, and the signature last, because signing
  binds the bytes. The other way round, the signpost wipes out Video Seal in flat images (see
  [What survives](#what-survives)).
- **Right after marking, Lanternist checks its own output.** If the marks cannot be read back, the run stops.
- **The record** of what was marked, with the read-back result, goes into the run's `montaje.json`, `miniatura.json`
  and `assets.json`.

### The signing certificate

The manifest is signed with a certificate that **your installation creates** the first time it signs, in
`~/.lanternist/c2pa/`. It never leaves your PC and never goes into git.

- **Public validators will say "untrusted signer".** A certificate only counts as trusted if a certificate authority
  on the C2PA trust list issued it. Lanternist cannot ship one: the private key would have to travel with the code, or
  every file would have to be signed on a remote server. Both break the rules of a local, open-source tool. The Code
  of Practice allows for this: it asks providers to keep their signing keys confidential "except in circumstances
  where the deployment context does not permit the secure handling or provisioning of the key, for example in a local
  deployment scenario" (Sub-measure 1.1.1).
- **The signature is still valid.** "Untrusted" means "I do not know who signed this", not "this was tampered with".
  A file changed after signing shows up as **invalid**.
- **There is no trusted timestamp.** The time in the manifest is your PC's clock, signed with the rest. A trusted
  timestamp needs a network service, and Lanternist does not send your files out of your PC except to upload them to
  YouTube.
- **Keep the folder.** If you delete `~/.lanternist/c2pa/`, Lanternist creates a new certificate, and the files you
  signed before can still be validated with the certificate they carry.

## Checking a file

The detector accepts videos, images and audio files. It looks for the four things it knows how to read: the C2PA
manifest, the picture watermark, the signpost and the sound watermark. It gives one line for each, then a conclusion
in plain language. It runs on the graphics card if it is free, and on the CPU otherwise. You can use it from a page in your
browser or from a terminal; both give the same result.

### On a page in your browser, without a terminal

1. Double-click **`detector.cmd`** in the Lanternist folder. A window called "Lanternist AI mark detector" opens, and
   then the detector page opens in your browser.
2. Drag a video, an image or an audio file onto the page, or click the page to choose one. Files of up to 2 GB are
   accepted.
3. Read the result: one line for each layer and the conclusion. The **Download the signed result** button saves the
   signed result described below.
4. Close the window to stop the detector. If you close the browser tab first, the window shows the address that opens
   the page again.

A file the detector cannot read is refused with the reason, as **not checked**. That is not the same as **not
marked**: it means the detector could not look at the file. A file with nothing to look at, with no picture, no sound
and a type that cannot carry C2PA metadata (a subtitle file, for example), is **not checked** too.

**Nothing leaves your PC.**

- The page talks only to the program in that window. The program listens on your own computer only (`127.0.0.1`),
  and answers only the page it opened: every request must carry a random key that changes each time it starts.
- The page contains everything it needs and loads nothing from the internet. Its security policy does not let the
  browser fetch or send anything elsewhere.
- The detector reads a copy of your file in a temporary folder, deleted as soon as the check ends. The signed result
  goes back to the page and is not kept. If you close the window in the middle of a check, the copy stays in your
  temporary folder until you open `detector.cmd` again more than six hours later, which deletes it.

The page needs Lanternist installed in that folder, because the detector runs with Lanternist's environments and
the model files of the marks. Lanternist does not offer an online detector: your file would have to leave your PC.

### From a terminal

```
.venv\Scripts\python scripts\detecta_marca.py <file>
```

| Option | What it does |
|---|---|
| `--cpu` | runs without a GPU. A 1-minute video takes about 20 seconds on a CPU |
| `--report <out.json>` | also writes a **signed** result (see below) |

The exit code is `0` when it finds a Lanternist mark in at least one layer, `1` when it finds none, and `2` when it
could not look (for example, a file it cannot open, or a file with nothing to look at).

### The signed result, and how to read the result

**The signed result** is a JSON file with two parts:

- `report`: the file name and its SHA-256, the detector (`lanternist-ai-mark-detector`, its version and the SHA-256
  of the models it used), the time in UTC, every finding, whether the Lanternist mark was found, and the conclusion
  as printed;
- `signature`: an ES256 signature (`value`, the raw r‖s pair in base64) over `report` written as canonical JSON —
  keys sorted, separators `,` and `:`, UTF-8 — plus the certificate chain in PEM that verifies it.

Anyone can check it with the public key in the first certificate of the chain. Like the C2PA manifest, it is signed
with your installation's local certificate, so it proves that the result has not been edited since, not who ran the
detector.

**How to read the result:**

- **The picture watermark** is read as 256 bits and compared with the Lanternist message. Lanternist says "marked"
  when at least 167 bits match. An unmarked file matches about half of them, and the chance of reaching 167 by
  accident is below one in a million. The example episode, marked, matched 244 bits or more, even after heavy
  compression. The lowest figure so far is 185, on a small synthetic clip (see [What survives](#what-survives)).
- **The signpost** is read in the same frames as the picture watermark, each one with TrustMark's own decoder.
  Lanternist says "found" when at least one frame gives exactly one of Lanternist's numbers (today, 59) with the
  signpost's encoding, `BCH_SUPER`. Any other number with that encoding is reported as "another TrustMark mark, or a
  false reading". TrustMark's other encodings correct fewer errors and come out by chance in unmarked frames, so they
  are ignored. The marked example episode gave 59 in 108 of its 109 frames, also after a YouTube-like re-encode, and
  the unmarked one in none.
- **The sound watermark** comes with a probability and a 16-bit message. Lanternist says "marked" when the probability
  is 0.5 or more **and** all 16 bits match the Lanternist message. Marked audio in our tests scored 0.997 to 1.000
  with 16 of 16 bits, and the unmarked soundtrack 0.006 or less. A high probability with a different message is reported as
  "another AudioSeal mark, or a false alarm": a pure test tone with no mark at all made the detector answer 0.62.
- **The C2PA manifest** is reported as valid, invalid or missing, with the signer's trust status and the number of
  watermarks it declares.
- **"No marks found" does not prove that a file was not made with AI.** It only says that it carries no Lanternist
  marks.

## For other detectors

This section is for whoever builds or runs a detector that is not Lanternist's. It says exactly what each mark is and
how to read it with the tools of the people who made it. Lanternist's own code for all of this is in
`lib/marca_ia.py` (the constants and the verdict) and `lib/marca_ia_worker.py` (marking and reading).

**Start with the signpost.** C2PA metadata does not survive a platform upload, so in a file found online the
watermarks are usually all that is left. The signpost is there to tell you which detector to run for the rest.

### The signpost (TrustMark)

| | |
|---|---|
| Library | [`trustmark`](https://pypi.org/project/trustmark/) 0.9.2, by Adobe. MIT, code and model files |
| Model | variant **Q**: `trustmark_Q.yaml`, `encoder_Q.ckpt` and `decoder_Q.ckpt`, from Adobe's CDN (`https://cai-watermark.adobe.net/watermarking/trustmark-models/`). Their SHA-256 are in `datos/descargas.json` |
| Encoding | **`BCH_SUPER`**: 40 data bits, 56 error-correction bits (up to 8 wrong bits are corrected) and 4 version bits, 100 bits in all |
| Payload | the number **59** as an unsigned 40-bit binary number, most significant bit first: `format(59, "040b")`, passed with `MODE="binary"` |
| What 59 means | Lanternist's entry in the [C2PA soft-binding algorithm list](https://github.com/c2pa-org/softbinding-algorithm-list). This is TrustMark's *signpost* mode ([adobe/trustmark, `c2pa/README.md`](https://github.com/adobe/trustmark/blob/main/c2pa/README.md)) |
| Where | the whole image, in every frame of the video and in the thumbnail, at strength 1.0. It goes in before Video Seal. (TrustMark marks the whole image up to a 2:1 aspect ratio, and no Lanternist format is wider) |
| Found when | TrustMark decodes the frame, the schema is `BCH_SUPER` and the number is 59. Lanternist counts a file as carrying the signpost when at least one frame qualifies |

Reading it with the official package, and nothing from Lanternist:

```python
# pip install trustmark==0.9.2
# On Windows, set PYTHONUTF8=1 first: the package ships only its source, and it does not build otherwise.
from PIL import Image
from trustmark import TrustMark

# The first time, the constructor downloads the model files from Adobe. loadRemover=False skips the removal model.
tm = TrustMark(verbose=False, model_type="Q", encoding_type=TrustMark.Encoding.BCH_SUPER, loadRemover=False)
bits, found, schema = tm.decode(Image.open("frame.png").convert("RGB"), MODE="binary")
if found and schema == TrustMark.Encoding.BCH_SUPER and int(bits, 2) == 59:
    print("Lanternist signpost: check this file with Lanternist's detector")
```

For a video, extract a few frames first (for example `ffmpeg -i video.mp4 -vf fps=0.5 frame-%03d.png`) and read each
one. The same calls read 59 in frames of the example episode re-encoded like YouTube and in its thumbnail saved as
JPEG, and read nothing in the same frames without the signpost (26 October 2026).

**59 is provisional.** C2PA assigns the number when it accepts an entry, and Lanternist is asking for entry 59. If C2PA
assigns another number, new files will carry that one, and Lanternist's detector will keep reading 59 in the files
marked before (Measure 2.1.4).

### The picture watermark (Video Seal)

- **Model**: Video Seal 1.0, the TorchScript file
  [`y_256b_img.jit`](https://dl.fbaipublicfiles.com/videoseal/y_256b_img.jit) from
  [facebookresearch/videoseal](https://github.com/facebookresearch/videoseal).
- **Message**: 256 bits, the SHA-256 of the ASCII text `Lanternist: AI-generated content`, most significant bit first.
- **Reading**: `model.detect(x)[:, 1:]` gives one value per bit; a bit is 1 when its value is above 0. In a video,
  Lanternist averages the values over up to 240 frames taken at 2 per second and scaled to 256 × 256 pixels, with
  `is_video=True`. It says "marked" when at least 167 of the 256 bits match the message.

### The sound watermark (AudioSeal)

- **Model**: AudioSeal 0.2.0, the 16-bit `generator_base.pth` and `detector_base.pth` of
  [facebook/audioseal](https://huggingface.co/facebook/audioseal), revision `3c19eba`.
- **Message**: 16 bits, the first 16 bits of the same SHA-256.
- **Reading**: the sound in mono at 16 kHz, in windows of up to 60 seconds. The probability is the share of moments
  that the detector scores above 0.5. Lanternist says "marked" when that share is at least 0.5 and all 16 bits of the
  message match.

### The C2PA manifest

The claim generator is `Lanternist` with its version. The actions are `c2pa.created`, with the digital source type
`http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia`, and one `c2pa.watermarked.unbound` for each
watermark in the file, whose `description` names the technique. Any C2PA tool shows them, for example `c2patool`.

## What survives

Measured on the example episode (54.5 s, 1080p at 24 fps) on 15 October 2026.

| What was done to the file | Picture watermark (bits out of 256) | Sound watermark | C2PA manifest |
|---|---|---|---|
| Nothing | 256 | 1.000 | valid, untrusted signer |
| Re-encoded like YouTube: H.264 at 2.5 Mbit/s, AAC at 128 kbit/s | 256 | 1.000 | lost |
| Scaled to 720p at 1.2 Mbit/s; Opus at 128 kbit/s | 256 | 1.000 | lost |
| Scaled to 480p with heavy compression; Opus at 64 kbit/s; MP3 at 64 kbit/s | 256 | 1.000 | lost |
| Cropped by 20 %; a 15-second excerpt of the audio | 256 | 0.997 | lost |
| A screenshot of one frame, as PNG; as JPEG scaled to 720p | 256; 253 | — | lost |
| The thumbnail as JPEG at 1280, 480 and 320 px wide; at quality 50; as WebP | 256, 255, 244, 256, 255 | — | lost |
| One byte of the file changed | — | — | invalid |
| **An unmarked file (negative control)**: the video, a screenshot, the thumbnail | 116 to 123, 114, 116 | 0.006 or less | missing |

A synthetic 10-minute test clip (ffmpeg's `testsrc2` pattern at 320×180, with a tone and pink noise), marked by the
same code, read back 185 bits out of 256 for the picture and 16 of 16 for the sound. The picture is still above the
167 threshold, but it is the lowest figure measured so far. The small frame or the synthetic pattern may explain it;
they have not been tested apart.

**The signpost**, measured on 26 October 2026 on the example episode's `final.mp4` as Lanternist's pipeline marks it
(the signpost first, Video Seal on top). It was read with TrustMark's decoder on one full-size frame every 2 seconds
(27 frames). Lanternist's detector reads 109 smaller ones.

| What was done to the file | Signpost (frames that give 59) | Picture watermark (bits out of 256) |
|---|---|---|
| Nothing (H.264, as Lanternist encodes it) | 27 of 27 | 256 |
| Re-encoded like YouTube: 1080p at 2.5 Mbit/s; 720p at 1.2 Mbit/s | 27 of 27; 27 of 27 | 256; 256 |
| Cropped by 20 % | 27 of 27 | 256 |
| Scaled to 480p with heavy compression | 6 of 27 | 256 |
| The thumbnail as JPEG, at full size and at 1280 px wide | found in both | 256 |
| **Unmarked files (negative control)**: the video, a thumbnail, and the files marked before the signpost existed | 0 | — |

- **Lanternist's detector** found the signpost in 108 of 109 frames of the marked episode, before and after the
  YouTube-like re-encode, and in none of the unmarked one.
- **The order matters for the picture watermark.** On a flat synthetic picture (`testsrc2`, at 640×360 and at
  1080p), Video Seal with the signpost underneath read 223 to 237 bits; with the signpost on top, 123 to 131, which is
  chance. That is why the signpost goes in first.
- **The signpost is the weaker mark.** It is read in fewer frames than Video Seal after heavy compression, and it says
  nothing by itself about AI: it only says which detector to use.

**Not measured yet**: a real round trip through YouTube (upload, then download), filming the screen with a camera,
playing the audio through a speaker and recording it, mirroring and rotation, and deliberate attacks.

## Limits you should know

- **C2PA does not survive platforms.** Any re-encoding drops it, and so does a plain container copy
  (`ffmpeg -c copy`). Once the file is on YouTube, only the watermark is left.
- **The watermark can be attacked.** The models are public, so someone with time and skill can try to remove the
  mark with the detector at hand. Robustness against deliberate attacks is limited.
- **Measured on one format so far.** The figures above come from the "láminas" format: engraved illustrations with
  camera moves, narration and music. Flat images and silence may behave differently.

## YouTube may show its own AI label

When a video carries a C2PA manifest saying that the whole video was made with AI, YouTube can show its "AI-generated"
label, and since 27 May 2026 that label can be permanent
([YouTube Help](https://support.google.com/youtube/answer/15447836?hl=en),
[YouTube blog](https://blog.youtube/news-and-events/improving-ai-labels-viewers-creators/)). YouTube only does this
for manifests it considers secure, so a manifest signed with a local certificate will probably not trigger it.

It does not change much in practice, because the video is already declared as synthetic media: an API upload tells
YouTube so (`containsSyntheticMedia`), and by hand `LEEME.html` tells you to answer yes to Studio's question about
altered or synthetic content. YouTube labels the video for that reason. **Expect your videos to carry YouTube's AI
label.**

## Please do not remove the marks

Lanternist is MIT-licensed, and the licence does not stop you from changing the code. The EU Code of Practice asks the
providers of open-source AI systems to tell their users this (Measure 1.2): **do not remove or tamper with the AI
marks** in what Lanternist produces, and do not publish Lanternist's outputs without them. The only exceptions are
legitimate ones, such as security audits and research. Lanternist does not include, and will not promote, any tool
whose purpose is to remove the marks.

One honest note about the signpost: the `trustmark` package that the installer adds from PyPI also contains a function
that removes TrustMark watermarks (`remove_watermark`). It needs a separate model file. Lanternist never downloads that
file, never loads it and never calls the function, and it does not document how to use it.

If you publish AI-generated content in the EU, you may also have duties of your own as a *deployer* under
Article 50(4), for example to disclose deep fakes. They are separate from the marks described here.

## Comparison with Section 1 of the Code of Practice

The Code is voluntary, and Lanternist has not signed it. A provider that does not sign shows compliance by other
means, for example with a point-by-point comparison like this one (Commission guidelines on Article 50, §147-148).
Source: [the Code, final text of 10 June 2026](https://ec.europa.eu/newsroom/dae/redirection/document/129555).

In the Code, "will" marks a measure needed to comply, and "encouraged" or "may" marks an optional one.

| Measure | Kind | What Lanternist does | Status |
|---|---|---|---|
| 1.1 Two layers of machine-readable marking | will | C2PA plus watermarks on the picture (Video Seal and the TrustMark signpost), the sound and the thumbnail | Met |
| 1.1.1 Signed, time-stamped metadata saying the content is AI-generated | will | C2PA with `trainedAlgorithmicMedia`, signed with ES256. The time is the local clock inside the signed claim; there is no trusted timestamp. The key stays on the user's PC under the local-deployment exception | Met, without a trusted timestamp |
| 1.1.2 Imperceptible watermark, hard to separate from the content | will | Video Seal and AudioSeal | Met |
| 1.1.3 Fingerprinting or logging | may | Not implemented | Optional |
| 1.2 (a) Keep existing metadata of the inputs | will | Not done: the render writes a new file and does not carry the manifests of its inputs. Almost every input is generated inside the same run | Gap |
| 1.2 (b) Ask users not to remove the marks | will | [Please do not remove the marks](#please-do-not-remove-the-marks) | Met |
| 1.2 No tools to circumvent the marks | will | None is shipped or promoted. The `trustmark` package, installed from PyPI for the signpost, contains a removal function; Lanternist never downloads its model, never calls it and does not document it ([Please do not remove the marks](#please-do-not-remove-the-marks)) | Met |
| 1.3 Richer provenance: system name, provider, time, model | encouraged | System name, version and time. No provider name and no model identifiers | Partly |
| 1.4 An option to add a visible label | encouraged | Not in the video. The upload declares AI to YouTube, which shows its label | Optional |
| 2.1 A detector for each marking technique | will | `scripts/detecta_marca.py` reads the C2PA manifest, the picture watermark, the signpost and the sound watermark | Met |
| 2.1.1 Free of charge; portable, with low hardware needs | will / encouraged | Free and open source. Runs on a CPU. Tested on Windows only | Met on Windows |
| 2.1.2 An interface suited to the public who may see the content | will | A local page with no terminal: double-click `detector.cmd`, drag in a file, and read one line per layer and the verdict ([On a page in your browser](#on-a-page-in-your-browser-without-a-terminal)). It needs Lanternist installed; there is no online detector, because the file would have to leave the PC | Met |
| 2.1.2 A downloadable, signed detection result | will | `--report`, and the page's download button | Met |
| 2.1.3 Privacy of the content submitted | will | Detection runs on the user's PC and uploads nothing. The page talks only to `127.0.0.1` and deletes its copy of the file after each check | Met |
| 2.1.4 A replacement detector must still read old marks | will | The message, the signpost number and the models are fixed. A future version must keep reading the marks made by this one, including signpost 59 if C2PA assigns Lanternist another number. Files marked before the signpost existed still read as marked | Committed |
| 2.2 Forensic detection of content whose marks were stripped | may | Not implemented | Optional |
| 2.3 Clear results that say which layer they rest on | will | One line for each layer and a plain-language conclusion, as text that screen readers can read | Met |
| 2.4 Literacy material | encouraged | This page | Partly |
| 3.1 Effectiveness: people understand the result | will | A plain-language conclusion; no user study | Partly |
| 3.2 Reliability: error rates, also on unmarked content | will | The false-alarm threshold is below one in a million, and the negative controls read "not marked". The signpost counts only the exact number with its own encoding, and no unmarked file gave it. Measured on one episode and one format | Partly |
| 3.3 Robustness to common changes and to attacks | will | Measured: re-encoding, scaling, cropping, screenshots, audio codecs and excerpts; for the signpost, re-encoding, scaling, cropping and the thumbnail as JPEG. Not measured: a YouTube round trip, camcording, playback and recording, mirroring, rotation, attacks | Partly |
| 3.4 (a) Metadata through an established standard | will | C2PA | Met |
| 3.4 (b) Public information on how to detect the watermarks | will | This page, with the exact specification of every mark in [For other detectors](#for-other-detectors), and the detector's source code | Met |
| 3.4 (c) A watermark interoperability solution by 2 February 2027 | will | A publicly readable signpost (the Code's second option): a TrustMark watermark in every picture with the number 59, Lanternist's entry in the C2PA soft-binding algorithm list, which tells any detector which one to use. TrustMark's own open-source decoder reads it after a YouTube-like re-encode, and reads nothing in unmarked files. The C2PA manifest also declares each watermark (`c2pa.watermarked.unbound`). Lanternist is asking C2PA for entry 59; the number is provisional until they accept it | Met |
| 3.5 Advancing the state of the art | encouraged | — | Optional |
| 4.1 A documented compliance process | will | This page, kept with the code | Met |
| 4.2 Testing before release and regularly after | will | The test suite marks a clip and reads it back, with a negative control, whenever the marking environment and its model files are installed (otherwise those tests are skipped); the figures above come from the example episode. The YouTube round trip has not been done | Partly |
| 4.3 Training of the people involved | will | Proportionate to the project's size: the maintainers work from this page | Met |
| 4.4 Cooperation with market surveillance authorities | will | On a reasoned request, the maintainers provide this documentation and access to the detector. Both are already public | Committed |
