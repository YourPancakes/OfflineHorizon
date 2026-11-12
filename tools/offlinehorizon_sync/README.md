# OfflineHorizon source synchronization and release modes

## Current mode: VPS fallback (GitHub Actions budget exhausted)

Source checks run in the sibling Docker project `OfflineHorizon-sync`, not
inside this repository. The source checker runs every four hours, checks the
latest **fully green upstream main** commit, avoids downgrades, applies the
reviewed fork overlay, and removes temporary Git files. It can update the
private fork only when the server has an appropriately scoped token and
`SYNC_PUBLISH=1`.

The Docker `release-publisher` service is a separate, low-memory fallback.
It can only publish **already compiled and verified** platform archives.
It verifies the original Actions source SHA, successful test/build jobs,
the provenance manifest, archive formats, file sizes, and SHA-256 values.
It will not compile Rust or invent missing Windows/macOS assets. The
existing release `v0.2.9` has already been published and must not be
overwritten or reused as the binaries for a newer source commit.

Repository variables intentionally default to a paused hosted-runner mode:

| Variable | Value required to enable | Effect |
|---|---|---|
| `OFFLINEHORIZON_GITHUB_SYNC` | `1` | Activate the GitHub-hosted 4-hour source-sync job |
| `OFFLINEHORIZON_GITHUB_BUILDS` | `1` | Allow GitHub-hosted game/launcher builds and dispatches |

Leave both unset while GitHub-hosted Actions cannot start due to billing.
The external Docker source-checking service does **not** require these flags.

## Validating without paid GitHub-hosted runners

```sh
python3 -m unittest discover -s tools/offlinehorizon_sync/tests -p 'test_*.py' -q
python3 -m py_compile tools/offlinehorizon_sync/sync.py tools/offlinehorizon_sync/release_guard.py
actionlint .github/workflows/offline-upstream-sync.yml .github/workflows/offline-game.yml .github/workflows/launcher.yml
```

In the sibling `OfflineHorizon-sync` directory:

```sh
python3 -m unittest discover -s tests -v
python3 sync.py --once --dry-run
python3 release_fallback.py status --assets-dir /opt/OfflineHorizon-releases/v0.2.9
```

The last command needs the verified archives staged on the actual VPS,
not only `verified-artifacts.json` in the local source directory.

## Limits and recovery

- Do not push a new game binary release until actual tested Windows, Linux
  and both macOS archives exist for that exact source commit.
- A 2 GiB VPS can run Git synchronization and upload verified archives;
  it cannot safely replace the required cross-platform builders.
- After GitHub billing and hosted runners are restored, set the two repository
  variables to `1`, first verify a dry-run build, then enable publication.
- Until then, keep existing published assets immutable. Public anonymous
  auto-updates are not available from the private fork.
- Never store personal access tokens in this repository or in chat.
