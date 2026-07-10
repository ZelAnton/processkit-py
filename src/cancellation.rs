//! `CancellationToken` — a portable cancel switch for `Command.cancel_on()` /
//! `CliClient.default_cancel_on()` / `Pipeline.cancel_on()`.

use processkit::CancellationToken as PkCancellationToken;
use pyo3::prelude::*;

/// A cancel switch: fire it to tear down every run wired to it (via
/// `Command.cancel_on()`), surfacing `Cancelled`. Cheap to clone/share: every
/// clone refers to the same underlying state, so cancelling any clone cancels
/// every run wired to it. `child_token()` derives a separate, scoped token
/// instead: it is cancelled automatically when this one is, but cancelling it
/// back does NOT propagate to this token or to its other children —
/// cancellation only flows parent-to-child, never child-to-parent or between
/// siblings. A cancelled token stays cancelled forever — never call this to
/// mean "pause" (use `ProcessGroup.suspend()`/`resume()` for that).
#[pyclass(name = "CancellationToken", module = "processkit")]
pub(crate) struct PyCancellationToken {
    pub(crate) inner: PkCancellationToken,
}

impl From<PkCancellationToken> for PyCancellationToken {
    fn from(inner: PkCancellationToken) -> Self {
        Self { inner }
    }
}

#[pymethods]
impl PyCancellationToken {
    /// A fresh, not-yet-cancelled token.
    #[new]
    fn new() -> Self {
        Self {
            inner: PkCancellationToken::new(),
        }
    }

    /// Fire this token — every run wired to it (or to a `child_token()` of
    /// it) is torn down, surfacing `Cancelled`. Idempotent.
    fn cancel(&self) {
        self.inner.cancel();
    }

    /// Whether this token (or an ancestor it derives from) has been cancelled.
    fn is_cancelled(&self) -> bool {
        self.inner.is_cancelled()
    }

    /// A child token: cancelled automatically when this one is, but can also
    /// be cancelled independently without affecting this one or its other
    /// children — for scoping a broader shutdown token down to one operation
    /// while still reacting to the parent firing.
    fn child_token(&self) -> Self {
        Self {
            inner: self.inner.child_token(),
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "CancellationToken(is_cancelled={})",
            self.inner.is_cancelled()
        )
    }
}

/// Register this module's pyclass (`CancellationToken`) on `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCancellationToken>()?;
    Ok(())
}
