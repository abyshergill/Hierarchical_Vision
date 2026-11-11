import logging

from django.conf import settings
from django.core.mail import send_mail

from .models import Notification

logger = logging.getLogger(__name__)


def notify(recipient, title, message="", url="", send_email=True):
    """Create an in-app notification and (best effort) e-mail it."""
    title = " ".join(str(title).split())[:160]
    note = Notification.objects.create(recipient=recipient, title=title, message=message, url=url)
    if send_email and recipient.email:
        try:
            send_mail(title, message, settings.DEFAULT_FROM_EMAIL, [recipient.email], fail_silently=False)
        except Exception:  # never let a mail outage break leave workflows
            logger.exception("Could not e-mail notification %s", note.pk)
    return note


def broadcast(sender, recipients, title, message="", url="", audience="selected", send_email=False):
    """Push one notification to many people with a single bulk insert (+ optional e-mail).

    Only call this from views that already verified ``sender.is_admin``.
    """
    from django.core.mail import send_mass_mail

    from .models import Broadcast

    title = " ".join(str(title).split())[:160]
    recipients = list(recipients)
    Notification.objects.bulk_create(
        [Notification(recipient=u, title=title, message=message, url=url) for u in recipients], batch_size=500
    )
    emailed = False
    if send_email:
        mails = [(title, message, settings.DEFAULT_FROM_EMAIL, [u.email]) for u in recipients if u.email]
        if mails:
            try:
                send_mass_mail(mails, fail_silently=False)
                emailed = True
            except Exception:
                logger.exception("Could not e-mail broadcast %r", title)
    return Broadcast.objects.create(
        sent_by=sender, title=title, message=message, url=url, audience=audience,
        recipient_count=len(recipients), emailed=emailed,
    )
