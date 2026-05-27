from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .card_snapshot import build_card_snapshot
from .models import Cube, Submission
from .scryfall import fetch_card_by_name, is_card_legal_for_format

User = get_user_model()


class Bs5ModelFormBase(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _, f in self.fields.items():
            if 'class' in f.widget.attrs:
                f.widget.attrs['class'] += " form-control"
            else:
                f.widget.attrs['class'] = "form-control"


class CubeForm(Bs5ModelFormBase):
    participants = forms.ModelMultipleChoiceField(queryset=User.objects.none(), required=False)

    class Meta:
        model = Cube
        fields = ["name", "participants", "max_cards", "format_legality", "max_count_per_card"]

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["participants"].queryset = User.objects.exclude(pk=getattr(user, "pk", None)).order_by(
            "username"
        )


class SubmissionForm(Bs5ModelFormBase):
    class Meta:
        model = Submission
        fields = ["card_name", "related_to"]
        widgets = {"related_to": forms.TextInput()}

    def __init__(self, *args, cube: Cube, player, **kwargs):
        super().__init__(*args, **kwargs)
        self.cube = cube
        self.player = player
        self.card_data = None
        self.fields["related_to"].required = False
        self.fields["related_to"].label = "Reason (optional)"
        self.fields["related_to"].help_text = "How does this card connect to one or more cards from last round?"
        if cube.current_round == 1:
            self.fields["related_to"].help_text = (
                "Why this card?"
            )

    def clean_card_name(self) -> str:
        card_name = self.cleaned_data["card_name"].strip()
        card_data = fetch_card_by_name(card_name)
        if not card_data or "name" not in card_data:
            raise ValidationError("Card not found on Scryfall.")

        if self.cube.format_legality and not is_card_legal_for_format(card_data, self.cube.format_legality):
            raise ValidationError(
                f"{card_data['name']} is not legal in {self.cube.get_format_legality_display()} format."
            )

        self.card_data = card_data
        return card_data["name"]

    def clean(self):
        cleaned_data = super().clean()
        self.instance.cube = self.cube
        self.instance.player = self.player
        self.instance.round_number = self.cube.current_round
        return cleaned_data

    def save(self, commit: bool = True):
        instance: Submission = super().save(commit=False)
        instance.cube = self.cube
        instance.player = self.player
        instance.round_number = self.cube.current_round
        if self.card_data:
            instance.scryfall_id = self.card_data.get("id", "")
            instance.card_snapshot = build_card_snapshot(self.card_data)
        if commit:
            instance.full_clean()
            instance.save()
        return instance
