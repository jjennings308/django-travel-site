"""Who is making the current request, for code that has no request (model signals).

``CurrentUserMiddleware`` sets it for the length of each request; outside a request (management
commands, the shell) it is ``None``. A ``ContextVar``, so concurrent requests in threads or async
tasks never see each other's user.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_user = ContextVar("sbl_current_user", default=None)


def get_user():
    """The signed-in user making this request, or None."""
    user = _user.get()
    return user if user is not None and getattr(user, "is_authenticated", False) else None


@contextmanager
def acting_as(user):
    token = _user.set(user)
    try:
        yield
    finally:
        _user.reset(token)
