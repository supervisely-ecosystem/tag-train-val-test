"""Creates the tagged copy of a project."""

from __future__ import annotations

import random
from collections.abc import Callable

import supervisely as sly

from src import platform_io
from src.core.datasets import parents_first
from src.core.splits import (
    DESCRIPTION,
    TRAIN,
    VAL,
    SplitOptions,
    assign_splits,
    build_result_meta,
    result_project_name,
    retag,
    split_counts,
)

BATCH_SIZE = 50


def tag_project(
    api: sly.Api,
    project: sly.ProjectInfo,
    meta: sly.ProjectMeta,
    options: SplitOptions,
    total_images: int,
    workspace_id: int | None = None,
    progress: Callable[[int], object] | None = None,
    rng: random.Random | None = None,
) -> sly.ProjectInfo:
    """Copy `project` into a new project where every image carries a `train` or `val` tag (or both).

    `total_images` is the count the GUI showed: the split sizes are computed from it, and the images
    beyond the train count are val. The new project goes to `workspace_id` (default: the source
    project's workspace) and keeps the dataset tree, image names, image meta and all other annotation
    data. The source project is only read. `progress` gets the number of images done after every batch.
    """
    result_meta = build_result_meta(meta)
    counts = split_counts(total_images, options.train_percent, options.share)

    datasets = parents_first(platform_io.list_datasets(api, project.id))
    images = {dataset.id: platform_io.list_images(api, dataset.id) for dataset in datasets}
    all_ids = [image.id for dataset in datasets for image in images[dataset.id]]
    splits = assign_splits(all_ids, counts.train, options.share, rng)
    tagged_train = sum(TRAIN in names for names in splits.values())
    tagged_val = sum(VAL in names for names in splits.values())
    sly.logger.info(f"Split of {len(splits)} images: {tagged_train} train, {tagged_val} val")

    target_workspace = project.workspace_id if workspace_id is None else workspace_id
    name = result_project_name(options.result_name, project.name)
    destination = platform_io.create_project(api, target_workspace, name, DESCRIPTION, result_meta)
    sly.logger.info(f"Created project {destination.name!r} (id {destination.id})")

    new_dataset_ids: dict[int, int] = {}
    for dataset in datasets:
        parent_id = new_dataset_ids.get(dataset.parent_id) if dataset.parent_id is not None else None
        new_dataset = platform_io.create_dataset(api, destination.id, dataset, parent_id)
        new_dataset_ids[dataset.id] = new_dataset.id

        for batch in sly.batched(images[dataset.id], BATCH_SIZE):
            anns = platform_io.download_annotations(api, dataset.id, batch, meta)
            tagged = [retag(ann, splits[image.id], result_meta) for image, ann in zip(batch, anns, strict=True)]
            platform_io.copy_images(api, new_dataset.id, batch, tagged)
            if progress is not None:
                progress(len(batch))

    return platform_io.refresh_project(api, destination.id)
