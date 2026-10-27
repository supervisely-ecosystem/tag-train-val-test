# tag-train-val-test

GUI transform app: images project → new project (default `<name> (with train-val tags)`, same workspace) where
every image has a `train` or `val` image tag (both with "Train == Validation"). `MODERNIZE.md` has the behaviour
contract and the intentional changes versus the pre-2026 (AppService) version.

- Entry: `uvicorn src.main:app` (`config.json` `entrypoint`); modules import each other as `src.*`.
  `src/main.py` is the composition root (env → Api → GUI); creating `app` at import is required by uvicorn.
- `src/ui.py` (`TrainValGui`): slider, result name, "Train == Validation", Run; platform side effects arrive as
  callbacks from `main.py` (tag, then task output / workflow / `app.stop()`).
- `src/tagger.py` orchestrates the copy in one pass (dataset tree incl. nested, batches of 50: download source
  annotations, retag, `upload_ids` + `upload_anns`); `src/platform_io.py` is the only module calling the API;
  `src/core/splits.py` is the pure logic (split sizes, random assignment, result meta, retag, result name).
- Split size: `floor(total * percent / 100)` from the image count shown at startup, one global random
  shuffle across all datasets (unseeded; tests inject `rng`).

Runtime: bare `supervisely/base-py-sdk-hardened:<sdk>` (Python 3.14), no per-app image because
`dev_requirements.txt` holds only the SDK. SDK must stay within the range `supervisely/versions.json`
allows for `instance_version`.

Keep: `config.json` `name`/`context_menu` ("Training data"), tag names/colors `train` [0,255,0] / `val`
[255,128,0], project description "train/val", that the source project is only read, and that existing
`train`/`val` tag metas with a value type fail at startup.

Gotchas: `dataset.get_list` returns no `custom_data` (fetched per dataset with `get_info_by_id`).
`ProjectThumbnail` crashes on a project without images (`_thumbnail_info` guards it). `app.stop()` sends
SIGINT to the process, so never call the real `finished` callback in tests.

Tests: `pytest` (unit, offline; includes the GUI through `Application.test_client` and the copy against a
fake API) · `SLY_CONTRACT_TESTS=1 SLY_CONTRACT_PROJECT_ID=<id> SLY_CONTRACT_WORKSPACE_ID=<test ws> pytest -m contract tests/contract`
(creates one project per `cases/*.env` in the test workspace, deletes nothing).
