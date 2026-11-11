from datetime import date, time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import Role, User
from notifications.models import Notification

from .models import Holiday, LeaveApplication, LeavePolicy, LeaveType
from .utils import calculate_leave_hours, count_working_days, hourly_duration

PW = "S3cure-pass-Word!"
MON, TUE, WED, THU, SAT = (date(2027, 3, d) for d in (1, 2, 3, 4, 6))


class UtilsTests(SimpleTestCase):
    def test_working_days_skip_weekend_and_holidays(self):
        self.assertEqual(count_working_days(MON, date(2027, 3, 8)), 6)  # Mon..next Mon
        self.assertEqual(count_working_days(MON, date(2027, 3, 8), holidays={TUE}), 5)
        self.assertEqual(count_working_days(SAT, date(2027, 3, 7)), 0)

    def test_hours(self):
        self.assertEqual(hourly_duration(time(9, 0), time(11, 30)), Decimal("2.50"))
        self.assertEqual(hourly_duration(time(11), time(9)), Decimal("0.00"))
        self.assertEqual(calculate_leave_hours(MON, WED), Decimal("24.00"))
        self.assertEqual(calculate_leave_hours(MON, MON, hourly=True, start_time=time(9), end_time=time(10)), Decimal("1.00"))
        self.assertEqual(calculate_leave_hours(SAT, SAT, hourly=True, start_time=time(9), end_time=time(10)), Decimal("0.00"))


class LeaveFlow(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = lambda eid, name, role, mgr=None: User.objects.create_user(  # noqa: E731
            eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr)
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.emp = mk("EMP-101", "Erin Employee", Role.EMPLOYEE, cls.mgr)
        cls.other_mgr = mk("EMP-200", "Max Manager", Role.MANAGER, cls.admin)
        cls.al = LeaveType.objects.create(name="Annual", code="al", annual_quota_days=Decimal("10"), allow_hourly=True)
        cls.pl = LeaveType.objects.create(name="Personal", code="pl", annual_quota_days=Decimal("3"), allow_hourly=False)

    def apply(self, days=None, **data):
        """POST the apply form. ``days`` = [(date, "HH:MM", "HH:MM"), ...] - defaults to Monday 09:00-17:00."""
        days = days if days is not None else [(MON, "09:00", "17:00")]
        base = {"leave_type": self.al.pk, "start_date": days[0][0] if days else MON,
                "end_date": days[-1][0] if days else MON, "reason": "trip",
                "day_date": [d[0].isoformat() for d in days],
                "day_start": [d[1] for d in days], "day_end": [d[2] for d in days]}
        base.update(data)
        base = {k: v for k, v in base.items() if v is not None}
        return self.client.post(reverse("leaves:apply"), base)

    def full(self, *dates):
        return [(d, "09:00", "17:00") for d in dates]

    def test_reason_required_and_not_just_whitespace(self):
        self.client.force_login(self.emp)
        for reason in ("", "   ", None):
            response = self.apply(reason=reason)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors.get("reason"))
        self.assertFalse(LeaveApplication.objects.exists())

    def test_apply_notifies_manager(self):
        self.client.force_login(self.emp)
        resp = self.apply(self.full(MON, TUE))
        self.assertEqual(resp.status_code, 302)
        app = LeaveApplication.objects.get()
        self.assertEqual((app.status, app.total_hours), ("pending", Decimal("16.00")))
        self.assertEqual(app.days.count(), 2)
        note = Notification.objects.get(recipient=self.mgr)
        self.assertIn("Erin Employee", note.title)
        self.assertFalse(Notification.objects.filter(recipient=self.other_mgr).exists())

    def test_each_day_keeps_its_own_time(self):
        self.client.force_login(self.emp)
        self.apply([(MON, "09:00", "11:00"), (TUE, "13:00", "17:00")])
        app = LeaveApplication.objects.get()
        self.assertEqual(app.total_hours, Decimal("6.00"))
        self.assertEqual([(d.date, d.hours) for d in app.days.all()], [(MON, Decimal("2.00")), (TUE, Decimal("4.00"))])
        self.assertTrue(app.is_hourly)

    def test_every_working_day_needs_a_time(self):
        self.client.force_login(self.emp)
        resp = self.apply(self.full(MON), start_date=MON, end_date=TUE)        # TUE has no row
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Set the time for every working day")
        self.assertFalse(LeaveApplication.objects.exists())

    def test_admin_daily_limit_is_enforced(self):
        policy = LeavePolicy.load()
        policy.max_hours_per_day = Decimal("6")
        policy.save()
        self.client.force_login(self.emp)
        resp = self.apply([(MON, "09:00", "16:00")])                            # 7 h > 6 h
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "allowed by the admin")
        self.assertFalse(LeaveApplication.objects.exists())
        self.assertEqual(self.apply([(MON, "09:00", "15:00")]).status_code, 302)  # exactly 6 h is fine

    def test_leave_type_can_override_daily_limit(self):
        self.al.max_hours_per_day = Decimal("4")
        self.al.save()
        self.client.force_login(self.emp)
        self.assertEqual(self.apply([(MON, "09:00", "14:00")]).status_code, 200)   # 5 h > 4 h
        self.assertEqual(self.apply([(MON, "09:00", "13:00")]).status_code, 302)

    def test_hourly_flow_and_overlap(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.apply([(MON, "09:00", "11:00")]).status_code, 302)
        self.assertEqual(self.apply([(MON, "11:00", "12:30")]).status_code, 302)
        resp = self.apply([(MON, "10:00", "10:30")])                              # overlaps the first
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "overlaps")
        self.assertEqual(LeaveApplication.objects.count(), 2)
        self.assertEqual(sum(a.total_hours for a in LeaveApplication.objects.all()), Decimal("3.50"))

    def test_partial_day_blocked_for_full_day_only_type(self):
        self.client.force_login(self.emp)
        resp = self.apply([(MON, "09:00", "10:00")], leave_type=self.pl.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "full day")
        self.assertFalse(LeaveApplication.objects.exists())
        self.assertEqual(self.apply([(MON, "09:00", "17:00")], leave_type=self.pl.pk).status_code, 302)

    def test_end_before_start_time_rejected(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.apply([(MON, "12:00", "10:00")]).status_code, 200)
        self.assertFalse(LeaveApplication.objects.exists())

    def test_weekend_row_and_garbage_rejected(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.apply(self.full(SAT), start_date=SAT, end_date=SAT).status_code, 200)   # no working day
        resp = self.apply(self.full(MON, SAT), start_date=MON, end_date=TUE)                       # SAT not in range
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(reverse("leaves:apply"), {
            "leave_type": self.al.pk, "start_date": MON, "end_date": MON,
            "day_date": ["not-a-date"], "day_start": ["xx"], "day_end": ["yy"]})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LeaveApplication.objects.exists())

    def test_too_many_days_rejected(self):
        self.client.force_login(self.emp)
        resp = self.apply(self.full(MON), start_date=MON, end_date=date(2027, 12, 1))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(LeaveApplication.objects.exists())

    def test_balance_and_holiday_validation(self):
        self.client.force_login(self.emp)
        four = self.full(MON, TUE, WED, THU)
        self.assertEqual(self.apply(four, leave_type=self.pl.pk).status_code, 200)   # 4 d > 3 d quota
        Holiday.objects.create(date=MON, name="Holiday")
        self.assertEqual(self.apply(self.full(MON)).status_code, 200)                # only a holiday
        self.assertFalse(LeaveApplication.objects.exists())

    def test_admin_policy_page_is_admin_only(self):
        url = reverse("leaves:policy")
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.emp)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        resp = self.client.post(url, {"max_hours_per_day": "6.5", "default_start_time": "08:30"})
        self.assertEqual(resp.status_code, 302)
        policy = LeavePolicy.load()
        self.assertEqual((policy.max_hours_per_day, policy.updated_by), (Decimal("6.50"), self.admin))
        self.assertEqual(self.client.post(url, {"max_hours_per_day": "30", "default_start_time": "09:00"}).status_code, 200)

    def test_apply_page_shows_daily_limit(self):
        self.client.force_login(self.emp)
        self.assertContains(self.client.get(reverse("leaves:apply")), "per day")

    def test_legacy_application_without_day_rows_still_blocks_overlap(self):
        LeaveApplication.objects.create(applicant=self.emp, leave_type=self.al, start_date=MON, end_date=MON,
                                        total_hours=Decimal("8"), status="approved")
        self.client.force_login(self.emp)
        self.assertEqual(self.apply(self.full(MON)).status_code, 200)

    def test_manager_approves_and_employee_notified(self):
        self.client.force_login(self.emp)
        self.apply()
        app = LeaveApplication.objects.get()
        self.client.force_login(self.mgr)
        resp = self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "approve", "comment": "Enjoy"})
        self.assertEqual(resp.status_code, 302)
        app.refresh_from_db()
        self.assertEqual((app.status, app.reviewed_by), ("approved", self.mgr))
        note = Notification.objects.get(recipient=self.emp)
        self.assertIn("approved", note.title.lower())

    def test_reject_notifies_employee(self):
        self.client.force_login(self.emp)
        self.apply()
        app = LeaveApplication.objects.get()
        self.client.force_login(self.admin)
        self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "reject"})
        app.refresh_from_db()
        self.assertEqual(app.status, "rejected")
        self.assertIn("rejected", Notification.objects.get(recipient=self.emp).title.lower())

    def test_unauthorised_reviewers(self):
        self.client.force_login(self.emp)
        self.apply()
        app = LeaveApplication.objects.get()
        for who in (self.other_mgr, self.emp):
            self.client.force_login(who)
            self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "approve"})
            app.refresh_from_db()
            self.assertEqual(app.status, "pending", who.full_name)

    def test_employee_cannot_open_team_page(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.client.get(reverse("leaves:team")).status_code, 403)
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("leaves:team")).status_code, 200)

    def test_only_admin_defines_standard_leaves(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("leaves:type_create")).status_code, 403)
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("leaves:type_create"), {
            "name": "Study", "code": "st", "annual_quota_days": "2", "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(LeaveType.objects.filter(code="ST").exists())

    def test_cancel_own_pending(self):
        self.client.force_login(self.emp)
        self.apply()
        app = LeaveApplication.objects.get()
        self.client.post(reverse("leaves:cancel", args=[app.pk]))
        app.refresh_from_db()
        self.assertEqual(app.status, "cancelled")
