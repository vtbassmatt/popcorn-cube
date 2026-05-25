from .reminders import queue_due_submission_reminders


class SubmissionReminderMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        queue_due_submission_reminders()
        return self.get_response(request)
