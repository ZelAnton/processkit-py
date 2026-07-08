# Security Policy

## Supported versions

Security fixes are applied to the latest released version of **processkit**.
Older versions are not maintained — upgrade to the latest release to receive
fixes.

## Reporting a vulnerability

**Do not open a public issue for security vulnerabilities.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/ZelAnton/processkit-py/security/advisories/new)
(repository **Security → Advisories → Report a vulnerability**). If that is
unavailable, contact the maintainer listed on the
[ZelAnton](https://github.com/ZelAnton) profile.

Please include:

- a description of the vulnerability and its impact;
- steps to reproduce (a minimal proof of concept is ideal);
- affected version(s).

You can expect an initial acknowledgement within a few days. Once a fix is
ready, a patched release is published to PyPI and the advisory is disclosed.

## Automated scanning

- **[CodeQL](.github/workflows/codeql.yml)** runs GitHub's static analysis
  (`security-and-quality` queries) on every push and pull request to `main`, and
  on a weekly schedule. Two parallel jobs cover Python (interpreted, no build step)
  and Rust (compiled via `cargo build --features extension-module`).
- **[pip-audit](https://pypi.org/project/pip-audit/)** runs in CI on every pull
  request and every push to `main` (the `pip-audit` job in
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml)). It scans the resolved
  Python dependency tree against the [PyPI Advisory Database](https://github.com/pypa/advisory-database)
  and fails the build on a known vulnerability.
- **[cargo-deny](https://github.com/EmbarkStudios/cargo-deny)** is the Rust
  analogue of pip-audit: the `rust-audit` job in
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs
  `cargo deny check advisories bans licenses sources` on every pull request
  and every push to `main`, scanning the compiled Rust dependency tree
  (configured in [`deny.toml`](deny.toml)) against the RustSec Advisory
  Database and failing the build on a known vulnerability, a yanked crate, or
  a disallowed license.
- **[Dependabot](.github/dependabot.yml)** opens weekly pull requests to keep
  GitHub Actions, Python packages (`uv` ecosystem), and Rust crates (`cargo`
  ecosystem) current, so advisory fixes land promptly.
