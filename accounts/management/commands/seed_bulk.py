"""Load a large, realistic demo organisation (about 2,100 people) for load and UI testing.

    python manage.py seed_demo     # base data: EMP-001 admin, leave types, holidays
    python manage.py seed_bulk     # this command

Creates 10 IT admins, 85 managers (5 department heads + 80 team managers), 2,000 employees, leave and OT requests
in every status, IT-support tickets with status updates, profile status lines, 20 department newsletter groups
(with members, posts and pending access requests) and pinned newsletter posts. Everyone's password is the same as
in ``seed_demo``. The run is deterministic (fixed random seed) and refuses to run twice.
"""
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from leaves.models import Holiday, LeaveApplication, LeaveDay, LeaveType, OvertimeRequest
from newsletter.models import Comment, GroupAccessRequest, GroupMembership, NewsGroup, Post
from notifications.models import Notification
from support.models import SupportRequest

from .seed_demo import PASSWORD

FIRST = [
    "Somchai", "Somsak", "Anan", "Arthit", "Chaiwat", "Kittipong", "Nattapong", "Prasert", "Sombat", "Thanakorn",
    "Wichai", "Pornchai", "Supachai", "Kritsada", "Jirayu", "Siriporn", "Malee", "Kanya", "Pimchanok", "Nok",
    "Ploy", "Achara", "Ratana", "Suda", "Wanida", "Busaba", "Chalida", "Nicha", "Pensri", "Lamai",
    "James", "Olivia", "Liam", "Emma", "Noah", "Ava", "Ethan", "Sophia", "Lucas", "Mia",
    "Mason", "Isabella", "Logan", "Amelia", "Arjun", "Priya", "Rahul", "Ananya", "Vikram", "Neha",
    "Ravi", "Pooja", "Kenji", "Yuki", "Haruto", "Sakura", "Wei", "Mei", "Jun", "Lin",
    "Minh", "Linh", "Duc", "Hoa", "Carlos", "Lucia", "Diego", "Sofia", "Mateo", "Elena",
    "Omar", "Layla", "Hassan", "Amira", "Daniel", "Grace", "Samuel", "Chloe", "Benjamin", "Zoe",
]
LAST = [
    "Srisuk", "Wongsawat", "Chaiyaporn", "Rattanakul", "Sukprasert", "Thongchai", "Boonmee", "Saetang", "Phromma",
    "Kaewkla", "Jaidee", "Siriwat", "Nakprasert", "Intharasuk", "Pongpanit", "Chantarasiri", "Somboon", "Yodsuwan",
    "Smith", "Johnson", "Brown", "Taylor", "Wilson", "Anderson", "Thomas", "Moore", "Martin", "Clark",
    "Sharma", "Patel", "Gupta", "Singh", "Reddy", "Iyer", "Tanaka", "Sato", "Suzuki", "Watanabe",
    "Chen", "Wang", "Li", "Zhang", "Nguyen", "Tran", "Pham", "Le", "Garcia", "Martinez",
    "Lopez", "Hernandez", "Rossi", "Muller", "Schmidt", "Khan", "Ali", "Ahmed", "Kim", "Park",
]

DEPARTMENTS = {
    "Engineering": ["Software Engineer", "Senior Software Engineer", "Test Engineer", "QA Analyst", "DevOps Engineer",
                    "Data Engineer", "Firmware Engineer"],
    "Operations": ["Operations Analyst", "Logistics Coordinator", "Planner", "Warehouse Supervisor", "Buyer",
                   "Supply Chain Analyst"],
    "Production": ["Technician", "Senior Technician", "Machine Operator", "Process Engineer", "Quality Inspector",
                   "Maintenance Technician", "Line Leader"],
    "Sales & Marketing": ["Account Executive", "Sales Coordinator", "Marketing Specialist", "Customer Success Manager",
                          "Content Writer", "Graphic Designer"],
    "Finance & HR": ["Accountant", "Payroll Officer", "HR Generalist", "Recruiter", "Financial Analyst",
                     "Training Coordinator"],
}
TEAM_NAMES = {
    "Engineering": ["Platform", "Mobile Apps", "Web Portal", "Test Automation", "Data", "Embedded", "Cloud Infra",
                    "Security", "Integration", "Tools", "Analytics", "API", "Firmware", "Release", "Reliability", "R&D"],
    "Operations": ["Logistics", "Planning", "Warehouse A", "Warehouse B", "Procurement", "Import / Export", "Fleet",
                   "Inventory", "Facilities", "Vendor Mgmt", "Customer Service", "Returns", "Shipping", "Receiving",
                   "Scheduling", "Continuous Improvement"],
    "Production": ["Line 1", "Line 2", "Line 3", "Line 4", "SMT", "Final Assembly", "Test Manufacturing", "Packaging",
                   "Maintenance", "Quality Control", "Process Eng", "Tooling", "Clean Room", "Night Shift",
                   "Calibration", "Rework"],
    "Sales & Marketing": ["Key Accounts", "APAC Sales", "EU Sales", "US Sales", "Inside Sales", "Partner Channel",
                          "Brand", "Digital Marketing", "Events", "Product Marketing", "Customer Success", "Pre-sales",
                          "Pricing", "Market Research", "Communications", "Social Media"],
    "Finance & HR": ["Accounting", "Payroll", "Treasury", "Tax", "Audit", "Budgeting", "Recruitment", "Training",
                     "Employee Relations", "Compensation", "HR Operations", "Health & Safety", "Legal", "Admin Office",
                     "Procure-to-Pay", "Reporting"],
}
STATUS_LINES = [
    "Working from the Bangkok office this week.", "On a customer visit until Friday - reply may be slow.",
    "Working from home today.", "In training all morning, available after 13:00.", "Back from leave - catching up!",
    "Focus time: please message instead of calling.", "At the Chonburi plant this week.",
    "Happy to help with onboarding questions.", "Travelling to Singapore - limited availability.",
    "Out at lunch 12:00-13:00, back soon.", "Night shift this week (22:00-06:00).", "Busy with month-end closing.",
    "Coordinating the year-end stock count.", "Available for code reviews.", "Running the new hire orientation today.",
]
LEAVE_REASONS = ["Family trip", "Medical appointment", "Personal matters", "Feeling unwell", "Child's school event",
                 "Moving house", "Wedding of a relative", "Rest after project delivery", "Dentist", "Government paperwork"]
OT_REASONS = ["Month-end closing", "Urgent customer order", "Production backlog", "System migration window",
              "Line maintenance after hours", "Stock count", "Release deployment", "Audit preparation",
              "Covering for a colleague on leave", "Server patching window", "Trade show preparation"]
TICKETS = [
    ("Laptop will not boot", "My laptop shows a black screen after the logo."),
    ("VPN keeps disconnecting", "VPN drops every 10-15 minutes when working from home."),
    ("Request: second monitor", "Could I get a second monitor for my desk?"),
    ("Printer on 3rd floor jammed", "The shared printer near the meeting room jams on every job."),
    ("Password reset for ERP", "I am locked out of the ERP after too many attempts."),
    ("Outlook not syncing", "New e-mails are not arriving on my phone."),
    ("Install CAD software", "Please install the CAD viewer for drawing reviews."),
    ("Wi-Fi weak in canteen", "Wi-Fi signal in the canteen is very weak."),
    ("New starter account", "A new team member starts on Monday and needs an account."),
    ("Teams camera not detected", "Camera is not detected in video calls."),
    ("Shared drive access", "Need read access to the Quality shared drive."),
    ("Keyboard replacement", "Several keys on my keyboard stopped working."),
]
PINNED = [
    ("Year-end holiday schedule 2026/27", "The office closes on 31 December and reopens on 4 January. Check the Holidays "
     "page for the full list and plan your leave early."),
    ("New overtime approval process", "Overtime is now requested under *Overtime* in the top bar and approved by your "
     "manager. Please submit OT at least one day in advance where possible."),
    ("IT security reminder: phishing", "Never share your password. IT will never ask for it by e-mail or phone. Report "
     "suspicious messages through IT support."),
    ("Annual health check - book your slot", "The annual health check runs from 1-12 December in the training room. "
     "Book a slot with HR."),
    ("Town hall: Q4 results", "Join the company town hall on 20 November at 15:00 in the main hall or online."),
    ("Fire drill on 25 November", "A fire drill will take place at 10:30. Please follow the wardens to the assembly point."),
    ("Car park resurfacing", "Car park B is closed from 1-7 December. Please use car park A or the shuttle."),
    ("Welcome to our new colleagues", "Over 100 people joined us this quarter - say hello and help them settle in!"),
    ("Leave balances carry-over", "Unused annual leave (max 5 days) carries over to March 2027. Check your profile."),
]


class Command(BaseCommand):
    help = "Load a large demo organisation (2,000 employees, 85 managers, 10 IT admins, leaves, OT, groups...)."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=2026, help="Random seed (default 2026).")

    def handle(self, *args, **opts):
        if User.objects.filter(employee_id="EMP-10001").exists():
            raise CommandError("Bulk demo data is already loaded (EMP-10001 exists).")
        top = User.objects.filter(employee_id="EMP-001").first()
        if top is None or not LeaveType.objects.exists():
            raise CommandError("Run `python manage.py seed_demo` first.")
        self.rng = random.Random(opts["seed"])
        self.now = timezone.now()
        self.today = timezone.localdate()
        self.pw = make_password(PASSWORD)  # hash once; hashing 2,000 times would take minutes
        self._emails = set(User.objects.values_list("email", flat=True))
        with transaction.atomic():
            it_admins, heads, managers, teams = self.people(top)
            self.statuses(teams)
            self.leaves(teams)
            self.overtime(teams)
            self.tickets(teams, it_admins)
            self.groups(top, managers, teams)
        self.stdout.write(self.style.SUCCESS(f"Bulk demo data ready. Password for everyone: {PASSWORD}"))

    # ------------------------------------------------------------------ people
    def name(self):
        first, last = self.rng.choice(FIRST), self.rng.choice(LAST)
        base = f"{first}.{last}".lower()
        email, n = f"{base}@example.com", 1
        while email in self._emails:
            n += 1
            email = f"{base}{n}@example.com"
        self._emails.add(email)
        return f"{first} {last}", email

    def user(self, eid, role, position, manager, **extra):
        full_name, email = self.name()
        is_admin = role == Role.ADMIN
        return User(employee_id=eid, email=email, full_name=full_name, role=role, position=position,
                    manager=manager, password=self.pw, is_staff=is_admin, is_superuser=is_admin,
                    contact_info=f"+66 8{self.rng.randint(0, 9)} {self.rng.randint(100, 999)} {self.rng.randint(1000, 9999)}",
                    **extra)

    def people(self, top):
        it_lead = User.objects.bulk_create([self.user("EMP-IT01", Role.ADMIN, "Head of IT", top)])[0]
        it_admins = [it_lead] + User.objects.bulk_create([
            self.user(f"EMP-IT{i:02d}", Role.ADMIN, self.rng.choice(["IT Administrator", "System Administrator",
                                                                      "Network Administrator"]), it_lead)
            for i in range(2, 11)
        ])
        depts = list(DEPARTMENTS)
        heads = User.objects.bulk_create([
            self.user(f"MGR-{i + 1:03d}", Role.MANAGER, f"Head of {d}", top, newsletter_publisher=True)
            for i, d in enumerate(depts)
        ])
        mgr_rows, n = [], len(heads)
        for di, dept in enumerate(depts):
            for team in TEAM_NAMES[dept]:
                n += 1
                u = self.user(f"MGR-{n:03d}", Role.MANAGER, f"{team} Manager", heads[di])
                u._dept, u._team = dept, team
                mgr_rows.append(u)
        managers = User.objects.bulk_create(mgr_rows)  # 80 team managers -> 85 managers in total
        for m, src in zip(managers, mgr_rows):
            m._dept, m._team = src._dept, src._team

        emp_rows, teams = [], {}
        for i in range(2000):
            m = managers[i % len(managers)]
            u = self.user(f"EMP-{10001 + i}", Role.EMPLOYEE, self.rng.choice(DEPARTMENTS[m._dept]), m)
            emp_rows.append(u)
        employees = User.objects.bulk_create(emp_rows, batch_size=500)
        for e in employees:
            teams.setdefault(e.manager_id, []).append(e)
        self.mgr_by_pk = {m.pk: m for m in managers}
        self.stdout.write(f"  people: {len(it_admins)} IT admins, {len(heads) + len(managers)} managers, "
                          f"{len(employees)} employees")
        return it_admins, heads, managers, teams

    def statuses(self, teams):
        everyone = [e for team in teams.values() for e in team]
        chosen = self.rng.sample(everyone, 350)
        for u in chosen:
            u.description = self.rng.choice(STATUS_LINES)
        User.objects.bulk_update(chosen, ["description"], batch_size=500)
        self.stdout.write(f"  profile status updates: {len(chosen)}")

    # ------------------------------------------------------------------ leaves + OT
    def working_days(self, start, end):
        holidays = set(Holiday.objects.values_list("date", flat=True))
        d, out = start, []
        while d <= end:
            if d.weekday() < 5 and d not in holidays:
                out.append(d)
            d += timedelta(days=1)
        return out

    def leaves(self, teams):
        types = {t.code: t for t in LeaveType.objects.filter(is_active=True)}
        weighted = [c for c, w in (("AL", 6), ("SL", 3), ("PL", 1)) for _ in range(w) if c in types] or list(types)
        days = self.working_days(self.today - timedelta(days=45), self.today + timedelta(days=75))
        apps, day_rows, notes = [], [], []
        on_leave = set()
        for mgr_pk, team in teams.items():
            mgr = self.mgr_by_pk[mgr_pk]
            for person in self.rng.sample(team, 6):  # 6 per team -> 480 requests
                lt = types[self.rng.choice(weighted)]
                i = self.rng.randrange(len(days) - 3)
                span = days[i:i + self.rng.choice([1, 1, 2, 3])]
                span = [d for d in span if d.year == span[0].year]
                partial = lt.allow_hourly and len(span) == 1 and self.rng.random() < 0.3
                windows = [(time(9), time(13)) if partial else (time(9), time(17)) for _ in span]
                hours = sum(Decimal((e.hour - s.hour)) for s, e in windows)
                future = span[0] >= self.today
                r = self.rng.random()
                status = (LeaveApplication.Status.PENDING if future and r < 0.5 else
                          LeaveApplication.Status.REJECTED if r > 0.9 else LeaveApplication.Status.APPROVED)
                alt = self.rng.choice([p for p in team if p.pk != person.pk and p.pk not in on_leave])
                on_leave.add(person.pk)
                decided = status != LeaveApplication.Status.PENDING
                app = LeaveApplication(
                    applicant=person, leave_type=lt, is_hourly=partial, start_date=span[0], end_date=span[-1],
                    start_time=windows[0][0] if len(span) == 1 else None,
                    end_time=windows[0][1] if len(span) == 1 else None,
                    total_hours=hours, reason=self.rng.choice(LEAVE_REASONS), alternate_employee=alt, status=status,
                    reviewed_by=mgr if decided else None, reviewed_at=self.now if decided else None,
                    review_comment=("Enjoy!" if status == LeaveApplication.Status.APPROVED else
                                    "Team is short-staffed that week, please pick other dates.") if decided else "",
                )
                app._span, app._windows = span, windows
                apps.append(app)
        LeaveApplication.objects.bulk_create(apps, batch_size=500)
        for app in apps:
            for d, (s, e) in zip(app._span, app._windows):
                day_rows.append(LeaveDay(application=app, date=d, start_time=s, end_time=e,
                                         hours=Decimal(e.hour - s.hour)))
            if app.status == LeaveApplication.Status.PENDING:
                notes.append(Notification(recipient_id=app.applicant.manager_id,
                                          title=f"Leave request from {app.applicant.full_name}",
                                          message=f"{app.leave_type.name}: {app.period_display}", url=reverse("leaves:team")))
            else:
                notes.append(Notification(recipient=app.applicant, is_read=self.rng.random() < 0.6,
                                          title=f"Leave {app.status}: {app.leave_type.name}",
                                          message=f"Your request for {app.period_display} was {app.status}.",
                                          url=app.applicant.get_absolute_url() + "?tab=leaves"))
        LeaveDay.objects.bulk_create(day_rows, batch_size=1000)
        Notification.objects.bulk_create(notes, batch_size=1000)
        by = {s: sum(a.status == s for a in apps) for s in LeaveApplication.Status.values}
        self.stdout.write(f"  leave requests: {len(apps)} ({by})")

    def overtime(self, teams):
        days = self.working_days(self.today - timedelta(days=28), self.today + timedelta(days=30))
        rows, notes = [], []
        for mgr_pk, team in teams.items():
            mgr = self.mgr_by_pk[mgr_pk]
            for person in self.rng.sample(team, 5):  # 5 per team -> 400 requests
                for d in self.rng.sample(days, self.rng.choice([1, 1, 2])):
                    start = self.rng.choice([time(17, 30), time(18), time(18, 30)])
                    length = self.rng.choice([1, 2, 2, 3, 4])
                    end = (datetime.combine(d, start) + timedelta(hours=length)).time()
                    r = self.rng.random()
                    status = (OvertimeRequest.Status.PENDING if (d >= self.today and r < 0.6) or r < 0.25 else
                              OvertimeRequest.Status.REJECTED if r > 0.9 else OvertimeRequest.Status.APPROVED)
                    decided = status != OvertimeRequest.Status.PENDING
                    rows.append(OvertimeRequest(
                        applicant=person, date=d, start_time=start, end_time=end, hours=Decimal(length),
                        reason=self.rng.choice(OT_REASONS), status=status,
                        reviewed_by=mgr if decided else None, reviewed_at=self.now if decided else None,
                    ))
                    if status == OvertimeRequest.Status.PENDING:
                        notes.append(Notification(recipient=mgr, title=f"OT request from {person.full_name}",
                                                  message=f"{rows[-1].period_display} ({length} h)",
                                                  url=reverse("leaves:team") + "#overtime"))
        OvertimeRequest.objects.bulk_create(rows, batch_size=500)
        Notification.objects.bulk_create(notes, batch_size=1000)
        by = {s: sum(o.status == s for o in rows) for s in OvertimeRequest.Status.values}
        self.stdout.write(f"  OT requests: {len(rows)} ({by})")

    # ------------------------------------------------------------------ IT support
    def tickets(self, teams, it_admins):
        everyone = [e for team in teams.values() for e in team]
        rows = []
        for person in self.rng.sample(everyone, 150):
            subject, body = self.rng.choice(TICKETS)
            rows.append(SupportRequest(requester=person, subject=subject, description=body,
                                       status=self.rng.choice(SupportRequest.Status.values)))
        SupportRequest.objects.bulk_create(rows)
        Notification.objects.bulk_create([
            Notification(recipient=t.requester, title=f"IT support: {t.get_status_display()}",
                         message=f"Your request “{t.subject}” is now: {t.get_status_display()}.",
                         url=reverse("support:create"))
            for t in rows if t.status != SupportRequest.Status.RECEIVED
        ])
        by = {s: sum(t.status == s for t in rows) for s in SupportRequest.Status.values}
        self.stdout.write(f"  IT support tickets: {len(rows)} ({by})")

    # ------------------------------------------------------------------ newsletter groups + pinned posts
    def groups(self, top, managers, teams):
        existing = {n.lower() for n in NewsGroup.objects.values_list("name", flat=True)}
        chosen = [m for m in managers if f"{m._team} Team".lower() not in existing][::4][:20]
        groups = NewsGroup.objects.bulk_create([
            NewsGroup(name=f"{m._team} Team", manager=m, created_by=top,
                      description=f"{m._dept} · updates, shift plans and photos for the {m._team} team")
            for m in chosen
        ])
        everyone = [e for team in teams.values() for e in team]
        members, requests, posts = [], [], []
        for g, m in zip(groups, chosen):
            team = teams[m.pk]
            for p in team:
                members.append(GroupMembership(group=g, user=p, added_by=m))
            outsiders = [p for p in self.rng.sample(everyone, 6) if p.manager_id != m.pk][:3]
            for p in outsiders:
                requests.append(GroupAccessRequest(group=g, user=p, message="I work closely with this team."))
            for title in (f"{m._team}: weekly update", f"{m._team}: shift plan for next week"):
                posts.append(Post(title=title, author=m, group=g,
                                  body="Hi team,\nHere is the latest from our side. Questions go in the comments."))
        GroupMembership.objects.bulk_create(members, batch_size=1000)
        GroupAccessRequest.objects.bulk_create(requests)

        pinned_now = Post.objects.filter(is_pinned=True).count()
        for title, body in PINNED[: max(10 - pinned_now - 1, 0)]:  # company-wide pinned posts
            posts.append(Post(title=title, body=body, author=top, is_pinned=True))
        if pinned_now + len([p for p in posts if p.is_pinned]) < 10:  # plus one pinned post inside a group
            posts.append(Post(title=f"{chosen[0]._team}: team rules (pinned)", author=chosen[0], group=groups[0],
                              is_pinned=True, body="Please read before posting: be kind, keep it work related."))
        posts = Post.objects.bulk_create(posts)
        comments = []
        for post in posts:
            pool = teams.get(post.author_id) or self.rng.sample(everyone, 5)
            for p in self.rng.sample(pool, min(3, len(pool))):
                comments.append(Comment(post=post, author=p, body=self.rng.choice(
                    ["Thanks for sharing!", "Noted, thank you.", "Great news!", "Will do.", "See you there."])))
        Comment.objects.bulk_create(comments, batch_size=1000)
        self.stdout.write(f"  newsletter: {len(groups)} groups, {len(members)} memberships, {len(requests)} pending "
                          f"access requests, {len(posts)} posts ({Post.objects.filter(is_pinned=True).count()} pinned "
                          f"in total), {len(comments)} comments")
