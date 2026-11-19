from datetime import time
from decimal import Decimal

from django.urls import reverse

from notifications.models import Notification

from .models import LeaveApplication, OvertimeRequest
from .test_overtime_alternate import MON, TUE, Base

S = LeaveApplication.Status


class BulkApproveTests(Base):
    def leave(self, who, day=MON, hours="8"):
        return LeaveApplication.objects.create(applicant=who, leave_type=self.al, start_date=day, end_date=day,
                                               total_hours=Decimal(hours), alternate_employee=self.admin)

    def ot(self, who, day=MON):
        return OvertimeRequest.objects.create(applicant=who, date=day, start_time=time(18), end_time=time(20),
                                              hours=Decimal("2"), reason="backlog")

    def test_manager_approves_all_pending_leaves(self):
        a, b = self.leave(self.emp), self.leave(self.peer, TUE)
        self.client.force_login(self.mgr)
        r = self.client.post(reverse("leaves:review_all"), {"ids": [a.pk, b.pk], "comment": "ok"})
        self.assertRedirects(r, reverse("leaves:team"), fetch_redirect_response=False)
        for app in (a, b):
            app.refresh_from_db()
            self.assertEqual((app.status, app.reviewed_by, app.review_comment), (S.APPROVED, self.mgr, "ok"))
        self.assertTrue(Notification.objects.filter(recipient=self.emp, title__startswith="Leave approved").exists())

    def test_manager_approves_all_pending_ot(self):
        a, b = self.ot(self.emp), self.ot(self.peer)
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:overtime_review_all"), {"ids": [a.pk, b.pk]})
        self.assertEqual(set(OvertimeRequest.objects.values_list("status", flat=True)), {S.APPROVED})

    def test_only_listed_ids_and_only_own_team(self):
        mine, later = self.leave(self.emp), self.leave(self.peer, TUE)
        outsider = self.leave(self.stranger_mgr)          # not below self.mgr
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:review_all"), {"ids": [mine.pk, outsider.pk, "junk"]})
        statuses = dict(LeaveApplication.objects.values_list("pk", "status"))
        self.assertEqual(statuses[mine.pk], S.APPROVED)
        self.assertEqual(statuses[later.pk], S.PENDING)    # not listed -> untouched
        self.assertEqual(statuses[outsider.pk], S.PENDING)  # not allowed -> untouched

    def test_one_failure_does_not_block_the_rest(self):
        ok, too_big = self.leave(self.emp), self.leave(self.peer, TUE, hours="500")
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:review_all"), {"ids": [too_big.pk, ok.pk]})
        ok.refresh_from_db(); too_big.refresh_from_db()
        self.assertEqual((ok.status, too_big.status), (S.APPROVED, S.PENDING))

    def test_employee_and_get_refused(self):
        a = self.leave(self.peer)
        self.client.force_login(self.emp)
        self.assertEqual(self.client.post(reverse("leaves:review_all"), {"ids": [a.pk]}).status_code, 403)
        self.assertEqual(self.client.post(reverse("leaves:overtime_review_all"), {"ids": [a.pk]}).status_code, 403)
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("leaves:review_all")).status_code, 405)
        a.refresh_from_db()
        self.assertEqual(a.status, S.PENDING)

    def test_team_page_shows_approve_all(self):
        self.leave(self.emp); self.leave(self.peer, TUE); self.ot(self.emp); self.ot(self.peer)
        self.client.force_login(self.mgr)
        html = self.client.get(reverse("leaves:team")).content.decode()
        self.assertIn(reverse("leaves:review_all"), html)
        self.assertIn(reverse("leaves:overtime_review_all"), html)
        self.assertIn("Approve all (2)", html)


class TeamPaginationTests(Base):
    def leave(self, who, day=MON):
        return LeaveApplication.objects.create(applicant=who, leave_type=self.al, start_date=day, end_date=day,
                                               total_hours=Decimal("8"), alternate_employee=self.admin)

    def test_pending_leaves_are_paginated(self):
        from datetime import timedelta

        from . import views

        apps = [self.leave(self.emp, MON + timedelta(days=7 * i)) for i in range(views.TEAM_PENDING_PER_PAGE + 3)]
        self.client.force_login(self.mgr)
        r = self.client.get(reverse("leaves:team"))
        self.assertEqual(len(r.context["pending"]), len(apps))
        self.assertEqual(len(r.context["pending_page"].object_list), views.TEAM_PENDING_PER_PAGE)
        self.assertContains(r, "Page 1 / 2")
        self.assertContains(r, "?lp=2#pending")
        self.assertContains(r, f"Approve all ({len(apps)})")
        self.assertContains(r, f"Approve this page ({views.TEAM_PENDING_PER_PAGE})")
        r = self.client.get(reverse("leaves:team"), {"lp": 2, "op": 1})
        self.assertEqual(len(r.context["pending_page"].object_list), 3)
        self.assertContains(r, "op=1")                       # other lists' page numbers are kept in the links
        self.assertEqual(self.client.get(reverse("leaves:team"), {"lp": "junk"}).status_code, 200)

    def test_approve_this_page_only_touches_page_ids(self):
        a, b = self.leave(self.emp), self.leave(self.peer, TUE)
        self.client.force_login(self.mgr)
        self.client.post(reverse("leaves:review_all"), {"scope": "page", "ids": [a.pk, b.pk], "page_ids": [a.pk]})
        a.refresh_from_db(); b.refresh_from_db()
        self.assertEqual((a.status, b.status), (S.APPROVED, S.PENDING))

    def test_balances_filter(self):
        self.client.force_login(self.mgr)
        r = self.client.get(reverse("leaves:team"), {"q": self.emp.employee_id})
        self.assertEqual([m.pk for m, _ in r.context["team_rows"]], [self.emp.pk])
