from django.core.cache import cache

from .reminders import queue_due_submission_reminders

REMINDER_CHECK_CACHE_KEY = "cubes:submission-reminder-check"


class SubmissionReminderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            getattr(request, "user", None)
            and request.user.is_authenticated
            and cache.add(REMINDER_CHECK_CACHE_KEY, True, timeout=60)
        ):
            queue_due_submission_reminders()
        return self.get_response(request)
