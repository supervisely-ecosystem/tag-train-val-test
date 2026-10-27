"""Pure train/val split logic: split sizes, which images get which tag, result meta and annotations."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

import supervisely as sly

TRAIN = "train"
VAL = "val"
SPLIT_TAG_METAS = (
    sly.TagMeta(TRAIN, sly.TagValueType.NONE, color=[0, 255, 0]),
    sly.TagMeta(VAL, sly.TagValueType.NONE, color=[255, 128, 0]),
)
DEFAULT_TRAIN_PERCENT = 80
NAME_SUFFIX = " (with train-val tags)"
DESCRIPTION = "train/val"
_FORBIDDEN_NAME_CHARS = ("/", "\\", "|")


@dataclass(frozen=True)
class SplitOptions:
    """What the user chose in the GUI."""

    train_percent: int = DEFAULT_TRAIN_PERCENT  # 1..100, ignored when `share` is set
    share: bool = False  # "Train == Validation": every image gets both tags
    result_name: str = ""


@dataclass(frozen=True)
class SplitCounts:
    train: int
    val: int
    total: int


def split_counts(total: int, train_percent: int, share: bool = False) -> SplitCounts:
    """Number of images per split, as the GUI shows it: train = floor(total * percent / 100)."""
    if share:
        return SplitCounts(train=total, val=total, total=total)
    if not 1 <= train_percent <= 100:
        raise ValueError(f"Train percent must be in [1, 100], got {train_percent}")
    train = total * train_percent // 100
    return SplitCounts(train=train, val=total - train, total=total)


def assign_splits(
    image_ids: Sequence[int], train_count: int, share: bool = False, rng: random.Random | None = None
) -> dict[int, tuple[str, ...]]:
    """Image id -> split tag names. A random `train_count` images are train, the rest val; with `share`
    every image is both train and val."""
    if share:
        return {image_id: (TRAIN, VAL) for image_id in image_ids}
    shuffled = list(image_ids)
    (rng or random.Random()).shuffle(shuffled)
    return {image_id: (TRAIN,) if i < train_count else (VAL,) for i, image_id in enumerate(shuffled)}


def build_result_meta(meta: sly.ProjectMeta) -> sly.ProjectMeta:
    """Source meta plus the `train`/`val` tag metas. Existing ones are reused; they must have no value."""
    result = meta
    for split_meta in SPLIT_TAG_METAS:
        existing = meta.get_tag_meta(split_meta.name)
        if existing is None:
            result = result.add_tag_meta(split_meta)
        elif existing.value_type != sly.TagValueType.NONE:
            raise ValueError(
                f"Existing tag {split_meta.name!r} in project meta has value type {existing.value_type!r} "
                f"instead of {sly.TagValueType.NONE!r}. Please check your project tags."
            )
        else:
            sly.logger.warning(
                f"Tag {split_meta.name!r} already exists in project meta: "
                f"existing {split_meta.name!r} tags on images will be replaced with new ones"
            )
    return result


def retag(ann: sly.Annotation, split_names: Sequence[str], result_meta: sly.ProjectMeta) -> sly.Annotation:
    """Drop the image's `train`/`val` tags and add the given ones; everything else stays."""
    kept = [tag for tag in ann.img_tags if tag.meta.name not in (TRAIN, VAL)]
    added = [sly.Tag(result_meta.get_tag_meta(name)) for name in split_names]
    return ann.clone(img_tags=sly.TagCollection(kept + added))


def default_result_name(source_name: str) -> str:
    return f"{source_name}{NAME_SUFFIX}"


def result_project_name(requested: str, source_name: str) -> str:
    """The name typed by the user without `/ \\ |`; an empty one becomes `<source>_tagged`."""
    for char in _FORBIDDEN_NAME_CHARS:
        requested = requested.replace(char, "")
    if not requested.strip():
        return f"{source_name}_tagged"
    return requested
