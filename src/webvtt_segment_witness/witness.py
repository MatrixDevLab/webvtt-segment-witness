"""Deterministic, dependency-free checks for a local HLS WebVTT rendition."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlparse


_TIME = re.compile(r"^(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})$")
_CUE = re.compile(
    r"^(?P<start>(?:\d+:)?\d{2}:\d{2}\.\d{3})\s+-->\s+"
    r"(?P<end>(?:\d+:)?\d{2}:\d{2}\.\d{3})(?:\s+.*)?$"
)
_MAP = re.compile(r"^X-TIMESTAMP-MAP=(?P<body>.+)$")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    segment: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    line: int


@dataclass(frozen=True)
class ParsedVtt:
    header: bool
    timestamp_map: tuple[float, int] | None
    cues: tuple[Cue, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class Segment:
    uri: str
    duration: float
    start: float
    end: float
    discontinuity_sequence: int
    discontinuity_before: bool


def _time(value: str) -> float:
    match = _TIME.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid WebVTT timestamp: {value!r}")
    hours, minutes, seconds, millis = match.groups()
    if int(seconds) > 59 or int(minutes) > 59:
        raise ValueError(f"invalid WebVTT timestamp: {value!r}")
    return (int(hours or 0) * 3600) + (int(minutes) * 60) + int(seconds) + int(millis) / 1000


def _timestamp_map(line: str) -> tuple[float, int] | None:
    match = _MAP.fullmatch(line.strip())
    if not match:
        return None
    fields: dict[str, str] = {}
    for item in match.group("body").split(","):
        key, separator, value = item.partition(":")
        if not separator:
            raise ValueError("timestamp map field lacks ':'")
        fields[key.strip()] = value.strip()
    if "LOCAL" not in fields or "MPEGTS" not in fields:
        raise ValueError("timestamp map needs LOCAL and MPEGTS")
    local = _time(fields["LOCAL"])
    mpegts = int(fields["MPEGTS"])
    if mpegts < 0:
        raise ValueError("MPEGTS cannot be negative")
    return local, mpegts


def parse_vtt(text: str, segment: str) -> ParsedVtt:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    diagnostics: list[Diagnostic] = []
    header = bool(lines) and lines[0].lstrip("\ufeff") == "WEBVTT"
    if not header:
        diagnostics.append(Diagnostic("missing_webvtt_header", "error", "segment does not start with WEBVTT", segment, 1))
        return ParsedVtt(False, None, (), tuple(diagnostics))

    timestamp_map: tuple[float, int] | None = None
    index = 1
    while index < len(lines) and lines[index].strip():
        if lines[index].startswith("X-TIMESTAMP-MAP="):
            try:
                timestamp_map = _timestamp_map(lines[index])
            except (ValueError, TypeError) as exc:
                diagnostics.append(Diagnostic("malformed_timestamp_map", "error", str(exc), segment, index + 1))
        index += 1

    cues: list[Cue] = []
    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        cue_line = index
        match = _CUE.fullmatch(lines[index].strip())
        if match is None:
            # A non-timing line can be a cue identifier. The next line must be timing.
            index += 1
            if index >= len(lines):
                diagnostics.append(Diagnostic("orphan_cue_identifier", "error", "cue identifier has no timing line", segment, cue_line + 1))
                break
            match = _CUE.fullmatch(lines[index].strip())
        if match is None:
            diagnostics.append(Diagnostic("malformed_cue_timing", "error", "expected a WebVTT cue timing line", segment, index + 1))
            while index < len(lines) and lines[index].strip():
                index += 1
            continue
        try:
            start = _time(match.group("start"))
            end = _time(match.group("end"))
        except ValueError as exc:
            diagnostics.append(Diagnostic("malformed_cue_timestamp", "error", str(exc), segment, index + 1))
            start = end = 0.0
        if end <= start:
            diagnostics.append(Diagnostic("non_positive_cue_duration", "error", "cue end must be after cue start", segment, index + 1))
        cues.append(Cue(start, end, index + 1))
        index += 1
        while index < len(lines) and lines[index].strip():
            index += 1
    return ParsedVtt(header, timestamp_map, tuple(cues), tuple(diagnostics))


def parse_playlist(text: str) -> tuple[float | None, tuple[Segment, ...], tuple[Diagnostic, ...], bool]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    diagnostics: list[Diagnostic] = []
    if not lines or lines[0].lstrip("\ufeff") != "#EXTM3U":
        diagnostics.append(Diagnostic("missing_extm3u", "error", "playlist does not start with #EXTM3U"))
    target_duration: float | None = None
    media_sequence = 0
    discontinuity_sequence = 0
    pending_duration: float | None = None
    pending_discontinuity = False
    presentation_time = 0.0
    segments: list[Segment] = []
    ended = False
    for line_number, raw in enumerate(lines[1:], 2):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                target_duration = float(line.split(":", 1)[1])
            except ValueError:
                diagnostics.append(Diagnostic("malformed_target_duration", "error", "target duration is not numeric", line=line_number))
        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                diagnostics.append(Diagnostic("malformed_media_sequence", "error", "media sequence is not an integer", line=line_number))
        elif line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"):
            try:
                discontinuity_sequence = int(line.split(":", 1)[1])
            except ValueError:
                diagnostics.append(Diagnostic("malformed_discontinuity_sequence", "error", "discontinuity sequence is not an integer", line=line_number))
        elif line.startswith("#EXTINF:"):
            try:
                pending_duration = float(line.split(":", 1)[1].split(",", 1)[0])
                if pending_duration < 0:
                    raise ValueError
            except ValueError:
                diagnostics.append(Diagnostic("malformed_extinf", "error", "EXTINF duration is not a non-negative number", line=line_number))
                pending_duration = None
        elif line == "#EXT-X-DISCONTINUITY":
            discontinuity_sequence += 1
            pending_discontinuity = True
        elif line == "#EXT-X-ENDLIST":
            ended = True
        elif line.startswith("#"):
            continue
        elif pending_duration is None:
            diagnostics.append(Diagnostic("uri_without_extinf", "error", "segment URI is not preceded by EXTINF", line=line_number))
        else:
            segments.append(Segment(line, pending_duration, presentation_time, presentation_time + pending_duration, discontinuity_sequence, pending_discontinuity))
            presentation_time += pending_duration
            media_sequence += 1
            pending_duration = None
            pending_discontinuity = False
    if pending_duration is not None:
        diagnostics.append(Diagnostic("extinf_without_uri", "error", "EXTINF is not followed by a segment URI"))
    return target_duration, tuple(segments), tuple(diagnostics), ended


def _local_segment(root: Path, uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme or parsed.netloc:
        raise ValueError("network segment URIs are outside the offline scope")
    candidate = (root / unquote(parsed.path)).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("segment URI escapes the playlist directory")
    return candidate


def validate(playlist: str | Path) -> dict[str, object]:
    playlist_path = Path(playlist).resolve()
    target, segments, diagnostics, ended = parse_playlist(playlist_path.read_text(encoding="utf-8"))
    result_diags = list(diagnostics)
    if not segments:
        result_diags.append(Diagnostic("empty_playlist", "error", "playlist has no media segments"))
    if target is not None:
        for segment in segments:
            if segment.duration > target + 1e-6:
                result_diags.append(Diagnostic("segment_exceeds_target_duration", "error", f"{segment.duration:g}s exceeds {target:g}s target duration", segment.uri))

    segment_rows: list[dict[str, object]] = []
    previous_offsets: dict[int, float] = {}
    group_starts: dict[int, float] = {}
    for item in segments:
        group_starts.setdefault(item.discontinuity_sequence, item.start)
    for segment in segments:
        row: dict[str, object] = {"uri": segment.uri, "start": segment.start, "end": segment.end, "discontinuity_sequence": segment.discontinuity_sequence, "cues": 0}
        try:
            segment_path = _local_segment(playlist_path.parent, segment.uri)
            text = segment_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            result_diags.append(Diagnostic("segment_unreadable", "error", str(exc), segment.uri))
            segment_rows.append(row)
            continue
        parsed = parse_vtt(text, segment.uri)
        result_diags.extend(parsed.diagnostics)
        row["cues"] = len(parsed.cues)
        if parsed.timestamp_map is None:
            result_diags.append(Diagnostic("missing_timestamp_map", "warning", "segment relies on the HLS zero-to-zero timestamp fallback", segment.uri))
        else:
            local, mpegts = parsed.timestamp_map
            offset = (mpegts / 90000.0) - local
            row["timestamp_offset_seconds"] = round(offset, 9)
            prior = previous_offsets.get(segment.discontinuity_sequence)
            offset_changed = prior is not None and abs(prior - offset) > 1e-9
            if offset_changed:
                result_diags.append(Diagnostic("timestamp_map_changed_without_discontinuity", "error", f"offset changed from {prior:g}s to {offset:g}s inside discontinuity sequence {segment.discontinuity_sequence}", segment.uri))
            previous_offsets[segment.discontinuity_sequence] = offset
            # Once the sequence contract is already broken, do not cascade a
            # second window error from the untrusted replacement offset.
            for cue in () if offset_changed else parsed.cues:
                mapped_start = cue.start + offset
                mapped_end = cue.end + offset
                # A new discontinuity sequence starts a fresh subtitle timeline
                # origin; the playlist duration is relative to that sequence.
                group_start = group_starts[segment.discontinuity_sequence]
                window_start = (segment.start - group_start) + offset
                window_end = (segment.end - group_start) + offset
                if mapped_end <= window_start - 1e-9 or mapped_start >= window_end + 1e-9:
                    result_diags.append(Diagnostic("cue_outside_segment_window", "error", f"mapped cue {mapped_start:g}-{mapped_end:g}s does not overlap {window_start:g}-{window_end:g}s", segment.uri, cue.line))
        segment_rows.append(row)

    errors = [item for item in result_diags if item.severity == "error"]
    return {
        "valid": not errors,
        "playlist": str(playlist_path),
        "ended": ended,
        "segments": segment_rows,
        "diagnostics": [asdict(item) for item in result_diags],
    }


def render_json(result: dict[str, object]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
