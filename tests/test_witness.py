from pathlib import Path
import json
import unittest

from webvtt_segment_witness.witness import parse_vtt, render_json, validate


FIXTURES = Path(__file__).parent / "fixtures"


class WitnessTests(unittest.TestCase):
    def test_clean_rendition_is_valid(self) -> None:
        result = validate(FIXTURES / "clean" / "subtitles.m3u8")
        self.assertTrue(result["valid"], result)
        self.assertEqual([], [d for d in result["diagnostics"] if d["severity"] == "error"])
        self.assertEqual(["seg0.vtt", "seg1.vtt"], [s["uri"] for s in result["segments"]])

    def test_map_change_without_discontinuity_is_rejected(self) -> None:
        result = validate(FIXTURES / "map-change" / "subtitles.m3u8")
        self.assertFalse(result["valid"])
        self.assertIn("timestamp_map_changed_without_discontinuity", {d["code"] for d in result["diagnostics"]})

    def test_missing_map_is_a_warning_only(self) -> None:
        result = validate(FIXTURES / "no-map" / "subtitles.m3u8")
        self.assertTrue(result["valid"], result)
        self.assertIn("missing_timestamp_map", {d["code"] for d in result["diagnostics"]})

    def test_malformed_cue_is_rejected(self) -> None:
        parsed = parse_vtt("WEBVTT\n\n00:00.00 --> 00:01.000\nwrong\n", "bad.vtt")
        self.assertFalse(parsed.header is False)
        self.assertIn("malformed_cue_timing", {d.code for d in parsed.diagnostics})

    def test_json_is_deterministic_and_serializable(self) -> None:
        result = validate(FIXTURES / "clean" / "subtitles.m3u8")
        rendered = render_json(result)
        self.assertEqual(rendered, render_json(json.loads(rendered)))

    def test_missing_segment_is_reported(self) -> None:
        result = validate(FIXTURES / "missing" / "subtitles.m3u8")
        self.assertFalse(result["valid"])
        self.assertIn("segment_unreadable", {d["code"] for d in result["diagnostics"]})


if __name__ == "__main__":
    unittest.main()
