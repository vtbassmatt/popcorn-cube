from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

User = get_user_model()

FORMAT_CHOICES = [
    ("standard", "Standard"),
    ("pioneer", "Pioneer"),
    ("modern", "Modern"),
    ("legacy", "Legacy"),
    ("vintage", "Vintage"),
    ("commander", "Commander"),
    ("pauper", "Pauper"),
]


class Cube(models.Model):
    name = models.CharField(max_length=200)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_cubes")
    participants = models.ManyToManyField(User, related_name="cubes")
    max_cards = models.PositiveIntegerField(default=360)
    format_legality = models.CharField(max_length=32, blank=True, choices=FORMAT_CHOICES)
    max_count_per_card = models.IntegerField(default=1, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @property
    def participant_count(self) -> int:
        return self.participants.count()

    @property
    def effective_max_cards(self) -> int:
        if self.participant_count == 0:
            return self.max_cards
        remainder = self.max_cards % self.participant_count
        if remainder == 0:
            return self.max_cards
        return self.max_cards + (self.participant_count - remainder)

    @property
    def cards_submitted(self) -> int:
        return self.submissions.count()

    @property
    def current_round(self) -> int:
        if self.participant_count == 0:
            return 1
        return (self.cards_submitted // self.participant_count) + 1

    @property
    def is_open(self) -> bool:
        return self.cards_submitted < self.effective_max_cards


@receiver(post_save, sender=Cube)
def ensure_owner_participant(sender, instance: Cube, created: bool, **kwargs) -> None:
    if created:
        instance.participants.add(instance.owner)


class Submission(models.Model):
    cube = models.ForeignKey(Cube, on_delete=models.CASCADE, related_name="submissions")
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="submissions")
    round_number = models.PositiveIntegerField()
    card_name = models.CharField(max_length=200)
    scryfall_id = models.CharField(max_length=64, blank=True)
    related_to = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cube", "player", "round_number"],
                name="unique_submission_per_user_per_round",
            )
        ]
        ordering = ["created_at"]

    def clean(self) -> None:
        if not self.cube.participants.filter(pk=self.player_id).exists():
            raise ValidationError("Only cube participants can submit cards.")

        if not self.cube.is_open:
            raise ValidationError("This cube has reached its card limit.")

        submissions_without_self = self.cube.submissions.exclude(pk=self.pk)
        expected_round = (submissions_without_self.count() // max(self.cube.participant_count, 1)) + 1
        if self.round_number != expected_round:
            raise ValidationError("Submission does not match the current round.")

        if self.cube.max_count_per_card > 0:
            existing_count = submissions_without_self.filter(card_name__iexact=self.card_name).count()
            if existing_count >= self.cube.max_count_per_card:
                raise ValidationError("This card has reached the max allowed copies in this cube.")

    def __str__(self) -> str:
        return f"{self.cube.name} R{self.round_number}: {self.card_name}"

    @property
    def scryfall_url(self) -> str:
        if self.scryfall_id:
            return f"https://scryfall.com/card/{self.scryfall_id}"
        return f'https://scryfall.com/search?q=%21%22{quote(self.card_name)}%22'
