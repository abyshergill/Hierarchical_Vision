from datetime import date

from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

from .models import Holiday

PW = "S3cure-pass-Word!"


class HolidayPdfTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.emp = User.objects.create_user("EMP-101", "e101@example.com", "Erin Employee", password=PW, role=Role.EMPLOYEE)
        Holiday.objects.create(date=date(2027, 1, 1), name="New Year's Day", description="<b>Public</b> & fun")
        Holiday.objects.create(date=date(2027, 4, 13), name="วันสงกรานต์ Songkran")

    def test_requires_login(self):
        resp = self.client.get(reverse("leaves:holidays_pdf"), {"year": 2027})
        self.assertEqual(resp.status_code, 302)

    def test_download_is_a_pdf_attachment(self):
        self.client.force_login(self.emp)
        resp = self.client.get(reverse("leaves:holidays_pdf"), {"year": 2027})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="holidays-2027.pdf"')
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_bad_year_falls_back_and_never_reaches_the_filename(self):
        self.client.force_login(self.emp)
        for bad in ("abc", '2027"; x=y', "99999999999999999999", "1"):
            resp = self.client.get(reverse("leaves:holidays_pdf"), {"year": bad})
            self.assertEqual(resp.status_code, 200)
            self.assertRegex(resp["Content-Disposition"], r'^attachment; filename="holidays-\d{4}\.pdf"$')

    def test_page_offers_the_download_button(self):
        self.client.force_login(self.emp)
        page = self.client.get(reverse("leaves:holidays"), {"year": 2027})
        self.assertContains(page, "Download PDF")
        self.assertContains(page, reverse("leaves:holidays_pdf") + "?year=2027")
