//! Opt-in bridge: forward the underlying `processkit` crate's `tracing` events to
//! Python's `logging`. Off by default; `enable_logging()` installs it once.
//!
//! The crate emits a small set of events (a `debug!("child spawned")` per run,
//! plus `warn!`/`trace!` on teardown / pump edge cases), tagged `target:
//! "processkit"`. Each becomes a record on `logging.getLogger("processkit")`,
//! with the level mapped TRACE->5, DEBUG->10, INFO->20, WARNING->30, ERROR->40,
//! so a plain `logging.basicConfig(level=...)` (or a per-logger level) filters
//! them like any other library's logs. argv/env are never in the events (the
//! crate omits them — they routinely carry secrets), so nothing sensitive leaks.

use std::sync::OnceLock;

use pyo3::prelude::*;
use tracing::field::{Field, Visit};
use tracing::{Event, Level, Subscriber};
use tracing_subscriber::layer::{Context, Layer};

/// Collects an event's `message` and its other fields into one rendered string.
#[derive(Default)]
struct EventFields {
    message: String,
    extra: Vec<String>,
}

impl Visit for EventFields {
    // The typed `record_*` methods default to forwarding here, so implementing
    // only `record_debug` captures every field (str/int/bool/Display/Debug).
    fn record_debug(&mut self, field: &Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            use std::fmt::Write;
            let _ = write!(self.message, "{value:?}");
        } else {
            self.extra.push(format!("{}={:?}", field.name(), value));
        }
    }
}

impl EventFields {
    fn render(self) -> String {
        match (self.message.is_empty(), self.extra.is_empty()) {
            (false, true) => self.message,
            (true, false) => self.extra.join(" "),
            (false, false) => format!("{} {}", self.message, self.extra.join(" ")),
            (true, true) => String::new(),
        }
    }
}

/// A `tracing` layer that forwards each event to Python `logging`.
struct PyLoggingLayer;

impl<S: Subscriber> Layer<S> for PyLoggingLayer {
    fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
        let meta = event.metadata();
        let level: i32 = match *meta.level() {
            Level::ERROR => 40,
            Level::WARN => 30,
            Level::INFO => 20,
            Level::DEBUG => 10,
            Level::TRACE => 5,
        };
        let target = meta.target().to_owned();
        let mut fields = EventFields::default();
        event.record(&mut fields);
        let message = fields.render();

        // Best-effort. Events fire on tokio worker threads (the GIL is released
        // there), so re-acquiring it is safe and never deadlocks. `try_attach`
        // (not `attach`) returns `None` — dropping the event — when the
        // interpreter is finalizing or mid-GC: this is a kill-on-drop library
        // whose teardown paths also emit events, which could fire during shutdown,
        // and `attach` would panic/crash there. A logging failure is likewise
        // dropped, never propagated — we must not leave a Python error set on a
        // runtime thread.
        let _ = Python::try_attach(|py| {
            let _ = forward(py, &target, level, &message);
        });
    }
}

fn forward(py: Python<'_>, target: &str, level: i32, message: &str) -> PyResult<()> {
    let logging = py.import("logging")?;
    let logger = logging.call_method1("getLogger", (target,))?;
    logger.call_method1("log", (level, message))?;
    Ok(())
}

static INSTALLED: OnceLock<bool> = OnceLock::new();

/// Forward the underlying Rust crate's `tracing` events to Python's `logging`
/// (loggers named after the event target, usually ``"processkit"``).
///
/// Opt-in and idempotent: the first call installs a process-global subscriber;
/// later calls are no-ops. Returns ``True`` if the bridge is active, or ``False``
/// if some other library already installed a global `tracing` subscriber (then
/// the crate's events go there, not to Python logging). Levels map TRACE->5,
/// DEBUG->10, INFO->20, WARNING->30, ERROR->40.
#[pyfunction]
pub(crate) fn enable_logging() -> bool {
    *INSTALLED.get_or_init(|| {
        use tracing_subscriber::layer::SubscriberExt;
        use tracing_subscriber::util::SubscriberInitExt;
        tracing_subscriber::registry()
            .with(PyLoggingLayer)
            .try_init()
            .is_ok()
    })
}
