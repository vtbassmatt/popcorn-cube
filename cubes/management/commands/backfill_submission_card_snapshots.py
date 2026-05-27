from django.core.management.base import BaseCommand
from django.db.models import Q

from cubes.card_snapshot import build_card_snapshot
from cubes.models import Submission
from cubes.scryfall import fetch_card_by_id, fetch_card_by_name


class Command(BaseCommand):
    help = "Backfill missing submission card snapshots from Scryfall."

    def add_arguments(self, parser):
        parser.add_argument("--cube-id", type=int, help="Only backfill submissions from this cube.")

    def handle(self, *args, **options):
        queryset = Submission.objects.filter(Q(card_snapshot={}) | Q(card_snapshot__isnull=True)).order_by("pk")
        cube_id = options.get("cube_id")
        if cube_id is not None:
            queryset = queryset.filter(cube_id=cube_id)

        updated = 0
        skipped = 0
        for submission in queryset.iterator():
            card_data = None
            if submission.scryfall_id:
                card_data = fetch_card_by_id(submission.scryfall_id)
            if not card_data:
                card_data = fetch_card_by_name(submission.card_name)

            if not card_data:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"Skipped submission {submission.pk}: could not fetch card data"))
                continue

            submission.card_snapshot = build_card_snapshot(card_data)
            submission.save(update_fields=["card_snapshot"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Backfill complete. Updated: {updated}. Skipped: {skipped}."))
