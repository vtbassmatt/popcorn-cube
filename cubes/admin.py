from django.contrib import admin

from .models import Cube, Submission


@admin.register(Cube)
class CubeAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "max_cards", "format_legality", "max_count_per_card")
    filter_horizontal = ("participants",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("cube", "round_number", "player", "card_name")
    list_filter = ("cube", "round_number")
