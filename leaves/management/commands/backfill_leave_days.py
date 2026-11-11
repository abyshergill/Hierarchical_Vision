from datetime import date, datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from leaves.models import LeaveApplication, LeaveDay, LeavePolicy
from leaves.services import holiday_dates
from leaves.utils import working_days_between


class Command(BaseCommand):
    help = ("Create per-day rows (LeaveDay) for leave applications made before the per-day feature existed. "
            "Safe to run more than once; applications that already have rows are skipped.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be created.")

    @transaction.atomic
    def handle(self, *args, **opts):
        start_default = LeavePolicy.load().default_start_time
        created = 0
        for app in LeaveApplication.objects.filter(days__isnull=True):
            if app.is_hourly and app.start_time and app.end_time:
                rows = [(app.start_date, app.start_time, app.end_time, app.total_hours)]
            else:
                days = working_days_between(app.start_date, app.end_date, holiday_dates(app.start_date, app.end_date),
                                            settings.WORKING_WEEKDAYS)
                if not days:
                    continue
                per_day = (Decimal(app.total_hours) / len(days)).quantize(Decimal("0.01"))
                end = (datetime.combine(date(2000, 1, 1), start_default) + timedelta(hours=float(per_day))).time()
                rows = [(d, start_default, end, per_day) for d in days]
            if not opts["dry_run"]:
                LeaveDay.objects.bulk_create([
                    LeaveDay(application=app, date=d, start_time=s, end_time=e, hours=h) for d, s, e, h in rows
                ])
            created += len(rows)
        verb = "Would create" if opts["dry_run"] else "Created"
        self.stdout.write(self.style.SUCCESS(f"{verb} {created} leave day row(s)."))
