# OfflineHorizon source synchronizer

This service runs **beside**, not inside, `Offline-Horizon`.
Its versioned source is mirrored in the private GitHub repository at
`OfflineHorizon-sync/`, while the deployed directory remains a separate
sibling: `/opt/OfflineHorizon-sync` on VPS or `E:/Files/Projcet/OfflineHorizon-sync`
on Windows. Keep this layout: `compose.yaml` mounts `../Offline-Horizon`.
Never publish `.env`, `secrets/`, runtime work files or downloaded archives.

## Billing-exhausted fallback mode (November 12, 2026)

GitHub-hosted builds in this fork are paused by default. The checked-in GitHub
workflows now require repository variable `OFFLINEHORIZON_GITHUB_BUILDS=1`
before they may compile a game or launcher. Hosted source-sync additionally
requires `OFFLINEHORIZON_GITHUB_SYNC=1`. Leave both unset while the GitHub
Actions budget is exhausted.

Use `docker compose up -d --build sync release-publisher` on the VPS with
the server-side authorization configured. The publisher reads the existing
root-owned `secrets/github_release_token` (0600); the unprivileged sync service
reads `secrets/github_sync_token` owned by UID/GID 10001 (0600). Both mounts are
read-only; neither service puts the token in Docker environment variables.
On the VPS, provision the sync token without printing its contents:
`install -o 10001 -g 10001 -m 0600 secrets/github_release_token secrets/github_sync_token`.
Never commit either file; the `secrets/` directory is ignored.
Source publication is disabled by default (`SYNC_PUBLISH=0`) while GitHub-hosted
build validation is blocked. Set `SYNC_PUBLISH=1` in the server-side environment
only after an independent fork build/test path is available.
The `sync` service checks and transplants source on the **1st and 15th of each month at 03:00 UTC**, recording each attempted date in the persistent `/work` volume. The `release-publisher` checks already-verified archives on the same dates. It does not compile Windows/macOS binaries and cannot publish unverified archives. Publication remains disabled until
`SYNC_PUBLISH=1` is explicitly configured and the required GitHub token is
installed on the server. Never put the secret in the repository or this chat.

`v0.2.9` is already published; its six game archives and seven launcher files
must not be reused as the binaries for a different source commit. The present
2 GiB VPS cannot compile Windows, macOS and Linux releases. The external
publisher verifies SHA-256 of existing release files, including their
GitHub-provided asset digests. To publish a newer commit, first provide all
platform archives from independently successful native builds and a new
verified provenance manifest. If the required archives do not exist, remain
in a waiting state, not an invented "successful" release.

## Behavior

1. On the **1st and 15th at 03:00 UTC**, obtain the hash of `horizon-rust/horizon` `main` via `git ls-remote`. Each scheduled date is attempted at most once, even across container restarts. No immediate startup sync or four-hour loop remains.
2. **Search the upstream push history for the most recent fully green commit**, rather than requiring current `main` to be green. The latest green SHA must have successful `checks` (`ci.yml`) and `parity-main` (`parity-main.yml`) runs **for the same SHA**. Their `verify`, `launcher`, and `parity-main` jobs must individually have `success`, not `skipped`. This covers upstream Python/Rust tests, lint, launcher tests, and vanilla parity. Newer failed/queued/pending commits are ignored in favor of the most recent verified green ancestor. A successful workflow summary with skipped required jobs is insufficient.
3. Confirm the selected SHA belongs to the current `main` history, and compare it with the fork's stored `.offline-horizon-upstream-sha` (or the dry-run cache). **If it is the same green SHA, do nothing. If the selected green SHA is newer than both the fork's recorded SHA and the overlay's original BASE_SHA, update. If it is older or divergent, do not roll back.** This matters because `parity-main` can have no recent successes: a November 7 green SHA must not replace a November 8 fork base. API failures block synchronization.
4. Fetch the specific verified historical SHA, **not** `main` HEAD, into a short-lived volume. Even if newer unverified commits are pushed during the run, none are imported. **First synchronization** applies the explicitly curated `manifest.txt` fork overlay against the configured base SHA, including uncommitted *tracked* changes from the mounted local source. **Later synchronizations** three-way apply only the change from the previous upstream SHA to the new one, preserving fork commits.
5. Fail closed on merge conflicts, missing source paths, validation failures, concurrent changes in the private fork, or a verified SHA that is no longer in main's history. Never force-push, never overwrite the mounted checkout, and never publish a partial result.
6. Push one ordinary fast-forward commit to `YourPancakes/OfflineHorizon:main` only when `SYNC_PUBLISH=1` and an appropriate GitHub token is securely installed **on the server**, not sent through chat. The normal release method is GitHub Actions (`.github/workflows/offline-game.yml`). If its **publication** job is blocked by billing or a runner outage, a separate low-resource `release-publisher` container may upload exactly the already-verified build archives from GitHub Actions, using a separately installed GitHub token. The source-sync container does not compile or publish binaries.
7. Delete all temporary clones, patches, and work trees after every sync attempt. The current 2 GiB VPS **never compiles Rust automatically**. A separate optional native-Linux rebuild method checks CPU, available RAM, free disk, exact clean source SHA and an existing Docker builder image before running with limited resources; it cannot produce Windows or macOS binaries. Merge conflicts still block the branch push.

**Upstream CI is mandatory, including for dry-runs.** GitHub REST API selects **successful** `parity-main` runs (rather than paging through thousands of cancelled and pending ones), then verifies that `checks/verify` and `checks/launcher` also passed on exactly the same SHA. The scan checks up to five pages of 100 successful `parity-main` runs (configurable using `UPSTREAM_CI_SCAN_PAGES`, maximum 10). To avoid uncontrolled API requests, at most 15 successful parity candidates per cycle are checked against the complete `checks` suite. If no fully green commit can be confirmed in that bounded history, synchronization stops and retries next cycle. Public unauthenticated requests can hit a `403` rate limit; use `GH_TOKEN` for authenticated status reads. A token is required to publish to the private fork. This gate verifies the original project's CI for the chosen SHA; it does **not** prove that OfflineHorizon's own patched source compiles. The fork's GitHub Actions must test it before release. Only green *source commits* are adopted; this tool does not download Mojang files or official Nightly executables.

**Patch exclusions (2026-11-12):** Owner-requested GPU bind-group caching, compact particle vertices, worker-cached side sorting, sky-disc, snow/CPU-GPU weather, sprite-sharing changes, and direct/relay networking modifications are **not** fork features. Their files and auxiliary benchmarks are intentionally omitted from `manifest.txt`: the initial bootstrap uses official Horizon implementations. The local source was also restored to original v0.2.97 behavior for these features. Preserve other customizations (offline accounts, privacy, launcher release selection, lighting and game simulation) when updating the manifest. These excluded optimizations are intentionally not part of the fork overlay.

**Important:** This checkout was initialized independently of upstream history. The initial synchronization includes the local commits that are ahead of the GitHub fork as ancestors of the new commit (fast-forward only). If the two branches have genuinely diverged, publication stops rather than force-pushing. Always inspect a dry-run before enabling publication.

## Commands

Build locally:

```sh
cd E:/Files/Projcet/OfflineHorizon-sync
docker compose build
docker compose run --rm --entrypoint python sync /app/sync.py --once --dry-run
```

Or run without Docker on a system with Python 3.12 and Git:

```sh
python sync.py --once --dry-run
```

Run the repeated service after successful validation:

```sh
cp .env.example .env
# Provision `secrets/github_release_token` (root:root, 0600) and
# `secrets/github_sync_token` (10001:10001, 0600) directly on the VPS.
# Never put tokens into .env or Compose environment variables.
# Keep SYNC_PUBLISH=0 until separate fork builds can be tested.
docker compose up -d --build
docker compose logs -f --tail=100
```

Stop: `docker compose down`. Logs rotate at 10 MB. The Docker `sync-work` volume holds a small lock and last dry-run hash; temporary clones are deleted after each cycle. No Docker-based Rust compilation is done.

The `sync` service is a **source synchronizer**, not a game builder. The optional `release-publisher` service distributes already-verified, prebuilt game archives; native Linux rebuilding is available as a separate, guarded command only on a sufficiently powerful server. OfflineHorizon distributes its game, server, and launcher together in a single `vX.Y.Z` release. Game versions inside the launcher come from public `horizon-rust/horizon`; launcher updates come from this fork. GitHub Actions is currently unavailable due to billing restrictions; independent platform builds must be verified before the server fallback can replace any public release asset. The fork `YourPancakes/OfflineHorizon` is private as of 2026-11-12; its release assets are not anonymously downloadable. Do not embed any private PAT in launcher binaries. Use a separate public distribution repository only after explicitly deciding to expose the code/assets, or make the fork public after auditing it.

## Failure handling and CI

The service never ignores upstream merge conflicts. CI has a separate required suite for offline accounts, correct game/launcher asset selection, signing fallback, and translations, and an informational upstream-wide suite (which may be flaky). Linux x64, Windows x64, macOS ARM64 and Intel artifacts are required to publish a release. Game and launcher use the same `vMAJOR.MINOR.PATCH` release tag; no separate `launcher@` release is created.

Before the initial push, inspect `manifest.txt` and ensure every custom source file is represented. The overlay is deliberately limited to documented fork changes; unrelated upstream files are copied from the new official source unchanged. Legacy `tools/autopatch.py` and `xtask/src/autopatch.rs` have been retired, along with optional parity-signal, Cargo-validation, particle-benchmark, rendering-hotpath and agent-performance test files; their paths are excluded from the bootstrap manifest. Neither old autopatch implementation is executed.

## Release methods and GitHub Actions fallback

**Method 1 — GitHub Actions:** `.github/workflows/offline-game.yml`
runs Rust tests, compiles Linux/Windows/macOS and a Linux server, generates
`SHA256SUMS`, and automatically publishes GitHub Releases when its release
runner is available. `python3 release_fallback.py github` can explicitly
dispatch that workflow using a securely installed GitHub token.

**Method 2 — low-resource server fallback:** when all six GitHub Actions
artifacts have already passed tests but the publication job is blocked,
`release_fallback.py server` validates the pinned original Actions run and
all six recovered archives against `verified-artifacts.json`; then it
creates a GitHub draft release via the REST API, uploads the assets and
`SHA256SUMS` using streaming 1 MiB chunks, and publishes only when complete.
It never publishes a partial release and never uses unverified game binaries.
The `release-publisher` Docker service runs `auto` every four hours.
Without credentials, it reports `waiting_credentials` and does nothing.

Server commands:

```sh
python3 /opt/OfflineHorizon-sync/release_fallback.py status --assets-dir /opt/OfflineHorizon-releases/v0.2.9
python3 /opt/OfflineHorizon-sync/release_fallback.py server --assets-dir /opt/OfflineHorizon-releases/v0.2.9 --token-file /opt/OfflineHorizon-sync/secrets/github_release_token
python3 /opt/OfflineHorizon-sync/release_fallback.py build-linux --assets-dir /opt/OfflineHorizon-releases/v0.2.9 --source-dir /opt/Offline-Horizon
```

**Credentials:** GitHub Release creation requires a NEW fine-grained GitHub
token for `YourPancakes/OfflineHorizon`, with `Contents: read and write` and `Actions: read` (or `Actions: write` to trigger the primary workflow)
(and Workflows write only if GitHub demands it for workflow-changing commits).
Do not reuse a PAT exposed in chat. Place the token directly on the server
at `/opt/OfflineHorizon-sync/secrets/github_release_token`, mode `0600`.
The publisher bind-mounts the secret read-only; no token is embedded in
source, command-line arguments, Docker environment variables, or logs.

**Guarded server compilation:** `build-linux` requires >=2 CPUs, >=6 GiB
currently available memory, >=18 GiB free disk, a clean source checkout at
the exact pinned release commit, and a prebuilt
`offlinehorizon-builder:rust-1.99` image (see `Dockerfile.builder`). It
limits the build to 0.75 CPU, 4 GiB RAM, 1 Cargo job and 160 processes.
The present 1-core/2-GiB/9-GiB-free VPS intentionally fails this safety
gate. Linux alone cannot compile Windows/macOS artifacts; those must be
provided by successful builds on the appropriate platforms.

The repository remains private; do not open a public asset server without
explicit permission. As of November 12 the `v0.2.9` assets have been
recovered from GitHub Actions and are staged on the VPS, but GitHub Release
publication requires an authorized fresh token or restoration of the
GitHub Actions runner quota.
