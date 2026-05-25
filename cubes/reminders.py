from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.tasks import task
from django.utils import timezone

from .models import Cube, NotificationDelivery, SubmissionReminder, User


def _reminder_delay_days() -> int:
    return getattr(settings, "SUBMISSION_REMINDER_DAYS", 3)


def queue_round_open_notifications(
    cube: Cube,
    round_number: int,
    round_opened_at: datetime,
    participants=None,
) -> None:
    participant_list = list(participants or cube.participants.all())
    for participant in participant_list:
        send_round_ready_notification.enqueue(cube.pk, participant.pk, round_number)
        reminder, created = SubmissionReminder.objects.get_or_create(
            cube=cube,
            player=participant,
            round_number=round_number,
            defaults={
                "remind_after": round_opened_at + timedelta(days=_reminder_delay_days()),
            },
        )
        if created and reminder.remind_after <= timezone.now():
            send_submission_reminder.enqueue(reminder.pk)


def queue_due_submission_reminders() -> None:
    due_reminders = SubmissionReminder.objects.select_related("cube", "player").filter(
        processed_at__isnull=True,
        remind_after__lte=timezone.now(),
    )
    for reminder in due_reminders:
        send_submission_reminder.enqueue(reminder.pk)


def _deliver_notification(
    *,
    cube: Cube,
    player: User,
    round_number: int,
    kind: NotificationDelivery.Kind,
) -> bool:
    if not player.email:
        return False

    subject, body = _build_notification_email(
        cube=cube,
        player=player,
        round_number=round_number,
        kind=kind,
    )
    return bool(
        send_mail(
            subject,
            body,
            getattr(settings, "DEFAULT_FROM_EMAIL", None),
            [player.email],
        )
    )


def _build_notification_email(
    *,
    cube: Cube,
    player: User,
    round_number: int,
    kind: NotificationDelivery.Kind,
) -> tuple[str, str]:
    if kind == NotificationDelivery.Kind.ROUND_READY:
        return (
            f"[Popcorn Cube] Round {round_number} is ready in {cube.name}",
            (
                f"Hi {player.username},\n\n"
                f"Everyone has submitted for the previous round in {cube.name}.\n"
                f"It's time to submit your card for round {round_number}.\n"
            ),
        )
    return (
        f"[Popcorn Cube] Gentle reminder for round {round_number} in {cube.name}",
        (
            f"Hi {player.username},\n\n"
            f"This is a gentle reminder to submit your card for round {round_number} in {cube.name}.\n"
        ),
    )


def _record_notification_delivery(
    *,
    cube: Cube,
    player: User,
    round_number: int,
    kind: NotificationDelivery.Kind,
) -> bool:
    if NotificationDelivery.objects.filter(
        cube=cube,
        player=player,
        round_number=round_number,
        kind=kind,
    ).exists():
        return False

    sent = _deliver_notification(
        cube=cube,
        player=player,
        round_number=round_number,
        kind=kind,
    )
    if sent:
        NotificationDelivery.objects.create(
            cube=cube,
            player=player,
            round_number=round_number,
            kind=kind,
        )
    return sent


@task
def send_round_ready_notification(cube_id: int, player_id: int, round_number: int) -> bool:
    cube = Cube.objects.get(pk=cube_id)
    player = User.objects.get(pk=player_id)
    if not cube.is_open or cube.current_round != round_number:
        return False
    if cube.submissions.filter(round_number=round_number, player=player).exists():
        return False
    return _record_notification_delivery(
        cube=cube,
        player=player,
        round_number=round_number,
        kind=NotificationDelivery.Kind.ROUND_READY,
    )


@task
def send_submission_reminder(reminder_id: int) -> bool:
    reminder = SubmissionReminder.objects.select_related("cube", "player").get(pk=reminder_id)
    if reminder.processed_at is not None:
        return False

    cube = reminder.cube
    player = reminder.player
    if (
        not cube.is_open
        or cube.current_round != reminder.round_number
        or cube.submissions.filter(round_number=reminder.round_number, player=player).exists()
    ):
        reminder.processed_at = timezone.now()
        reminder.save(update_fields=["processed_at"])
        return False

    sent = _record_notification_delivery(
        cube=cube,
        player=player,
        round_number=reminder.round_number,
        kind=NotificationDelivery.Kind.GENTLE_REMINDER,
    )
    reminder.processed_at = timezone.now()
    reminder.save(update_fields=["processed_at"])
    return sent
