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

3. **GitHub App for the push to protected `main`** — **required** (`main` has branch
   protection). The release pushes the version commit + `v<version>` tag to `main` as
   the **`ZelAnton-release-bot`** App, which sits in the ruleset's bypass list; the
   default `github-actions[bot]` **cannot** be granted a ruleset bypass (system actor,
   not an App). The repo variable `RELEASE_APP_ID` (`3951739`, the shared App) is
   already set — add the secret **`RELEASE_APP_PRIVATE_KEY`** = the App's `.pem` private
   key (the same App/key as the sibling repos). See
   [release-token-bypass.md](.github/release-token-bypass.md). Until the secret is set the App
   step is skipped and the push falls back to `GITHUB_TOKEN`, which the protection
   rejects — so set it before the first release.

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
   Done for v1.0.0 — not needed again for subsequent releases.

## Docs site

The guides in `docs/` render as a [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
site, versioned with [mike](https://github.com/jimporter/mike) so a reader
pinned to an old release can still read *that release's* docs instead of
whatever is newest on `main`. The build (`mkdocs build --strict`) runs on every
docs change as a link/anchor check; **deployment is opt-in** so there are no
red runs before Pages is set up. To publish the site:

1. Repo **Settings → Pages → Source: GitHub Actions**. (Pages is *not* switched
   to "Deploy from a branch" — `mike deploy` uses the `gh-pages` branch only as
   its own storage for the built versions; a GitHub Actions job then
   republishes that whole tree as a Pages *artifact*, same as before mike.)
2. Repo **Settings → Secrets and variables → Actions → Variables**: add
   `DOCS_DEPLOY` = `true`.

From then on:

- **Every push to `main`** that touches `docs/` or `mkdocs.yml`
  (`.github/workflows/docs.yml`) deploys the rolling, unreleased build to the
  `dev` slot (`mike deploy dev`), then republishes the full `gh-pages` tree
  (every slot below, plus `dev`) to
  `https://zelanton.github.io/processkit-py/`. `dev` is its own slot — it is
  never aliased to a released version and never touches `latest`.
- **Every published release** (the `release.yml` `publish` job, right after
  the GitHub Release is created) deploys that release's docs under a
  `MAJOR.MINOR` slot (mike's own recommended scheme — the patch number is
  deliberately dropped) and moves the `latest` alias to point at it:
  `mike deploy --update-aliases MAJOR.MINOR latest`. A **patch** release of an
  already-published minor version (e.g. `1.2.3` after `1.2.2`) therefore
  re-deploys into the *same* `1.2` slot — mike overwrites that slot's content
  and bumps its displayed title to the new patch version — while a **minor**
  or **major** release creates a brand-new slot and moves `latest` to it. This
  docs-deploy step is best-effort and runs only here, once per actual
  `workflow_dispatch` release run (this workflow has no draft-then-publish
  loop to guard against — it already only executes at the point of a real,
  manually-dispatched release): if it fails, PyPI/the tag/the GitHub Release
  are already done, so the step warns instead of failing the job, and prints
  the exact `mike deploy`/`mike set-default` commands to finish by hand — do
  **not** treat a docs-deploy failure as a reason to re-run the whole release
  workflow (a re-run computes the *next* version). Right after that, a
  separate `publish-pages` job (needs the `publish` job, so it only runs if
  the release succeeded) republishes the whole `gh-pages` tree as a Pages
  artifact — the same step docs.yml's own `publish-pages` job performs after
  an ordinary push — so the live site actually shows the new version and the
  moved `latest` immediately, instead of waiting for some unrelated future
  push to `main` that happens to touch `docs/` and trigger docs.yml.

Preview the plain (unversioned) docs locally with `uv run --group docs mkdocs
serve`. To see the real version selector as readers will, deploy at least one
version to a local `gh-pages` branch and serve that instead:
`uv run --group docs mike deploy --update-aliases 0.0 dev && uv run --group
docs mike serve` (never pass `--push` for a local check — that would push to
the real `origin/gh-pages`).

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
