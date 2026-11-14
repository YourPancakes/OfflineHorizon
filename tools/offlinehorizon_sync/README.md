# OfflineHorizon synchronization and releases

The VPS watcher (`scheduler.py`) checks GitHub every 120 seconds for the
**newest completely green commit in the official `horizon-rust/horizon` main
history**. It is not tied to the Nightly tag. An upstream main HEAD which is
still pending or red does not block the most recent older fully green SHA.
The controller requires successful official `checks/verify`,
`checks/launcher` and `parity-main` on the **same exact commit**.

When the selected official green SHA is newer than the fork's recorded upstream
SHA, `sync.py` builds an immutable
`offlinehorizon/candidate/<upstream40>-<fork-base12>` branch. **It never
pushes untested merged source to `main`.** The watcher dispatches
`offline-game.yml` on that branch. No repeat dispatch is made for an already
observed candidate or failed build while the fork base and green upstream SHA
remain unchanged.

The combined workflow tests the fork and builds all game, dedicated-server
and launcher targets on the candidate SHA. Only when every required job is
successful may `promote` fast-forward the fork's `main` to the **exact
tested SHA**, after verifying the original fork parent and the official CI again.
The same run publishes a single combined `v0.2.X` release using the already
built assets, without rebuilding on the promoted `main` SHA.

If fork tests fail, the old `main` and published release stay unchanged.
A newer fully green official commit or a changed fork main can cause another
candidate to be prepared; no code is changed automatically to make red tests
green. A main push which races promotion blocks the candidate and requires
re-staging and re-testing.

`.github/workflows/offline-upstream-sync.yml` is now **manual fallback only**;
the old every-four-hours GitHub Actions schedule is disabled. The VPS watcher
provides prompt detection without continuous paid GitHub runners. A manual
`workflow_dispatch` invokes the same safe staging and candidate dispatch.

Run the synchronization regression tests:

```sh
python3 -m unittest discover -s tools/offlinehorizon_sync/tests -p 'test_*.py' -q
```

Publication requires game tests, all five cross-platform build targets and
complete game/server/launcher archives. Use `rebuild_029` on a deliberate
manual `offline-game.yml` run to rebuild `v0.2.9`.
