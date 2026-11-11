from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from accounts.models import Role, User
from leaves.models import Holiday, LeavePolicy, LeaveType
from newsletter.models import GroupMembership, NewsGroup, Post

PASSWORD = "ChangeMe!2026"


class Command(BaseCommand):
    help = "Create demo users, standard leaves and holidays (password for all: %s)." % PASSWORD

    def handle(self, *args, **options):
        def make(eid, name, email, role, position, manager=None):
            user, created = User.objects.get_or_create(
                employee_id=eid,
                defaults=dict(full_name=name, email=email, role=role, position=position, manager=manager),
            )
            if created:
                user.set_password(PASSWORD)
                user.save()
            return user

        admin = make("EMP-001", "Alex Admin", "admin@example.com", Role.ADMIN, "HR Director")
        m1 = make("EMP-100", "Mia Manager", "mia@example.com", Role.MANAGER, "Engineering Manager", admin)
        m2 = make("EMP-200", "Max Manager", "max@example.com", Role.MANAGER, "Operations Manager", admin)
        make("EMP-101", "Erin Employee", "erin@example.com", Role.EMPLOYEE, "Test Engineer", m1)
        make("EMP-102", "Eli Employee", "eli@example.com", Role.EMPLOYEE, "Technician", m1)
        make("EMP-201", "Eva Employee", "eva@example.com", Role.EMPLOYEE, "Planner", m2)

        User.objects.filter(employee_id="EMP-100").update(newsletter_publisher=True)
        for name, code, days, hourly in [
            ("Annual Leave", "AL", "10", True),
            ("Sick Leave", "SL", "30", True),
            ("Personal Leave", "PL", "3", False),
        ]:
            LeaveType.objects.get_or_create(
                code=code,
                defaults=dict(name=name, annual_quota_days=Decimal(days), allow_hourly=hourly, created_by=admin),
            )
        for d, n in [(date(2026, 12, 5), "King's Birthday"), (date(2026, 12, 10), "Constitution Day"),
                     (date(2026, 12, 31), "New Year's Eve"), (date(2027, 1, 1), "New Year's Day")]:
            Holiday.objects.get_or_create(date=d, defaults={"name": n})
        LeavePolicy.load()
        if not Post.objects.exists():
            Post.objects.create(
                title="Welcome to the company newsletter", author=admin, is_pinned=True,
                body="This is where we share what is happening around the company.\nAdmins can post text and images and "
                     "can allow selected managers and employees to publish too.")
        group, _ = NewsGroup.objects.get_or_create(
            name="Test Manufacturing", defaults={"description": "Test engineering updates", "manager": m1, "created_by": admin})
        GroupMembership.objects.get_or_create(group=group, user=User.objects.get(employee_id="EMP-101"), defaults={"added_by": admin})
        self.stdout.write(self.style.SUCCESS(f"Demo data ready. Sign in as EMP-001 / EMP-100 / EMP-101 with password {PASSWORD}"))
