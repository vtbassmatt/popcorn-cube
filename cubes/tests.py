from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

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
