"""Small helpers shared by the views and the sidebar template tag."""
from django.db.models import Q

from accounts.models import Role, User

from .models import GroupAccessRequest, GroupMembership

MANAGER, MEMBER, PENDING = "manager", "member", "pending"


def group_states(user, groups):
    """{group_id: 'manager' | 'member' | 'pending'} for one signed-in user (two queries, whatever the group count)."""
    if not (user.is_authenticated and user.is_active):
        return {}
    ids = [g.pk for g in groups]
    states = {}
    pending = GroupAccessRequest.objects.filter(user=user, group_id__in=ids, status=GroupAccessRequest.Status.PENDING)
    states.update({gid: PENDING for gid in pending.values_list("group_id", flat=True)})
    states.update({gid: MEMBER for gid in GroupMembership.objects.filter(user=user, group_id__in=ids).values_list("group_id", flat=True)})
    for g in groups:
        if user.is_admin or g.manager_id == user.pk:
            states[g.pk] = MANAGER
    return states


def approvers(group):
    """Who should hear about a new access request: the group manager, otherwise every active Admin."""
    if group.manager_id and group.manager.is_active:
        return [group.manager]
    return list(User.objects.filter(is_active=True, role=Role.ADMIN))
