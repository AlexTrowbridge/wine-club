from .permissions import is_organiser, member_for


def club(request):
    user = getattr(request, "user", None)
    if user is None:
        return {}
    return {"is_organiser": is_organiser(user), "me": member_for(user)}
