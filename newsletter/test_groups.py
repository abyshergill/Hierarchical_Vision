import shutil
import tempfile
from io import BytesIO

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.models import Role, User
from notifications.models import Notification

from .models import GroupAccessRequest, GroupMembership, NewsGroup, Post, PostImage

PW = "S3cure-pass-Word!"
TMP_MEDIA = tempfile.mkdtemp(prefix="hv-test-groups-")


def img(name="pic.png", fmt="PNG", size=(12, 12)):
    buf = BytesIO()
    Image.new("RGB", size, "tomato").save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/" + fmt.lower())


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class GroupTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        mk = lambda eid, name, role, mgr=None: User.objects.create_user(  # noqa: E731
            eid, f"{eid.lower()}@example.com", name, password=PW, role=role, manager=mgr)
        cls.admin = mk("EMP-001", "Alex Admin", Role.ADMIN)
        cls.mgr = mk("EMP-100", "Mia Manager", Role.MANAGER, cls.admin)
        cls.other_mgr = mk("EMP-200", "Max Manager", Role.MANAGER, cls.admin)
        cls.member = mk("EMP-101", "Erin Member", Role.EMPLOYEE, cls.mgr)
        cls.outsider = mk("EMP-102", "Olga Outsider", Role.EMPLOYEE, cls.mgr)
        cls.group = NewsGroup.objects.create(name="Test Manufacturing", description="TM dept", manager=cls.mgr, created_by=cls.admin)
        GroupMembership.objects.create(group=cls.group, user=cls.member, added_by=cls.admin)

    def setUp(self):
        cache.clear()

    def secret_post(self, **kw):
        defaults = dict(title="Secret plan", body="Only for TM", author=self.member, group=self.group)
        defaults.update(kw)
        return Post.objects.create(**defaults)

    # ---- who can create groups / assign managers
    def test_only_admin_creates_groups_and_manager_must_have_manager_role(self):
        url = reverse("newsletter:group_create")
        for who in (self.mgr, self.member):
            self.client.force_login(who)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {"name": "Hack"}).status_code, 403)
        self.client.force_login(self.admin)
        bad = self.client.post(url, {"name": "Quality", "manager": self.member.pk})          # employee cannot be manager
        self.assertEqual(bad.status_code, 200)
        self.assertFalse(NewsGroup.objects.filter(name="Quality").exists())
        ok = self.client.post(url, {"name": "Quality", "description": "QA", "manager": self.other_mgr.pk})
        self.assertEqual(ok.status_code, 302)
        group = NewsGroup.objects.get(name="Quality")
        self.assertEqual(group.manager, self.other_mgr)
        self.assertTrue(Notification.objects.filter(recipient=self.other_mgr, title__contains="Quality").exists())
        dup = self.client.post(url, {"name": "quality"})                                     # case-insensitive duplicate
        self.assertEqual(dup.status_code, 200)
        self.assertEqual(NewsGroup.objects.filter(name__iexact="quality").count(), 1)

    # ---- privacy
    def test_outsider_sees_only_request_page(self):
        self.secret_post()
        self.client.force_login(self.outsider)
        page = self.client.get(self.group.get_absolute_url())
        self.assertContains(page, "Request access")
        self.assertNotContains(page, "Secret plan")
        self.assertNotContains(self.client.get(reverse("newsletter:list")), "Secret plan")
        self.assertEqual(self.client.get(reverse("newsletter:group_post_create", args=[self.group.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("newsletter:group_members", args=[self.group.pk])).status_code, 403)

    def test_group_post_detail_comments_and_images_are_blocked_for_outsiders(self):
        post = self.secret_post()
        image = PostImage.objects.create(post=post, image=img())
        self.client.force_login(self.outsider)
        resp = self.client.get(post.get_absolute_url())
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], self.group.get_absolute_url())
        self.assertEqual(self.client.post(reverse("newsletter:comment_create", args=[post.pk]), {"body": "hi"}).status_code, 403)
        self.assertEqual(self.client.get(image.image.url).status_code, 403)
        self.assertEqual(post.comments.count(), 0)
        self.client.logout()
        self.assertEqual(self.client.get(image.image.url).status_code, 302)                  # anonymous -> sign in
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 302)

    def test_member_manager_and_admin_can_read(self):
        post = self.secret_post()
        image = PostImage.objects.create(post=post, image=img())
        for who in (self.member, self.mgr, self.admin):
            self.client.force_login(who)
            self.assertContains(self.client.get(self.group.get_absolute_url()), "Secret plan")
            self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 200)
            served = self.client.get(image.image.url)
            self.assertEqual(served.status_code, 200)
            served.close()
        self.client.force_login(self.other_mgr)                                                # manager of ANOTHER group
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 302)

    # ---- posting
    def test_member_posts_text_picture_and_comment(self):
        self.client.force_login(self.member)
        resp = self.client.post(reverse("newsletter:group_post_create", args=[self.group.pk]),
                                {"title": "Line 3 update", "body": "Yield up", "images": [img("a.png")]})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], self.group.get_absolute_url())
        post = Post.objects.get(title="Line 3 update")
        self.assertEqual(post.group, self.group)
        self.assertEqual(post.images.count(), 1)
        self.assertNotContains(self.client.get(reverse("newsletter:list")), "Line 3 update")   # not on the company page
        self.assertEqual(self.client.post(reverse("newsletter:comment_create", args=[post.pk]), {"body": "Nice"}).status_code, 302)
        self.assertEqual(post.comments.count(), 1)

    def test_member_cannot_pin_manager_can(self):
        url = reverse("newsletter:group_post_create", args=[self.group.pk])
        self.client.force_login(self.member)
        self.client.post(url, {"title": "A", "body": "b", "is_pinned": "on"})
        self.assertFalse(Post.objects.get(title="A").is_pinned)
        self.client.force_login(self.mgr)
        self.client.post(url, {"title": "B", "body": "b", "is_pinned": "on"})
        self.assertTrue(Post.objects.get(title="B").is_pinned)

    def test_group_manager_moderates_but_other_members_cannot(self):
        post = self.secret_post(author=self.member)
        buddy = User.objects.create_user("EMP-103", "e103@example.com", "Bo Buddy", password=PW, role=Role.EMPLOYEE)
        GroupMembership.objects.create(group=self.group, user=buddy)
        self.client.force_login(buddy)
        self.assertEqual(self.client.get(reverse("newsletter:edit", args=[post.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("newsletter:delete", args=[post.pk])).status_code, 403)
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(reverse("newsletter:edit", args=[post.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("newsletter:delete", args=[post.pk])).status_code, 302)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_removed_member_loses_access_immediately(self):
        post = self.secret_post()
        self.client.force_login(self.mgr)
        self.client.post(reverse("newsletter:member_remove", args=[self.group.pk, self.member.pk]))
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(post.get_absolute_url()).status_code, 302)
        self.assertEqual(self.client.get(reverse("newsletter:edit", args=[post.pk])).status_code, 403)

    # ---- request / approval flow
    def test_request_approve_flow(self):
        self.client.force_login(self.outsider)
        url = reverse("newsletter:request_access", args=[self.group.pk])
        self.assertEqual(self.client.post(url, {"message": "I joined TM"}).status_code, 302)
        self.client.post(url, {"message": "again"})                                           # duplicate -> still one
        req = GroupAccessRequest.objects.get()
        self.assertEqual(req.status, "pending")
        self.assertTrue(Notification.objects.filter(recipient=self.mgr, title__startswith="Access request").exists())
        self.assertContains(self.client.get(self.group.get_absolute_url()), "waiting for approval")

        approve = reverse("newsletter:request_approve", args=[req.pk])
        self.assertEqual(self.client.post(approve).status_code, 403)                           # can't approve yourself
        self.client.force_login(self.other_mgr)
        self.assertEqual(self.client.post(approve).status_code, 403)                           # not this group's manager
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.get(approve).status_code, 405)                            # POST only
        self.assertEqual(self.client.post(approve).status_code, 302)
        req.refresh_from_db()
        self.assertEqual((req.status, req.decided_by), ("approved", self.mgr))
        self.assertTrue(GroupMembership.objects.filter(group=self.group, user=self.outsider).exists())
        self.assertTrue(Notification.objects.filter(recipient=self.outsider, title__contains="approved").exists())
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.group.get_absolute_url()).status_code, 200)
        self.assertContains(self.client.get(self.group.get_absolute_url()), "New post")

    def test_admin_can_decline_and_user_may_ask_again(self):
        self.client.force_login(self.outsider)
        self.client.post(reverse("newsletter:request_access", args=[self.group.pk]))
        req = GroupAccessRequest.objects.get()
        self.client.force_login(self.admin)
        self.client.post(reverse("newsletter:request_reject", args=[req.pk]))
        req.refresh_from_db()
        self.assertEqual(req.status, "rejected")
        self.assertFalse(GroupMembership.objects.filter(group=self.group, user=self.outsider).exists())
        self.client.force_login(self.outsider)
        self.client.post(reverse("newsletter:request_access", args=[self.group.pk]))
        self.assertEqual(GroupAccessRequest.objects.filter(status="pending").count(), 1)

    def test_manager_can_add_people_directly_and_only_valid_ids(self):
        url = reverse("newsletter:group_members", args=[self.group.pk])
        self.client.force_login(self.mgr)
        self.client.post(url, {"people": [self.outsider.pk, 99999, "x"]})
        self.assertTrue(GroupMembership.objects.filter(group=self.group, user=self.outsider).exists())
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.post(url, {"people": [self.outsider.pk]}).status_code, 403)

    # ---- sidebar
    def test_sidebar_has_groups_and_pinned_sections_and_hides_private_pins(self):
        Post.objects.create(title="Company pin", body="x", author=self.admin, is_pinned=True)
        self.secret_post(title="Private pin", is_pinned=True)
        self.client.force_login(self.outsider)
        page = self.client.get(reverse("newsletter:list"))
        self.assertContains(page, 'id="side-groups"')
        self.assertContains(page, 'id="side-pinned"')
        self.assertContains(page, "Test Manufacturing")
        self.assertContains(page, "Company pin")
        self.assertNotContains(page, "Private pin")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("newsletter:list")), "Private pin")

    def test_admin_sees_new_group_button_others_do_not(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("newsletter:list")), reverse("newsletter:group_create"))
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(reverse("newsletter:list")), reverse("newsletter:group_create"))

    def test_deleting_group_removes_posts_and_files(self):
        import os
        post = self.secret_post()
        path = PostImage.objects.create(post=post, image=img()).image.path
        self.client.force_login(self.mgr)
        self.assertEqual(self.client.post(reverse("newsletter:group_delete", args=[self.group.pk])).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse("newsletter:group_delete", args=[self.group.pk])).status_code, 302)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())
        self.assertFalse(os.path.exists(path))

    # ---- uploads
    def test_only_jpg_jpeg_png_are_accepted_and_files_are_re_encoded(self):
        url = reverse("newsletter:group_post_create", args=[self.group.pk])
        self.client.force_login(self.member)
        for bad in (img("x.gif", "GIF"), img("x.webp", "WEBP"), img("fake.png", "GIF"),
                    SimpleUploadedFile("x.svg", b"<svg/>"), SimpleUploadedFile("x.png", b"<?php ?>")):
            self.assertEqual(self.client.post(url, {"title": "T", "body": "b", "images": [bad]}).status_code, 200, bad.name)
        self.assertFalse(Post.objects.filter(title="T").exists())
        self.assertEqual(self.client.post(url, {"title": "T", "body": "b", "images": [img("a.jpeg", "JPEG"), img("b.jpg", "JPEG"), img("c.png")]}).status_code, 302)
        names = [i.image.name for i in Post.objects.get(title="T").images.all()]
        self.assertEqual(sorted(n.rsplit(".", 1)[1] for n in names), ["jpg", "jpg", "png"])      # extension = real format

    @override_settings(MAX_IMAGE_UPLOAD_MB=1)
    def test_size_limit_is_enforced(self):
        url = reverse("newsletter:group_post_create", args=[self.group.pk])
        self.client.force_login(self.member)
        big = SimpleUploadedFile("big.png", b"0" * (1024 * 1024 + 1), content_type="image/png")
        self.assertEqual(self.client.post(url, {"title": "Big", "body": "b", "images": [big]}).status_code, 200)
        self.assertFalse(Post.objects.filter(title="Big").exists())

    def test_text_is_sanitised_and_escaped(self):
        url = reverse("newsletter:group_post_create", args=[self.group.pk])
        self.client.force_login(self.member)
        self.client.post(url, {"title": "Hi\x07 <i>there</i>\u202e", "body": "<script>alert(1)</script>\x07ok"})
        post = Post.objects.get(group=self.group, author=self.member)
        self.assertNotIn("\x07", post.title)
        self.assertNotIn("\u202e", post.title)
        page = self.client.get(self.group.get_absolute_url()).content.decode()
        self.assertNotIn("<script>alert(1)</script>", page)


class SidebarLimitTests(TestCase):
    def test_sidebar_lists_my_groups_first_and_hides_extras(self):
        from django.urls import reverse
        from accounts.models import User
        user = User.objects.create_user(employee_id="SB1", password="pw-12345-xx", full_name="Side Bar", email="sb1@example.com")
        for i in range(7):
            NewsGroup.objects.create(name=f"A group {i}")
        mine = NewsGroup.objects.create(name="Zeta mine")
        GroupMembership.objects.create(group=mine, user=user)
        self.client.force_login(user)
        html = self.client.get(reverse("newsletter:list")).content.decode()
        self.assertLess(html.index("Zeta mine"), html.index("A group 0"))
        self.assertIn("Show all groups (8)", html)
        self.assertEqual(html.count('class="extra" hidden'), 3)
