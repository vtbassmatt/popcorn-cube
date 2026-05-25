from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import m2m_changed, post_save
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
        existing_submission = None
        if self.pk:
            existing_submission = Submission.objects.filter(pk=self.pk).only("cube_id", "round_number").first()
        is_round_unchanged_edit = (
            existing_submission is not None
            and existing_submission.cube_id == self.cube_id
            and existing_submission.round_number == self.round_number
        )

        if not self.cube.participants.filter(pk=self.player_id).exists():
            raise ValidationError("Only cube participants can submit cards.")

        if not self.cube.is_open and not is_round_unchanged_edit:
            raise ValidationError("This cube has reached its card limit.")

        submissions_without_self = self.cube.submissions.exclude(pk=self.pk)
        expected_round = (submissions_without_self.count() // max(self.cube.participant_count, 1)) + 1
        if self.round_number != expected_round and not is_round_unchanged_edit:
            raise ValidationError("Submission does not match the current round.")

        if self.cube.max_count_per_card > 0:
            existing_count = submissions_without_self.filter(card_name__iexact=self.card_name).count()
            if existing_count >= self.cube.max_count_per_card:
                # TODO: put this validation error on the specific field
                raise ValidationError("This card has reached the max allowed copies in this cube.")

    def __str__(self) -> str:
        return f"{self.cube.name} R{self.round_number}: {self.card_name}"

    @property
    def scryfall_url(self) -> str:
        if self.scryfall_id:
            return f"https://scryfall.com/card/{self.scryfall_id}"
        return f'https://scryfall.com/search?q=%21%22{quote(self.card_name)}%22'


class NotificationDelivery(models.Model):
    class Kind(models.TextChoices):
        ROUND_READY = "round_ready", "Round ready"
        GENTLE_REMINDER = "gentle_reminder", "Gentle reminder"

    cube = models.ForeignKey(Cube, on_delete=models.CASCADE, related_name="notification_deliveries")
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_deliveries")
    round_number = models.PositiveIntegerField()
    kind = models.CharField(max_length=32, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cube", "player", "round_number", "kind"],
                name="unique_notification_delivery_per_kind",
            )
        ]
        ordering = ["created_at"]


class SubmissionReminder(models.Model):
    cube = models.ForeignKey(Cube, on_delete=models.CASCADE, related_name="submission_reminders")
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="submission_reminders")
    round_number = models.PositiveIntegerField()
    remind_after = models.DateTimeField()
    processed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cube", "player", "round_number"],
                name="unique_submission_reminder_per_round",
            )
        ]
        ordering = ["remind_after", "created_at"]


@receiver(m2m_changed, sender=Cube.participants.through)
def queue_initial_round_notifications(
    sender,
    instance: Cube,
    action: str,
    reverse: bool,
    pk_set,
    **kwargs,
) -> None:
    if action != "post_add" or reverse or not pk_set or instance.submissions.exists():
        return

    from .reminders import queue_round_open_notifications

    participants = User.objects.filter(pk__in=pk_set)
    queue_round_open_notifications(
        cube=instance,
        round_number=1,
        round_opened_at=instance.created_at,
        participants=participants,
    )


@receiver(post_save, sender=Submission)
def queue_next_round_notifications(sender, instance: Submission, created: bool, **kwargs) -> None:
    if not created:
        return

    cube = instance.cube
    if not cube.is_open:
        return

    if cube.submissions.filter(round_number=instance.round_number).count() != cube.participant_count:
        return

    from .reminders import queue_round_open_notifications

    queue_round_open_notifications(
        cube=cube,
        round_number=instance.round_number + 1,
        round_opened_at=instance.created_at,
    )
