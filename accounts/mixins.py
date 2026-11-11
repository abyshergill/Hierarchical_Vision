from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class AdminRequiredMixin(LoginRequiredMixin):
    """Anonymous -> login page; signed-in non-admin -> 403."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_admin:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(LoginRequiredMixin):
    """Managers and Admins only."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.can_approve_leaves:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
