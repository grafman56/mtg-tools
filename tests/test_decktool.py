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

    def test_taxonomy_sets_eight_theme_suggestions(self):
        self.assertEqual(self.taxonomy["max_theme_suggestions"], 8)

    def test_oracle_tag_can_identify_commander_theme_without_regex_match(self):
        cards = [{"name": "Tagged Commander", "text": "Vigilance",
                  "types": ["Creature"], "subtypes": ["Human"]}]
        ranked, _ = decktool.detect_themes(
            cards, self.taxonomy, ["Tagged Commander"], {"Landfall / lands matter"})
        landfall = next(row for row in ranked if row[0] == "Landfall / lands matter")
        self.assertEqual(landfall, ("Landfall / lands matter", ["Tagged Commander"], False))

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

    def test_named_and_general_death_triggers_support_aristocrats(self):
        cards = [
            {"name": "Death Payoff", "text": "Whenever one or more other creatures die, draw a card.",
             "types": ["Creature"], "subtypes": []},
            {"name": "Named Dragon", "text": "When Named Dragon dies, each opponent loses 5 life.",
             "types": ["Creature"], "subtypes": ["Dragon"]},
            {"name": "Commander Outlet", "text": "Sacrifice another creature: This becomes a copy of it.",
             "types": ["Creature"], "subtypes": []},
        ]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy, ["Commander Outlet"])
        aristocrats = next(row for row in ranked if row[0] == "Sacrifice / aristocrats")
        self.assertTrue(aristocrats[2])
        self.assertEqual(set(aristocrats[1]), {c["name"] for c in cards})

    def test_weak_self_sacrifice_alone_does_not_invent_theme(self):
        cards = [{"name": f"Temporary {i}",
                  "text": "Sacrifice it at the beginning of the next end step.",
                  "types": ["Creature"], "subtypes": []} for i in range(8)]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertNotIn("Sacrifice / aristocrats", {row[0] for row in ranked})

    def test_configured_theme_cap_is_enforced(self):
        cards = [{"name": f"Card {i}",
                  "text": "Create a Treasure token. You gain 2 life. Landfall. "
                          "Each opponent mills two cards. Equip {1}.",
                  "types": ["Artifact", "Creature"], "subtypes": ["Goblin"]}
                 for i in range(8)]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertEqual(len(ranked), self.taxonomy["max_themes"])

    def test_strong_evidence_outranks_more_weak_matches(self):
        cards = [
            {"name": f"Sacrifice Payoff {i}",
             "text": "Sacrifice another creature: Draw a card.",
             "types": ["Creature"], "subtypes": []}
            for i in range(3)
        ] + [
            {"name": f"Treasure Card {i}", "text": "Create a Treasure token.",
             "types": ["Artifact"], "subtypes": []}
            for i in range(5)
        ]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertEqual(ranked[0][0], "Sacrifice / aristocrats")

    def test_generic_etb_cards_do_not_establish_blink_theme(self):
        cards = [
            {"name": f"Value Creature {i}",
             "text": "When this creature enters the battlefield, draw a card.",
             "types": ["Creature"], "subtypes": []}
            for i in range(6)
        ]
        ranked, _ = decktool.detect_themes(cards, self.taxonomy)
        self.assertNotIn("Blink / ETB value", {row[0] for row in ranked})

    def test_land_sacrifice_support_matches_lands_matter_theme(self):
        baloth_prime = {
            "name": "Baloth Prime", "types": ["Creature"], "subtypes": ["Beast"],
            "text": "Whenever you sacrifice a land, create a tapped 4/4 green Beast creature token and untap this creature. {4}, Sacrifice a land: You gain 2 life.",
        }
        nonland_sacrifice = {
            "name": "Viscera Seer", "types": ["Creature"], "subtypes": ["Vampire"],
            "text": "Sacrifice a creature: Scry 1.",
        }
        self.assertEqual(decktool.theme_evidence_for_card(
            baloth_prime, "Landfall / lands matter", self.taxonomy), "strong")
        self.assertIsNone(decktool.theme_evidence_for_card(
            nonland_sacrifice, "Landfall / lands matter", self.taxonomy))

    def test_semantic_tag_does_not_label_unrelated_commander_as_blink_theme(self):
        necrobloom = {
            "name": "The Necrobloom", "types": ["Legendary", "Creature"],
            "subtypes": ["Plant"],
            "text": "Landfall — Whenever a land you control enters, create a 0/1 green Plant creature token. Land cards in your graveyard have dredge 2.",
        }
        etb_card = {
            "name": "ETB Value", "types": ["Creature"], "subtypes": [],
            "text": "When this creature enters, draw a card.",
        }
        ranked, _ = decktool.detect_themes(
            [necrobloom, etb_card], self.taxonomy,
            ["The Necrobloom"], {"Blink / ETB value"})
        self.assertNotIn("Blink / ETB value", {row[0] for row in ranked})


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.taxonomy = json.loads(Path("docs/themes.json").read_text())

    def test_cut_policy_has_conservative_thresholds(self):
        policy = self.taxonomy["cut_candidates"]
        self.assertEqual(policy["max_results"], 5)
        self.assertGreater(policy["weak_theme_minimum_replacement_delta"],
                           policy["minimum_replacement_delta"])

    def test_default_max_price_is_100(self):
        self.assertEqual(decktool.DEFAULT_MAX_PRICE, 100.0)

    def test_repeatable_treasure_and_draw_engine_is_protected_from_cut_review(self):
        black_market_connections = {
            "name": "Black Market Connections", "types": ["Enchantment"], "subtypes": [],
            "text": "At the beginning of your first main phase, choose one or more — Create a Treasure token. You lose 1 life. Draw a card. You lose 2 life. Create a 3/2 colorless Shapeshifter creature token with changeling. You lose 3 life.",
        }
        cuts = decktool.cut_candidates(
            [black_market_connections], [], {"Landfall / lands matter"}, None, [],
            self.taxonomy,
            role_counts={"Lands": 37, "Ramp": 12, "Card draw": 12,
                         "Interaction": 10, "Board wipes": 3}, scale=1,
        )
        self.assertEqual(decktool.card_roles(black_market_connections), ["Ramp", "Card draw"])
        self.assertEqual(cuts, [])

    def test_token_linked_draw_is_protected_when_deck_creates_tokens(self):
        necrobloom = {
            "name": "The Necrobloom", "types": ["Legendary", "Creature"],
            "subtypes": ["Plant"],
            "text": "Landfall — Whenever a land you control enters, create a 0/1 green Plant creature token.",
        }
        tocasias_welcome = {
            "name": "Tocasia's Welcome", "types": ["Enchantment"], "subtypes": [],
            "text": "Whenever one or more creatures with mana value 3 or less enter, draw a card. This ability triggers only once each turn.",
        }
        cuts = decktool.cut_candidates(
            [necrobloom, tocasias_welcome], [],
            {"Landfall / lands matter"}, None, ["The Necrobloom"], self.taxonomy,
            role_counts={"Lands": 37, "Ramp": 10, "Card draw": 12,
                         "Interaction": 10, "Board wipes": 3}, scale=1,
        )
        self.assertEqual(cuts, [])

    def test_efficient_land_ramp_is_not_cut_from_lands_matter_deck(self):
        farseek = {
            "name": "Farseek", "types": ["Sorcery"], "subtypes": [], "mana_value": 2,
            "text": "Search your library for a Plains, Island, Swamp, or Mountain card, put it onto the battlefield tapped, then shuffle.",
        }
        cuts = decktool.cut_candidates(
            [farseek], [], {"Landfall / lands matter"}, None, [], self.taxonomy,
            role_counts={"Lands": 37, "Ramp": 12, "Card draw": 10,
                         "Interaction": 10, "Board wipes": 3}, scale=1,
        )
        self.assertEqual(decktool.card_roles(farseek), ["Ramp"])
        self.assertEqual(cuts, [])

    def test_blink_oracle_wording_marks_brago_and_etb_cards_as_theme_support(self):
        brago = {"name": "Brago, King Eternal", "types": ["Legendary", "Creature"],
                 "subtypes": ["Spirit"], "text": "Whenever Brago deals combat damage to a player, exile any number of target nonland permanents you control, then return those cards to the battlefield under their owner's control."}
        channeler = {"name": "Aether Channeler", "types": ["Creature"], "subtypes": [],
                     "text": "When this creature enters, choose one — Draw a card."}
        cloud = {"name": "Cloud of Faeries", "types": ["Creature"], "subtypes": [],
                 "text": "When this creature enters, untap up to two lands."}
        self.assertEqual(decktool.theme_evidence_for_card(
            brago, "Blink / ETB value", self.taxonomy), "strong")
        self.assertEqual(decktool.theme_evidence_for_card(
            channeler, "Blink / ETB value", self.taxonomy), "weak")
        self.assertEqual(decktool.theme_evidence_for_card(
            cloud, "Blink / ETB value", self.taxonomy), "weak")

    def test_blink_commander_protects_etb_and_artifact_ramp_from_cuts(self):
        cards = [
            {"name": "Brago, King Eternal", "types": ["Legendary", "Creature"],
             "subtypes": ["Spirit"], "text": "Whenever Brago deals combat damage to a player, exile any number of target nonland permanents you control, then return those cards to the battlefield under their owner's control."},
            {"name": "Aether Channeler", "types": ["Creature"], "subtypes": [],
             "text": "When this creature enters, choose one — Draw a card."},
            {"name": "Arcane Signet", "types": ["Artifact"], "subtypes": [],
             "text": "{T}: Add one mana of any color in your commander's color identity."},
            {"name": "Basalt Monolith", "types": ["Artifact"], "subtypes": [],
             "text": "This artifact doesn't untap during your untap step. {T}: Add {C}{C}{C}. {3}: Untap this artifact."},
            {"name": "Cloud of Faeries", "types": ["Creature"], "subtypes": [],
             "text": "When this creature enters, untap up to two lands."},
            {"name": "Off Theme", "types": ["Creature"], "subtypes": [], "text": "Flying"},
        ]
        suggestions = [
            {"name": "Psychosis Crawler", "_theme_matches": 2,
             "oracle_text": "Whenever you draw a card, each opponent loses 1 life."},
            {"name": "Blink Payoff", "_theme_matches": 2,
             "oracle_text": "Whenever a creature enters, each opponent loses 1 life."},
        ]
        cuts = decktool.cut_candidates(
            cards, suggestions, {"Blink / ETB value"}, None,
            ["Brago, King Eternal"], self.taxonomy,
            role_counts={"Lands": 37, "Ramp": 12, "Card draw": 12,
                         "Interaction": 10, "Board wipes": 3}, scale=1,
        )
        self.assertEqual([cut["name"] for cut in cuts], ["Off Theme"])
        self.assertNotIn("replacement", cuts[0])

    def test_cut_candidates_keep_strong_theme_and_protected_roles(self):
        cards = [
            {"name": "Commander", "text": "Sacrifice another creature: Draw a card.",
             "types": ["Creature"], "subtypes": []},
            {"name": "Strong Payoff", "text": "Whenever another creature dies, draw a card.",
             "types": ["Creature"], "subtypes": []},
            {"name": "Weak Sacrifice", "text": "Sacrifice this creature: Draw a card.",
             "types": ["Creature"], "subtypes": []},
            {"name": "Off Theme", "text": "Flying", "types": ["Creature"], "subtypes": []},
            {"name": "Needed Ramp", "text": "{T}: Add {G}.",
             "types": ["Artifact"], "subtypes": []},
        ]
        suggestion = {"name": "Table Replacement", "oracle_text":
                      "Whenever another creature dies, each opponent loses 1 life.",
                      "_theme_matches": 2}
        cuts = decktool.cut_candidates(
            cards, [suggestion], {"Sacrifice / aristocrats"}, None,
            ["Commander"], self.taxonomy,
            role_counts={"Lands": 37, "Ramp": 0, "Card draw": 10,
                         "Interaction": 10, "Board wipes": 3}, scale=1,
        )
        self.assertEqual([cut["name"] for cut in cuts], ["Off Theme"])

    def test_cut_candidates_require_theme_confidence(self):
        cards = [{"name": "Off Theme", "text": "Flying",
                  "types": ["Creature"], "subtypes": []}]
        suggestion = {"name": "Table Replacement", "oracle_text":
                      "Each opponent loses 1 life.", "_theme_matches": 2}
        self.assertEqual(
            decktool.cut_candidates(cards, [suggestion], set(), None, [], self.taxonomy), [])

    def test_print_cut_candidates_shows_review_reasons_without_universal_replacement(self):
        cut = {
            "name": "Off Theme", "reasons": ["no active-theme evidence", "no multiplayer impact"],
        }
        with patch("builtins.print") as printed:
            decktool.print_cut_candidates([cut], self.taxonomy)
        output = "\n".join(" ".join(map(str, call.args)) for call in printed.call_args_list)
        self.assertIn("Potential cuts to review", output)
        self.assertIn("Off Theme", output)
        self.assertNotIn("Possible upgrade", output)
        self.assertIn("review aid", output)

    def test_print_themes_includes_cut_review_from_returned_suggestions(self):
        cards = [{"name": "Off Theme", "text": "Flying",
                  "types": ["Creature"], "subtypes": []}]
        suggestion = {"name": "Table Replacement", "oracle_text":
                      "Whenever another creature dies, each opponent loses 1 life."}
        with patch("decktool.detect_themes", return_value=(
                [("Sacrifice / aristocrats", ["Theme Card"], False)], None)), \
             patch("decktool.commander_identity", return_value="B"), \
             patch("decktool.suggestion_cards", return_value=[suggestion]), \
             patch("builtins.print") as printed:
            decktool.print_themes("Test Deck", [], {"Off Theme": 1}, cards, 20)
        output = "\n".join(" ".join(map(str, call.args)) for call in printed.call_args_list)
        self.assertIn("Potential cuts to review", output)
        self.assertIn("Off Theme", output)

    def test_each_opponent_effect_outranks_target_opponent(self):
        target = {"name": "Target Drain", "oracle_text": "Target opponent loses 1 life."}
        table = {"name": "Table Drain", "oracle_text": "Each opponent loses 1 life."}
        ranked = decktool.rank_suggestions(
            [(target, 1, 0), (table, 1, 1)],
            json.loads(Path("docs/themes.json").read_text()),
        )
        self.assertEqual([card["name"] for card in ranked], ["Table Drain", "Target Drain"])

    def test_repeatable_table_wide_effect_outranks_one_shot_effect(self):
        one_shot = {"name": "One Shot", "oracle_text": "Each opponent loses 1 life."}
        repeatable = {"name": "Repeatable", "oracle_text": "Whenever a creature dies, each opponent loses 1 life."}
        ranked = decktool.rank_suggestions(
            [(one_shot, 1, 0), (repeatable, 1, 1)],
            json.loads(Path("docs/themes.json").read_text()),
        )
        self.assertEqual([card["name"] for card in ranked], ["Repeatable", "One Shot"])

    def test_each_player_effect_scores_below_each_opponent(self):
        taxonomy = json.loads(Path("docs/themes.json").read_text())
        each_player = decktool.impact_for_card(
            {"name": "Symmetrical", "oracle_text": "Each player loses 1 life."}, taxonomy)
        each_opponent = decktool.impact_for_card(
            {"name": "Table", "oracle_text": "Each opponent loses 1 life."}, taxonomy)
        self.assertLess(each_player["score"], each_opponent["score"])

    @patch.object(decktool, "scryfall_search")
    def test_suggestions_prioritize_cards_matching_multiple_theme_queries(self, search):
        search.side_effect = [
            [{"name": "First Query Only"}, {"name": "Both Queries"}],
            [{"name": "Both Queries"}, {"name": "Second Query Only"}],
        ]
        cards = decktool.suggestion_cards(
            ["o:first", "o:second"], "WU", 10, set(), limit=2)
        self.assertEqual([c["name"] for c in cards],
                         ["Both Queries", "First Query Only"])
        self.assertEqual(search.call_count, 2)

    @patch.object(decktool, "scryfall_search")
    def test_suggestions_use_impact_to_break_equal_theme_matches(self, search):
        search.return_value = [
            {"name": "Target Drain", "oracle_text": "Target opponent loses 1 life."},
            {"name": "Table Drain", "oracle_text": "Each opponent loses 1 life."},
        ]
        cards = decktool.suggestion_cards(["o:drain"], "B", 10, set(), limit=2)
        self.assertEqual([card["name"] for card in cards], ["Table Drain", "Target Drain"])

    @patch.object(decktool, "scryfall_search")
    def test_tag_results_are_filtered_before_multi_query_ranking(self, search):
        search.return_value = [
            {"name": "Already Owned"}, {"name": "Theme Finisher"},
            {"name": "Theme Engine"},
        ]
        cards = decktool.suggestion_cards(
            ["otag:blink", "o:fallback"], "WU", 10,
            {"already owned"}, limit=2)
        self.assertEqual([c["name"] for c in cards],
                         ["Theme Finisher", "Theme Engine"])
        self.assertEqual(search.call_count, 2)
        query = search.call_args_list[0].args[0]
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
