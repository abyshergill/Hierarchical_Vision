from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from . import throttle


class EmployeeIdOrEmailBackend(ModelBackend):
    """Sign in with Employee ID or e-mail, with brute-force lock-out.

    Raising PermissionDenied makes ``authenticate()`` stop and return None, so a locked
    account/IP is refused even if the password is correct. Applies to the admin login too.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        username = username or kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        if throttle.is_locked(request, username):
            raise PermissionDenied("Too many failed attempts.")
        user = User.objects.filter(Q(employee_id__iexact=username) | Q(email__iexact=username)).first()
        if user is None:
            User().set_password(password)  # equalise timing so unknown IDs cannot be detected
        elif user.check_password(password) and self.user_can_authenticate(user):
            throttle.reset(request, username)
            return user
        throttle.register_failure(request, username)
        return None
