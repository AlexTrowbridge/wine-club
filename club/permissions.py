from functools import wraps

from django.core.exceptions import PermissionDenied

ORGANISER_GROUP = "Organiser"


def is_organiser(user) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    # Cache on the user object: this is checked many times per page.
    if not hasattr(user, "_is_organiser"):
        user._is_organiser = user.groups.filter(name=ORGANISER_GROUP).exists()
    return user._is_organiser


def member_for(user):
    if not user.is_authenticated:
        return None
    return getattr(user, "member", None)


def can_see_scores(user, session) -> bool:
    """Members only see other people's scores once a session is revealed or closed."""
    return session.status != session.Status.OPEN or session.scores_revealed or is_organiser(user)


def can_rate(user, tasting, member) -> bool:
    if is_organiser(user):
        return True
    own = member_for(user)
    return own is not None and own.pk == member.pk and tasting.session.is_open


def organiser_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_organiser(request.user):
            raise PermissionDenied("Organisers only")
        return view(request, *args, **kwargs)

    return wrapper
