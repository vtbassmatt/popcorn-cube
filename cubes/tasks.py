from django.conf import settings
from django.core import mail
from django.tasks import task
from django.template.loader import render_to_string

from cubes.models import Submission


@task
def email_about_submission(submission_id: int, url_base: str):
    submission = Submission.objects.filter(pk=submission_id).select_related('cube', 'player').first()

    if not submission:
        raise ValueError(f"Submission {submission_id} not found; no emails queued.")
    
    if submission.round_number == submission.cube.current_round:
        # this was not the last player to submit
        return _send_midround_emails(submission, url_base)
    
    # this was the last player to submit
    if submission.cube.is_open:
        # new round
        return _send_newround_emails(submission, url_base)

    # the cube must be complete
    return _send_cubecomplete_emails(submission, url_base)


def _send_midround_emails(submission: Submission, url_base: str):
    if not settings.EMAIL_SEND_MIDROUND:
        return 'disabled'

    subject = f"[Popcorn Cube] {submission.player.get_short_name() or submission.player.get_username()} submitted a card for round {submission.round_number} in {submission.cube.name}"
    current_round_submitted_player_ids = set(
        submission.cube.submissions.filter(round_number=submission.round_number).values_list("player_id", flat=True)
    )
    waiting_on_participants = [
        participant
        for participant in submission.cube.participants.all()
        if participant.pk != submission.player.pk and participant.pk not in current_round_submitted_player_ids
    ]

    return _send_email(submission, url_base, 'midround', subject, {'waiting_on': waiting_on_participants})


def _send_newround_emails(submission: Submission, url_base: str):
    subject = f"[Popcorn Cube] Round {submission.cube.current_round} for {submission.cube.name} starts now"
    round_submissions = (
        submission.cube
        .submissions
        .filter(round_number=submission.round_number)
        .select_related("player")
    )
    return _send_email(submission, url_base, 'newround', subject, {'round_submissions': round_submissions})


def _send_cubecomplete_emails(submission: Submission, url_base: str):
    subject = f"[Popcorn Cube] {submission.cube.name} is complete"
    return _send_email(submission, url_base, 'cubecomplete', subject)


def _send_email(submission: Submission, url_base: str, template: str, subject: str, context: dict = {}):
    recipients = [p.email for p in submission.cube.participants.all()]
    context.update({
        "submission": submission,
        "url_base": url_base,
    })

    text_content = render_to_string(
        f"cubes/emails/{template}.txt",
        context=context,
    )
    html_content = render_to_string(
        f"cubes/emails/{template}.html",
        context=context,
    )

    with mail.get_connection() as connection:
        msg = mail.EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.EMAIL_FROM,
            to=recipients,
            connection=connection,
        )
        msg.attach_alternative(html_content, 'text/html')
        return msg.send()
