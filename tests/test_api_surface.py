"""Drift guards for the public API surface.

The compiled module (`_processkit`), the hand-written type stub
(`_processkit.pyi`), and the package's `__all__` are three parallel mirrors of
one surface. Nothing makes them agree automatically, so these tests fail loudly
when they drift — a new/removed Rust class, method, property, or exception base
that wasn't reflected in the stub or the re-exports.
"""

from __future__ import annotations

import ast
import pathlib

import processkit
from processkit import _processkit


def _public_names(obj: object) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_")}


def _stub_classes() -> dict[str, ast.ClassDef]:
    stub_path = pathlib.Path(processkit.__file__).with_name("_processkit.pyi")
    assert stub_path.is_file(), f"type stub not found at {stub_path}"
    tree = ast.parse(stub_path.read_text(encoding="utf-8"))
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def _declared_members(classdef: ast.ClassDef) -> set[str]:
    members: set[str] = set()
    for stmt in classdef.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            members.add(stmt.name)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            members.add(stmt.target.id)
    return members


def _compiled_classes() -> dict[str, type]:
    return {
        name: obj
        for name in _public_names(_processkit)
        if isinstance(obj := getattr(_processkit, name), type)
    }


def test_all_is_sorted_unique_and_importable() -> None:
    assert processkit.__all__ == sorted(processkit.__all__)
    assert len(processkit.__all__) == len(set(processkit.__all__))
    for name in processkit.__all__:
        assert hasattr(processkit, name), f"__all__ lists {name!r} but it is not importable"


def test_every_compiled_export_is_reexported() -> None:
    missing = _public_names(_processkit) - set(processkit.__all__)
    assert not missing, f"compiled names not re-exported in processkit.__all__: {sorted(missing)}"


def test_every_compiled_class_is_declared_in_the_stub() -> None:
    missing = set(_compiled_classes()) - set(_stub_classes())
    assert not missing, f"compiled classes missing from _processkit.pyi: {sorted(missing)}"


def test_stub_has_no_dead_class_entries() -> None:
    # Every class declared in the stub must exist in the compiled module — a
    # stub-only class is stale documentation that lies to IDEs and type checkers.
    extra = set(_stub_classes()) - _public_names(_processkit)
    assert not extra, (
        f"_processkit.pyi declares classes not exported by the module: {sorted(extra)}"
    )


def test_compiled_class_members_match_the_stub() -> None:
    # Methods and properties of each pyclass (exceptions excluded — their fields
    # are instance attributes set at raise time, not type members) must be
    # declared in the stub, so a new/renamed method can't silently go unstubbed.
    stub = _stub_classes()
    for name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        own = {member for member in vars(cls) if not member.startswith("_")}
        declared = _declared_members(stub[name])
        missing = own - declared
        assert not missing, f"{name}: members missing from stub: {sorted(missing)}"


def test_stub_has_no_dead_class_members() -> None:
    # Reverse of the member-parity check: every public method/property declared
    # in the stub for a (non-exception) pyclass must exist at runtime, so a
    # stub-only entry can't drift into stale documentation.
    stub = _stub_classes()
    for name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        runtime = {m for m in vars(cls) if not m.startswith("_")}
        declared = {m for m in _declared_members(stub[name]) if not m.startswith("_")}
        extra = declared - runtime
        assert not extra, f"{name}: stub declares members not present at runtime: {sorted(extra)}"


def test_context_manager_protocol_is_declared() -> None:
    # The `__enter__`/`__exit__`/`__aenter__`/`__aexit__` dunders are excluded
    # from the member-parity check (leading underscore), so guard them explicitly
    # for the classes that promise the (async) context-manager protocol.
    stub = _stub_classes()
    protocol = ("__enter__", "__exit__", "__aenter__", "__aexit__")
    for name in ("RunningProcess", "ProcessGroup"):
        cls = getattr(_processkit, name)
        declared = _declared_members(stub[name])
        for dunder in protocol:
            assert hasattr(cls, dunder), f"{name} lost {dunder} at runtime"
            assert dunder in declared, f"{name}.{dunder} missing from the stub"


def test_dual_base_exceptions_match_stdlib_and_stub() -> None:
    # The stdlib aliasing is the whole point of these exceptions; assert it
    # both at runtime and in the stub so none can regress silently.
    assert issubclass(processkit.Timeout, TimeoutError)
    assert issubclass(processkit.ProcessNotFound, FileNotFoundError)
    assert issubclass(processkit.PermissionDenied, PermissionError)
    stub = _stub_classes()

    def stub_bases(classdef: ast.ClassDef) -> set[str]:
        return {base.id for base in classdef.bases if isinstance(base, ast.Name)}

    assert {"ProcessError", "TimeoutError"} <= stub_bases(stub["Timeout"])
    assert {"ProcessError", "FileNotFoundError"} <= stub_bases(stub["ProcessNotFound"])
    assert {"ProcessError", "PermissionError"} <= stub_bases(stub["PermissionDenied"])
