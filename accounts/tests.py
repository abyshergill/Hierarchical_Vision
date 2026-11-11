from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Role, User, search_employees

PW = "S3cure-pass-Word!"


def make(eid, name, role=Role.EMPLOYEE, manager=None, **kw):
    return User.objects.create_user(
        eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=manager, **kw
    )


class BaseCase(TestCase):
    def setUp(self):
        cache.clear()  # rate-limit counters must not leak between tests

    @classmethod
    def setUpTestData(cls):
        cls.admin = make("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = make("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.emp = make("EMP-101", "Erin Employee", Role.EMPLOYEE, cls.mgr)
        cls.other_mgr = make("EMP-200", "Max Manager", Role.MANAGER, cls.admin)
        cls.outsider = make("EMP-201", "Olga Outsider", Role.EMPLOYEE, cls.other_mgr)


class ModelTests(BaseCase):
    def test_admin_role_is_superuser(self):
        self.assertTrue(self.admin.is_superuser and self.admin.is_staff)
        self.assertFalse(self.mgr.is_superuser)

    def test_hierarchy(self):
        self.assertEqual(set(self.admin.get_all_subordinates()), {self.mgr, self.emp, self.other_mgr, self.outsider})
        self.assertEqual(list(self.emp.get_management_chain()), [self.mgr, self.admin])
        self.assertTrue(self.mgr.can_review(self.emp))
        self.assertFalse(self.other_mgr.can_review(self.emp))
        self.assertFalse(self.emp.can_review(self.emp))
        self.assertTrue(self.admin.can_review(self.outsider))

    def test_cycle_rejected(self):
        self.mgr.manager = self.emp
        with self.assertRaises(ValidationError):
            self.mgr.full_clean(exclude=["password"])

    def test_search(self):
        self.assertEqual(list(search_employees("emp-101")), [self.emp])
        self.assertEqual(list(search_employees("employee erin")), [self.emp])
        self.assertIn(self.mgr, search_employees("manager"))
        self.assertEqual(search_employees("  ").count(), 0)


class AuthAndSearchViews(BaseCase):
    def test_login_by_id_and_email(self):
        self.assertTrue(self.client.login(username="emp-101", password=PW))
        self.client.logout()
        self.assertTrue(self.client.login(username="EMP-101@example.com", password=PW))

    def test_anonymous_can_search(self):
        self.assertEqual(self.client.get(reverse("accounts:home")).status_code, 200)
        self.assertContains(self.client.get(reverse("accounts:search"), {"q": "Erin"}), "Erin Employee")
        self.assertEqual(self.client.get(self.emp.get_absolute_url()).status_code, 302)

    def test_search_cards_and_exact_redirect(self):
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("accounts:search"), {"q": "man"})
        self.assertContains(resp, "Mia Manager")
        self.assertContains(resp, "Max Manager")
        resp = self.client.get(reverse("accounts:search"), {"q": "EMP-100"})
        self.assertRedirects(resp, self.mgr.get_absolute_url(), fetch_redirect_response=False)

    def test_api_search(self):
        self.client.force_login(self.emp)
        data = self.client.get(reverse("accounts:api_search"), {"q": "olga"}).json()
        self.assertEqual([r["employee_id"] for r in data["results"]], ["EMP-201"])


class ProfileViews(BaseCase):
    def test_self_edit_limited_fields(self):
        self.client.force_login(self.emp)
        resp = self.client.post(reverse("accounts:profile_edit"), {
            "contact_info": "+66 1234", "description": "Hello",
            "full_name": "Hacker", "position": "CEO", "role": "admin", "manager": "", "email": "x@x.com",
        })
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.contact_info, "+66 1234")
        self.assertEqual(self.emp.description, "Hello")
        self.assertEqual(self.emp.full_name, "Erin Employee")
        self.assertEqual(self.emp.position, "")
        self.assertEqual(self.emp.role, Role.EMPLOYEE)
        self.assertEqual(self.emp.manager, self.mgr)

    def test_tab_visibility(self):
        url = self.emp.get_absolute_url() + "?tab=leaves"
        for who, visible in [(self.emp, True), (self.mgr, True), (self.admin, True),
                             (self.other_mgr, False), (self.outsider, False)]:
            self.client.force_login(who)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual("Leave balances" in resp.content.decode(), visible, who.full_name)

    def test_salary_tab_in_progress_for_owner(self):
        self.client.force_login(self.emp)
        resp = self.client.get(self.emp.get_absolute_url() + "?tab=salary")
        self.assertContains(resp, "In Progress")

    def test_salary_only_for_admin_and_owner_not_manager(self):
        url = self.emp.get_absolute_url() + "?tab=salary"
        for who, visible in [(self.emp, True), (self.admin, True),
                             (self.mgr, False),          # direct manager must NOT see it
                             (self.other_mgr, False), (self.outsider, False)]:
            self.client.force_login(who)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual("Salary — In Progress" in resp.content.decode(), visible, who.full_name)

    def test_salary_tab_link_hidden_from_manager(self):
        self.client.force_login(self.mgr)
        resp = self.client.get(self.emp.get_absolute_url())
        self.assertNotContains(resp, "tab=salary")
        self.assertContains(resp, "tab=leaves")           # managers still see leaves
        self.client.force_login(self.mgr)
        self.assertContains(self.client.get(self.mgr.get_absolute_url()), "tab=salary")   # their own account

    def test_info_tab_lists_all_fields(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(self.emp.get_absolute_url())
        for text in ["Erin Employee", "EMP-101", "emp-101@example.com", "Mia Manager"]:
            self.assertContains(resp, text)


class AdminViews(BaseCase):
    def test_non_admin_forbidden(self):
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("accounts:user_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)

    def test_admin_creates_user_with_manager(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("accounts:user_create"), {
            "employee_id": "emp-300", "full_name": "New Hire", "email": "new@example.com",
            "position": "Tech", "role": Role.EMPLOYEE, "manager": self.mgr.pk,
            "password1": PW, "password2": PW, "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
        new = User.objects.get(employee_id="EMP-300")
        self.assertEqual(new.manager, self.mgr)
        self.assertTrue(new.check_password(PW))

    def test_org_chart_renders(self):
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("accounts:org_chart"))
        self.assertContains(resp, "org-canvas")
        names = {u["name"] for u in self.client.get(reverse("accounts:org_data")).json()["users"]}
        self.assertIn("Alex Admin", names)
        self.assertIn("Olga Outsider", names)


class HomePageTests(BaseCase):
    def test_home_is_minimal_search_only(self):
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("accounts:home"))
        self.assertContains(resp, 'id="search-input"')
        self.assertNotContains(resp, "hero-actions")           # no My profile / Org chart / Apply buttons under the box

    def test_theme_controls_present(self):
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("accounts:home"))
        self.assertContains(resp, 'id="theme-cycle"')
        self.assertContains(resp, 'data-theme-set="dark"')
        self.assertContains(resp, "js/theme.js")

    def test_admin_menu_only_for_admin(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("accounts:home")), reverse("notifications:broadcast"))
        self.client.force_login(self.mgr)
        self.assertNotContains(self.client.get(reverse("accounts:home")), reverse("notifications:broadcast"))


class LastAdminGuardTests(BaseCase):
    def _post(self, user, **over):
        data = {"employee_id": user.employee_id, "full_name": user.full_name, "email": user.email,
                "role": user.role, "is_active": "on"}
        data.update(over)
        data = {k: v for k, v in data.items() if v is not None}
        return self.client.post(reverse("accounts:user_edit", args=[user.pk]), data)

    def test_sole_admin_cannot_demote_or_deactivate_self(self):
        self.client.force_login(self.admin)
        self.assertEqual(self._post(self.admin, role=Role.EMPLOYEE).status_code, 200)
        self.assertEqual(self._post(self.admin, is_active=None).status_code, 200)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_admin and self.admin.is_active)

    def test_admin_can_be_demoted_when_another_admin_exists(self):
        other = make("EMP-002", "Second Admin", Role.ADMIN)
        self.client.force_login(self.admin)
        self.assertEqual(self._post(other, role=Role.MANAGER).status_code, 302)
