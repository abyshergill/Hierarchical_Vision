from django.test import Client, TestCase
from django.urls import reverse
from accounts.models import Role, User
from .models import SupportRequest


class SupportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("A1", "a@example.com", "Admin", password="test-password-123", role=Role.ADMIN)
        cls.employee = User.objects.create_user("E1", "e@example.com", "Employee", password="test-password-123", role=Role.EMPLOYEE)
        cls.manager = User.objects.create_user("M1", "m@example.com", "Manager", password="test-password-123", role=Role.MANAGER)
        cls.ticket = SupportRequest.objects.create(requester=cls.employee, subject="Private issue", description="Sensitive text")

    def test_only_signed_in_users_can_submit(self):
        url = reverse("support:create")
        self.assertEqual(self.client.post(url, {"subject": "x", "description": "y"}).status_code, 302)
        self.assertEqual(SupportRequest.objects.count(), 1)
        self.client.force_login(self.employee)
        self.assertEqual(self.client.post(url, {"subject": "Help", "description": "Broken"}).status_code, 302)
        self.assertEqual(SupportRequest.objects.get(subject="Help").requester, self.employee)

    def test_inbox_and_updates_admin_only(self):
        inbox = reverse("support:inbox")
        update = reverse("support:update", args=[self.ticket.pk])
        self.assertEqual(self.client.get(inbox).status_code, 302)
        for user in (self.employee, self.manager):
            self.client.force_login(user)
            self.assertEqual(self.client.get(inbox).status_code, 403)
            self.assertEqual(self.client.post(update, {"status": "complete"}).status_code, 403)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "received")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(inbox), "Sensitive text")
        for status in ("in_progress", "complete"):
            self.assertEqual(self.client.post(update, {"status": status}).status_code, 302)
            self.ticket.refresh_from_db()
            self.assertEqual(self.ticket.status, status)
        self.client.post(update, {"status": "invalid"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "complete")
        self.assertEqual(self.client.get(update).status_code, 405)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.employee)
        self.assertEqual(client.post(reverse("support:create"), {"subject": "a", "description": "b"}).status_code, 403)
