"""Drift guards for the public API surface.

The compiled module (`_processkit`), the hand-written type stub
(`_processkit.pyi`), and the package's `__all__` are three parallel mirrors of
one surface. Nothing makes them agree automatically, so these tests fail loudly
when they drift — a new/removed Rust class, method, property, or exception base
that wasn't reflected in the stub or the re-exports.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import re
import types
from collections.abc import Callable

import pytest

import processkit
import processkit.testing
from processkit import _aio, _processkit, _protocols, _types

# The runner test doubles live in the `processkit.testing` submodule, not the
# top-level surface; both re-export from the same compiled `_processkit`.
_TESTING_DOUBLES = {
    "Invocation",
    "RecordReplayRunner",
    "RecordingRunner",
    "Reply",
    "ScriptedRunner",
}

# `_RunnerVerbs` is a private, stub-only base (`_processkit.pyi`) that
# de-duplicates the run-verb surface five runtime classes (`ProcessGroup`,
# `Runner`, `ScriptedRunner`, `RecordReplayRunner`, `RecordingRunner`) each
# implement independently in Rust — there is no such class at runtime, by
# design (see the stub's own docstring on it).
_STUB_ONLY_BASES = {"_RunnerVerbs"}


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


def _stub_bases(
    classdef: ast.ClassDef, stub_classes: dict[str, ast.ClassDef]
) -> list[ast.ClassDef]:
    """The stub-declared base `ClassDef`s of `classdef` that are themselves
    stub classes (e.g. `_RunnerVerbs`) — skips builtin/stdlib bases
    (`Exception`, `TimeoutError`, …), which aren't stub-declared classes."""
    return [
        stub_classes[base.id]
        for base in classdef.bases
        if isinstance(base, ast.Name) and base.id in stub_classes
    ]


def _declared_members_with_bases(
    classdef: ast.ClassDef, stub_classes: dict[str, ast.ClassDef]
) -> set[str]:
    """`_declared_members`, also walking stub-only bases (`_RunnerVerbs`): a
    runtime class implements those members directly (no real inheritance),
    but the stub factors the shared declarations into one base to avoid N
    identical copies — so member/signature parity must look there too."""
    members = _declared_members(classdef)
    for base in _stub_bases(classdef, stub_classes):
        members |= _declared_members_with_bases(base, stub_classes)
    return members


def _stub_member_is_property(
    classdef: ast.ClassDef, name: str, stub_classes: dict[str, ast.ClassDef] | None = None
) -> bool:
    """Whether the stub declares `name` with an `@property` decorator — in
    `classdef` itself, or (if `stub_classes` is given) in a stub-only base."""
    for stmt in classdef.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and stmt.name == name:
            return any(isinstance(d, ast.Name) and d.id == "property" for d in stmt.decorator_list)
    if stub_classes is not None:
        for base in _stub_bases(classdef, stub_classes):
            if name in _declared_members(base):
                return _stub_member_is_property(base, name, stub_classes)
    return False


def _runtime_is_data_descriptor(cls: type, name: str) -> bool:
    """Whether `cls.name` is a read accessor at runtime — a Python `property` or a
    PyO3 `#[getter]` (which is a `getset_descriptor`, NOT a `property`)."""
    attr = inspect.getattr_static(cls, name)
    return isinstance(attr, property | types.GetSetDescriptorType)


def _compiled_classes() -> dict[str, type]:
    return {
        name: obj
        for name in _public_names(_processkit)
        if isinstance(obj := getattr(_processkit, name), type)
    }


def _stub_module_functions() -> set[str]:
    stub_path = pathlib.Path(processkit.__file__).with_name("_processkit.pyi")
    tree = ast.parse(stub_path.read_text(encoding="utf-8"))
    return {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _compiled_functions() -> set[str]:
    # Module-level callables that are not classes — the batch verbs (output_all, …).
    return {
        name
        for name in _public_names(_processkit)
        if callable(obj := getattr(_processkit, name)) and not isinstance(obj, type)
    }


def test_package_importable() -> None:
    assert isinstance(processkit.__all__, list)


def test_version_is_exposed() -> None:
    # `__version__` is lazy (module `__getattr__`, PEP 562) — this is also the
    # one place that exercises it actually resolving to a real value.
    assert isinstance(processkit.__version__, str)
    assert processkit.__version__


def test_all_is_sorted_unique_and_importable() -> None:
    assert processkit.__all__ == sorted(processkit.__all__)
    assert len(processkit.__all__) == len(set(processkit.__all__))
    for name in processkit.__all__:
        assert hasattr(processkit, name), f"__all__ lists {name!r} but it is not importable"


def test_every_compiled_export_is_reexported() -> None:
    # Every compiled public name must surface either on the top-level package or
    # on the `processkit.testing` submodule (the test doubles).
    reexported = set(processkit.__all__) | set(processkit.testing.__all__)
    missing = _public_names(_processkit) - reexported
    assert not missing, f"compiled names not re-exported: {sorted(missing)}"


def test_top_level_all_covers_every_shim_modules_all() -> None:
    # The pure-Python "shim" modules (`_aio.py`, `_protocols.py`, `_types.py`)
    # each declare their own `__all__`, folded into the top-level
    # `processkit.__all__` by `__init__.py`'s re-exports. Nothing enforces that
    # fold-in automatically — a new helper added to a shim's `__all__` but
    # forgotten from the top-level list would otherwise ship silently
    # unexported.
    shim_all = set(_aio.__all__) | set(_protocols.__all__) | set(_types.__all__)
    missing = shim_all - set(processkit.__all__)
    assert not missing, f"shim-module exports missing from processkit.__all__: {sorted(missing)}"


def test_testing_submodule_exports_the_doubles_only() -> None:
    # The testing submodule exposes exactly the runner doubles, sorted/unique and
    # importable, and they are absent from the top-level surface (clean split).
    testing = processkit.testing
    assert set(testing.__all__) == _TESTING_DOUBLES
    assert testing.__all__ == sorted(testing.__all__)
    assert len(testing.__all__) == len(set(testing.__all__))
    for name in testing.__all__:
        assert hasattr(testing, name), f"testing.__all__ lists {name!r} but it is not importable"
    assert _TESTING_DOUBLES.isdisjoint(set(processkit.__all__)), (
        "test doubles must not be on the top-level surface"
    )


def test_every_compiled_class_is_declared_in_the_stub() -> None:
    missing = set(_compiled_classes()) - set(_stub_classes())
    assert not missing, f"compiled classes missing from _processkit.pyi: {sorted(missing)}"


def test_stub_has_no_dead_class_entries() -> None:
    # Every class declared in the stub must exist in the compiled module — a
    # stub-only class is stale documentation that lies to IDEs and type
    # checkers. `_STUB_ONLY_BASES` (`_RunnerVerbs`) is the deliberate
    # exception: a private, never-instantiated stub base with no runtime
    # counterpart by design.
    extra = set(_stub_classes()) - _public_names(_processkit) - _STUB_ONLY_BASES
    assert not extra, (
        f"_processkit.pyi declares classes not exported by the module: {sorted(extra)}"
    )


def test_compiled_class_members_match_the_stub() -> None:
    # Methods and properties of each pyclass (exceptions excluded — their fields
    # are instance attributes set at raise time, not type members) must be
    # declared in the stub (its own body, or a stub-only base's — e.g.
    # `_RunnerVerbs`), so a new/renamed method can't silently go unstubbed.
    stub = _stub_classes()
    for name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        own = {member for member in vars(cls) if not member.startswith("_")}
        declared = _declared_members_with_bases(stub[name], stub)
        missing = own - declared
        assert not missing, f"{name}: members missing from stub: {sorted(missing)}"


def test_stub_has_no_dead_class_members() -> None:
    # Reverse of the member-parity check: every public method/property declared
    # in the stub for a (non-exception) pyclass — including via a stub-only
    # base like `_RunnerVerbs` — must exist at runtime, so a stub-only entry
    # can't drift into stale documentation.
    stub = _stub_classes()
    for name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        runtime = {m for m in vars(cls) if not m.startswith("_")}
        declared = {
            m for m in _declared_members_with_bases(stub[name], stub) if not m.startswith("_")
        }
        extra = declared - runtime
        assert not extra, f"{name}: stub declares members not present at runtime: {sorted(extra)}"


def test_every_compiled_function_is_declared_in_the_stub() -> None:
    # Module-level functions (the batch verbs) must appear in the stub, so a new
    # or renamed one can't ship without its type signature.
    missing = _compiled_functions() - _stub_module_functions()
    assert not missing, f"compiled module functions missing from _processkit.pyi: {sorted(missing)}"


def test_stub_has_no_dead_module_functions() -> None:
    # Reverse: a module-level function in the stub must exist at runtime.
    extra = _stub_module_functions() - _compiled_functions()
    assert not extra, f"_processkit.pyi declares module functions not at runtime: {sorted(extra)}"


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


def test_every_package_exception_subclasses_process_error() -> None:
    # The "except ProcessError catches everything" contract: every exported
    # exception must remain a `ProcessError` subclass. The name-only member guard
    # cannot see a changed base, so a `Signalled`/`ResourceLimit`/… that regressed
    # to a different base would otherwise ship green.
    for name, cls in _compiled_classes().items():
        if not issubclass(cls, BaseException) or cls is processkit.ProcessError:
            continue
        assert issubclass(cls, processkit.ProcessError), f"{name} is no longer a ProcessError"


def test_property_vs_method_matches_stub() -> None:
    # A getter (`#[getter]`/`@property`) and a plain method share a member name, so
    # the name-only parity checks can't tell a property↔method flip apart. Compare
    # the descriptor *kind* at runtime against the stub's `@property` decorator, so
    # e.g. `combined` silently reverting from a property to a method fails here.
    stub = _stub_classes()
    for name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        for member in vars(cls):
            if member.startswith("_"):
                continue
            runtime_prop = _runtime_is_data_descriptor(cls, member)
            stub_prop = _stub_member_is_property(stub[name], member, stub)
            assert runtime_prop == stub_prop, (
                f"{name}.{member}: property/method mismatch "
                f"(runtime property={runtime_prop}, stub @property={stub_prop})"
            )


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


def _section_version(text: str, section: str) -> str | None:
    """Extract `version = "..."` from a named TOML `[section]` table.

    A deliberately tiny TOML reader — `tomllib` is 3.11+ and the floor is 3.10.
    Scans for the `[section]` header and returns the first `version = "..."`
    before the next table header.
    """
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section:
            match = re.match(r'version\s*=\s*"([^"]+)"', stripped)
            if match:
                return match.group(1)
    return None


# --- parameter-level signature drift (E2) -----------------------------------

# A normalized parameter: (name, `inspect._ParameterKind` name, has-a-default).
_Param = tuple[str, str, bool]


def _runtime_params(sig: inspect.Signature) -> list[_Param]:
    params = [p for p in sig.parameters.values() if p.name not in ("self", "cls")]
    return [(p.name, p.kind.name, p.default is not inspect.Parameter.empty) for p in params]


def _stub_params(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_Param]:
    a = fn.args
    result: list[_Param] = []
    for arg in a.posonlyargs:
        result.append((arg.arg, "POSITIONAL_ONLY", False))
    n_no_default = len(a.args) - len(a.defaults)
    for i, arg in enumerate(a.args):
        result.append((arg.arg, "POSITIONAL_OR_KEYWORD", i >= n_no_default))
    if a.vararg:
        result.append((a.vararg.arg, "VAR_POSITIONAL", False))
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        result.append((arg.arg, "KEYWORD_ONLY", default is not None))
    if a.kwarg:
        result.append((a.kwarg.arg, "VAR_KEYWORD", False))
    return [p for p in result if p[0] not in ("self", "cls")]


_StubFn = ast.FunctionDef | ast.AsyncFunctionDef
_CallablePair = tuple[str, Callable[..., object], _StubFn]


def _stub_funcdefs(body: list[ast.stmt]) -> dict[str, _StubFn]:
    return {
        node.name: node for node in body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _stub_funcdefs_with_bases(
    classdef: ast.ClassDef, stub_classes: dict[str, ast.ClassDef]
) -> dict[str, _StubFn]:
    """`_stub_funcdefs`, also walking stub-only bases (`_RunnerVerbs`) — see
    `_declared_members_with_bases`. A method declared on both the class and a
    base (there are none today) would resolve to the class's own version,
    matching normal MRO lookup order."""
    funcs: dict[str, _StubFn] = {}
    for base in _stub_bases(classdef, stub_classes):
        funcs |= _stub_funcdefs_with_bases(base, stub_classes)
    funcs |= _stub_funcdefs(classdef.body)
    return funcs


def _iter_callables_with_stub_defs() -> list[_CallablePair]:
    """Every (qualified name, runtime callable, stub AST def) pair worth a
    parameter-level signature comparison: module-level functions, plus every
    non-property, non-dunder method of every non-exception compiled class."""
    stub_classes = _stub_classes()
    pairs: list[_CallablePair] = []

    stub_path = pathlib.Path(processkit.__file__).with_name("_processkit.pyi")
    tree = ast.parse(stub_path.read_text(encoding="utf-8"))
    module_stub_fns = _stub_funcdefs(tree.body)
    for name in _compiled_functions():
        runtime_fn = getattr(_processkit, name)
        stub_fn = module_stub_fns.get(name)
        if stub_fn is not None:
            pairs.append((name, runtime_fn, stub_fn))

    for cls_name, cls in _compiled_classes().items():
        if issubclass(cls, BaseException):
            continue
        stub_methods = _stub_funcdefs_with_bases(stub_classes[cls_name], stub_classes)
        for member in vars(cls):
            if member.startswith("_"):
                continue
            if _runtime_is_data_descriptor(cls, member):
                continue  # properties/getters have no call signature
            stub_fn = stub_methods.get(member)
            if stub_fn is None:
                continue  # already caught by test_compiled_class_members_match_the_stub
            pairs.append((f"{cls_name}.{member}", getattr(cls, member), stub_fn))
    return pairs


def test_signature_parameters_match_the_stub() -> None:
    # The AST-based drift guards above only compare NAMES (methods, classes,
    # module functions); this compares each callable's actual PARAMETER LIST
    # (name, positional/keyword kind, and whether it has a default) against the
    # stub's declared parameters — the level a renamed/reordered/reworked
    # kwarg, or a dropped default, drifts at, invisible to the name-only guards.
    mismatches = []
    for qualname, runtime_fn, stub_fn in _iter_callables_with_stub_defs():
        try:
            sig = inspect.signature(runtime_fn)
        except (TypeError, ValueError) as exc:
            mismatches.append(f"{qualname}: could not read a runtime signature ({exc})")
            continue
        runtime_params = _runtime_params(sig)
        stub_params = _stub_params(stub_fn)
        if runtime_params != stub_params:
            mismatches.append(f"{qualname}: runtime {runtime_params} != stub {stub_params}")
    assert not mismatches, "signature drift vs the stub:\n" + "\n".join(mismatches)


def test_pyproject_and_cargo_versions_agree() -> None:
    # The release workflow bumps pyproject `[project]` and Cargo `[package]` in
    # lockstep; nothing else enforces it. A skew means a wheel whose Python
    # metadata and binding-crate version disagree — caught here at build time
    # rather than after the irreversible publish.
    root = pathlib.Path(processkit.__file__).resolve().parents[2]
    pyproject = root / "pyproject.toml"
    cargo = root / "Cargo.toml"
    if not (pyproject.is_file() and cargo.is_file()):
        pytest.skip("source-tree manifests not present (installed wheel)")
    py_version = _section_version(pyproject.read_text(encoding="utf-8"), "project")
    rs_version = _section_version(cargo.read_text(encoding="utf-8"), "package")
    assert py_version is not None, "no [project] version in pyproject.toml"
    assert rs_version is not None, "no [package] version in Cargo.toml"
    assert py_version == rs_version, (
        f"version skew: pyproject [project] {py_version!r} != Cargo [package] {rs_version!r}"
    )
