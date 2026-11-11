from django import forms
from .models import SupportRequest


class SupportForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["subject", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 6, "placeholder": "Describe the issue and any steps you have tried."})}


class StatusForm(forms.ModelForm):
    class Meta:
        model = SupportRequest
        fields = ["status"]
