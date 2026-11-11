from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role, User
from notifications.models import Notification

from .models import LeaveApplication, LeaveType, OvertimeRequest

PW = "S3cure-pass-Word!"
MON, TUE = date(2027, 3, 1), date(2027, 3, 2)


def mk(eid, name, role, mgr=None):
    return User.objects.create_user(eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.emp = mk("EMP-101", "Erin Employee", Role.EMPLOYEE, cls.mgr)
        cls.peer = mk("EMP-102", "Pat Peer", Role.EMPLOYEE, cls.mgr)
        cls.stranger_mgr = mk("EMP-200", "Max Manager", Role.MANAGER, cls.admin)
        cls.al = LeaveType.objects.create(name="Annual", code="al", annual_quota_days=Decimal("10"), allow_hourly=True)


class AlternateEmployeeTests(Base):
    def post(self, **over):
        data = {"leave_type": self.al.pk, "start_date": MON, "end_date": MON, "reason": "trip",
                "alternate_employee": self.peer.pk,
                "day_date": [MON.isoformat()], "day_start": ["09:00"], "day_end": ["17:00"]}
        data.update(over)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(reverse("leaves:apply"), data)

    def test_alternate_required(self):
        self.client.force_login(self.emp)
        for value in (None, ""):
            r = self.post(alternate_employee=value)
            self.assertEqual(r.status_code, 200)
            self.assertIn("alternate_employee", r.context["form"].errors)
        self.assertFalse(LeaveApplication.objects.exists())

    def test_cannot_pick_self_or_inactive_or_unknown(self):
        self.client.force_login(self.emp)
        User.objects.filter(pk=self.peer.pk).update(is_active=False)
        for pk in (self.emp.pk, self.peer.pk, 99999, "abc"):
            self.assertEqual(self.post(alternate_employee=pk).status_code, 200)
        self.assertFalse(LeaveApplication.objects.exists())

    def test_alternate_on_leave_is_rejected(self):
        self.client.force_login(self.peer)
        self.assertEqual(self.post(alternate_employee=self.stranger_mgr.pk).status_code, 302)   # peer is now away on MON
        self.client.force_login(self.emp)
        r = self.post(alternate_employee=self.peer.pk)
        self.assertEqual(r.status_code, 200)
        self.assertIn("already on leave", str(r.context["form"].non_field_errors()))
        self.assertEqual(LeaveApplication.objects.filter(applicant=self.emp).count(), 0)

    def test_saved_notified_on_approval_and_shown_to_manager(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.post().status_code, 302)
        app = LeaveApplication.objects.get()
        self.assertEqual(app.alternate_employee, self.peer)
        self.assertFalse(Notification.objects.filter(recipient=self.peer).exists())  # not before approval
        self.client.force_login(self.mgr)
        page = self.client.get(reverse("leaves:team"))
        self.assertContains(page, "Pat Peer")
        self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "approve"})
        self.assertTrue(Notification.objects.filter(recipient=self.peer, title__icontains="covering").exists())

    def test_rejection_does_not_notify_alternate(self):
        self.client.force_login(self.emp)
        self.post()
        app = LeaveApplication.objects.get()
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:review", args=[app.pk]), {"decision": "reject"})
        self.assertFalse(Notification.objects.filter(recipient=self.peer).exists())

    def test_invalid_review_decision_is_400(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.post(reverse("leaves:review", args=[1]), {"decision": "x"}).status_code, 400)


class OvertimeTests(Base):
    def ot(self, day=None, start="18:00", end="21:00", reason="Release", **over):
        day = day or timezone.localdate()
        data = {"date": day, "start_time": start, "end_time": end, "reason": reason}
        data.update(over)
        return self.client.post(reverse("leaves:overtime"), data)

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("leaves:overtime")).status_code, 302)
        self.assertEqual(self.client.post(reverse("leaves:overtime_review", args=[1]), {"decision": "approve"}).status_code, 302)

    def test_submit_calculates_hours_and_notifies_manager(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.ot().status_code, 302)
        o = OvertimeRequest.objects.get()
        self.assertEqual(o.hours, Decimal("3.00"))
        self.assertEqual(o.status, "pending")
        self.assertTrue(Notification.objects.filter(recipient=self.mgr, title__icontains="OT").exists())

    def test_client_cannot_set_hours_or_status(self):
        self.client.force_login(self.emp)
        self.ot(hours="99", status="approved", applicant=self.admin.pk)
        o = OvertimeRequest.objects.get()
        self.assertEqual((o.hours, o.status, o.applicant), (Decimal("3.00"), "pending", self.emp))

    def test_validation(self):
        self.client.force_login(self.emp)
        today = timezone.localdate()
        bad = [
            dict(end="17:00"),                                    # end before start
            dict(end="18:00"),                                    # zero
            dict(start="06:00", end="20:00"),                     # 14 h > cap
            dict(reason="   "),
            dict(day=today - timedelta(days=400)),
            dict(day=today + timedelta(days=400)),
            dict(day="not-a-date"),
        ]
        for kw in bad:
            self.assertEqual(self.ot(**kw).status_code, 200, kw)
        self.assertFalse(OvertimeRequest.objects.exists())

    def test_overlap_and_daily_cap(self):
        self.client.force_login(self.emp)
        self.assertEqual(self.ot(start="18:00", end="20:00").status_code, 302)
        self.assertEqual(self.ot(start="19:00", end="21:00").status_code, 200)       # overlaps
        self.assertEqual(self.ot(start="20:00", end="23:00").status_code, 302)       # adjacent ok (5 h total)
        self.assertEqual(self.ot(start="04:00", end="12:00").status_code, 200)       # 5+8 > 12
        self.assertEqual(OvertimeRequest.objects.count(), 2)

    def test_overlap_with_leave_is_blocked(self):
        from .models import LeaveDay
        today = timezone.localdate()
        app = LeaveApplication.objects.create(applicant=self.emp, leave_type=self.al, start_date=today, end_date=today,
                                              total_hours=Decimal("8"), reason="x", status="approved", alternate_employee=self.peer)
        LeaveDay.objects.create(application=app, date=today, start_time="09:00", end_time="17:00", hours=8)
        self.client.force_login(self.emp)
        self.assertEqual(self.ot(start="16:00", end="18:00").status_code, 200)
        self.assertEqual(self.ot(start="17:00", end="19:00").status_code, 302)

    def _make(self, who=None):
        return OvertimeRequest.objects.create(applicant=who or self.emp, date=timezone.localdate(),
                                              start_time="18:00", end_time="20:00", hours=Decimal("2"), reason="r")

    def test_manager_approves_and_employee_is_notified(self):
        o = self._make()
        self.client.force_login(self.mgr)
        self.assertContains(self.client.get(reverse("leaves:team")), "Erin Employee")
        r = self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "approve", "comment": "ok"})
        self.assertEqual(r.status_code, 302)
        o.refresh_from_db()
        self.assertEqual((o.status, o.reviewed_by, o.review_comment), ("approved", self.mgr, "ok"))
        self.assertTrue(Notification.objects.filter(recipient=self.emp, title="OT approved").exists())
        # cannot be decided twice
        self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "reject"})
        o.refresh_from_db()
        self.assertEqual(o.status, "approved")

    def test_reject(self):
        o = self._make()
        self.client.force_login(self.admin)
        self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "reject"})
        o.refresh_from_db()
        self.assertEqual(o.status, "rejected")

    def test_unauthorised_people_cannot_review(self):
        o = self._make()
        for user in (self.emp, self.peer, self.stranger_mgr):
            self.client.force_login(user)
            r = self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "approve"})
            o.refresh_from_db()
            self.assertEqual(o.status, "pending", user)
            self.assertIn(r.status_code, (302, 403))
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "bogus"}).status_code, 400)
        self.assertEqual(self.client.get(reverse("leaves:overtime_review", args=[o.pk])).status_code, 405)
        self.assertEqual(self.client.post(reverse("leaves:overtime_review", args=[9999]), {"decision": "approve"}).status_code, 404)

    def test_cannot_approve_own_overtime(self):
        o = self._make(self.mgr)
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:overtime_review", args=[o.pk]), {"decision": "approve"})
        o.refresh_from_db()
        self.assertEqual(o.status, "pending")

    def test_cancel_only_by_owner_and_only_pending(self):
        o = self._make()
        self.client.force_login(self.peer)
        self.client.post(reverse("leaves:overtime_cancel", args=[o.pk]))
        o.refresh_from_db()
        self.assertEqual(o.status, "pending")
        self.client.force_login(self.emp)
        self.client.post(reverse("leaves:overtime_cancel", args=[o.pk]), {"next": "https://evil.example/"})
        o.refresh_from_db()
        self.assertEqual(o.status, "cancelled")

    def test_reason_is_escaped(self):
        self.client.force_login(self.emp)
        self.ot(reason="<script>alert(1)</script>")
        page = self.client.get(reverse("leaves:overtime"))
        self.assertNotContains(page, "<script>alert(1)</script>")

    def test_csv_contains_overtime_and_neutralises_formulas(self):
        o = self._make()
        OvertimeRequest.objects.filter(pk=o.pk).update(reason="=HYPERLINK(1)")
        self.client.force_login(self.mgr)
        body = self.client.get(reverse("leaves:employee_download", args=[self.emp.employee_id])).content.decode()
        self.assertIn("OVERTIME (OT)", body)
        self.assertIn("'=HYPERLINK(1)", body)
