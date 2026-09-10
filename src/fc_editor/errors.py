class RomFormatError(ValueError):
    """Raised when a ROM does not match the supported layout."""


class ProjectFormatError(ValueError):
    """Raised when a project file is malformed or targets another base ROM."""


class ChangeConflictError(ValueError):
    """Raised when two editor modules attempt incompatible overlapping writes."""
