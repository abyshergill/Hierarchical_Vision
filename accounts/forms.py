from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.validators import MaxLengthValidator

from .models import User
from .sanitize import SecureImageField, clean_text, image_widget_attrs

IMAGE_FIELDS = ("profile_picture", "background_image")


class EmployeeLoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Employee ID or email"
        self.fields["username"].widget.attrs.update({"autofocus": True, "placeholder": "EMP-105"})


class ProfileSelfForm(forms.ModelForm):
    """The ONLY fields a regular user may change on their own profile."""

    remove_profile_picture = forms.BooleanField(required=False, label="Remove my current profile picture")
    remove_background_image = forms.BooleanField(required=False, label="Remove my current background image")

    class Meta:
        model = User
        fields = ["contact_info", "description", "profile_picture", "background_image"]
        field_classes = {"profile_picture": SecureImageField, "background_image": SecureImageField}
        widgets = {
            "contact_info": forms.TextInput(attrs={"placeholder": "Phone, LINE, desk location ...", "maxlength": 255}),
            "description": forms.Textarea(attrs={"rows": 5, "maxlength": 2000, "placeholder": "Tell colleagues a little about yourself"}),
            "profile_picture": forms.FileInput(attrs=image_widget_attrs()),
            "background_image": forms.FileInput(attrs=image_widget_attrs()),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["profile_picture"].label = "Profile picture"
        self.fields["background_image"].label = "Background image"
        self.fields["description"].max_length = 2000
        self.fields["description"].validators.append(MaxLengthValidator(2000))
        # remember stored files so replaced / removed ones can be deleted after a successful save
        self._old_files = {n: getattr(self.instance, n).name or "" for n in IMAGE_FIELDS}

    def clean_contact_info(self):
        return clean_text(self.cleaned_data.get("contact_info"), multiline=False)

    def clean_description(self):
        return clean_text(self.cleaned_data.get("description"))

    def clean(self):
        data = super().clean()
        for name in IMAGE_FIELDS:
            if data.get(f"remove_{name}") and not self.files.get(name):    # a freshly chosen file always wins
                data[name] = False                                          # FileField convention for "clear"
        return data

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            for name in IMAGE_FIELDS:
                old, new = self._old_files.get(name), getattr(user, name).name or ""
                if old and old != new:
                    try:
                        user._meta.get_field(name).storage.delete(old)
                    except Exception:            # never fail a profile save because an old file was already gone
                        pass
        return user


class UserAdminForm(forms.ModelForm):
    """Admin-only: create users and wire up the hierarchy."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, required=False, strip=False)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, required=False, strip=False)

    class Meta:
        model = User
        fields = [
            "employee_id", "full_name", "email", "position", "role", "manager",
            "newsletter_publisher", "contact_info", "description", "profile_picture", "background_image", "is_active",
        ]
        field_classes = {"profile_picture": SecureImageField, "background_image": SecureImageField}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "profile_picture": forms.ClearableFileInput(attrs=image_widget_attrs()),
            "background_image": forms.ClearableFileInput(attrs=image_widget_attrs()),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(is_active=True).order_by("full_name")
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        self.fields["manager"].queryset = qs
        self.fields["manager"].required = False
        creating = self.instance.pk is None
        self.fields["password1"].required = creating
        self.fields["password2"].required = creating
        if not creating:
            self.fields["password1"].help_text = "Leave blank to keep the current password."

    def clean_full_name(self):
        return clean_text(self.cleaned_data.get("full_name"), multiline=False)

    def clean_position(self):
        return clean_text(self.cleaned_data.get("position"), multiline=False)

    def clean_description(self):
        return clean_text(self.cleaned_data.get("description"))

    def clean_employee_id(self):
        return self.cleaned_data["employee_id"].strip().upper()

    def clean(self):
        cleaned = super().clean()
        # Never let the last active Admin be demoted or deactivated - nobody could manage the system afterwards.
        if self.instance.pk and self.instance.is_admin and self.instance.is_active:
            still_admin = cleaned.get("role", self.instance.role) == "admin" and cleaned.get("is_active", True)
            if not still_admin and not User.objects.filter(role="admin", is_active=True).exclude(pk=self.instance.pk).exists():
                raise forms.ValidationError("This is the last active Admin - promote someone else before changing this account.")
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Passwords do not match.")
            else:
                try:
                    validate_password(p1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            self.save_m2m()
        return user
