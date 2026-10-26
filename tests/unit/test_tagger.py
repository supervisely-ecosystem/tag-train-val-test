"""tag_project end to end against an in-memory stand-in for the few API calls it makes."""

import itertools
import random
from collections import Counter
from types import SimpleNamespace as NS

import pytest
import supervisely as sly

from src.core.splits import SplitOptions
from src.tagger import tag_project

BOX = sly.ObjClass("box", sly.Rectangle)
NOTE = sly.TagMeta("note", sly.TagValueType.ANY_STRING)
OLD_TRAIN = sly.TagMeta("train", sly.TagValueType.NONE, color=[9, 9, 9])
META = sly.ProjectMeta(obj_classes=[BOX], tag_metas=[NOTE, OLD_TRAIN])


def info(cls, **values):
    return cls(**{**{f: None for f in cls._fields}, **values})


class FakeApi:
    """Project 10 in workspace 5: root "train" (60 images) with nested "hard" (30), root "empty"."""

    def __init__(self):
        self._ids = itertools.count(10_000)
        self.source = info(sly.ProjectInfo, id=10, name="fruits", workspace_id=5, type="images", items_count=90)
        self.datasets = [
            info(sly.DatasetInfo, id=2, name="hard", parent_id=1, description="", custom_data={}),  # child first
            info(sly.DatasetInfo, id=1, name="train", parent_id=None, description="d", custom_data={"k": 1}),
            info(sly.DatasetInfo, id=3, name="empty", parent_id=None, description="", custom_data={}),
        ]
        self.images = {
            1: [self._image(100 + i, f"a{i}.jpg", {"i": i}) for i in range(60)],
            2: [self._image(200 + i, f"b{i}.jpg", {}) for i in range(30)],
            3: [],
        }
        box = sly.Label(sly.Rectangle(1, 1, 3, 4), BOX)
        self.anns = {}
        for image in self.images[1] + self.images[2]:
            tags = [sly.Tag(NOTE, image.name)] + ([sly.Tag(OLD_TRAIN)] if image.id % 2 else [])
            self.anns[image.id] = sly.Annotation((6, 8), labels=[box], img_tags=sly.TagCollection(tags)).to_json()

        self.created_projects, self.created_datasets, self.uploaded_images, self.uploaded_anns = [], [], [], {}
        self.metas, self.custom_data = {}, {}
        self.project = NS(create=self._create_project, update_meta=self.metas.__setitem__, get_info_by_id=self._project)
        self.dataset = NS(
            get_list=self._list_datasets,
            get_info_by_id=self._dataset_info,
            create=self._create_dataset,
            update_custom_data=self.custom_data.__setitem__,
        )
        self.image = NS(get_list=lambda ds_id: self.images[ds_id], upload_ids=self._upload_ids)
        self.annotation = NS(download_batch=self._download, upload_anns=self._upload_anns)
        self._new_to_src = {}

    @staticmethod
    def _image(image_id, name, image_meta):
        return info(sly.ImageInfo, id=image_id, name=name, meta=image_meta, width=8, height=6)

    def _create_project(self, workspace_id, name, type, description, change_name_if_conflict):
        assert change_name_if_conflict is True and type == sly.ProjectType.IMAGES
        project = info(
            sly.ProjectInfo, id=next(self._ids), name=name, workspace_id=workspace_id, description=description
        )
        self.created_projects.append(project)
        return project

    def _project(self, project_id):
        return next(p for p in self.created_projects if p.id == project_id)

    def _list_datasets(self, project_id, recursive):
        assert (project_id, recursive) == (10, True)
        return [ds._replace(custom_data={}) for ds in self.datasets]  # like the API: no custom data in lists

    def _dataset_info(self, dataset_id):
        return next(ds for ds in self.datasets if ds.id == dataset_id)

    def _create_dataset(self, project_id, name, description, change_name_if_conflict, parent_id):
        assert change_name_if_conflict is True
        dataset = info(
            sly.DatasetInfo, id=next(self._ids), name=name, parent_id=parent_id, project_id=project_id,
            description=description,
        )  # fmt: skip
        self.created_datasets.append(dataset)
        return dataset

    def _download(self, dataset_id, ids):
        assert all(i in {im.id for im in self.images[dataset_id]} for i in ids)
        return [NS(image_id=i, annotation=self.anns[i]) for i in reversed(ids)]  # order must not matter

    def _upload_ids(self, dataset_id, names, ids, metas, force_metadata_for_links):
        new = [info(sly.ImageInfo, id=next(self._ids), name=n) for n in names]
        self._new_to_src.update({n.id: src for n, src in zip(new, ids, strict=True)})
        self.uploaded_images.append((dataset_id, list(names), list(ids), list(metas)))
        return new

    def _upload_anns(self, image_ids, anns):
        for image_id, ann in zip(image_ids, anns, strict=True):
            self.uploaded_anns[self._new_to_src[image_id]] = ann


@pytest.fixture
def api():
    return FakeApi()


def split_of(ann):
    return tuple(t.name for t in ann.img_tags if t.name in ("train", "val"))


def test_copies_tree_images_and_tags_every_image(api):
    done = []
    options = SplitOptions(train_percent=70, result_name="out")
    result = tag_project(api, api.source, META, options, total_images=90, progress=done.append)

    assert (result.name, result.workspace_id, result.description) == ("out", 5, "train/val")
    result_meta = sly.ProjectMeta.from_json(api.metas[result.id])
    assert result_meta.get_tag_meta("train").color == [9, 9, 9]  # existing meta kept
    assert result_meta.get_tag_meta("val").value_type == sly.TagValueType.NONE

    by_id = {ds.id: ds for ds in api.created_datasets}
    tree = sorted((ds.name, by_id[ds.parent_id].name if ds.parent_id else None) for ds in api.created_datasets)
    assert tree == [("empty", None), ("hard", "train"), ("train", None)]
    assert [ds.description for ds in api.created_datasets if ds.name == "train"] == ["d"]
    assert list(api.custom_data.values()) == [{"k": 1}]

    copied = {src for _, _, ids, _ in api.uploaded_images for src in ids}
    assert copied == set(api.anns)
    first_batch = api.uploaded_images[0]
    assert by_id[first_batch[0]].name == "train" and first_batch[3][:2] == [{"i": 0}, {"i": 1}]
    assert all(len(ids) <= 50 for _, _, ids, _ in api.uploaded_images)

    splits = Counter(split_of(ann) for ann in api.uploaded_anns.values())
    assert splits == {("train",): 63, ("val",): 27}
    names = {image.id: image.name for images in api.images.values() for image in images}
    for src_id, ann in api.uploaded_anns.items():
        assert [t.value for t in ann.img_tags if t.name == "note"] == [names[src_id]]
        assert len(ann.labels) == 1
    assert sum(done) == 90


def test_split_is_global_across_datasets_and_random(api):
    train_by_ds = Counter()
    for seed in range(10):
        fake = FakeApi()
        tag_project(fake, fake.source, META, SplitOptions(50), 90, rng=random.Random(seed))
        train_by_ds.update(src < 200 for src, ann in fake.uploaded_anns.items() if split_of(ann) == ("train",))
    assert train_by_ds[True] + train_by_ds[False] == 450
    assert train_by_ds[False] > 0 and train_by_ds[True] > 0


def test_share_tags_every_image_train_and_val(api):
    tag_project(api, api.source, META, SplitOptions(30, share=True), 90)
    assert {split_of(ann) for ann in api.uploaded_anns.values()} == {("train", "val")}


def test_empty_name_and_workspace_override(api):
    result = tag_project(api, api.source, META, SplitOptions(result_name=" "), 90, workspace_id=99)
    assert (result.name, result.workspace_id) == ("fruits_tagged", 99)


def test_split_sizes_come_from_the_count_shown_in_the_gui(api):
    # 100 images were shown, 90 exist now: 80 train as shown, the remaining 10 are val
    tag_project(api, api.source, META, SplitOptions(80), total_images=100)
    assert Counter(split_of(ann) for ann in api.uploaded_anns.values()) == {("train",): 80, ("val",): 10}


def test_nothing_is_created_for_split_tags_with_values(api):
    bad = sly.ProjectMeta(tag_metas=[sly.TagMeta("val", sly.TagValueType.ANY_NUMBER)])
    with pytest.raises(ValueError):
        tag_project(api, api.source, bad, SplitOptions(), 90)
    assert api.created_projects == []
