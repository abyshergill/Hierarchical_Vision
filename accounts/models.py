import os
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from .sanitize import (  # noqa: F401  (re-exported: newsletter imports them from here)
    IMAGE_EXTENSIONS, MAX_IMAGE_SIDE, _is_new_upload, validate_image_content, validate_image_dimensions, validate_image_size,
)


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    MANAGER = "manager", "Manager"
    EMPLOYEE = "employee", "Employee"


employee_id_validator = RegexValidator(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$",
    "Employee ID may contain only letters, digits, '-' and '_' (2-30 characters).",
)


# NOTE: upload_to callables MUST be plain module-level functions, otherwise
# `makemigrations` fails with "Could not find function _path in accounts.models".
def profile_picture_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"profiles/{instance.employee_id}/avatar-{uuid.uuid4().hex[:10]}{ext}"


def background_image_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"profiles/{instance.employee_id}/cover-{uuid.uuid4().hex[:10]}{ext}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, employee_id, email, full_name, password, **extra):
        if not employee_id:
            raise ValueError("Employee ID is required.")
        if not email:
            raise ValueError("Email is required.")
        user = self.model(
            employee_id=employee_id.strip().upper(),
            email=self.normalize_email(email),
            full_name=full_name,
            **extra,
        )
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, employee_id, email, full_name, password=None, **extra):
        extra.setdefault("role", Role.EMPLOYEE)
        return self._create_user(employee_id, email, full_name, password, **extra)

    def create_superuser(self, employee_id, email, full_name, password=None, **extra):
        extra["role"] = Role.ADMIN
        return self._create_user(employee_id, email, full_name, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Every person in the company has their own account.

    ``role`` is the single source of truth for privileges; ``is_staff`` and
    ``is_superuser`` are derived from it in ``save()`` (Admin == Django superuser).
    """

    employee_id = models.CharField(
        max_length=30, unique=True, validators=[employee_id_validator], help_text="e.g. EMP-105. Used to sign in."
    )
    email = models.EmailField("email address", unique=True)
    full_name = models.CharField(max_length=150)
    position = models.CharField(max_length=120, blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EMPLOYEE, db_index=True)
    manager = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="direct_reports",
        verbose_name="Peer / Reporting manager",
    )
    contact_info = models.CharField("contact information", max_length=255, blank=True)
    description = models.TextField(blank=True)
    profile_picture = models.ImageField(
        upload_to=profile_picture_path, blank=True, null=True, validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size, validate_image_dimensions, validate_image_content]
    )
    background_image = models.ImageField(
        upload_to=background_image_path, blank=True, null=True, validators=[FileExtensionValidator(IMAGE_EXTENSIONS), validate_image_size, validate_image_dimensions, validate_image_content]
    )

    newsletter_publisher = models.BooleanField(
        "may publish to the newsletter", default=False,
        help_text="Lets this employee/manager post in the company newsletter (Admins can always post).",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, editable=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "employee_id"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email", "full_name"]

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.employee_id})"

    # ----- identity helpers -------------------------------------------------
    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split(" ")[0] if self.full_name else self.employee_id

    @property
    def initials(self):
        parts = [p for p in self.full_name.split() if p]
        if not parts:
            return self.employee_id[:2].upper()
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    def get_absolute_url(self):
        return reverse("accounts:profile", kwargs={"employee_id": self.employee_id})

    # ----- role helpers -----------------------------------------------------
    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_manager_role(self):
        return self.role == Role.MANAGER

    @property
    def can_approve_leaves(self):
        return self.role in (Role.ADMIN, Role.MANAGER)

    @property
    def can_publish_newsletter(self):
        return self.is_admin or self.newsletter_publisher

    # ----- validation / persistence ----------------------------------------
    def clean(self):
        super().clean()
        if self.employee_id:
            self.employee_id = self.employee_id.strip().upper()
        if self.manager_id and self.pk:
            seen, node = set(), self.manager
            while node is not None and node.pk not in seen:
                if node.pk == self.pk:
                    raise ValidationError({"manager": "A person cannot report (directly or indirectly) to themselves."})
                seen.add(node.pk)
                node = node.manager

    def save(self, *args, **kwargs):
        if self.employee_id:
            self.employee_id = self.employee_id.strip().upper()
        # Role drives Django's privilege flags.
        self.is_superuser = self.is_staff = self.role == Role.ADMIN
        super().save(*args, **kwargs)

    # ----- hierarchy --------------------------------------------------------
    def get_management_chain(self):
        """Ancestors, nearest first (direct manager, their manager, ...)."""
        chain, seen, node = [], {self.pk}, self.manager
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.manager
        return chain

    def get_all_subordinates(self):
        """Everyone below this user in the hierarchy (recursive), as a queryset."""
        found, frontier = set(), [self.pk]
        while frontier:
            children = list(
                User.objects.filter(manager_id__in=frontier).exclude(pk__in=found | {self.pk}).values_list("pk", flat=True)
            )
            found.update(children)
            frontier = children
        return User.objects.filter(pk__in=found, is_active=True)

    def is_above(self, other):
        """True if ``self`` is somewhere in ``other``'s management chain."""
        return any(m.pk == self.pk for m in other.get_management_chain())

    def can_view_private(self, target):
        """Leaves tab: self, admins, and anyone above the target (salary is stricter, see can_view_salary)."""
        return self == target or self.is_admin or self.is_above(target)

    def can_view_salary(self, target):
        """Salary is the most sensitive tab: ONLY Admins and the account's own owner.
        Being someone's manager does NOT grant access."""
        return self.is_admin or self.pk == target.pk

    def can_export_leaves(self, target):
        """Managers/Admins may download leave data: Admin -> anyone, Manager -> own
        recursive subordinates; both may download their own. Employees never."""
        if not self.can_approve_leaves:
            return False
        return self.pk == target.pk or self.is_admin or self.is_above(target)

    def can_review(self, applicant):
        """May this user approve/reject ``applicant``'s leave?"""
        if self.pk == applicant.pk or not self.can_approve_leaves:
            return False
        return self.is_admin or self.is_above(applicant)


def search_employees(query):
    """Google-style lookup by name (any word order, partial) or employee ID."""
    query = (query or "").strip()
    if not query:
        return User.objects.none()
    name_q = Q()
    for token in query.split():
        name_q &= Q(full_name__icontains=token)
    cond = Q(employee_id__iexact=query) | Q(employee_id__icontains=query) | name_q
    return User.objects.filter(is_active=True).filter(cond).select_related("manager").order_by("full_name")


class LoginAttempt(models.Model):
    """Failed-login counters used for brute-force lockout (see accounts/throttle.py)."""

    key = models.CharField(max_length=120, unique=True)
    failures = models.PositiveIntegerField(default=0)
    last_failure = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.key} ({self.failures})"
