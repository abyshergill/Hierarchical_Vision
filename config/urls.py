from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from accounts.models import User
from newsletter.models import PostImage
from django.views.static import serve


def protected_media(request, path):
    """Only published company-newsletter images and active users' avatars are public.

    Pictures that belong to a private newsletter group are served only to that group's members, its manager and
    Admins. All other uploads, including background images, require authentication.
    Production web servers must route media through this view (see README).
    """
    from django.contrib.auth.views import redirect_to_login
    from django.core.exceptions import PermissionDenied

    user = request.user
    news = PostImage.objects.select_related("post__group").filter(image=path).first()
    if news is not None and news.post.group_id:
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not news.post.group.can_access(user):
            raise PermissionDenied
    elif not user.is_authenticated:
        public_avatar = User.objects.filter(is_active=True, profile_picture=path).exists()
        if not (public_avatar or news is not None):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("media/<path:path>", protected_media, name="media"),
    path("leaves/", include("leaves.urls")),
    path("notifications/", include("notifications.urls")),
    path("newsletter/", include("newsletter.urls")),
    path("support/", include("support.urls")),
    path("", include("accounts.urls")),
]
