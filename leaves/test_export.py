from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

from .models import LeaveApplication, LeaveType

PW = "S3cure-pass-Word!"


class LeaveExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = lambda eid, name, role, mgr=None: User.objects.create_user(  # noqa: E731
            eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr)
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.emp = mk("EMP-101", "Erin Employee", Role.EMPLOYEE, cls.mgr)
        cls.grand = mk("EMP-102", "Gus Grand", Role.EMPLOYEE, cls.emp)
        cls.other_mgr = mk("EMP-200", "Max Manager", Role.MANAGER, cls.admin)
        cls.other_emp = mk("EMP-201", "Olly Other", Role.EMPLOYEE, cls.other_mgr)
        cls.al = LeaveType.objects.create(name="Annual", code="AL", annual_quota_days=Decimal("10"))
        LeaveApplication.objects.create(
            applicant=cls.emp, leave_type=cls.al, start_date=date(2027, 3, 1), end_date=date(2027, 3, 1),
            total_hours=Decimal("8"), status=LeaveApplication.Status.APPROVED, reason="=HYPERLINK(\"http://evil\")")
        LeaveApplication.objects.create(
            applicant=cls.emp, leave_type=cls.al, start_date=date(2027, 3, 8), end_date=date(2027, 3, 8),
            total_hours=Decimal("8"), status=LeaveApplication.Status.PENDING, reason="Trip")

    def get(self, viewer, target, **params):
        self.client.force_login(viewer)
        url = reverse("leaves:employee_download", args=[target.employee_id])
        return self.client.get(url, params)

    def test_admin_can_download_anyone(self):
        r = self.get(self.admin, self.emp, year=2027)
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn("leaves_EMP-101_2027.csv", r["Content-Disposition"])
        self.assertEqual(self.get(self.admin, self.other_emp, year=2027).status_code, 200)

    def test_manager_can_download_direct_and_indirect_reports(self):
        self.assertEqual(self.get(self.mgr, self.emp, year=2027).status_code, 200)
        self.assertEqual(self.get(self.mgr, self.grand, year=2027).status_code, 200)

    def test_manager_cannot_download_unrelated_employee(self):
        self.assertEqual(self.get(self.mgr, self.other_emp, year=2027).status_code, 403)
        self.assertEqual(self.get(self.mgr, self.other_mgr, year=2027).status_code, 403)

    def test_manager_cannot_download_their_own_manager(self):
        self.assertEqual(self.get(self.mgr, self.admin, year=2027).status_code, 403)

    def test_employee_is_forbidden_even_for_their_own_or_a_report(self):
        self.assertEqual(self.get(self.emp, self.emp, year=2027).status_code, 403)
        self.assertEqual(self.get(self.emp, self.grand, year=2027).status_code, 403)
        self.assertEqual(self.get(self.grand, self.emp, year=2027).status_code, 403)

    def test_anonymous_is_redirected_to_login(self):
        url = reverse("leaves:employee_download", args=[self.emp.employee_id])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])

    def test_unknown_employee_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("leaves:employee_download", args=["NOPE"])).status_code, 404)

    def test_csv_contents_and_formula_neutralised(self):
        body = self.get(self.mgr, self.emp, year=2027).content.decode("utf-8-sig")
        self.assertIn("Erin Employee", body)
        self.assertIn("EMP-101", body)
        self.assertIn("Annual", body)
        self.assertIn("Approved", body)
        self.assertIn("Pending", body)
        self.assertIn("'=HYPERLINK", body)          # prefixed, so Excel will not run it
        self.assertNotIn(',=HYPERLINK', body)

    def test_bad_year_does_not_crash(self):
        self.assertEqual(self.get(self.admin, self.emp, year="abc").status_code, 200)
        self.assertEqual(self.get(self.admin, self.emp, year="999999").status_code, 200)

    def test_buttons_visibility(self):
        self.client.force_login(self.mgr)
        page = self.client.get(reverse("leaves:team"))
        self.assertContains(page, reverse("leaves:employee_download", args=["EMP-101"]))
        self.assertNotContains(page, reverse("leaves:employee_download", args=["EMP-201"]))
        self.client.force_login(self.emp)
        page = self.client.get(self.emp.get_absolute_url() + "?tab=leaves")
        self.assertNotContains(page, "employee_download")
        self.assertNotContains(page, "/download/")


class OrgChartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("EMP-001", "a@example.com", "Alex Admin", password=PW, role=Role.ADMIN)
        cls.emp = User.objects.create_user("EMP-101", "e@example.com", "Erin", password=PW, role=Role.EMPLOYEE, manager=cls.admin)

    def test_public_chart_hides_private_data(self):
        for name in ("accounts:org_chart", "accounts:org_data"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        people = self.client.get(reverse("accounts:org_data")).json()["users"]
        self.assertFalse(any("email" in u or "contact" in u or "edit_url" in u for u in people))

    def test_page_renders(self):
        self.client.force_login(self.emp)
        self.assertContains(self.client.get(reverse("accounts:org_chart")), "org-canvas")

    def test_admin_gets_edit_links_employee_does_not(self):
        self.client.force_login(self.admin)
        users = self.client.get(reverse("accounts:org_data")).json()["users"]
        self.assertEqual(len(users), 2)
        self.assertTrue(all("edit_url" in u for u in users))
        self.client.force_login(self.emp)
        users = self.client.get(reverse("accounts:org_data")).json()["users"]
        self.assertFalse(any("edit_url" in u or "add_url" in u for u in users))
        self.assertEqual({u["employee_id"] for u in users}, {"EMP-001", "EMP-101"})

    def test_add_button_preselects_manager(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("accounts:user_create") + f"?manager={self.admin.pk}")
        self.assertEqual(r.context["form"].initial.get("manager"), self.admin.pk)
