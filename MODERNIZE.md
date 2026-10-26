# Modernization notes: tag-train-val-test

Rewrite of `tag-train-val-test` ("Assign train/val tags to images") to the `sly-app-standard` (local, not released).
Base: `origin/master` @ b140597. Branch `local/modernize`, nothing committed. Archetype: transform, GUI
(was `AppService` + `gui_template`), now `sly.Application(layout=...)` like the convert-class-shape pilot.

## Behaviour contract (kept)

**Entry point.** Context menu of an images project → "Training data" → Assign train/val tags to images. GUI
session (`task_location: workspace_tasks`, `isolate: true`); the modal (`src/modal.html`) is empty; the project
arrives as `modal.state.slyProjectId`. Non-images projects are rejected at startup.

**Startup check.** If the project meta already has a `train` or `val` tag meta whose value type is not `none`,
the app fails at startup with "Existing tag … Please check your project tags." (verified on fixture #9419, old and new).

**GUI.** Input card (source project), Output card (Run, progress, result project), Settings:
- *Train / Val proportion*: train percent 1–100, default 80; counts shown as train = `floor(total * p / 100)`,
  val = total − train (same formula as the old JS, checked for every total 0–399 × percent 1–100);
- *Result project name*, default `<source name> (with train-val tags)`;
- *FOR NN DEBUG: Train == Validation*: train = val = total (100 %/100 %), slider disabled; unchecking resets the
  slider to 80 (as the old page did).

**Output.** A new images project in the source project's workspace:
- name: the typed name without `/ \ |`; empty (or blank) → `<source name>_tagged`; the platform appends `_001`, … on
  conflicts; description `train/val`;
- meta = source meta + tag metas `train` (none, [0,255,0]) and `val` (none, [255,128,0]); existing ones are reused as they are;
- same dataset tree (names, descriptions, custom data, nesting), same images by id (no pixel re-upload) with names and image meta;
- annotations as in the source with the image's `train`/`val` tags replaced: a random `train_count` images (one global
  shuffle over the whole project, not per dataset, unseeded) get `train`, the rest `val`; with "Train == Validation"
  every image gets both. All other image tags, objects, object tags and descriptions are kept.
- task output = the new project; workflow lineage: source project in, new project out; the session stops itself.
- The source project is only read.

## Intentional changes

1. **Object bindings are kept.** The old app copied the project server-side and re-uploaded annotations downloaded
   from the copy, which had lost the binding keys (`instance`). Now annotations come from the source and keep their
   groups. Verified on #9390: source and new have the group {building, building, roof}; old had none.
2. **One pass instead of copy + re-tag.** Images are added once with the re-tagged annotations (old: server-side copy
   with annotations, then download and upload every annotation again). One progress bar "Assigning tags" instead of
   "Cloning project..." then "Tagging".
3. **Dead "Advanced: inplace operation" checkbox removed** (it was always disabled and raised `NotImplementedError`).
4. **New UI on `sly.Application` widgets** instead of `gui_template`: same cards, field titles and descriptions; the
   train/val/total table is now a slider with an input plus one line "train: N images (p%) · val: … · total: …".
5. **A name made only of `/ \ |`** becomes `<source>_tagged` (old: the empty result was sent to `project.create`).
6. **A failure during the run no longer kills the session**: the Run request fails (the SDK shows it to the user),
   the controls unlock and the user can retry; a partially filled project stays (as before). Unit-tested, not
   exercised on the instance.
7. **Workflow input is registered when Run is pressed** (old: at startup, also when the user never ran it).
8. **Runs on the hardened image (Python 3.14).**

## Dropped

- `src/tag_train_val_test.py` (module-level env reads, globals, `AppService`), `src/gui.html`.
- `src/workflow.py` → `src/platform_io.py` (same lineage calls).
- `debug.env`, `secret_debug_example.env` (token placeholders) → `local.env` + `~/supervisely.env`.
- No tests existed in the repo.

## Versions and image

- **Image: `supervisely/base-py-sdk-hardened:6.74.34`** (was the shared `supervisely/data-operations:6.74.34`, bumped
  in #13 for an exit-139 startup segfault). No deps beyond the SDK, so no per-app image. Tag checked on Docker Hub.
- **SDK stays at 6.74.34**, `instance_version` stays 6.17.22 (CI range [6.74.29, 6.74.35)). A newer SDK needs a higher
  `instance_version` — a product decision, not taken here.
- CI: `.github/workflows/*.yml` only call `workflows/common.yml`; this repo has no `build-image` job, so the
  "unused per-app image" question from the other pilots does not apply. Left unchanged.
- README screenshots/GIF show the old UI; not retaken.

## Open questions for the user

- Raise `instance_version` to allow a newer SDK?
- Show the "train/val tag has a value" error on the page instead of failing the session at startup?
- Offer a random seed (reproducible splits)? Today every run gives a different split, as before.
- Existing `train`/`val` tag metas applicable only to objects are not checked (same as old; not verified what the server does).

## Verification (2026-10-25, dev.internal.supervisely.com)

- **Unit tests** 35/35 in a macOS venv (Python 3.14.3, SDK 6.74.34) and 35/35 inside
  `base-py-sdk-hardened:6.74.34` (Python 3.14.7, amd64). `ruff check` / `ruff format --check` clean (target py314).
- **Equivalence, real projects** (`git show origin/HEAD` code run in-process with `AppService`, task fields and lineage
  stubbed and output redirected to ws 733; both sides given the same deterministic shuffle so the split must match per
  image; compared meta, dataset tree + description + custom data, image name/meta/hash/link/size and normalized
  annotations): #46, #26, #27, #1317 (nested, 80 % and 33 %), #9390 (80 % and 1 %) and fixture #9418 (existing
  `train`/`val` metas with own colors, pre-tagged images incl. both tags, 3-level nesting, dataset custom data;
  80 %, 100 %, Train == Validation). **0 differences** except intentional change 1 on #9390 (binding keys). Source
  projects unchanged. Old and new both fail at startup on #9419 (same condition, reworded message).
- **Contract tests** (`cases/*.env`, real randomness): 3/3 on #9418 and 3/3 on #1317.
- **In the real image, production mode:** `uvicorn src.main:app` in `base-py-sdk-hardened:6.74.34`, `ENV=production`,
  debug task 62725 (port 8015), source #9418, driven over HTTP like the browser: page rendered, slider → 60 % updated
  counts to 6/4, Run → project #9533 "ttvt-prod-run" (10 images: 6 train, 4 val), task output set to it, workflow calls
  without errors, offline page dumped, session shut down by itself; no errors in the log.
- Not verified: the page in a real browser on the platform, a failure mid-run (change 6), very large projects.

## Objects created on dev (nothing deleted)

Workspace 733: fixtures #9418 `ttvt-fixture-existing-split-tags`, #9419 `ttvt-fixture-train-tag-with-value`;
comparison results #9426, #9427, #9429, #9431, #9432, #9434, #9436, #9438, #9441, #9442, #9443, #9445, #9446, #9447,
#9448, #9451, #9455, #9459, #9469, #9471, #9474, #9478 (`ttvt-cmp-<project>-<percent>[-share]-old|new`); contract
results #9496, #9502, #9506 (`ttvt-fixture-existing-split-tags_tagged*`), #9513, #9517, #9520
(`Fruits Nested (Annotated)_tagged*`); production run #9533 `ttvt-prod-run`. Debug task 62725 (team 1).
Comparison scripts: `/private/tmp/claude-501/-Users-vorozhkog-workapps/e813a6a6-06b5-41f3-a039-0dd120111c3a/scratchpad/ttvt/compare.py` (log: `compare.log`), `/private/tmp/claude-501/-Users-vorozhkog-workapps/e813a6a6-06b5-41f3-a039-0dd120111c3a/scratchpad/ttvt/make_fixture.py`.
