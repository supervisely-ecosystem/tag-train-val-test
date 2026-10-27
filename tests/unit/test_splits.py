"""Pure split logic: sizes, assignment, result meta, re-tagging, result name."""

import random

import pytest
import supervisely as sly

from src.core.splits import (
    TRAIN,
    VAL,
    assign_splits,
    build_result_meta,
    default_result_name,
    result_project_name,
    retag,
    split_counts,
)

BOX = sly.ObjClass("box", sly.Rectangle)
NOTE = sly.TagMeta("note", sly.TagValueType.ANY_STRING)


@pytest.mark.parametrize(
    ("total", "percent", "train"),
    [(100, 80, 80), (5, 80, 4), (7, 80, 5), (3, 1, 0), (3, 100, 3), (0, 80, 0), (35, 80, 28), (22, 33, 7)],
)
def test_split_counts_floor_like_the_gui(total, percent, train):
    counts = split_counts(total, percent)
    assert (counts.train, counts.val, counts.total) == (train, total - train, total)


def test_split_counts_match_the_old_gui_formula_for_every_percent():
    for total in range(0, 400):
        for percent in range(1, 101):
            assert split_counts(total, percent).train == int(total * percent / 100)


def test_share_puts_every_image_in_both_splits():
    counts = split_counts(10, 30, share=True)
    assert (counts.train, counts.val, counts.total) == (10, 10, 10)
    assert assign_splits([1, 2, 3], 3, share=True) == {1: (TRAIN, VAL), 2: (TRAIN, VAL), 3: (TRAIN, VAL)}


@pytest.mark.parametrize("percent", [0, 101])
def test_split_counts_reject_out_of_range_percent(percent):
    with pytest.raises(ValueError):
        split_counts(10, percent)


def test_assign_splits_takes_a_random_train_subset_of_the_requested_size():
    ids = list(range(100, 200))
    seen_train = set()
    for seed in range(20):
        splits = assign_splits(ids, 30, rng=random.Random(seed))
        assert set(splits) == set(ids)
        train = {i for i, names in splits.items() if names == (TRAIN,)}
        assert len(train) == 30
        assert all(names == (VAL,) for i, names in splits.items() if i not in train)
        seen_train |= train
    assert len(seen_train) > 60, "the train subset must vary between runs"


def test_assign_splits_with_more_train_than_images_makes_all_train():
    assert assign_splits([1, 2], 5) == {1: (TRAIN,), 2: (TRAIN,)}
    assert assign_splits([], 0) == {}


def test_result_meta_adds_split_tags_and_keeps_everything_else():
    meta = sly.ProjectMeta(obj_classes=[BOX], tag_metas=[NOTE])
    result = build_result_meta(meta)
    assert result.get_obj_class("box") == BOX
    assert result.get_tag_meta("note") == NOTE
    for name, color in ((TRAIN, [0, 255, 0]), (VAL, [255, 128, 0])):
        tag_meta = result.get_tag_meta(name)
        assert tag_meta.value_type == sly.TagValueType.NONE
        assert tag_meta.color == color


def test_result_meta_reuses_existing_split_tags():
    existing = sly.TagMeta(TRAIN, sly.TagValueType.NONE, color=[1, 2, 3])
    result = build_result_meta(sly.ProjectMeta(tag_metas=[existing]))
    assert result.get_tag_meta(TRAIN).color == [1, 2, 3]
    assert result.get_tag_meta(VAL) is not None


@pytest.mark.parametrize("name", [TRAIN, VAL])
def test_result_meta_rejects_split_tags_with_values(name):
    meta = sly.ProjectMeta(tag_metas=[sly.TagMeta(name, sly.TagValueType.ANY_STRING)])
    with pytest.raises(ValueError, match=name):
        build_result_meta(meta)


def test_retag_replaces_split_tags_and_keeps_labels_and_other_tags():
    old_val = sly.TagMeta(VAL, sly.TagValueType.NONE)
    meta = sly.ProjectMeta(obj_classes=[BOX], tag_metas=[NOTE, old_val])
    result_meta = build_result_meta(meta)
    label = sly.Label(sly.Rectangle(1, 1, 3, 4), BOX, tags=sly.TagCollection([sly.Tag(NOTE, "on object")]))
    ann = sly.Annotation((6, 8), labels=[label], img_tags=sly.TagCollection([sly.Tag(NOTE, "keep"), sly.Tag(old_val)]))

    tagged = retag(ann, (TRAIN,), result_meta)

    assert [(t.name, t.value) for t in tagged.img_tags] == [("note", "keep"), (TRAIN, None)]
    assert tagged.labels[0].to_json() == label.to_json()
    both = retag(tagged, (TRAIN, VAL), result_meta)
    assert [t.name for t in both.img_tags] == ["note", TRAIN, VAL]
    sly.Annotation.from_json(both.to_json(), result_meta)  # valid against the result meta


def test_result_name():
    assert default_result_name("Lemons") == "Lemons (with train-val tags)"
    assert result_project_name("a/b\\c|d", "src") == "abcd"
    assert result_project_name("  keep spaces ", "src") == "  keep spaces "
    assert result_project_name("", "src") == "src_tagged"
    assert result_project_name("   ", "src") == "src_tagged"
    assert result_project_name("//", "src") == "src_tagged"
