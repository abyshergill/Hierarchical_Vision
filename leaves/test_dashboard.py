from datetime import time
from decimal import Decimal

from django.urls import reverse

from accounts.models import DashboardAccess, Role, User
from notifications.models import Notification

from .models import LeaveApplication, LeaveDay, OvertimeRequest
from .test_overtime_alternate import MON, TUE, Base, mk

S = LeaveApplication.Status


class DashboardTests(Base):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.outsider = mk("EMP-201", "Olly Outsider", Role.EMPLOYEE, cls.stranger_mgr)

    def leave(self, who, day=MON, status=S.APPROVED, hours="8", end=time(17)):
        app = LeaveApplication.objects.create(applicant=who, leave_type=self.al, start_date=day, end_date=day,
                                              total_hours=Decimal(hours), status=status, alternate_employee=self.admin)
        LeaveDay.objects.create(application=app, date=day, start_time=time(9), end_time=end, hours=Decimal(hours))
        return app

    def ot(self, who, day=MON, status=S.APPROVED):
        return OvertimeRequest.objects.create(applicant=who, date=day, start_time=time(18), end_time=time(20),
                                              hours=Decimal("2"), reason="backlog", status=status)

    def get(self, **params):
        params.setdefault("date", MON.isoformat())
        return self.client.get(reverse("leaves:dashboard"), params)

    def grant(self, user, value):
        User.objects.filter(pk=user.pk).update(leave_dashboard=value)

    def test_admin_sees_whole_company_counts(self):
        self.leave(self.emp); self.leave(self.outsider, hours="4", end=time(13))
        self.leave(self.peer, status=S.PENDING); self.leave(self.peer, day=TUE)
        self.ot(self.emp); self.ot(self.outsider, status=S.PENDING)
        self.client.force_login(self.admin)
        r = self.get()
        self.assertEqual(r.status_code, 200)
        c = r.context
        self.assertEqual((c["on_leave"], c["pending_leave_people"], c["partial"]), (2, 1, 1))
        self.assertEqual(c["leave_hours"], Decimal("12"))
        self.assertEqual((c["ot_people"], c["ot_hours"], c["ot_pending"]), (1, Decimal("2"), 1))
        self.assertEqual(c["by_type"][0]["people"], 2)
        self.assertEqual(c["leave_page"].paginator.count, 2)
        self.assertEqual(self.get(pending="1").context["leave_page"].paginator.count, 3)
        month = {m["date"]: m["leave"] for m in c["month"]}
        self.assertEqual((month[MON], month[TUE]), (2, 1))
        self.assertEqual(c["chart_data"]["leaveTypes"][0]["people"], 2)

    def test_managers_need_access(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.get().status_code, 403)
        self.client.force_login(self.emp)
        self.grant(self.emp, DashboardAccess.ALL)          # the flag means nothing for non-managers
        self.assertEqual(self.get().status_code, 403)

    def test_team_scope_only_shows_own_team(self):
        self.leave(self.emp); self.leave(self.outsider)
        self.grant(self.mgr, DashboardAccess.TEAM)
        self.client.force_login(self.mgr)
        r = self.get()
        self.assertEqual(r.context["on_leave"], 1)
        self.assertContains(r, "Erin Employee")
        self.assertNotContains(r, "Olly Outsider")
        self.assertEqual(self.get(team=self.stranger_mgr.pk).status_code, 403)   # cannot peek at another team
        self.grant(self.mgr, DashboardAccess.ALL)
        self.assertEqual(self.get().context["on_leave"], 2)
        self.assertEqual(self.get(team=self.stranger_mgr.pk).context["on_leave"], 1)

    def test_bad_params_fall_back(self):
        self.client.force_login(self.admin)
        for params in ({"date": "nope"}, {"date": "1900-01-01"}, {"team": "x"}, {"lp": "zz"}):
            self.assertEqual(self.get(**params).status_code, 200)

    def test_admin_grants_access(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("leaves:dashboard_access")).status_code, 403)
        self.client.force_login(self.admin)
        url = reverse("leaves:dashboard_access")
        self.assertContains(self.client.get(url), "Mia Manager")
        self.client.post(url, {f"access_{self.mgr.pk}": "team", f"access_{self.stranger_mgr.pk}": "bogus",
                               f"access_{self.emp.pk}": "all"})
        self.mgr.refresh_from_db(); self.stranger_mgr.refresh_from_db(); self.emp.refresh_from_db()
        self.assertEqual((self.mgr.leave_dashboard, self.stranger_mgr.leave_dashboard, self.emp.leave_dashboard),
                         ("team", "", ""))
        self.assertTrue(Notification.objects.filter(recipient=self.mgr, url=reverse("leaves:dashboard")).exists())
        self.client.force_login(self.mgr)
        self.assertEqual(self.get().status_code, 200)

    def test_tabs_show_one_table_at_a_time(self):
        self.leave(self.emp); self.ot(self.peer)
        self.client.force_login(self.admin)
        leave_tab = self.get().content.decode()
        self.assertIn("Erin Employee", leave_tab)
        self.assertNotIn("Pat Peer", leave_tab)
        ot_tab = self.get(tab="ot").content.decode()
        self.assertIn("Pat Peer", ot_tab)
        self.assertNotIn("Erin Employee", ot_tab)
        self.assertEqual(self.get(tab="junk").status_code, 200)

    def export(self, **params):
        params.setdefault("date", MON.isoformat())
        return self.client.get(reverse("leaves:dashboard_export"), params)

    def test_csv_export_leave_and_overtime(self):
        self.leave(self.emp); self.leave(self.outsider); self.leave(self.peer, status=S.PENDING)
        evil = self.ot(self.emp)
        OvertimeRequest.objects.filter(pk=evil.pk).update(reason="=HYPERLINK(\"http://x\")")
        self.client.force_login(self.admin)
        r = self.export()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("leave-2027-03-01.csv", r["Content-Disposition"])
        body = r.content.decode("utf-8-sig")
        self.assertIn("Erin Employee", body); self.assertIn("Olly Outsider", body)
        self.assertNotIn("Pat Peer", body)                         # pending is left out unless asked for
        self.assertIn("Pat Peer", self.export(pending="1").content.decode())
        ot = self.export(tab="ot").content.decode("utf-8-sig")
        self.assertIn("overtime-2027-03-01.csv", self.export(tab="ot")["Content-Disposition"])
        self.assertIn("'=HYPERLINK", ot)                           # neutralised, never a live formula
        self.assertNotIn(",=HYPERLINK", ot)

    def test_csv_export_respects_access_and_scope(self):
        self.leave(self.emp); self.leave(self.outsider)
        self.client.force_login(self.mgr)
        self.assertEqual(self.export().status_code, 403)
        self.grant(self.mgr, DashboardAccess.TEAM)
        body = self.export().content.decode("utf-8-sig")
        self.assertIn("Erin Employee", body)
        self.assertNotIn("Olly Outsider", body)
        self.assertEqual(self.export(team=self.stranger_mgr.pk).status_code, 403)
        self.client.logout()
        self.assertEqual(self.export().status_code, 302)           # anonymous -> login

    def test_page_links_to_download_with_filters(self):
        self.client.force_login(self.admin)
        r = self.get(pending="1", tab="ot")
        self.assertContains(r, reverse("leaves:dashboard_export"))
        self.assertIn("tab=ot", r.context["export_query"])
        self.assertIn("pending=1", r.context["export_query"])
        self.assertIn("date=2027-03-01", r.context["export_query"])
