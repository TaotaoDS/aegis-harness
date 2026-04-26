"""Shared slowapi Limiter instance.

Defined in its own module to avoid circular imports between main.py and routes.

Usage in route files::

    from api.rate_limit import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    async def login(request: Request, ...):
        ...

The limiter is wired into the FastAPI app inside ``api/main.py``::

    from api.rate_limit import limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
