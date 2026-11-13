# OfflineHorizon synchronization and releases

GitHub Actions checks Horizon at 00:17, 04:17, 08:17, 12:17, 16:17 and 20:17 UTC (cron `17 */4 * * *`). The synchronization workflow
requires successful upstream checks and parity on the same commit before
applying the OfflineHorizon changes and updating `main`.

`offline-game.yml` builds the game, dedicated server and launcher for a single
release. Publication requires the Rust tests, all five build targets, and the
complete set of archives and installers. Use the `rebuild_029` input on a
manual run to rebuild version `v0.2.9`.

Run the synchronization tests locally with:

```sh
python3 -m unittest discover -s tools/offlinehorizon_sync/tests -p 'test_*.py' -q
```

The controller requires successful upstream `checks/verify`, `checks/launcher`
and `parity-main` for the same commit before synchronization. The release
guard compares immutable Git trees, so edits limited to GitHub CI and this
controller do not rebuild an unchanged game/launcher. Any changes to game,
launcher or packaging inputs require a new tested build and release.
GitHub scheduled workflows can be delayed or skipped during high load; inspect
the Actions page rather than assuming strict wall-clock execution.
