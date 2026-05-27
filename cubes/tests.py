from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .forms import SubmissionForm
from .models import Cube, Submission

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
        self.assertIn("form", response.context)
        self.assertFalse(response.context["form"].is_bound)

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
        mock_fetch.return_value = {"id": "abc123", "name": "Opt", "legalities": {"modern": "legal"}}
        self.client.login(username="owner", password="pass")

        response = self.client.post(
            reverse("cube-detail", kwargs={"pk": self.cube.pk}),
            {"card_name": "opt", "related_to": ""},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Submission.objects.filter(cube=self.cube, player=self.owner, card_name="Opt").exists())
        self.assertContains(response, "Card submitted.")

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
