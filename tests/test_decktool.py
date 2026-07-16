import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import decktool


class DeckInputTests(unittest.TestCase):
    def test_text_sections_and_quantities(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deck.txt"
            path.write_text("Commander\n1 Atraxa, Praetors' Voice\nMainboard\n2x Forest\n")
            name, commanders, main = decktool.parse_text_decklist(path)
        self.assertEqual(name, "deck")
        self.assertEqual(commanders, ["Atraxa, Praetors' Voice"])
        self.assertEqual(main, {"Forest": 2})

    @patch.object(decktool, "http_json")
    def test_any_excluded_archidekt_category_excludes_card(self, http_json):
        http_json.return_value = {
            "name": "Test",
            "categories": [{"name": "Main", "includedInDeck": True},
                           {"name": "Maybeboard", "includedInDeck": False}],
            "cards": [{"quantity": 1, "categories": ["Main", "Maybeboard"],
                       "card": {"oracleCard": {"name": "Maybe Card"}}}],
        }
        _, _, main = decktool.fetch_archidekt("123")
        self.assertEqual(main, {})


class ThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = json.loads(Path("docs/themes.json").read_text())

    def test_oracle_tag_can_identify_commander_theme_without_regex_match(self):
        cards = [{"name": "Tagged Commander", "text": "Vigilance",
                  "types": ["Creature"], "subtypes": ["Human"]}]
        ranked, _ = decktool.detect_themes(
            cards, self.taxonomy, ["Tagged Commander"], {"Landfall / lands matter"})
        landfall = next(row for row in ranked if row[0] == "Landfall / lands matter")
        self.assertEqual(landfall, ("Landfall / lands matter", [], True))

    def test_tag_index_adds_card_as_theme_evidence(self):
        cards = [{"name": "Semantic Match", "text": "Vigilance",
                  "types": ["Creature"], "subtypes": ["Human"]}]
        tag_index = {"semantic match": ["Landfall / lands matter"]}
        ranked, _ = decktool.detect_themes(
            cards, self.taxonomy, tag_index=tag_index,
            tagged_themes={"Landfall / lands matter"})
        self.assertEqual(ranked[0][1], ["Semantic Match"])

    def test_generic_theme_still_needs_minimum_support(self):
        cards = [{"name": "One Treasure Card", "text": "Create a Treasure token.",
                  "types": ["Artifact"], "subtypes": []}]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertNotIn("Treasure / artifact tokens", {row[0] for row in ranked})

    def test_configured_theme_cap_is_enforced(self):
        cards = [{"name": f"Card {i}",
                  "text": "Create a Treasure token. You gain 2 life. Landfall. "
                          "Each opponent mills two cards. Equip {1}.",
                  "types": ["Artifact", "Creature"], "subtypes": ["Goblin"]}
                 for i in range(8)]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertEqual(len(ranked), self.taxonomy["max_themes"])


class RecommendationTests(unittest.TestCase):
    @patch.object(decktool, "scryfall_search")
    def test_tag_results_are_filtered_and_can_avoid_extra_searches(self, search):
        search.return_value = [
            {"name": "Already Owned"}, {"name": "Theme Finisher"},
            {"name": "Theme Engine"},
        ]
        cards = decktool.suggestion_cards(
            ["otag:blink", "o:fallback"], "WU", 10,
            {"already owned"}, limit=2)
        self.assertEqual([c["name"] for c in cards],
                         ["Theme Finisher", "Theme Engine"])
        self.assertEqual(search.call_count, 1)
        query = search.call_args.args[0]
        self.assertIn("otag:blink", query)
        self.assertIn("id<=WU", query)
        self.assertIn("usd<=10", query)

    @patch.object(decktool, "scryfall_search",
                  side_effect=TimeoutError("slow upstream"))
    def test_optional_suggestions_fail_soft_on_timeout(self, search):
        self.assertEqual(
            decktool.suggestion_cards(["otag:blink", "o:fallback"],
                                      "WU", 10, set()), [])
        self.assertEqual(search.call_count, 1)


if __name__ == "__main__":
    unittest.main()
