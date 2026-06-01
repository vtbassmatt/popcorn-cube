import re
from functools import partial

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView
from django.views.generic.base import TemplateView

from .forms import CubeForm, SubmissionForm
from .models import Cube, Submission
from .stats import compute_cube_stats
from .tasks import email_about_submission

FIRST_ROUND_WITH_STATS_DISPLAY = 2


class CubeListView(LoginRequiredMixin, ListView):
    model = Cube
    template_name = "cubes/cube_list.html"
    context_object_name = "cubes"

    def get_queryset(self):
        return Cube.objects.filter(participants=self.request.user).distinct()


class HowThisWorksView(TemplateView):
    template_name = "cubes/how_this_works.html"


class CubeCreateView(LoginRequiredMixin, CreateView):
    model = Cube
    form_class = CubeForm
    template_name = "cubes/cube_form.html"
    success_url = reverse_lazy("cube-list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.owner = self.request.user
        response = super().form_valid(form)
        selected_participants = form.cleaned_data["participants"]
        self.object.participants.add(self.request.user, *selected_participants)
        messages.success(self.request, "Cube created.")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)


class CubeDetailView(LoginRequiredMixin, DetailView):
    model = Cube
    template_name = "cubes/cube_detail.html"
    context_object_name = "cube"

    def get_queryset(self):
        return Cube.objects.filter(participants=self.request.user)

    def _submission(self, cube: Cube):
        return cube.submissions.filter(round_number=cube.current_round, player=self.request.user)

    def _already_submitted(self, cube: Cube) -> bool:
        return self._submission(cube).exists()

    def _can_submit(self, cube: Cube) -> bool:
        return cube.is_open and not self._already_submitted(cube)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cube: Cube = self.object
        current_round = cube.current_round
        previous_round_cards = cube.submissions.filter(round_number=current_round - 1).select_related("player").order_by("pk")
        current_round_submitted_player_ids = set(
            cube.submissions.filter(round_number=current_round).values_list("player_id", flat=True)
        )
        submission = self._submission(cube).first()
        already_submitted = self._already_submitted(cube)
        can_submit = self._can_submit(cube)
        display_mode = "alphabetical" if self.request.GET.get("view") == "alphabetical" else "table"
        show_prior_submissions = self.request.GET.get("show_prior_submissions") == "1"
        prior_submissions = Submission.objects.none()
        if show_prior_submissions:
            prior_submissions = cube.submissions.filter(player=self.request.user, round_number__lt=current_round).order_by(
                "round_number", "created_at"
            )
        participants = list(cube.participants.order_by("username"))
        waiting_on_participants = [
            participant
            for participant in participants
            if participant.pk != self.request.user.pk and participant.pk not in current_round_submitted_player_ids
        ]
        ordered_submissions = cube.submissions.select_related("player").order_by(
            "round_number", "player__username", "created_at"
        )
        round_rows = []
        alphabetical_submissions = []
        if cube.is_open:
            stats_submissions = list(ordered_submissions.filter(round_number__lt=current_round))
        else:
            display_submissions = list(ordered_submissions)
            stats_submissions = display_submissions
            submissions_by_round = {}
            for submission in display_submissions:
                submissions_by_round.setdefault(submission.round_number, {})[submission.player_id] = submission
            for round_number in sorted(submissions_by_round):
                round_rows.append(
                    {
                        "round_number": round_number,
                        "cards": [submissions_by_round[round_number].get(participant.pk) for participant in participants],
                    }
                )
            alphabetical_submissions = sorted(
                display_submissions,
                key=lambda submission: (
                    submission.card_name.lower(),
                    submission.player.username.lower(),
                    submission.round_number,
                ),
            )
        has_stats = current_round >= FIRST_ROUND_WITH_STATS_DISPLAY
        cube_stats = compute_cube_stats(stats_submissions) if has_stats else None
        # POST re-renders this view with a bound form on validation errors.
        form = kwargs.get("form", None)
        if can_submit and form is None:
            form = SubmissionForm(cube=cube, player=self.request.user)

        context.update(
            {
                "current_round": current_round,
                "previous_round_cards": previous_round_cards,
                "submitted_card": submission,
                "already_submitted": already_submitted,
                "can_submit": can_submit,
                "waiting_on_participants": waiting_on_participants,
                "form": form,
                "display_mode": display_mode,
                "show_prior_submissions": show_prior_submissions,
                "prior_submissions": prior_submissions,
                "results_participants": participants,
                "round_rows": round_rows,
                "alphabetical_submissions": alphabetical_submissions,
                "has_stats": has_stats,
                "cube_stats": cube_stats,
            }
        )
        return context

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Handle inline card submission.

        Success and pre-submit state failures redirect with a flash message.
        Validation errors re-render this page with a bound form.
        """
        self.object = self.get_object()
        cube: Cube = self.object

        if not cube.is_open:
            messages.error(request, "This cube has reached its card limit.")
            return redirect("cube-detail", pk=cube.pk)

        if self._already_submitted(cube):
            messages.info(request, "You have already submitted for this round.")
            return redirect("cube-detail", pk=cube.pk)

        form = SubmissionForm(request.POST, cube=cube, player=request.user)
        if form.is_valid():
            with transaction.atomic():
                submission = form.save()
                transaction.on_commit(partial(
                    email_about_submission.enqueue,
                    submission_id=submission.id,
                    url_base=request._current_scheme_host,
                ))

            messages.success(request, "Card submitted.")
            return redirect("cube-detail", pk=cube.pk)

        # self.object must be set so DetailView.get_context_data can access the current cube.
        context = self.get_context_data(form=form)
        return self.render_to_response(context)


@login_required
def submit_card(request: HttpRequest, pk: int) -> HttpResponse:
    cube = get_object_or_404(Cube.objects.prefetch_related("participants"), pk=pk)
    if not cube.participants.filter(pk=request.user.pk).exists():
        messages.error(request, "You are not part of this cube.")
        return redirect("cube-list")

    if not cube.is_open:
        messages.error(request, "This cube has reached its card limit.")
        return redirect("cube-detail", pk=cube.pk)

    if cube.submissions.filter(round_number=cube.current_round, player=request.user).exists():
        messages.info(request, "You have already submitted for this round.")
        return redirect("cube-detail", pk=cube.pk)

    if request.method == "POST":
        form = SubmissionForm(request.POST, cube=cube, player=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Card submitted.")
            return redirect("cube-detail", pk=cube.pk)
    else:
        form = SubmissionForm(cube=cube, player=request.user)

    return render(request, "cubes/submission_form.html", {"form": form, "cube": cube})


@login_required
def export_cube_csv(request: HttpRequest, pk: int) -> HttpResponse:
    cube = get_object_or_404(Cube.objects.filter(participants=request.user).distinct(), pk=pk)

    if cube.is_open:
        messages.error(request, "Cube export is only available when the cube is complete.")
        return redirect("cube-detail", pk=cube.pk)

    card_names = cube.submissions.order_by("card_name").values_list("card_name", flat=True).iterator()

    filename = f"{cube.name}.txt"
    response = HttpResponse(content_type="text/plain")
    # Sanitize filename: remove path separators, quotes, and control characters
    # that could be problematic in Content-Disposition headers or file systems.
    safe_filename = re.sub(r'["\\/\r\n\t]', '_', filename)
    response["Content-Disposition"] = f'attachment; filename="{safe_filename}"'

    for card_name in card_names:
        response.write(f"{card_name}\n")

    return response
