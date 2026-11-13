# OfflineHorizon synchronization and releases

GitHub Actions checks Horizon every four hours. The synchronization workflow
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
