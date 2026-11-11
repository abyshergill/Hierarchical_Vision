from django import forms
from django.conf import settings

from accounts.models import Role, User
from accounts.sanitize import SecureImageField, clean_text, image_widget_attrs

from .models import NewsGroup, Post, PostImage


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(SecureImageField):
    """Several pictures from one <input multiple>. Every file goes through the same checks as a profile picture:
    .jpg/.jpeg/.png only, size cap, real-format check with Pillow and a metadata-stripping re-encode."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs=image_widget_attrs(multiple=True)))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        files = data if isinstance(data, (list, tuple)) else [data]
        return [single(f, initial) for f in files if f]


class PostForm(forms.ModelForm):
    body = forms.CharField(max_length=5000, widget=forms.Textarea(attrs={"rows": 9}), help_text="Plain text. Line breaks and web links are kept.")
    images = MultipleImageField(required=False, help_text="Optional. JPG, JPEG or PNG.")
    remove_images = forms.ModelMultipleChoiceField(
        queryset=PostImage.objects.none(), required=False, widget=forms.CheckboxSelectMultiple, label="Remove images"
    )
    notify_everyone = forms.BooleanField(required=False, label="Notify everyone about this post")

    class Meta:
        model = Post
        fields = ["title", "body", "is_pinned"]

    def __init__(self, *args, user, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.group = group or (self.instance.group if self.instance.pk else None)
        self.max_mb = settings.MAX_IMAGE_UPLOAD_MB
        self.max_images = settings.NEWSLETTER_MAX_IMAGES
        self.fields["images"].widget.attrs["data-max-files"] = str(settings.NEWSLETTER_MAX_IMAGES)
        self.fields["images"].help_text += (
            f" Up to {settings.NEWSLETTER_MAX_IMAGES} per post, {settings.MAX_IMAGE_UPLOAD_MB} MB each."
        )
        if self.instance.pk:
            self.fields["remove_images"].queryset = self.instance.images.all()
        else:
            del self.fields["remove_images"]
        can_pin = user.is_admin or bool(self.group and self.group.can_manage(user))
        if not can_pin:                            # pinning: Admins everywhere, group managers inside their group
            del self.fields["is_pinned"]
        if self.group or not user.is_admin:        # mass notification: Admin, company-wide posts only
            del self.fields["notify_everyone"]

    def clean_title(self):
        title = clean_text(self.cleaned_data.get("title"), multiline=False)
        if not title:
            raise forms.ValidationError("Enter a title.")
        return title

    def clean_body(self):
        body = clean_text(self.cleaned_data.get("body"))
        if not body:
            raise forms.ValidationError("Enter some text.")
        return body

    def clean(self):
        data = super().clean()
        new = data.get("images") or []
        removing = data.get("remove_images")
        existing = self.instance.images.count() if self.instance.pk else 0
        total = existing - (len(removing) if removing else 0) + len(new)
        if total > settings.NEWSLETTER_MAX_IMAGES:
            self.add_error("images", f"A post can have at most {settings.NEWSLETTER_MAX_IMAGES} images (this would be {total}).")
        return data


class CommentForm(forms.Form):
    body = forms.CharField(max_length=1000, strip=True, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_body(self):
        body = clean_text(self.cleaned_data.get("body"))
        if not body:
            raise forms.ValidationError("Enter a comment.")
        return body


class GroupForm(forms.ModelForm):
    """Admin-only: create / rename a department group and assign its manager."""

    class Meta:
        model = NewsGroup
        fields = ["name", "description", "manager"]
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. Test Manufacturing"}),
                   "description": forms.Textarea(attrs={"rows": 3, "maxlength": 300, "placeholder": "What is this group for? Who should join?"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_active=True, role=Role.MANAGER).order_by("full_name")
        self.fields["manager"].required = False
        self.fields["manager"].empty_label = "— no manager yet (Admins manage it) —"
        self.fields["manager"].label_from_instance = lambda u: f"{u.full_name} ({u.employee_id})"
        self.fields["manager"].help_text = "Managers only. They approve access requests and moderate the group."

    def clean_name(self):
        name = clean_text(self.cleaned_data.get("name"), multiline=False)
        if len(name) < 2:
            raise forms.ValidationError("Enter a group name (at least 2 characters).")
        clash = NewsGroup.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A group with this name already exists.")
        return name

    def clean_description(self):
        return clean_text(self.cleaned_data.get("description"), multiline=False)


class AccessRequestForm(forms.Form):
    message = forms.CharField(max_length=300, required=False, strip=True, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_message(self):
        return clean_text(self.cleaned_data.get("message"), multiline=False)
