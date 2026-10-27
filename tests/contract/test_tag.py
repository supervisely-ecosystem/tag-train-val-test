"""Runs the tagging against a real instance for every case in cases/.

Opt-in: SLY_CONTRACT_TESTS=1, credentials in ~/supervisely.env (SERVER_ADDRESS, API_TOKEN),
SLY_CONTRACT_PROJECT_ID (images project, only read) and SLY_CONTRACT_WORKSPACE_ID (a dedicated test
workspace: every case creates one new project there; nothing is deleted).

    SLY_CONTRACT_TESTS=1 SLY_CONTRACT_PROJECT_ID=123 SLY_CONTRACT_WORKSPACE_ID=45 pytest -m contract tests/contract
"""

import glob
import os
from collections import Counter

import pytest
import supervisely as sly
from dotenv import dotenv_values, load_dotenv

from src import platform_io
from src.core.splits import DESCRIPTION, TRAIN, VAL, SplitOptions, split_counts
from src.tagger import tag_project

CASES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "..", "cases", "*.env")))

pytestmark = [
    pytest.mark.contract,
    pytest.mark.skipif(os.getenv("SLY_CONTRACT_TESTS") != "1", reason="contract tests are opt-in"),
]


@pytest.fixture(scope="module")
def api():
    load_dotenv(os.path.expanduser("~/supervisely.env"))
    return sly.Api.from_env()


def tree(api, project_id):
    """{(dataset path, image name): (image meta, split tags, other image tags, objects per class)}."""
    datasets = {ds.id: ds for ds in api.dataset.get_list(project_id, recursive=True)}

    def path(ds):
        return (path(datasets[ds.parent_id]) + "/" if ds.parent_id else "") + ds.name

    result = {}
    for ds in datasets.values():
        images = api.image.get_list(ds.id)
        anns = {a.image_id: a.annotation for a in api.annotation.download_batch(ds.id, [i.id for i in images])}
        for image in images:
            tags = anns[image.id]["tags"]
            result[(path(ds), image.name)] = (
                image.meta,
                tuple(sorted(t["name"] for t in tags if t["name"] in (TRAIN, VAL))),
                sorted((t["name"], str(t.get("value"))) for t in tags if t["name"] not in (TRAIN, VAL)),
                Counter((o["classTitle"], o["geometryType"]) for o in anns[image.id]["objects"]),
            )
    return result


@pytest.mark.parametrize("case", CASES, ids=os.path.basename)
def test_case_creates_a_tagged_copy(case, api):
    project_id = int(os.environ["SLY_CONTRACT_PROJECT_ID"])
    workspace_id = int(os.environ["SLY_CONTRACT_WORKSPACE_ID"])
    values = dotenv_values(case)
    options = SplitOptions(int(values["TRAIN_PERCENT"]), values["SHARE"] == "1", "")
    project, meta = platform_io.get_project(api, project_id)
    total = platform_io.count_images(api, project_id)
    source_before = tree(api, project_id)

    result = tag_project(api, project, meta, options, total, workspace_id=workspace_id)

    assert result.name.startswith(f"{project.name}_tagged")
    assert (result.workspace_id, result.description) == (workspace_id, DESCRIPTION)
    new_meta = sly.ProjectMeta.from_json(api.project.get_meta(result.id))
    for name in (TRAIN, VAL):
        assert new_meta.get_tag_meta(name).value_type == sly.TagValueType.NONE

    tagged = tree(api, result.id)
    assert set(tagged) == set(source_before)
    counts = split_counts(total, options.train_percent, options.share)
    expected = {(TRAIN, VAL): total} if options.share else {(TRAIN,): counts.train, (VAL,): counts.val}
    assert Counter(split for _, split, _, _ in tagged.values()) == +Counter(expected)
    for key, (image_meta, _, other_tags, objects) in tagged.items():
        assert (image_meta, other_tags, objects) == (
            source_before[key][0],
            source_before[key][2],
            source_before[key][3],
        )

    assert tree(api, project_id) == source_before, "the source project must not change"
