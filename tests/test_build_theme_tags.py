import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from scripts import build_theme_tags


class ThemeTagBuilderTests(unittest.TestCase):
    def test_cached_tag_is_not_refetched_and_merged_index_is_static(self):
        taxonomy = {
            "themes": {
                "Blink / ETB value": {"oracle_tags": ["blink"]},
            },
            "strength": {
                "oracle_tags": [{"tag": "ramp", "factor": "Ramp role"}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_path = root / "tag-cache.json"
            output_path = root / "theme-tags.json"
            cache_path.write_text(json.dumps({"tags": {"blink": ["Blink Card"]}}))
            calls = []

            def fetch_cards(tag):
                calls.append(tag)
                return ["Ramp Card"]

            complete = build_theme_tags.build_index(
                taxonomy, cache_path, output_path, fetch_cards)

            self.assertTrue(complete)
            self.assertEqual(calls, ["ramp"])
            self.assertEqual(json.loads(cache_path.read_text())["tags"], {
                "blink": ["Blink Card"], "ramp": ["Ramp Card"],
            })
            self.assertEqual(json.loads(output_path.read_text())["cards"], {
                "blink card": ["Blink / ETB value"],
                "ramp card": ["Ramp role"],
            })

    def test_incomplete_refresh_preserves_existing_static_index(self):
        taxonomy = {
            "themes": {},
            "strength": {
                "oracle_tags": [
                    {"tag": "ramp", "factor": "Ramp role"},
                    {"tag": "draw", "factor": "Card draw role"},
                ],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_path = root / "tag-cache.json"
            output_path = root / "theme-tags.json"
            output_path.write_text(json.dumps({"cards": {"old card": ["Old label"]}}))

            complete = build_theme_tags.build_index(
                taxonomy, cache_path, output_path,
                lambda tag: [f"{tag.title()} Card"])

            self.assertFalse(complete)
            self.assertEqual(json.loads(output_path.read_text())["cards"], {
                "old card": ["Old label"],
            })
            self.assertEqual(json.loads(cache_path.read_text())["tags"], {
                "ramp": ["Ramp Card"],
            })

    def test_rate_limit_keeps_seeded_cache_for_a_later_retry(self):
        taxonomy = {
            "themes": {"Blink / ETB value": {"oracle_tags": ["blink"]}},
            "strength": {
                "oracle_tags": [{"tag": "ramp", "factor": "Ramp role"}],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_path = root / "tag-cache.json"
            output_path = root / "theme-tags.json"
            output_path.write_text(json.dumps({
                "cards": {"blink card": ["Blink / ETB value"]},
            }))

            with self.assertRaises(urllib.error.HTTPError):
                build_theme_tags.build_index(
                    taxonomy, cache_path, output_path,
                    lambda _tag: (_ for _ in ()).throw(urllib.error.HTTPError(
                        "https://api.scryfall.com", 429, "Too Many Requests", None, None)),
                )

            self.assertEqual(json.loads(cache_path.read_text())["tags"], {
                "blink": ["blink card"],
            })


if __name__ == "__main__":
    unittest.main()
