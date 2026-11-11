import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Role, User
from notifications.models import Notification

from .models import Post, PostImage

PW = "S3cure-pass-Word!"
TMP_MEDIA = tempfile.mkdtemp(prefix="hv-test-media-")


def png(name="pic.png", size=(12, 12)):
    buf = BytesIO()
    Image.new("RGB", size, "tomato").save(buf, "PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class NewsletterTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        mk = lambda eid, name, role, mgr=None, **kw: User.objects.create_user(  # noqa: E731
            eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr, **kw)
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.pub = mk("EMP-101", "Pia Publisher", Role.EMPLOYEE, cls.mgr, newsletter_publisher=True)
        cls.emp = mk("EMP-102", "Erin Employee", Role.EMPLOYEE, cls.mgr)

    def create(self, **extra):
        data = {"title": "Hello", "body": "First post"}
        data.update(extra)
        return self.client.post(reverse("newsletter:create"), data)

    # ---- reading
    def test_everyone_signed_in_can_read(self):
        Post.objects.create(title="Town hall", body="Friday 10:00", author=self.admin)
        for who in (self.admin, self.mgr, self.pub, self.emp):
            self.client.force_login(who)
            self.assertContains(self.client.get(reverse("newsletter:list")), "Town hall")

    def test_anonymous_can_read(self):
        self.assertEqual(self.client.get(reverse("newsletter:list")).status_code, 200)

    # ---- who may publish
    def test_plain_employee_and_unpermitted_manager_cannot_publish(self):
        for who in (self.emp, self.mgr):
            self.client.force_login(who)
            self.assertEqual(self.client.get(reverse("newsletter:create")).status_code, 403)
            self.assertEqual(self.create().status_code, 403)
        self.assertFalse(Post.objects.exists())

    def test_admin_publishes_text_and_images(self):
        self.client.force_login(self.admin)
        resp = self.create(images=[png("a.png"), png("b.png")])
        self.assertEqual(resp.status_code, 302)
        post = Post.objects.get()
        self.assertEqual(post.images.count(), 2)
        self.assertEqual(post.author, self.admin)
        page = self.client.get(reverse("newsletter:list")).content.decode()
        self.assertIn("/media/newsletter/", page)

    def test_permitted_employee_can_publish_and_manage_only_own(self):
        self.client.force_login(self.pub)
        self.assertEqual(self.create(title="Mine").status_code, 302)
        mine = Post.objects.get(title="Mine")
        other = Post.objects.create(title="Theirs", body="x", author=self.admin)
        self.assertEqual(self.client.get(reverse("newsletter:edit", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("newsletter:edit", args=[other.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("newsletter:delete", args=[other.pk])).status_code, 403)
        self.assertTrue(Post.objects.filter(pk=other.pk).exists())
        self.assertEqual(self.client.post(reverse("newsletter:delete", args=[mine.pk])).status_code, 302)
        self.assertFalse(Post.objects.filter(pk=mine.pk).exists())

    def test_publisher_cannot_pin_or_mass_notify(self):
        self.client.force_login(self.pub)
        self.create(title="Sneaky", is_pinned="on", notify_everyone="on")
        self.assertFalse(Post.objects.get(title="Sneaky").is_pinned)
        self.assertFalse(Notification.objects.exists())

    def test_admin_can_pin_edit_delete_any_and_notify_everyone(self):
        self.client.force_login(self.admin)
        self.create(title="Big news", is_pinned="on", notify_everyone="on")
        post = Post.objects.get()
        self.assertTrue(post.is_pinned)
        self.assertEqual(Notification.objects.filter(title__startswith="Newsletter:").count(), 3)   # everyone but the author
        self.assertFalse(Notification.objects.filter(recipient=self.admin).exists())
        self.assertEqual(self.client.post(reverse("newsletter:edit", args=[post.pk]), {"title": "Edited", "body": "b"}).status_code, 302)
        post.refresh_from_db()
        self.assertEqual(post.title, "Edited")
        self.assertEqual(self.client.post(reverse("newsletter:delete", args=[post.pk])).status_code, 302)
        self.assertFalse(Post.objects.exists())

    def test_edit_can_remove_and_add_images_and_files_are_deleted(self):
        self.client.force_login(self.admin)
        self.create(images=[png("a.png")])
        post = Post.objects.get()
        img = post.images.get()
        path = img.image.path
        resp = self.client.post(reverse("newsletter:edit", args=[post.pk]),
                                {"title": "T", "body": "b", "remove_images": [img.pk], "images": [png("c.png")]})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(post.images.count(), 1)
        self.assertFalse(PostImage.objects.filter(pk=img.pk).exists())
        import os
        self.assertFalse(os.path.exists(path))

    # ---- hostile input
    def test_html_in_body_is_escaped(self):
        self.client.force_login(self.admin)
        self.create(title="<b>x</b>", body="<script>alert(1)</script>")
        page = self.client.get(reverse("newsletter:list")).content.decode()
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)

    def test_svg_and_fake_images_rejected(self):
        self.client.force_login(self.admin)
        svg = SimpleUploadedFile("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", content_type="image/svg+xml")
        fake = SimpleUploadedFile("evil.png", b"<?php echo 1; ?>", content_type="image/png")
        for bad in (svg, fake):
            self.assertEqual(self.create(images=[bad]).status_code, 200)
        self.assertFalse(Post.objects.exists())

    def test_too_many_images_rejected(self):
        self.client.force_login(self.admin)
        resp = self.create(images=[png(f"{i}.png") for i in range(7)])
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Post.objects.exists())

    def test_delete_requires_post(self):
        post = Post.objects.create(title="t", body="b", author=self.admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("newsletter:delete", args=[post.pk])).status_code, 405)

    # ---- publisher management
    def test_only_admin_manages_publishers(self):
        url = reverse("newsletter:publishers")
        for who in (self.mgr, self.pub, self.emp):
            self.client.force_login(who)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"publishers": [self.emp.pk]}).status_code, 403)
        self.emp.refresh_from_db()
        self.assertFalse(self.emp.newsletter_publisher)

    def test_admin_grants_and_revokes_publish_permission(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("newsletter:publishers"), {"publishers": [self.mgr.pk, self.emp.pk]})
        self.assertEqual(resp.status_code, 302)
        for u in (self.mgr, self.emp, self.pub):
            u.refresh_from_db()
        self.assertTrue(self.mgr.newsletter_publisher and self.emp.newsletter_publisher)
        self.assertFalse(self.pub.newsletter_publisher)                  # not ticked -> revoked
        self.assertTrue(Notification.objects.filter(recipient=self.emp, title__icontains="publish").exists())
        self.assertFalse(Notification.objects.filter(recipient=self.pub).exists())
        self.client.force_login(self.emp)
        self.assertEqual(self.create(title="Now allowed").status_code, 302)

    def test_admin_cannot_be_demoted_via_publisher_form(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("newsletter:publishers"), {"publishers": [self.admin.pk]})
        self.assertTrue(self.admin.can_publish_newsletter)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.newsletter_publisher)                # admins are not listed / touched
        self.assertTrue(self.admin.can_publish_newsletter)               # ...and always publish anyway


class CommentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("A1", "admin@example.com", "Admin", password=PW, role=Role.ADMIN)
        cls.user = User.objects.create_user("E1", "user@example.com", "Employee", password=PW, role=Role.EMPLOYEE)
        cls.other = User.objects.create_user("E2", "other@example.com", "Other", password=PW, role=Role.EMPLOYEE)
        cls.post = Post.objects.create(title="News", body="Body", author=cls.admin)

    def test_public_read_and_authenticated_comment(self):
        from .models import Comment
        detail = reverse("newsletter:detail", args=[self.post.pk])
        url = reverse("newsletter:comment_create", args=[self.post.pk])
        self.assertContains(self.client.get(detail), "News")
        self.assertEqual(self.client.post(url, {"body": "anonymous"}).status_code, 302)
        self.assertFalse(Comment.objects.exists())
        self.client.force_login(self.user)
        self.client.post(url, {"body": "  "})
        self.assertFalse(Comment.objects.exists())
        self.client.post(url, {"body": "<script>alert(1)</script>"})
        comment = Comment.objects.get()
        self.assertEqual(comment.author, self.user)
        self.client.logout()
        self.assertContains(self.client.get(detail), "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_comment_deletion_owner_or_admin_only(self):
        from .models import Comment
        comment = Comment.objects.create(post=self.post, author=self.user, body="hello")
        url = reverse("newsletter:comment_delete", args=[comment.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(Comment.objects.exists())
