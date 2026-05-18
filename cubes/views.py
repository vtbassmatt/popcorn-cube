from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView

from .forms import CubeForm, SubmissionForm
from .models import Cube


class CubeListView(LoginRequiredMixin, ListView):
    model = Cube
    template_name = "cubes/cube_list.html"
    context_object_name = "cubes"

    def get_queryset(self):
        return Cube.objects.filter(participants=self.request.user).distinct()


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

    def _already_submitted(self, cube: Cube) -> bool:
        return cube.submissions.filter(round_number=cube.current_round, player=self.request.user).exists()

    def _can_submit(self, cube: Cube) -> bool:
        return cube.is_open and not self._already_submitted(cube)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cube: Cube = self.object
        current_round = cube.current_round
        previous_round_cards = cube.submissions.filter(round_number=current_round - 1).exclude(
            player=self.request.user
        )
        already_submitted = self._already_submitted(cube)
        can_submit = self._can_submit(cube)
        # POST re-renders this view with a bound form on validation errors.
        form = kwargs.get("form", None)
        if can_submit and form is None:
            form = SubmissionForm(cube=cube, player=self.request.user)

        context.update(
            {
                "current_round": current_round,
                "previous_round_cards": previous_round_cards,
                "already_submitted": already_submitted,
                "can_submit": can_submit,
                "form": form,
            }
        )
        return context

    def post(self, request: HttpRequest, *args, **kwargs) -> HttpResponse:
        """Handle inline card submission from the cube detail page."""
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
            form.save()
            messages.success(request, "Card submitted.")
            return redirect("cube-detail", pk=cube.pk)

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
