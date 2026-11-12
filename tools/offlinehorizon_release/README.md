# OfflineHorizon release methods

**Primary:** `.github/workflows/offline-game.yml` runs on GitHub Actions,
tests and compiles Windows, macOS and Linux, then publishes a GitHub Release.

**Fallback:** `release_fallback.py server` is a low-memory, streaming
publisher designed for a separate server. It checks the exact GitHub
Actions source SHA and all green test/platform jobs, validates the six
archived binaries against a pinned manifest, uploads them to a draft
release and publishes only after all archives plus SHA256SUMS arrive.
`release_fallback.py github` requests the normal GitHub workflow.
`release_fallback.py auto --interval 14400` watches for a failed release
job and publishes the already-built artifacts when securely authorized.

Deployment beside the fork is in `/opt/OfflineHorizon-sync/` on
`144.31.49.71` under Docker Compose, with a release publisher limited to
0.12 CPU, 160 MiB RAM, a read-only root filesystem and no Docker socket.
The original source-sync service runs independently.

The current staging directory is `/opt/OfflineHorizon-releases/v0.2.9`.
The six build files were retrieved from GitHub Actions run 43181646362
(source SHA `d2e75698121d9aef17d4547f702bd87ca7e65f6b`).
`verified-artifacts-v0.2.9.json` records their actual release-archive
SHA256 checksums; the `Actions artifact ZIP` has a different checksum.

**Security / permissions:** the private repository requires an
authenticated GitHub REST call to create a release. Configure a NEW
fine-grained token on the server, limited to the repository, with
`Contents: read/write` and `Actions: read` (Actions write only if
triggering the primary workflow from the server). Never embed the token
in the project or chat; install it as a mode-0600 secret file at
`/opt/OfflineHorizon-sync/secrets/github_release_token`.

**Optional native Linux build:** `release_fallback.py build-linux` checks
at least 2 CPU cores, >=6 GiB available RAM, >=18 GiB free disk,
clean source at the exact release SHA, and a prebuilt builder image
before starting. Docker then caps it to 0.75 CPU, 4 GiB memory and one
Cargo job. This method **intentionally refuses** to run on the current
1-vCPU/2-GiB server. A Linux host cannot generate Windows/macOS assets;
their verified prebuilt artifacts are still required.

Do not change repository visibility or host these private assets
publicly without the repository owner's permission.
