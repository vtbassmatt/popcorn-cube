from unittest.mock import patch
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import SubmissionForm
from .models import Cube, Submission
from .stats import compute_cube_stats
from .tasks import _send_cubecomplete_emails, _send_newround_emails

User = get_user_model()


class CubeModelTests(TestCase):
    def test_effective_max_cards_rounds_up_to_participant_count(self):
        owner = User.objects.create_user(username="owner", password="pass")
        other = User.objects.create_user(username="other", password="pass")
        cube = Cube.objects.create(name="Test Cube", owner=owner, max_cards=10)
        cube.participants.add(other)

        self.assertEqual(cube.participant_count, 2)
        self.assertEqual(cube.effective_max_cards, 10)

        cube.max_cards = 11
        cube.save()
        self.assertEqual(cube.effective_max_cards, 12)

    def test_format_legality_scryfall_url_returns_none_when_no_format(self):
        owner = User.objects.create_user(username="owner2", password="pass")
        cube = Cube.objects.create(name="Test Cube", owner=owner)
        self.assertIsNone(cube.format_legality_scryfall_url)

    def test_format_legality_scryfall_url_for_commander_uses_edh(self):
        owner = User.objects.create_user(username="owner3", password="pass")
        cube = Cube.objects.create(name="Test Cube", owner=owner, format_legality="commander")
        url = cube.format_legality_scryfall_url
        self.assertIn("scryfall.com/search", url)
        self.assertIn("f%3Aedh", url)
        self.assertIn("in%3Apaper", url)

    def test_format_legality_scryfall_url_for_modern(self):
        owner = User.objects.create_user(username="owner4", password="pass")
        cube = Cube.objects.create(name="Test Cube", owner=owner, format_legality="modern")
        url = cube.format_legality_scryfall_url
        self.assertIn("scryfall.com/search", url)
        self.assertIn("f%3Amodern", url)
        self.assertIn("in%3Apaper", url)


class SubmissionRuleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.cube = Cube.objects.create(name="Draft Cube", owner=self.owner, max_cards=3)
        self.cube.participants.add(self.other)

    def test_one_submission_per_user_per_round(self):
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Lightning Bolt",
        )
        duplicate = Submission(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Counterspell",
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_cube_stops_at_effective_max_cards(self):
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="A")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="B")
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=2, card_name="C")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=2, card_name="D")

        self.assertEqual(self.cube.effective_max_cards, 4)
        blocked = Submission(cube=self.cube, player=self.owner, round_number=3, card_name="E")

        with self.assertRaises(ValidationError):
            blocked.full_clean()

    def test_max_count_per_card_limit(self):
        self.cube.max_count_per_card = 1
        self.cube.save()
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="Shock")
        second = Submission(cube=self.cube, player=self.other, round_number=1, card_name="Shock")

        with self.assertRaises(ValidationError):
            second.full_clean()

    def test_edit_submission_from_prior_round_is_allowed(self):
        earlier_submission = Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="A")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="B")
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=2, card_name="C")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=2, card_name="D")
        self.assertEqual(self.cube.current_round, 3)

        earlier_submission.card_name = "E"
        earlier_submission.full_clean()

    def test_edit_submission_in_closed_cube_is_allowed_when_round_unchanged(self):
        latest_submission = Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="A")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="B")
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=2, card_name="C")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=2, card_name="D")
        self.assertFalse(self.cube.is_open)

        latest_submission.card_name = "E"
        latest_submission.full_clean()

    @patch("cubes.forms.fetch_card_by_name")
    def test_submission_form_enforces_format_legality(self, mock_fetch):
        self.cube.format_legality = "modern"
        self.cube.save()
        mock_fetch.return_value = {
            "id": "abc",
            "name": "Cool Card",
            "legalities": {"modern": "not_legal"},
        }

        form = SubmissionForm(
            data={"card_name": "Cool Card", "related_to": "Seems neat"},
            cube=self.cube,
            player=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("not legal", form.errors["card_name"][0])


class SubmissionFormDisplayTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.cube = Cube.objects.create(name="Form Cube", owner=self.owner, max_cards=6)

    def test_related_to_is_optional_text_input(self):
        form = SubmissionForm(cube=self.cube, player=self.owner)

        self.assertFalse(form.fields["related_to"].required)
        self.assertEqual(form.fields["related_to"].label, "Reason (optional)")
        self.assertEqual(form.fields["related_to"].widget.__class__.__name__, "TextInput")

    def test_card_name_input_has_autocomplete_attributes(self):
        form = SubmissionForm(cube=self.cube, player=self.owner)

        self.assertEqual(form.fields["card_name"].widget.attrs["list"], "card-name-suggestions")
        self.assertEqual(form.fields["card_name"].widget.attrs["data-card-autocomplete"], "1")


class CubeDetailViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.cube = Cube.objects.create(name="View Cube", owner=self.owner, max_cards=6)
        self.cube.participants.add(self.other)

    def test_detail_page_shows_format_legality_link(self):
        self.cube.format_legality = "commander"
        self.cube.save()
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, 'href="https://scryfall.com/search?q=f%3Aedh+in%3Apaper"')
        self.assertContains(response, "Commander")

    def test_detail_page_shows_any_when_no_format_legality(self):
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, "Any")
        self.assertNotContains(response, "scryfall.com/search?q=f%3A")

    def test_previous_round_cards_include_scryfall_links(self):
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Lightning Bolt",
            scryfall_id="1234-abcd",
        )
        Submission.objects.create(
            cube=self.cube,
            player=self.other,
            round_number=1,
            card_name="Counterspell",
            scryfall_id="5678-efgh",
            related_to="Pairs with Lightning Bolt",
        )
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, 'href="https://scryfall.com/card/5678-efgh"')
        self.assertContains(response, 'target="_blank"')
        self.assertContains(response, "Pairs with Lightning Bolt")
        previous_round_names = [submission.card_name for submission in response.context["previous_round_cards"]]
        self.assertEqual(previous_round_names, ["Lightning Bolt", "Counterspell"])
        self.assertContains(response, "Previous round cards")
        self.assertContains(response, "Lightning Bolt")

    def test_detail_page_shows_inline_submission_form(self):
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Submit card for round 1')
        self.assertContains(response, 'name="card_name"')
        self.assertContains(response, 'name="related_to"')
        self.assertContains(response, 'id="card-name-suggestions"')
        self.assertContains(response, 'id="card-name-autocomplete-spinner"')
        self.assertContains(response, "spinner-border-sm")
        self.assertContains(response, "text-primary")
        self.assertContains(response, "api.scryfall.com/cards/autocomplete")
        self.assertIn("form", response.context)
        self.assertFalse(response.context["form"].is_bound)

    def test_detail_page_autocomplete_includes_format_legality(self):
        self.cube.format_legality = "modern"
        self.cube.save()
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, 'formatLegality = "modern"')

    def test_open_cube_hides_prior_submissions_by_default(self):
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="Opt")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="Bolt")
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, "Show my prior submissions")
        self.assertNotContains(response, "My prior submissions")
        self.assertNotContains(response, "Hide prior submissions")
        self.assertFalse(response.context["show_prior_submissions"])
        self.assertEqual(list(response.context["prior_submissions"]), [])

    def test_open_cube_can_show_prior_submissions_when_requested(self):
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Opt",
            related_to="Keeps options open",
        )
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="Bolt")
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=2, card_name="Doom Blade")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=2, card_name="Counterspell")
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}) + "?show_prior_submissions=1")

        self.assertContains(response, "My prior submissions")
        self.assertContains(response, "Hide prior submissions")
        self.assertContains(response, "Opt")
        self.assertContains(response, "Doom Blade")
        self.assertContains(response, "Keeps options open")
        prior_submission_names = [submission.card_name for submission in response.context["prior_submissions"]]
        self.assertEqual(prior_submission_names, ["Opt", "Doom Blade"])

    @patch("cubes.forms.fetch_card_by_name")
    def test_detail_page_post_submits_card(self, mock_fetch):
        mock_fetch.return_value = {
            "id": "abc123",
            "name": "Opt",
            "legalities": {"modern": "legal"},
            "mana_cost": "{U}",
            "type_line": "Instant",
            "colors": ["U"],
            "cmc": 1,
        }
        self.client.login(username="owner", password="pass")

        response = self.client.post(
            reverse("cube-detail", kwargs={"pk": self.cube.pk}),
            {"card_name": "opt", "related_to": ""},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        submission = Submission.objects.get(cube=self.cube, player=self.owner, card_name="Opt")
        self.assertEqual(submission.card_snapshot["name"], "Opt")
        self.assertContains(response, "Card submitted.")

    def test_cube_stats_are_available_after_first_round(self):
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Savannah Lions",
            card_snapshot={
                "name": "Savannah Lions",
                "type_line": "Creature — Cat",
                "colors": ["W"],
                "mana_cost": "{W}",
                "cmc": 1,
                "power": "2",
                "toughness": "1",
            },
        )
        Submission.objects.create(
            cube=self.cube,
            player=self.other,
            round_number=1,
            card_name="Fire // Ice",
            card_snapshot={
                "name": "Fire // Ice",
                "type_line": "Instant // Sorcery — Fuse",
                "colors": ["U", "R"],
                "mana_cost": "{1}{U}{R}",
                "cmc": 2,
                "card_faces": [
                    {"name": "Fire", "type_line": "Instant", "colors": ["R"], "mana_cost": "{1}{R}", "cmc": 2},
                    {"name": "Ice", "type_line": "Instant", "colors": ["U"], "mana_cost": "{1}{U}", "cmc": 2},
                ],
            },
        )
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertTrue(response.context["has_stats"])
        self.assertEqual(response.context["cube_stats"]["card_count"], 2)
        self.assertEqual(response.context["cube_stats"]["face_count"], 3)
        self.assertContains(response, "Cube stats")
        self.assertContains(response, "cdn.jsdelivr.net/npm/chart.js")
        self.assertContains(response, "cards-inclusive-chart")
        self.assertContains(response, "faces-pip-chart")
        self.assertContains(response, "<summary>Subtypes</summary>")
        self.assertContains(response, "beginAtZero: true")

    def test_cube_stats_ignore_incomplete_current_round(self):
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Savannah Lions",
            card_snapshot={
                "name": "Savannah Lions",
                "type_line": "Creature — Cat",
                "colors": ["W"],
                "mana_cost": "{W}",
                "cmc": 1,
            },
        )
        Submission.objects.create(
            cube=self.cube,
            player=self.other,
            round_number=1,
            card_name="Lightning Bolt",
            card_snapshot={
                "name": "Lightning Bolt",
                "type_line": "Instant",
                "colors": ["R"],
                "mana_cost": "{R}",
                "cmc": 1,
            },
        )
        Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=2,
            card_name="Raffine's Informant",
            card_snapshot={
                "name": "Raffine's Informant",
                "type_line": "Creature — Human Wizard",
                "colors": ["W"],
                "mana_cost": "{1}{W}",
                "cmc": 2,
            },
        )
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertTrue(response.context["has_stats"])
        self.assertEqual(response.context["cube_stats"]["card_count"], 2)
        self.assertEqual(response.context["cube_stats"]["cards"]["type_counts"], {"Creature": 1, "Instant": 1})
        self.assertEqual(response.context["cube_stats"]["cards"]["subtype_counts"], {"Cat": 1})
        self.assertNotIn("Wizard", response.context["cube_stats"]["cards"]["subtype_counts"])

    def test_detail_page_shows_who_you_are_waiting_on_after_submitting(self):
        third = User.objects.create_user(username="third", password="pass")
        self.cube.participants.add(third)
        Submission.objects.create(cube=self.cube, player=self.owner, round_number=1, card_name="Opt")
        Submission.objects.create(cube=self.cube, player=self.other, round_number=1, card_name="Bolt")
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-detail", kwargs={"pk": self.cube.pk}))

        self.assertContains(response, "You already submitted")
        self.assertContains(response, "Waiting on: third.")
        waiting_on_usernames = [participant.username for participant in response.context["waiting_on_participants"]]
        self.assertEqual(waiting_on_usernames, ["third"])

    def test_full_cube_defaults_to_tabular_results_view(self):
        closed_cube = Cube.objects.create(name="Closed Cube", owner=self.owner, max_cards=3)
        closed_cube.participants.add(self.other)
        Submission.objects.create(cube=closed_cube, player=self.owner, round_number=1, card_name="Opt")
        Submission.objects.create(
            cube=closed_cube,
            player=self.other,
            round_number=1,
            card_name="Bolt",
            related_to="Fast interaction",
        )
        Submission.objects.create(cube=closed_cube, player=self.owner, round_number=2, card_name="Doom Blade")
        Submission.objects.create(cube=closed_cube, player=self.other, round_number=2, card_name="Counterspell")

        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("cube-detail", kwargs={"pk": closed_cube.pk}))

        self.assertContains(response, "Cube is complete")
        self.assertContains(response, "Round 1")
        self.assertContains(response, "Round 2")
        self.assertContains(response, "owner")
        self.assertContains(response, "other")
        self.assertContains(response, "Fast interaction")
        self.assertContains(response, "?view=alphabetical")
        self.assertNotContains(response, 'name="card_name"')

    def test_full_cube_can_be_viewed_alphabetically(self):
        closed_cube = Cube.objects.create(name="Closed Cube", owner=self.owner, max_cards=3)
        closed_cube.participants.add(self.other)
        Submission.objects.create(
            cube=closed_cube,
            player=self.owner,
            round_number=1,
            card_name="Opt",
            related_to="Keeps options open",
        )
        Submission.objects.create(cube=closed_cube, player=self.other, round_number=1, card_name="Bolt")
        Submission.objects.create(cube=closed_cube, player=self.owner, round_number=2, card_name="Doom Blade")
        Submission.objects.create(cube=closed_cube, player=self.other, round_number=2, card_name="Counterspell")

        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("cube-detail", kwargs={"pk": closed_cube.pk}) + "?view=alphabetical")

        self.assertEqual(response.context["display_mode"], "alphabetical")
        alphabetical_names = [submission.card_name for submission in response.context["alphabetical_submissions"]]
        self.assertEqual(alphabetical_names, ["Bolt", "Counterspell", "Doom Blade", "Opt"])
        self.assertContains(response, "Keeps options open")
        self.assertContains(response, "?view=table")


class HowItWorksPageTests(TestCase):
    def test_how_it_works_page_shows_core_rules(self):
        response = self.client.get(reverse("how-this-works"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Submit one card each round.")
        self.assertContains(response, "Starting in round 2, try to riff on cards from the previous round.")
        self.assertContains(response, "Round 1 has no previous round")
        self.assertContains(response, "shown wherever that card is shown")
        self.assertContains(response, "Format legality")
        self.assertContains(response, "Max copies per card")
        self.assertContains(response, "singleton")
        self.assertContains(response, "unlimited copies")

    def test_login_page_links_to_how_it_works(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("how-this-works"))


class CubeStatsTests(TestCase):
    def test_compute_cube_stats_supports_card_and_face_counts(self):
        owner = User.objects.create_user(username="stats-owner", password="pass")
        other = User.objects.create_user(username="stats-other", password="pass")
        cube = Cube.objects.create(name="Stats Cube", owner=owner, max_cards=4)
        cube.participants.add(other)
        Submission.objects.create(
            cube=cube,
            player=owner,
            round_number=1,
            card_name="Arcbound Tracker",
            card_snapshot={
                "name": "Arcbound Tracker",
                "type_line": "Artifact Creature — Human Warrior",
                "colors": [],
                "mana_cost": "{2}{W/U}{W/P}{S}{C}",
                "cmc": 4,
                "power": "2",
                "toughness": "2",
            },
        )
        Submission.objects.create(
            cube=cube,
            player=other,
            round_number=1,
            card_name="Fire // Ice",
            card_snapshot={
                "name": "Fire // Ice",
                "type_line": "Instant // Sorcery — Fuse",
                "colors": ["U", "R"],
                "mana_cost": "{1}{U}{R}",
                "cmc": 2,
                "card_faces": [
                    {"name": "Fire", "type_line": "Instant", "colors": ["R"], "mana_cost": "{1}{R}", "cmc": 2},
                    {"name": "Ice", "type_line": "Instant", "colors": ["U"], "mana_cost": "{1}{U}", "cmc": 2},
                ],
            },
        )

        stats = compute_cube_stats(cube.submissions.order_by("pk"))

        self.assertEqual(stats["card_count"], 2)
        self.assertEqual(stats["face_count"], 3)
        self.assertEqual(stats["cards"]["type_counts"]["Artifact"], 1)
        self.assertEqual(stats["cards"]["type_counts"]["Creature"], 1)
        self.assertEqual(stats["cards"]["type_counts"]["Instant"], 1)
        self.assertEqual(stats["cards"]["type_counts"]["Sorcery"], 1)
        self.assertEqual(stats["cards"]["subtype_counts"]["Human"], 1)
        self.assertEqual(stats["cards"]["subtype_counts"]["Warrior"], 1)
        self.assertEqual(stats["cards"]["subtype_counts"]["Fuse"], 1)
        self.assertNotIn("//", stats["cards"]["subtype_counts"])
        self.assertNotIn("—", stats["cards"]["subtype_counts"])
        self.assertEqual(stats["cards"]["color_breakdown"]["strict"]["Colorless"], 1)
        self.assertEqual(stats["cards"]["color_breakdown"]["strict"]["UR"], 1)
        self.assertNotIn("W", stats["cards"]["color_breakdown"]["inclusive"])
        self.assertEqual(stats["cards"]["color_breakdown"]["inclusive"]["U"], 1)
        self.assertEqual(stats["cards"]["mana_pips"]["C"], 1)
        self.assertEqual(stats["cards"]["mana_pips"]["S"], 1)
        self.assertEqual(stats["cards"]["mana_pips"]["W/U"], 1)
        self.assertEqual(stats["cards"]["mana_pips"]["W"], 1)
        self.assertEqual(stats["cards"]["mana_value"]["overall"]["count_by_value"][2], 1)
        self.assertEqual(stats["cards"]["mana_value"]["overall"]["count_by_value"][4], 1)
        self.assertEqual(stats["faces"]["color_breakdown"]["strict"]["R"], 1)
        self.assertEqual(stats["faces"]["color_breakdown"]["strict"]["U"], 1)

    def test_compute_cube_stats_orders_color_outputs_for_display(self):
        owner = User.objects.create_user(username="order-owner", password="pass")
        cube = Cube.objects.create(name="Order Cube", owner=owner, max_cards=20)
        cube.participants.add(owner)

        snapshots = [
            {"colors": ["W"], "mana_cost": "{W}", "cmc": 1},
            {"colors": ["U"], "mana_cost": "{U}", "cmc": 1},
            {"colors": ["B"], "mana_cost": "{B}", "cmc": 1},
            {"colors": ["R"], "mana_cost": "{R}", "cmc": 1},
            {"colors": ["G"], "mana_cost": "{G}", "cmc": 1},
            {"colors": ["W", "U"], "mana_cost": "{W/U}", "cmc": 2},
            {"colors": ["U", "B"], "mana_cost": "{U/B}", "cmc": 2},
            {"colors": ["B", "R"], "mana_cost": "{B/R}", "cmc": 2},
            {"colors": ["R", "G"], "mana_cost": "{R/G}", "cmc": 2},
            {"colors": ["G", "W"], "mana_cost": "{G/W}", "cmc": 2},
            {"colors": ["W", "B"], "mana_cost": "{W/B}", "cmc": 2},
            {"colors": ["U", "R"], "mana_cost": "{U/R}", "cmc": 2},
            {"colors": ["B", "G"], "mana_cost": "{B/G}", "cmc": 2},
            {"colors": ["R", "W"], "mana_cost": "{R/W}", "cmc": 2},
            {"colors": ["G", "U"], "mana_cost": "{G/U}", "cmc": 2},
            {"colors": ["B", "W", "U"], "mana_cost": "{W}{U}{B}", "cmc": 3},
            {"colors": [], "mana_cost": "{C}{S}", "cmc": 2},
        ]

        for round_number, snapshot in enumerate(snapshots, start=1):
            Submission.objects.create(
                cube=cube,
                player=owner,
                round_number=round_number,
                card_name=f"Card {round_number}",
                card_snapshot={
                    "name": f"Card {round_number}",
                    "type_line": "Instant",
                    **snapshot,
                },
            )

        stats = compute_cube_stats(cube.submissions.order_by("pk"))

        self.assertEqual(
            list(stats["cards"]["color_breakdown"]["strict"].keys()),
            ["W", "U", "B", "R", "G", "WU", "UB", "BR", "RG", "GW", "WB", "UR", "BG", "RW", "GU", "WUB", "Colorless"],
        )
        self.assertEqual(list(stats["cards"]["color_breakdown"]["inclusive"].keys()), ["W", "U", "B", "R", "G", "Colorless"])
        self.assertEqual(
            list(stats["cards"]["mana_pips"].keys()),
            ["W", "U", "B", "R", "G", "W/U", "U/B", "B/R", "R/G", "G/W", "W/B", "U/R", "B/G", "R/W", "G/U", "C", "S"],
        )

    def test_compute_cube_stats_deduplicates_split_card_type_and_subtype_tokens(self):
        owner = User.objects.create_user(username="dedupe-owner", password="pass")
        cube = Cube.objects.create(name="Dedupe Cube", owner=owner, max_cards=2)
        cube.participants.add(owner)
        Submission.objects.create(
            cube=cube,
            player=owner,
            round_number=1,
            card_name="Echo // Echo",
            card_snapshot={
                "name": "Echo // Echo",
                "type_line": "Instant — Arcane // Instant — Arcane",
                "colors": ["U"],
                "mana_cost": "{U}",
                "cmc": 1,
            },
        )

        stats = compute_cube_stats(cube.submissions.order_by("pk"))

        self.assertEqual(stats["cards"]["type_counts"]["Instant"], 1)
        self.assertEqual(stats["cards"]["subtype_counts"]["Arcane"], 1)


class BackfillSubmissionCardSnapshotsCommandTests(TestCase):
    @patch("cubes.management.commands.backfill_submission_card_snapshots.fetch_card_by_name")
    @patch("cubes.management.commands.backfill_submission_card_snapshots.fetch_card_by_id")
    def test_backfill_submission_card_snapshots_updates_missing_snapshots(self, mock_fetch_by_id, mock_fetch_by_name):
        owner = User.objects.create_user(username="cmd-owner", password="pass")
        other = User.objects.create_user(username="cmd-other", password="pass")
        cube = Cube.objects.create(name="Command Cube", owner=owner, max_cards=4)
        cube.participants.add(other)
        with_id = Submission.objects.create(
            cube=cube,
            player=owner,
            round_number=1,
            card_name="Opt",
            scryfall_id="opt-id",
        )
        with_name = Submission.objects.create(
            cube=cube,
            player=other,
            round_number=1,
            card_name="Bolt",
        )

        mock_fetch_by_id.return_value = {"id": "opt-id", "name": "Opt", "type_line": "Instant", "mana_cost": "{U}", "cmc": 1}
        mock_fetch_by_name.return_value = {
            "id": "bolt-id",
            "name": "Bolt",
            "type_line": "Instant",
            "mana_cost": "{R}",
            "colors": ["R"],
            "cmc": 1,
        }
        stdout = StringIO()

        call_command("backfill_submission_card_snapshots", stdout=stdout)

        with_id.refresh_from_db()
        with_name.refresh_from_db()
        self.assertEqual(with_id.card_snapshot["name"], "Opt")
        self.assertEqual(with_name.card_snapshot["name"], "Bolt")
        self.assertIn("Updated: 2. Skipped: 0.", stdout.getvalue())
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_FROM="test@example.com")
class RoundCloseEmailTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass", email="owner@example.com")
        self.other = User.objects.create_user(username="other", password="pass", email="other@example.com")
        self.cube = Cube.objects.create(name="Test Cube", owner=self.owner, max_cards=4)
        self.cube.participants.add(self.owner, self.other)

    def _make_submissions(self, owner_reason="", other_reason=""):
        sub1 = Submission.objects.create(
            cube=self.cube,
            player=self.owner,
            round_number=1,
            card_name="Lightning Bolt",
            related_to=owner_reason,
        )
        sub2 = Submission.objects.create(
            cube=self.cube,
            player=self.other,
            round_number=1,
            card_name="Counterspell",
            related_to=other_reason,
        )
        return sub1, sub2

    def test_newround_email_includes_reasons(self):
        sub1, sub2 = self._make_submissions(
            owner_reason="", other_reason="Pairs with Lightning Bolt"
        )
        _send_newround_emails(sub2, "http://example.com")

        self.assertEqual(len(mail.outbox), 1)
        text_body = mail.outbox[0].body
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn("Pairs with Lightning Bolt", text_body)
        self.assertIn("Pairs with Lightning Bolt", html_body)

    def test_newround_email_omits_empty_reasons(self):
        sub1, sub2 = self._make_submissions(owner_reason="", other_reason="")
        _send_newround_emails(sub2, "http://example.com")

        self.assertEqual(len(mail.outbox), 1)
        text_body = mail.outbox[0].body
        # No stray parentheses for empty reasons
        self.assertNotIn("()", text_body)

    def test_cubecomplete_email_includes_reasons(self):
        sub1, sub2 = self._make_submissions(
            owner_reason="Goes wide", other_reason="Answers threats"
        )
        _send_cubecomplete_emails(sub2, "http://example.com")

        self.assertEqual(len(mail.outbox), 1)
        text_body = mail.outbox[0].body
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn("Goes wide", text_body)
        self.assertIn("Answers threats", text_body)
        self.assertIn("Goes wide", html_body)
        self.assertIn("Answers threats", html_body)

    def test_cubecomplete_email_lists_cards(self):
        sub1, sub2 = self._make_submissions(owner_reason="", other_reason="")
        _send_cubecomplete_emails(sub2, "http://example.com")

        self.assertEqual(len(mail.outbox), 1)
        text_body = mail.outbox[0].body
        html_body = mail.outbox[0].alternatives[0][0]
        self.assertIn("Lightning Bolt", text_body)
        self.assertIn("Counterspell", text_body)
        self.assertIn("Lightning Bolt", html_body)
        self.assertIn("Counterspell", html_body)



class CubeExportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.closed_cube = Cube.objects.create(name="My Export Cube", owner=self.owner, max_cards=4)
        self.closed_cube.participants.add(self.other)
        Submission.objects.create(cube=self.closed_cube, player=self.owner, round_number=1, card_name="Lightning Bolt")
        Submission.objects.create(cube=self.closed_cube, player=self.other, round_number=1, card_name="Counterspell")
        Submission.objects.create(cube=self.closed_cube, player=self.owner, round_number=2, card_name="Lightning Bolt")
        Submission.objects.create(cube=self.closed_cube, player=self.other, round_number=2, card_name="Opt")

    def test_export_requires_login(self):
        response = self.client.get(reverse("cube-export", kwargs={"pk": self.closed_cube.pk}))
        self.assertRedirects(response, f"/accounts/login/?next=/cubes/{self.closed_cube.pk}/export/")

    def test_export_returns_csv_for_complete_cube(self):
        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("cube-export", kwargs={"pk": self.closed_cube.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn('attachment; filename="My Export Cube.csv"', response["Content-Disposition"])

    def test_export_csv_contains_correct_quantities(self):
        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("cube-export", kwargs={"pk": self.closed_cube.pk}))

        content = response.content.decode("utf-8")
        lines = content.strip().splitlines()
        self.assertEqual(lines[0], "quantity,card name")
        # Rows are sorted alphabetically by card name
        self.assertIn("1,Counterspell", lines)
        self.assertIn("2,Lightning Bolt", lines)
        self.assertIn("1,Opt", lines)

    def test_export_redirects_for_open_cube(self):
        open_cube = Cube.objects.create(name="Open Cube", owner=self.owner, max_cards=10)
        Submission.objects.create(cube=open_cube, player=self.owner, round_number=1, card_name="Bolt")
        self.client.login(username="owner", password="pass")

        response = self.client.get(reverse("cube-export", kwargs={"pk": open_cube.pk}), follow=True)

        self.assertRedirects(response, reverse("cube-detail", kwargs={"pk": open_cube.pk}))
        self.assertContains(response, "only available when the cube is complete")

    def test_export_not_accessible_to_non_participant(self):
        outsider = User.objects.create_user(username="outsider", password="pass")
        self.client.login(username="outsider", password="pass")

        response = self.client.get(reverse("cube-export", kwargs={"pk": self.closed_cube.pk}))

        self.assertEqual(response.status_code, 404)
