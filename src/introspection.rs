//! Spawn-free process and host-containment introspection.

use pyo3::prelude::*;

use crate::errors::map_err;
use crate::group::PyMemberInfo;

/// A side-effect-free snapshot of this host's containment capabilities.
#[pyclass(name = "HostContainment", frozen, module = "processkit")]
pub(crate) struct PyHostContainment {
    mechanism: &'static str,
    soft_stop_scope: &'static str,
    parent_death_cleanup: &'static str,
    crate_version: &'static str,
}

#[pymethods]
impl PyHostContainment {
    #[getter]
    fn mechanism(&self) -> &'static str {
        self.mechanism
    }

    #[getter]
    fn soft_stop_scope(&self) -> &'static str {
        self.soft_stop_scope
    }

    #[getter]
    fn parent_death_cleanup(&self) -> &'static str {
        self.parent_death_cleanup
    }

    #[getter]
    fn crate_version(&self) -> &'static str {
        self.crate_version
    }

    fn __repr__(&self) -> String {
        format!(
            "HostContainment(mechanism={:?}, soft_stop_scope={:?}, parent_death_cleanup={:?}, crate_version={:?})",
            self.mechanism,
            self.soft_stop_scope,
            self.parent_death_cleanup,
            self.crate_version,
        )
    }
}

/// Return best-effort metadata for a live pid, or `None` when it is gone.
#[pyfunction]
fn process_info(pid: u32) -> PyResult<Option<PyMemberInfo>> {
    processkit::process_info(pid)
        .map(|info| info.map(PyMemberInfo::from))
        .map_err(map_err)
}

/// Reuse-safe liveness for a pid and its optional saved start-time token.
#[pyfunction(signature = (pid, start_time=None))]
fn process_is_alive(pid: u32, start_time: Option<u64>) -> PyResult<bool> {
    processkit::process_is_alive(pid, start_time).map_err(map_err)
}

/// Build the spawn-free host containment report.
#[pyfunction]
fn host_containment() -> PyHostContainment {
    let report = processkit::host_containment();
    PyHostContainment {
        mechanism: report.mechanism().name(),
        soft_stop_scope: report.soft_stop_scope().name(),
        parent_death_cleanup: report.parent_death_cleanup().name(),
        crate_version: report.crate_version(),
    }
}

/// Register this module's pyclass (`HostContainment`) and the module-level
/// `process_info`, `process_is_alive`, `host_containment` functions on
/// `_processkit`.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyHostContainment>()?;
    m.add_function(wrap_pyfunction!(process_info, m)?)?;
    m.add_function(wrap_pyfunction!(process_is_alive, m)?)?;
    m.add_function(wrap_pyfunction!(host_containment, m)?)?;
    Ok(())
}
