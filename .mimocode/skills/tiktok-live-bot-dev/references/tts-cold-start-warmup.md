# TTS Cold-Start Warmup

## Symptom

The first viewer TTS of a stream takes several seconds, even though startup logs say the TTS warmup started.

## Root cause pattern

A warmup can execute yet fail to prime Edge TTS. In the observed failure, the probe text was punctuation-only (`"."`). `edge_tts.Communicate(...).save(...)` returned:

```text
No audio was received. Please verify that your parameters are correct.
```

The launcher only logged that the background warmup thread started, while the TTS debug log showed every warmup generation failed. Therefore the first real viewer request still paid import/network/TLS/audio initialization costs.

## Correct implementation

1. Start warmup once per launcher process, before Flask/UI startup work where practical.
2. Use short **speakable alphanumeric text**, such as `"Ready"`; never whitespace or punctuation-only text.
3. Generate and save a real MP3 with the currently configured voice, rate, and pitch.
4. Initialize the playback mixer if needed.
5. Do **not** play the warmup clip, write TTS history, or mutate cooldown state.
6. Delete the generated clip afterward.
7. Log completion separately from scheduling:
   - scheduled/started means only that the thread launched;
   - success means a non-empty audio file was actually generated;
   - failure must include the provider exception.

## Investigation and verification

- Inspect both launcher and TTS debug logs. A launcher line like `TTS warmup started` is not proof of success.
- Reproduce the exact provider call outside Flask using the live voice/rate/pitch and check that the output file is non-empty.
- Add a regression test asserting the warmup probe contains at least one alphanumeric character.
- Run a real generation timing probe for the warmup text followed by representative viewer text.
- Compile and run the relevant test suite, then rebuild/deploy through the normal TikTokMCIntegrator deployment protocol.

## Pitfalls

- Importing `edge_tts` alone does not warm its network path.
- Initializing only `pygame.mixer` does not warm speech generation.
- A daemon thread can silently fail while startup continues normally.
- Do not use the dashboard test endpoint for startup warmup if it changes cooldown/history or plays audible output.
