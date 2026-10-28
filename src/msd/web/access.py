"""Who may see a workspace, and in which role. Every workspace view runs inside the workspace's
row-level-security scope, so even a query that forgets its filter sees only this workspace."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404

from msd.tenancy.models import Membership, Workspace
from msd.tenancy.scope import workspace_scope


def workspace_view(roles: tuple[str, ...] = ("analyst", "manager", "client")) -> Callable[..., Any]:
    def deco(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @login_required
        @wraps(view)
        def wrapper(request: HttpRequest, slug: str, *args: Any, **kwargs: Any) -> HttpResponse:
            ws = get_object_or_404(Workspace, slug=slug)
            m = Membership.objects.filter(user_id=request.user.pk or 0, workspace=ws).first()
            if m is None:
                raise Http404("no such workspace")  # do not confirm it exists
            if m.role not in roles:
                return HttpResponseForbidden("Your role cannot do this here.")
            request.workspace, request.membership = ws, m  # type: ignore[attr-defined]
            with workspace_scope(ws.pk):
                return view(request, *args, **kwargs)

        return wrapper

    return deco
