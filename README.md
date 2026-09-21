# webvtt-segment-witness

An offline, dependency-free witness for a narrow HLS subtitle failure boundary:
segmented WebVTT files can be individually parseable while their playlist timing
maps disagree across discontinuity sequences.

## Problem statement

HLS requires WebVTT segments to cover the cues intended for each segment period,
and defines `X-TIMESTAMP-MAP` as the bridge between WebVTT cue time and the
media timeline. A player can therefore report a runtime timing failure even
when every `.vtt` file parses on its own. This tool checks the artifact that is
usually reviewed together but often produced separately: one subtitle media
playlist plus its local WebVTT segments.

The first version deliberately does **not** render captions, fetch media, or
emulate a player. It reports deterministic, inspectable diagnostics for:

- playlist segment durations and target-duration violations;
- missing segment files and malformed WebVTT cue timing;
- missing WebVTT headers or malformed timestamp maps;
- timestamp-map changes inside one HLS discontinuity sequence; and
- cues that do not overlap the media-time window inferred for their segment.

Warnings and errors are kept distinct. A missing `X-TIMESTAMP-MAP` is a warning
because HLS defines a zero-to-zero fallback; a map change without an HLS
discontinuity is an error because it silently changes the timeline contract.

## Usage

```text
python -m webvtt_segment_witness path/to/subtitles.m3u8
python -m webvtt_segment_witness path/to/subtitles.m3u8 --json
```

The playlist and segment URIs are resolved below the playlist directory. A
non-zero exit status means at least one error diagnostic was emitted.

## Validation method

The fixtures model two short VOD subtitle renditions. The clean rendition keeps
one timestamp-map offset per discontinuity sequence. The invalid rendition
changes that offset without an `#EXT-X-DISCONTINUITY` tag; the witness must
reject it and identify the segment and diagnostic code. Tests also cover
malformed timestamps, missing files, JSON determinism, and the allowed
warning-only no-map case.

## Evidence boundary

This is a packaging and timing-consistency witness, not a claim that captions
are linguistically correct, visually readable, or synchronized to the primary
audio/video stream. It cannot prove a real player will render the track, and it
does not replace a full HLS validator or a browser/player integration test.

## Roadmap

1. Add explicit checks for live playlist reload snapshots and media-sequence
   continuity, while preserving the offline/no-network boundary.
2. Add a machine-readable explanation of inferred presentation-time origin when
   a caller supplies a primary-rendition timestamp anchor.
3. Stop if those additions require player emulation or duplicate a maintained
   full-stream validator.

## Sources

- HLS 2nd Edition draft, WebVTT segments: <https://datatracker.ietf.org/doc/draft-pantos-hls-rfc8216bis/19/#section-3.1.4>
- Shaka Player issue documenting a discontinuity-sequence timestamp-map
  misalignment: <https://github.com/shaka-project/shaka-player/issues/9470>
- `videojs/vtt.js`, an individual WebVTT parser: <https://github.com/videojs/vtt.js>
- `osk/node-webvtt`, a parser/segmenter: <https://github.com/osk/node-webvtt>
- Apple HLS tools, including the platform media stream validator:
  <https://developer.apple.com/documentation/http-live-streaming/using-apple-s-http-live-streaming-hls-tools>
