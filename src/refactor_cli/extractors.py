"""
LibCST-based extraction strategies for refactoring operations.
"""

import re
from typing import Dict, List, Set
import libcst as cst


class ConstantExtractor(cst.CSTVisitor):
    """Extract regex constants and configuration constants from code."""

    def __init__(self):
        self.regex_constants: Dict[str, str] = {}
        self.config_constants: Dict[str, str] = {}

    def visit_Assign(self, node: cst.Assign) -> None:
        """Visit assignment statements to find constants."""
        if not isinstance(node.targets[0].target, cst.Name):
            return

        const_name = node.targets[0].target.value

        # Check if it's a constant (UPPER_CASE)
        if not const_name.isupper():
            return

        # Extract value as string
        value_str = self._extract_value(node.value)

        # Classify by type
        if "re.compile" in value_str:
            self.regex_constants[const_name] = value_str
        elif const_name.endswith("PATH") or const_name.endswith("URL"):
            self.config_constants[const_name] = value_str

    def _extract_value(self, node) -> str:
        """Extract a human-readable representation of a value."""
        if isinstance(node, cst.Call):
            func_name = self._get_name(node.func)
            return f"{func_name}(...)"
        elif isinstance(node, cst.SimpleString):
            value = node.value[:50]
            return f'"{value}..."' if len(node.value) > 50 else node.value
        else:
            return str(type(node).__name__)

    def _get_name(self, node) -> str:
        """Extract function or attribute name."""
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            return f"{self._get_name(node.value)}.{node.attr.value}"
        return "???"


class ParkingDomainExtractor(cst.CSTVisitor):
    """Extract parking domain symbols (classes, functions, constants)."""

    PARKING_CLASSES = {"Layout", "LotDescription"}
    PARKING_REGEX = {"LOT_HEADER_RE", "TOP_RE", "LAYOUT_RE", "COORDS_RE", "DMS_RE"}
    PARKING_FUNCTIONS = {
        "parse_dms",
        "parse_segments",
        "parse_parking_file",
        "interpolate",
        "bilinear_interpolate",
        "get_google_maps_url",
        "get_google_maps_box_url",
        "command_url_get",
        "command_url_box",
    }

    def __init__(self):
        self.classes: List[str] = []
        self.constants: Set[str] = set()
        self.functions: List[str] = []
        self.imports: List[str] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Visit class definitions."""
        class_name = node.name.value
        if class_name in self.PARKING_CLASSES:
            self.classes.append(class_name)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Visit function definitions."""
        func_name = node.name.value
        if func_name in self.PARKING_FUNCTIONS:
            self.functions.append(func_name)

    def visit_Assign(self, node: cst.Assign) -> None:
        """Visit assignments to find regex constants."""
        if not isinstance(node.targets[0].target, cst.Name):
            return

        const_name = node.targets[0].target.value
        if const_name in self.PARKING_REGEX:
            self.constants.add(const_name)


class CodeStructureAnalyzer(cst.CSTVisitor):
    """Analyze overall code structure and organization."""

    def __init__(self):
        self.classes: List[str] = []
        self.functions: List[str] = []
        self.imports: List[str] = []
        self.constants: Set[str] = set()
        self.decorators: Dict[str, List[str]] = {}

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        """Visit class definitions."""
        class_name = node.name.value
        self.classes.append(class_name)

        # Track decorators
        if node.decorators:
            decorator_names = []
            for decorator in node.decorators:
                dec_str = self._decorator_to_string(decorator.decorator)
                decorator_names.append(dec_str)
            if decorator_names:
                self.decorators[class_name] = decorator_names

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Visit function definitions."""
        func_name = node.name.value
        self.functions.append(func_name)

    def visit_ImportFrom(self, node: cst.ImportFrom) -> None:
        """Visit import statements."""
        module = self._get_import_module(node.module)
        self.imports.append(module)

    def visit_Import(self, node: cst.Import) -> None:
        """Visit simple imports."""
        for name in node.names:
            if isinstance(name, cst.ImportAlias):
                self.imports.append(self._get_name(name.name))

    def visit_Assign(self, node: cst.Assign) -> None:
        """Visit assignments to find constants."""
        if isinstance(node.targets[0].target, cst.Name):
            const_name = node.targets[0].target.value
            if const_name.isupper():
                self.constants.add(const_name)

    def _decorator_to_string(self, node) -> str:
        """Convert decorator node to string representation."""
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Call):
            if isinstance(node.func, cst.Name):
                return f"{node.func.value}(...)"
            return "decorator(...)"
        else:
            return "decorator"

    def _get_import_module(self, node) -> str:
        """Extract module name from import."""
        if node is None:
            return "."
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            return f"{self._get_import_module(node.value)}.{node.attr.value}"
        return "unknown"

    def _get_name(self, node) -> str:
        """Extract name from import node."""
        if isinstance(node, cst.Name):
            return node.value
        elif isinstance(node, cst.Attribute):
            return f"{self._get_name(node.value)}.{node.attr.value}"
        return "unknown"
