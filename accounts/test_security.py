import io
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from notifications.models import Notification

from .models import LoginAttempt, Role, User
from .tests import PW, BaseCase


def png_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(buf, "PNG")
    return buf.getvalue()


class BruteForceTests(BaseCase):
    def bad(self, username="EMP-101", password="definitely-wrong-1"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": password})

    def good(self, username="EMP-101"):
        return self.client.post(reverse("accounts:login"), {"username": username, "password": PW})

    def test_lockout_blocks_even_the_correct_password(self):
        for _ in range(4):
            self.assertEqual(self.bad().status_code, 200)
        self.assertEqual(self.bad().status_code, 429)            # 5th failure locks the account+IP
        self.assertEqual(self.good().status_code, 429)           # ...so the right password is refused too
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_other_accounts_are_not_locked(self):
        for _ in range(5):
            self.bad()
        self.assertEqual(self.good("EMP-100").status_code, 302)

    def test_lock_expires(self):
        for _ in range(5):
            self.bad()
        LoginAttempt.objects.update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.good().status_code, 302)

    def test_unknown_accounts_are_throttled_too(self):
        for _ in range(5):
            resp = self.bad("nobody-here")
        self.assertEqual(resp.status_code, 429)

    @override_settings(LOGIN_MAX_ATTEMPTS_PER_IP=3)
    def test_password_spraying_from_one_ip_is_blocked(self):
        for name in ("a-user", "b-user", "c-user"):
            self.bad(name)
        self.assertEqual(self.good("EMP-100").status_code, 429)

    def test_lockout_also_protects_django_admin_login(self):
        for _ in range(5):
            self.client.post("/django-admin/login/", {"username": "EMP-001", "password": "nope-nope-nope", "next": "/django-admin/"})
        self.client.post("/django-admin/login/", {"username": "EMP-001", "password": PW, "next": "/django-admin/"})
        self.assertNotIn("_auth_user_id", self.client.session)


class WebSecurityTests(BaseCase):
    def test_csrf_enforced_on_state_changing_requests(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.emp)
        self.assertEqual(client.post(reverse("accounts:profile_edit"), {"description": "pwned"}).status_code, 403)
        self.assertEqual(client.post(reverse("accounts:logout")).status_code, 403)
        self.assertEqual(client.post(reverse("accounts:login"), {"username": "EMP-101", "password": PW}).status_code, 403)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.description, "")

    def test_security_headers(self):
        resp = self.client.get(reverse("accounts:login"))
        self.assertIn("frame-ancestors 'none'", resp["Content-Security-Policy"])
        self.assertIn("script-src 'self'", resp["Content-Security-Policy"])
        self.assertEqual(resp["X-Frame-Options"], "DENY")
        self.assertEqual(resp["X-Content-Type-Options"], "nosniff")

    def test_authenticated_pages_are_not_cached(self):
        self.client.force_login(self.emp)
        self.assertIn("no-store", self.client.get(reverse("accounts:home"))["Cache-Control"])

    def test_stored_xss_is_escaped(self):
        self.emp.description = "<script>alert(1)</script>"
        self.emp.save()
        self.client.force_login(self.outsider)
        html = self.client.get(self.emp.get_absolute_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_open_redirect_after_login(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "EMP-101", "password": PW, "next": "https://evil.example/"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/")

    def test_media_requires_login_and_blocks_traversal(self):
        self.assertEqual(self.client.get("/media/profiles/x.png").status_code, 302)
        self.client.force_login(self.emp)
        self.assertIn(self.client.get("/media/../config/settings.py").status_code, (400, 404))

    def test_notification_idor(self):
        note = Notification.objects.create(recipient=self.emp, title="private", url="/")
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("notifications:open", args=[note.pk])).status_code, 404)

    def test_employee_id_rejects_markup(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("accounts:user_create"), {
            "employee_id": 'EMP"><script>', "full_name": "X", "email": "x@example.com", "role": Role.EMPLOYEE,
            "password1": PW, "password2": PW, "is_active": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    def test_weak_password_rejected(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("accounts:user_create"), {
            "employee_id": "EMP-777", "full_name": "Weak", "email": "weak@example.com", "role": Role.EMPLOYEE,
            "password1": "password123", "password2": "password123", "is_active": "on"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(employee_id="EMP-777").exists())

    @override_settings(RATE_LIMIT_PER_MINUTE=3)
    def test_directory_scraping_is_rate_limited(self):
        cache.clear()
        self.client.force_login(self.emp)
        with mock.patch("accounts.ratelimit._current_minute", return_value=42):
            codes = [self.client.get(reverse("accounts:api_search"), {"q": "a"}).status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])


class UploadSecurityTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def upload(self, upload):
        self.client.force_login(self.emp)
        return self.client.post(reverse("accounts:profile_edit"), {"description": "d", "profile_picture": upload})

    def test_valid_png_is_stored_and_avatar_is_public(self):
        resp = self.upload(SimpleUploadedFile("me.png", png_bytes(), content_type="image/png"))
        self.assertEqual(resp.status_code, 302)
        self.emp.refresh_from_db()
        url = self.emp.profile_picture.url
        self.assertTrue(url.startswith("/media/profiles/EMP-101/avatar-"), url)
        served = self.client.get(url)
        self.assertEqual(served.status_code, 200)
        served.close()
        anon = Client().get(url)          # avatars are public by design
        self.assertEqual(anon.status_code, 200)
        anon.close()

    def test_non_images_and_dangerous_types_rejected(self):
        for name, data in [
            ("evil.png", b"<script>alert(1)</script>"),                      # not really an image
            ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>"),         # SVG can carry scripts
            ("x.html", png_bytes()),                                          # wrong extension
        ]:
            resp = self.upload(SimpleUploadedFile(name, data))
            self.assertEqual(resp.status_code, 200, name)
            self.emp.refresh_from_db()
            self.assertFalse(self.emp.profile_picture, name)


class ProfileImageRuleTests(BaseCase):
    """Edit-profile uploads: JPG/JPEG/PNG only, 20 MB, verified by content, metadata stripped, removable."""

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.tmp)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.client.force_login(self.emp)

    def post(self, **files):
        return self.client.post(reverse("accounts:profile_edit"), {"description": "d", **files})

    def pic(self, fmt, name, **kw):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (30, 20), "blue").save(buf, fmt, **kw)
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/" + fmt.lower())

    def test_gif_webp_and_renamed_gif_rejected(self):
        for bad in (self.pic("GIF", "a.gif"), self.pic("WEBP", "a.webp"), self.pic("GIF", "sneaky.png")):
            self.assertEqual(self.post(profile_picture=bad).status_code, 200, bad.name)
            self.emp.refresh_from_db()
            self.assertFalse(self.emp.profile_picture, bad.name)

    def test_jpg_jpeg_png_accepted_in_both_fields(self):
        for name, fmt in (("a.jpg", "JPEG"), ("a.jpeg", "JPEG"), ("a.png", "PNG")):
            self.assertEqual(self.post(profile_picture=self.pic(fmt, name), background_image=self.pic(fmt, name)).status_code, 302, name)
        self.emp.refresh_from_db()
        self.assertTrue(self.emp.profile_picture and self.emp.background_image)

    @override_settings(MAX_IMAGE_UPLOAD_MB=1)
    def test_over_limit_rejected(self):
        big = SimpleUploadedFile("big.jpg", b"0" * (1024 * 1024 + 1), content_type="image/jpeg")
        self.assertEqual(self.post(profile_picture=big).status_code, 200)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.profile_picture)

    def test_default_limit_is_20_mb(self):
        from django.conf import settings

        self.assertEqual(settings.MAX_IMAGE_UPLOAD_MB, 20)

    def test_metadata_is_stripped_and_name_is_random(self):
        from PIL import Image

        exif = Image.Exif()
        exif[0x010F] = "SecretCamera"
        self.assertEqual(self.post(profile_picture=self.pic("JPEG", "IMG_0001 (GPS).jpg", exif=exif)).status_code, 302)
        self.emp.refresh_from_db()
        self.assertNotIn("IMG_0001", self.emp.profile_picture.name)
        with Image.open(self.emp.profile_picture.path) as stored:
            self.assertEqual(dict(stored.getexif()), {})

    def test_remove_checkbox_clears_and_deletes_file_and_new_upload_replaces_old(self):
        import os

        self.post(profile_picture=self.pic("PNG", "a.png"))
        self.emp.refresh_from_db()
        first = self.emp.profile_picture.path
        self.assertTrue(os.path.exists(first))
        self.post(profile_picture=self.pic("PNG", "b.png"))
        self.emp.refresh_from_db()
        self.assertFalse(os.path.exists(first))                       # replaced file does not linger
        second = self.emp.profile_picture.path
        self.assertEqual(self.client.post(reverse("accounts:profile_edit"), {"description": "d", "remove_profile_picture": "on"}).status_code, 302)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.profile_picture)
        self.assertFalse(os.path.exists(second))

    def test_edit_page_has_preview_and_restricts_the_file_picker(self):
        page = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(page, 'id="preview-profile_picture"')
        self.assertContains(page, 'accept=".jpg,.jpeg,.png,image/jpeg,image/png"')
        self.assertContains(page, 'data-max-mb="20"')
        self.assertContains(page, "LIVE PREVIEW")

    def test_profile_text_is_cleaned(self):
        self.client.post(reverse("accounts:profile_edit"), {"description": "hi\x07 there\u202e", "contact_info": "  a   b\x07 "})
        self.emp.refresh_from_db()
        self.assertEqual((self.emp.description, self.emp.contact_info), ("hi there", "a b"))


class PublicMediaTests(BaseCase):
    def test_only_active_avatars_and_newsletter_images_are_public(self):
        from newsletter.models import Post, PostImage
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            self.emp.profile_picture.save("face.png", SimpleUploadedFile("face.png", png_bytes(), content_type="image/png"))
            self.emp.background_image.save("cover.png", SimpleUploadedFile("cover.png", png_bytes(), content_type="image/png"))
            post = Post.objects.create(title="News", body="Hello", author=self.admin)
            image = PostImage.objects.create(post=post, image=SimpleUploadedFile("news.png", png_bytes(), content_type="image/png"))
            for url in (self.emp.profile_picture.url, image.image.url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                response.close()
            self.assertEqual(self.client.get(self.emp.background_image.url).status_code, 302)
            self.emp.is_active = False
            self.emp.save()
            self.assertEqual(self.client.get(self.emp.profile_picture.url).status_code, 302)

    def test_profile_edit_includes_preview_targets(self):
        self.client.force_login(self.emp)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(response, 'id="preview-profile_picture"')
        self.assertContains(response, 'id="preview-background_image"')
