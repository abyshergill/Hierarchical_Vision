from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

from .models import Broadcast, Notification

PW = "S3cure-pass-Word!"


class BroadcastTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        mk = lambda eid, name, role, mgr=None: User.objects.create_user(  # noqa: E731
            eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr)
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.emp = mk("EMP-101", "Erin Employee", Role.EMPLOYEE, cls.mgr)
        cls.emp2 = mk("EMP-102", "Eli Employee", Role.EMPLOYEE, cls.mgr)
        cls.gone = mk("EMP-103", "Inactive Ian", Role.EMPLOYEE, cls.mgr)
        User.objects.filter(pk=cls.gone.pk).update(is_active=False)
        cls.url = reverse("notifications:broadcast")

    def send(self, **extra):
        data = {"audience": "all", "title": "Office closed", "message": "Typhoon warning"}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_only_admin_can_open_or_send(self):
        for who in (self.mgr, self.emp):
            self.client.force_login(who)
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.send().status_code, 403)
        self.assertFalse(Notification.objects.exists())

    def test_anonymous_redirected(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_send_to_everyone_active(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.send().status_code, 302)
        self.assertEqual(Notification.objects.filter(title="Office closed").count(), 4)   # not the inactive one
        self.assertFalse(Notification.objects.filter(recipient=self.gone).exists())
        b = Broadcast.objects.get()
        self.assertEqual((b.recipient_count, b.audience, b.sent_by), (4, "all", self.admin))
        self.assertEqual(len(mail.outbox), 0)                                          # e-mail is opt-in

    def test_send_to_specific_accounts(self):
        self.client.force_login(self.admin)
        self.send(audience="selected", recipients=[self.emp.pk, self.emp2.pk])
        self.assertEqual(set(Notification.objects.values_list("recipient_id", flat=True)), {self.emp.pk, self.emp2.pk})

    def test_selected_requires_a_person(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.send(audience="selected").status_code, 200)
        self.assertFalse(Notification.objects.exists())

    def test_send_to_role_groups(self):
        self.client.force_login(self.admin)
        self.send(audience="managers")
        self.assertEqual(list(Notification.objects.values_list("recipient_id", flat=True)), [self.mgr.pk])
        Notification.objects.all().delete()
        self.send(audience="employees")
        self.assertEqual(Notification.objects.count(), 2)

    def test_optional_email(self):
        self.client.force_login(self.admin)
        self.send(audience="selected", recipients=[self.emp.pk], send_email="on")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.emp.email])

    def test_link_must_be_internal(self):
        self.client.force_login(self.admin)
        for bad in ("https://evil.example/x", "//evil.example", "javascript:alert(1)"):
            self.assertEqual(self.send(url=bad).status_code, 200, bad)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(self.send(url="/newsletter/").status_code, 302)

    def test_recipient_can_open_notification_and_follow_link(self):
        self.client.force_login(self.admin)
        self.send(audience="selected", recipients=[self.emp.pk], url="/newsletter/")
        note = Notification.objects.get()
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("notifications:open", args=[note.pk]))
        self.assertRedirects(resp, "/newsletter/", fetch_redirect_response=False)

    def test_prefill_from_django_admin_action(self):
        self.client.force_login(self.admin)
        resp = self.client.get(f"{self.url}?ids={self.emp.pk},{self.emp2.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial["audience"], "selected")
