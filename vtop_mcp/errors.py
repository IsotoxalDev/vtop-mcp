class VtopError(RuntimeError):
    """Raised when VTOP returns an unexpected or unparsable response."""


class NotLoggedInError(VtopError):
    """Raised when a tool needs an authenticated session and none is present."""
