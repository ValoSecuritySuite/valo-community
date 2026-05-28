"""HTTP middleware components for the Valo API.

Currently exposes :class:`PolicyEnforcementMiddleware`, the inline AI Firewall
that turns advisory ``allow / warn / deny`` decisions into real-time
enforcement at the request edge.
"""

from app.middleware.policy_enforcement import PolicyEnforcementMiddleware

__all__ = ["PolicyEnforcementMiddleware"]
