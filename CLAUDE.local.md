# CLAUDE.local.md — локальные заметки для processkit-py

## Этот репозиторий в системе `.hq`
- Карточка: `d:\GitHub\Personal\.hq\projects\processkit-py\card.md`
- Смежный Rust-крейт: `ProcessKit-rs` (источник истины для логики ядра)
- Создан из `Python-repo-template`; инициализирован 2026-06-17

## Текущий статус
Phase 0 — de-risk spikes (async-bridge tokio↔asyncio, teardown на Windows/Linux).
`src/lib.rs` и `src/processkit/__init__.py` — заглушки. Настоящий код пойдёт в Phase 1+.

## Технический стек
- PyO3 0.23 + maturin (build backend); abi3-py310 wheels
- Async bridge (Phase 2): `pyo3-async-runtimes` (tokio ↔ asyncio)
- CI: dtolnay/rust-toolchain + setup-uv на всех jobs
- Dist: cibuildwheel (Phase 1+, когда появится реальный Rust код)

## Зависимость от processkit crate
Версия crate будет жёстко закреплена (exact pin) в Cargo.toml когда начнём Phase 1.
Отслеживать API churn ProcessKit-rs осознанно (не transitively).
