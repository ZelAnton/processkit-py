# Releasing processkit

The release is a manual, multi-platform publish to PyPI, driven by
`.github/workflows/release.yml` (`workflow_dispatch`-only — it never runs on its
own). It builds the wheel matrix + sdist, publishes to PyPI, pushes the version
commit + tag to `main`, and creates a GitHub Release. Publishing uses **PyPI
Trusted Publishing (OIDC)** — no long-lived secret — and attaches PEP 740
provenance attestations.

## One-time setup

1. **Configure a PyPI Trusted Publisher** (the recommended, secret-free path).
   On <https://pypi.org/manage/account/publishing/> add a GitHub publisher. For
   the first release the project does not exist yet, so use the **pending
   publisher** form there:
   - **PyPI Project Name:** `processkit-py` (the bare `processkit` is taken on
     PyPI; the import name is still `processkit`).
   - **Owner / Repository:** this repo.
   - **Workflow name:** `release.yml` (the filename, exactly).
   - **Environment name:** **leave blank.** The `publish` job sets no GitHub
     environment, so filling this in makes the OIDC subject mismatch and PyPI
     rejects the upload.

   See <https://docs.pypi.org/trusted-publishers/>. Nothing else is needed —
   `release.yml` already grants `id-token: write` and mints the credential per run.

   *Fallback (no trusted publisher):* set a `PYPI_API_TOKEN` repository secret to a
   PyPI API token; the publish action uses it instead. (Trusted publishing is
   preferred — no rotation, no secret to leak.)

2. **(Optional) TestPyPI dry-run publisher.** To use `test-release.yml`, add the
   same kind of publisher on <https://test.pypi.org/manage/account/publishing/>
   with workflow name `test-release.yml` (Environment blank), or set a
   `TESTPYPI_API_TOKEN` secret.

3. **(Only if `main` is protected with required PRs)** set up the GitHub App that
   lets the release push the version commit + tag directly to `main` — see
   [release-token-bypass.md](release-token-bypass.md). When `main` is unprotected,
   nothing is needed (the push uses the default `GITHUB_TOKEN`).

## Cutting a release

1. **Dry-run first (recommended):** Actions → **Test release (TestPyPI)** → *Run
   workflow*. This builds the full wheel matrix (manylinux + musllinux + macOS +
   Windows) and uploads to TestPyPI — the only thing that exercises the real
   `cibuildwheel` build + OIDC upload path. Fix any failure before the real run.
2. **Release:** Actions → **Release** → *Run workflow* (from `main`) → pick the
   bump (`patch` / `minor` / `major`; ignored on the first release, which seeds
   the version from `pyproject.toml`). The version is never typed by hand — the
   latest `v*` tag drives the next number.

The pipeline then: computes the version + release notes → builds wheels + sdist →
strict `twine check` → **publishes to PyPI** (the single irreversible pivot) →
atomically pushes the version commit + `v<version>` tag to `main` → creates the
GitHub Release (wheels + sdist + `SHA256SUMS`).

3. **After the first release:** uncomment the PyPI badge in `README.md`, and
   refresh the README prose that still says the release is pending (the
   build-from-source intro and the "first release to PyPI is pending" note).

## Docs site

The guides in `docs/` render as a [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
site via `.github/workflows/docs.yml`. The build (`mkdocs build --strict`) runs on
every docs change as a link/anchor check; **deployment is opt-in** so there are no
red runs before Pages is set up. To publish the site:

1. Repo **Settings → Pages → Source: GitHub Actions**.
2. Repo **Settings → Secrets and variables → Actions → Variables**: add
   `DOCS_DEPLOY` = `true`.

The next push to `main` that touches `docs/` or `mkdocs.yml` then deploys to
`https://zelanton.github.io/processkit-py/`. Preview locally with
`uvx --with mkdocs-material mkdocs serve`.

## If a release fails

The ordering is built so failures are safe to recover:

- **Before or at the PyPI publish** — nothing was pushed to the remote (and no tag
  exists yet, so a re-run recomputes the *same* version). Just re-run the workflow;
  `skip-existing` makes any file a partial upload already landed a no-op.
- **After the tag is pushed to `main`** — the package is on PyPI *and* the tag is
  on `main`. Do **not** re-run the whole workflow (a re-run computes the *next*
  version and orphans this release). Finish by hand: the failing step prints the
  exact `gh release` command to run.
- **The atomic tag push** can lose a race with an ordinary push to `main` that
  lands mid-run (it leaves package-on-PyPI / tag-not-pushed). Cut releases when
  `main` is quiet; if it happens, push the tag + version commit by hand, then
  create the Release as above.
