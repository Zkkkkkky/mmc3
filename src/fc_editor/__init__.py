"""Core package for the FC Super Robot Wars 2 ROM editor."""

from .changes import ChangeConflictError, ChangeSet, PatchOperation
from .errors import ProjectFormatError, RomFormatError
from .project import ProjectDocument
from .resources import Allocation, BankAllocator, ResourceGraph, ResourceNode, ResourceReference
from .rom_image import BankAddress, RomImage
from .unit_package import UnitPackage, UnitPackageAsset
from .text_table import TextTable

__all__ = [
    "BankAddress",
    "BankAllocator",
    "Allocation",
    "ChangeConflictError",
    "ChangeSet",
    "PatchOperation",
    "ProjectDocument",
    "ProjectFormatError",
    "ResourceGraph",
    "ResourceNode",
    "ResourceReference",
    "UnitPackage",
    "UnitPackageAsset",
    "TextTable",
    "RomFormatError",
    "RomImage",
]
