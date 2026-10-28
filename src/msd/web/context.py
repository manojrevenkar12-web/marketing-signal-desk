from __future__ import annotations

from typing import Any

from django.http import HttpRequest

NAV = [("overview", "Overview"), ("ask", "Ask"), ("proposals", "Proposals"), ("checks", "Data checks"), ("connections", "Connections"), ("audit", "Audit trail")]


def ui(request: HttpRequest) -> dict[str, Any]:
    return {"nav": NAV}
