from django import forms

from accounts.models import Role, User

from .models import Broadcast


class BroadcastForm(forms.Form):
    audience = forms.ChoiceField(choices=Broadcast.Audience.choices, initial=Broadcast.Audience.ALL, widget=forms.RadioSelect)
    recipients = forms.ModelMultipleChoiceField(queryset=User.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    title = forms.CharField(max_length=160)
    message = forms.CharField(max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 5}))
    url = forms.CharField(
        max_length=300, required=False, label="Link (optional)",
        help_text="An address inside this site, e.g. /newsletter/ or /leaves/holidays/.",
    )
    send_email = forms.BooleanField(required=False, label="Also send by e-mail")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipients"].queryset = User.objects.filter(is_active=True).order_by("full_name")

    def clean_url(self):
        url = self.cleaned_data["url"].strip()
        if url and (not url.startswith("/") or url.startswith("//") or "\\" in url or "\n" in url):
            raise forms.ValidationError("Use a path on this site that starts with a single '/'.")
        return url

    def clean(self):
        data = super().clean()
        if data.get("audience") == Broadcast.Audience.SELECTED and not data.get("recipients"):
            self.add_error("recipients", "Choose at least one person.")
        return data

    def resolve_recipients(self):
        audience = self.cleaned_data["audience"]
        active = User.objects.filter(is_active=True)
        if audience == Broadcast.Audience.ALL:
            return active
        if audience == Broadcast.Audience.MANAGERS:
            return active.filter(role=Role.MANAGER)
        if audience == Broadcast.Audience.EMPLOYEES:
            return active.filter(role=Role.EMPLOYEE)
        return self.cleaned_data["recipients"]
