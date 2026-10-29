# Speaking Stephen

> Spoiler warning: This document contains the analysis and complete solution.

## Overview

| Field | Value |
|---|---|
| Status | solved |
| Event or platform | PwnSec CTF 2026 |
| Category | misc |
| Difficulty | Hard |
| Flag format | `PWNSEC{...}` |

The service transcribes uploaded speech with tiny.en Whisper and speaks the result with `espeak-ng -m`. The decisive flaw is treating the transcript as trusted SSML. Combined BPE tokens bypass Whisper's symbol suppression and inject the server-side `flag.wav` through an `<audio>` element.

## Environment and Initial Analysis

There was no downloadable official attachment; the statement is preserved in [challenge/README.md](../challenge/README.md). The shared environment is restored from [requirements.txt](../../../requirements.txt). `/openapi.json` exposed a multipart `/transcribe` route, while the main page identified `tiny.en` and `espeak-ng` as the model and TTS engine.

The published `entrypoint.sh` fragment generated `$ICONDIR/flag.wav` by wrapping `FLAG` in `<say-as interpret-as="characters">`. The example containing `<break time="1s"/>` also proved that the raw transcript reaches `espeak-ng -m` as markup.

## Core Analysis

Speaking `<audio src="flag.wav"/>` directly does not work because Whisper's default `non_speech_tokens` suppresses standalone symbols such as `<`, `>`, `=`, and quotes. The same byte string can instead be assembled from combined BPE tokens. The complete target was:

```text
 The HTML code."><audio src="flag.wav"/>
```

The important tiny.en tokens are `526` (`."`), `6927` (`><`), `24051` (`audio`), `12351` (` src`), `2625` (`="`), `32109` (`flag`), `13` (`.`), `45137` (`wav`), and `26700` (`"/>`). None is in the applicable suppression set.

`analysis/optimize_audio.py` differentiates through tiny.en's log-mel path and minimizes teacher-forced cross entropy for those tokens. Its forward pass includes 16-bit storage quantization so the transcript survives an actual WAV upload. The remote service interprets the resulting transcript as SSML and mixes the sound icon `flag.wav` into its response.

## Solution and Reproduction

[solve.py](../solve.py) embeds the optimized WAV as gzip/base64. It uploads the payload to the URL in [instance.json](../instance.json) and transcribes the returned audio with both `medium.en` and `turbo`. The former preserves repeated-character counts, while the latter more reliably distinguishes eSpeak's `B` and `D` pronunciations and supplies character identity. The remote WAV is also preserved as [output/flag-audio.wav](../output/flag-audio.wav).

A single ASR result disagreed between `...663BB...` and `...663DD...`. Both candidates were synthesized with the server's eSpeak NG 1.51 settings (`en-us`, speed 110) and optimally aligned against the original response. The `DD` candidate reached cosine similarity `0.999999981` (normalized RMSE `0.000193`), while the `BB` candidate reached only `0.185697593`; this identifies the two characters as `DD`. The comparison is retained in [analysis/compare_espeak.py](../analysis/compare_espeak.py).

Activate the competition `.venv` and run from the challenge root.

```bash
python -m pip install -r ../../requirements.txt
python -m pip check
python solve.py
```

## Result

`python solve.py` exited with code 0, produced empty stderr, and wrote only these bytes to stdout:

```text
PWNSEC{2B1BA663DDAEE8A5}
```

The verified flag is `PWNSEC{2B1BA663DDAEE8A5}`.

## Takeaways

Generated text becomes injection input when it crosses into another interpreter without sanitization. Token suppression is not a string-level prohibition; alternate combined BPE tokens may still decode to the forbidden bytes. Audio adversarial examples also need storage quantization and the actual decoding path represented in their objective to reproduce remotely.

## References

- [OpenAI Whisper `transcribe.py`](https://github.com/openai/whisper/blob/main/whisper/transcribe.py): tiny.en transcription options and decoding flow.
- [eSpeak NG SSML and HTML Support](https://github.com/espeak-ng/espeak-ng/blob/master/docs/markup.md): `<audio src>` and `-m` SSML behavior.
