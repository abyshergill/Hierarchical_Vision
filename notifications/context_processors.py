from .models import Notification


def unread_notifications(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return {"unread_count": Notification.objects.filter(recipient=user, is_read=False).count()}
    return {}
