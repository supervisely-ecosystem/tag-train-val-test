import os
import random
from collections import defaultdict
from typing import Dict, List, Optional, Set
import supervisely as sly
from supervisely.app.v1.app_service import AppService
import workflow as w
from datetime import datetime

TEAM_ID = int(os.environ['context.teamId'])
WORKSPACE_ID = int(os.environ['context.workspaceId'])
PROJECT_ID = int(os.environ['modal.state.slyProjectId'])

my_app: AppService = AppService()
PROJECT = None
TOTAL_IMAGES_COUNT = None
META_ORIGINAL: sly.ProjectMeta = None
META_RESULT: sly.ProjectMeta = None

TRAIN_NAME = 'train'
TRAIN_COLOR = [0, 255, 0] #RGB
VAL_NAME = 'val'
VAL_COLOR = [255, 128, 0]
TRAIN_TAG_META = sly.TagMeta(TRAIN_NAME, sly.TagValueType.NONE, color=TRAIN_COLOR)
VAL_TAG_META = sly.TagMeta(VAL_NAME, sly.TagValueType.NONE, color=VAL_COLOR)


def sample_images(api, datasets, train_images_count):
    all_images = []
    for dataset in datasets:
        images = api.image.get_list(dataset.id)
        all_images.extend(images)
    cnt_images = len(all_images)

    shuffled_images = all_images.copy()
    random.shuffle(shuffled_images)

    train_images = shuffled_images[:int(train_images_count)]
    val_images = shuffled_images[int(train_images_count):]

    ds_images_train = defaultdict(list)
    for image_info in train_images:
        ds_images_train[image_info.dataset_id].append(image_info)

    ds_images_val = defaultdict(list)
    for image_info in val_images:
        ds_images_val[image_info.dataset_id].append(image_info)

    return ds_images_train, ds_images_val, len(train_images), len(val_images)

def _find_parents_in_tree(
    tree: Dict[sly.DatasetInfo, Dict], dataset_id: int, with_self: bool = False
) -> Optional[List[sly.DatasetInfo]]:
    """
    Find all parent datasets in the tree for a given dataset ID.
    """

    def _dfs(subtree: Dict[sly.DatasetInfo, Dict], parents: List[sly.DatasetInfo]):
        for dataset_info, children in subtree.items():
            if dataset_info.id == dataset_id:
                if with_self:
                    return parents + [dataset_info]
                return parents
            res = _dfs(children, parents + [dataset_info])
            if res is not None:
                return res
        return None

    return _dfs(tree, [])


def copy_project(
    task_id: int,
    api: sly.Api,
    project_name: str,
    workspace_id: int,
    project_id: int,
    dataset_ids: List[int] = [],
    with_annotations: bool = True,
    progress: sly.Progress = None,
):
    """
    Copy a project

    :param task_id: ID of the task
    :type task_id: int
    :param api: Supervisely API
    :type api: Api
    :param project_name: Name of the new project
    :type project_name: str
    :param workspace_id: ID of the workspace
    :type workspace_id: int
    :param project_id: ID of the project to copy
    :type project_id: int
    :param dataset_ids: List of dataset IDs to copy. If empty, all datasets from the project will be copied.
    :type dataset_ids: List[int]
    :param with_annotations: Whether to copy annotations
    :type with_annotations: bool
    :param progress: Progress object to report progress
    :type progress: Progress
    :return: Created project
    :rtype: ProjectInfo
    """

    def _create_project() -> sly.ProjectInfo:
        created_project = api.project.create(
            workspace_id,
            project_name,
            type=sly.ProjectType.IMAGES,
            description="train/val",
            change_name_if_conflict=True,
        )
        api.project.update_meta(created_project.id, META_RESULT)
        return created_project

    def _copy_full_project(
        created_project: sly.ProjectInfo, src_datasets_tree: Dict[sly.DatasetInfo, Dict]
    ):
        src_dst_ds_id_map: Dict[int, int] = {}

        def _create_full_tree(ds_tree: Dict[sly.DatasetInfo, Dict], parent_id: int = None):
            for src_ds, nested_src_ds_tree in ds_tree.items():
                dst_ds = api.dataset.create(
                    project_id=created_project.id,
                    name=src_ds.name,
                    description=src_ds.description,
                    change_name_if_conflict=True,
                    parent_id=parent_id,
                )
                src_dst_ds_id_map[src_ds.id] = dst_ds

                # Preserve dataset custom data
                info_ds = api.dataset.get_info_by_id(src_ds.id)
                if info_ds.custom_data:
                    api.dataset.update_custom_data(dst_ds.id, info_ds.custom_data)
                _create_full_tree(nested_src_ds_tree, parent_id=dst_ds.id)

        _create_full_tree(src_datasets_tree)

        for src_ds_id, dst_ds in src_dst_ds_id_map.items():
            _copy_items(src_ds_id, dst_ds)

    def _copy_datasets(created_project: sly.ProjectInfo, src_datasets_tree: Dict[sly.DatasetInfo, Dict]):
        created_datasets: Dict[int, sly.DatasetInfo] = {}
        processed_copy: Set[int] = set()

        for dataset_id in dataset_ids:
            chain = _find_parents_in_tree(src_datasets_tree, dataset_id, with_self=True)
            if not chain:
                sly.logger.warning(
                    f"Dataset id {dataset_id} not found in project {project_id}. Skipping."
                )
                continue

            parent_created_id = None
            for ds_info in chain:
                if ds_info.id in created_datasets:
                    parent_created_id = created_datasets[ds_info.id].id
                    continue

                created_ds = api.dataset.create(
                    created_project.id,
                    ds_info.name,
                    description=ds_info.description,
                    change_name_if_conflict=False,
                    parent_id=parent_created_id,
                )
                created_datasets[ds_info.id] = created_ds
                src_info = api.dataset.get_info_by_id(ds_info.id)
                if src_info.custom_data:
                    api.dataset.update_custom_data(created_ds.id, src_info.custom_data)
                parent_created_id = created_ds.id

            if dataset_id not in processed_copy:
                _copy_items(dataset_id, created_datasets[dataset_id])
                processed_copy.add(dataset_id)

    def _copy_items(src_ds_id: int, dst_ds: sly.DatasetInfo):
        input_img_infos = api.image.get_list(src_ds_id)
        api.image.copy_batch_optimized(
            src_dataset_id=src_ds_id,
            src_image_infos=input_img_infos,
            dst_dataset_id=dst_ds.id,
            with_annotations=with_annotations,
        )
        if progress is not None:
            progress.iters_done_report(len(input_img_infos))
            progress_percent = int(progress.current * 100 / progress.total)
            api.task.set_field(task_id, "data.progress", progress_percent)
            fields = [
                {"field": "data.progressCurrent", "payload": progress.current},
                {"field": "data.progressTotal", "payload": progress.total},
                {"field": "data.progress", "payload": progress_percent},
            ]
            api.task.set_fields(task_id, fields)

    fields = [
        {"field": "data.message", "payload": "Cloning project..."},
        {"field": "data.progress", "payload": 0},
        {"field": "data.progressCurrent", "payload": 0},
        {"field": "data.progressTotal", "payload": TOTAL_IMAGES_COUNT},
    ]
    api.task.set_fields(task_id, fields)
    created_project = _create_project()
    src_datasets_tree = api.dataset.get_tree(project_id)

    if not dataset_ids:
        _copy_full_project(created_project, src_datasets_tree)
    else:
        _copy_datasets(created_project, src_datasets_tree)
    return created_project

def _assign_tag(task_id, api: sly.Api, split, tag_metas, new_project, created_datasets, progress):
    for dataset_id, images in split.items():
        dataset = api.dataset.get_info_by_id(dataset_id)
        if dataset.name not in created_datasets:
            new_dataset = api.dataset.create(new_project.id, dataset.name)
            created_datasets[dataset.name] = new_dataset
        new_dataset = created_datasets[dataset.name]

        for batch in sly.batched(images):
            image_ids = [image_info.id for image_info in batch]
            image_names = [image_info.name for image_info in batch]
            ann_infos = api.annotation.download_batch(dataset.id, image_ids)
            new_annotations = []

            for ann_info in ann_infos:
                ann_json = ann_info.annotation
                new_ann = sly.Annotation.from_json(ann_json, META_ORIGINAL)
                img_tags = new_ann.img_tags.items()
                img_tags = [tag for tag in img_tags if tag.meta.name not in [TRAIN_NAME, VAL_NAME]]
                for tag_meta in tag_metas:
                    img_tags.append(sly.Tag(tag_meta))
                new_ann = new_ann.clone(img_tags=sly.TagCollection(img_tags))
                new_annotations.append(new_ann)

            new_images = api.image.upload_ids(new_dataset.id, image_names, image_ids)
            new_image_ids = [image_info.id for image_info in new_images]
            api.annotation.upload_anns(new_image_ids, new_annotations)

            progress.iters_done_report(len(batch))
            progress_percent = int(progress.current * 100 / progress.total)
            api.task.set_field(task_id, "data.progress", progress_percent)
            fields = [
                {"field": "data.progressCurrent", "payload": progress.current},
                {"field": "data.progressTotal", "payload": progress.total},
                {"field": "data.progress", "payload": progress_percent},
            ]
            api.task.set_fields(task_id, fields)

def _assign_tag_inplace(task_id, api: sly.Api, split, tag_metas, progress):
    for dataset_id, images in split.items():
        dataset = api.dataset.get_info_by_id(dataset_id)
        for batch in sly.batched(images):
            image_ids = [image_info.id for image_info in batch]
            ann_infos = api.annotation.download_batch(dataset.id, image_ids)
            new_annotations = []

            for ann_info in ann_infos:
                ann_json = ann_info.annotation
                new_ann = sly.Annotation.from_json(ann_json, META_ORIGINAL)
                img_tags = new_ann.img_tags.items()
                img_tags = [tag for tag in img_tags if tag.meta.name not in [TRAIN_NAME, VAL_NAME]]
                for tag_meta in tag_metas:
                    img_tags.append(sly.Tag(tag_meta))
                new_ann = new_ann.clone(img_tags=sly.TagCollection(img_tags))
                new_annotations.append(new_ann)

            api.annotation.upload_anns(image_ids, new_annotations)

            progress.iters_done_report(len(batch))
            progress_percent = int(progress.current * 100 / progress.total)
            fields = [
                {"field": "data.progressCurrent", "payload": progress.current},
                {"field": "data.progressTotal", "payload": progress.total},
                {"field": "data.progress", "payload": progress_percent},
            ]
            api.task.set_fields(task_id, fields)

def validate_project_name(name):
    if not name or name.strip() == "":
        return f"{PROJECT.name}_tagged"
    
    special_chars = ['/', '\\', '|']
    for char in special_chars:
        name = name.replace(char, '')
    
    return name

@my_app.callback("assign_tags")
@sly.timeit
def assign_tags(api: sly.Api, task_id, context, state, app_logger):
    api.task.set_field(task_id, "data.started", True)

    train_count = state["count"]["train"]
    val_count = state["count"]["val"]
    share_images = state["shareImagesBetweenSplits"]

    inplace = state["inplace"]
    if inplace is True:
        raise NotImplementedError("Inplace operation will be implemented in the future...")

    res_name = validate_project_name(state["resultProjectName"])

    progress = sly.Progress("Cloning project...", TOTAL_IMAGES_COUNT)
    new_project = copy_project(task_id, api, res_name, WORKSPACE_ID, PROJECT.id, progress=progress)
    
    datasets = api.dataset.get_list(new_project.id, recursive=True)
    images_train, images_val, _cnt_train, _cnt_val = sample_images(api, datasets, train_count)

    progress = sly.Progress("Tagging", TOTAL_IMAGES_COUNT)
    fields = [
        {"field": "data.message", "payload": "Tagging..."},
        {"field": "data.progress", "payload": 0},
        {"field": "data.progressCurrent", "payload": 0},
        {"field": "data.progressTotal", "payload": TOTAL_IMAGES_COUNT},
    ]
    api.task.set_fields(task_id, fields)

    if share_images is True:
        if _cnt_val == 0:
            _assign_tag_inplace(task_id, api, images_train, [TRAIN_TAG_META, VAL_TAG_META], progress)
        else:
            raise RuntimeError("_cnt_val != 0")
    else:
        if train_count + val_count != TOTAL_IMAGES_COUNT:
            raise ValueError("train_count + val_count != TOTAL_IMAGES_COUNT")

        _assign_tag_inplace(task_id, api, images_train, [TRAIN_TAG_META], progress)
        _assign_tag_inplace(task_id, api, images_val, [VAL_TAG_META], progress)

    # to get correct "reference_image_url"
    new_project = api.project.get_info_by_id(new_project.id)
    fields = [
        {"field": "data.resultProject", "payload": new_project.name},
        {"field": "data.resultProjectId", "payload": new_project.id},
        {"field": "data.resultProjectPreviewUrl",
         "payload": api.image.preview_url(new_project.reference_image_url, 100, 100)},
        {"field": "data.finished", "payload": True}
    ]
    api.task.set_fields(task_id, fields)
    api.task.set_output_project(task_id, new_project.id, new_project.name)
    w.workflow_output(api, new_project.id)
    my_app.stop()


def main():
    sly.logger.info("Input params", extra={"context.teamId": TEAM_ID,
                                           "context.workspaceId": WORKSPACE_ID,
                                           "modal.state.slyProjectId": PROJECT_ID})
    global PROJECT, TOTAL_IMAGES_COUNT, META_ORIGINAL, META_RESULT

    api = sly.Api.from_env()
    PROJECT = api.project.get_info_by_id(PROJECT_ID)
    w.workflow_input(api, PROJECT.id)
    meta_json = api.project.get_meta(PROJECT.id)
    META_ORIGINAL = sly.ProjectMeta.from_json(meta_json)
    original_train_tag_meta = META_ORIGINAL.get_tag_meta(TRAIN_NAME)
    original_val_tag_meta = META_ORIGINAL.get_tag_meta(VAL_NAME)
    META_RESULT = META_ORIGINAL.clone()
    if original_train_tag_meta is not None:
        sly.logger.warn(f"Tag {TRAIN_NAME} already exists in project meta")
        if original_train_tag_meta.value_type != sly.TagValueType.NONE:
            err = f"Existing tag {TRAIN_NAME} in project meta has value_type != NONE. Please check your project tags."
            sly.logger.error(err)
            raise ValueError(err)
        sly.logger.warn(f"Existing {TRAIN_NAME} tags on images will be replaced with new ones")
    else:
        META_RESULT = META_RESULT.add_tag_metas([TRAIN_TAG_META])

    if original_val_tag_meta is not None:
        sly.logger.warn(f"Tag {VAL_NAME} already exists in project meta")
        if original_val_tag_meta.value_type != sly.TagValueType.NONE:
            err = f"Existing tag {VAL_NAME} in project meta has value_type != NONE. Please check your project tags."
            sly.logger.error(err)
            raise ValueError(err)
        sly.logger.warn(f"Existing {VAL_NAME} tags on images will be replaced with new ones")
    else:
        META_RESULT = META_RESULT.add_tag_metas([VAL_TAG_META])

    TOTAL_IMAGES_COUNT = api.project.get_images_count(PROJECT.id)
    data = {
        "projectId": PROJECT.id,
        "projectName": PROJECT.name,
        "projectPreviewUrl": api.image.preview_url(PROJECT.reference_image_url, 100, 100),
        "progress": 0,
        "progressCurrent": 0,
        "progressTotal": TOTAL_IMAGES_COUNT,
        "resultProjectId": None,
        "resultProject": "",
        "resultProjectPreviewUrl": "",
        "started": False,
        "message": "",
        "finished": False,
        "totalImagesCount": TOTAL_IMAGES_COUNT,
        "table": [
            {"name": TRAIN_NAME, "type": "success"},
            {"name": "val", "type": "primary"},
            {"name": "total", "type": "gray"},
        ]
    }

    train_percent = 80
    train_count = int(TOTAL_IMAGES_COUNT / 100 * train_percent)
    state = {
        "count": {
            "total": TOTAL_IMAGES_COUNT,
            TRAIN_NAME: train_count,
            "val": TOTAL_IMAGES_COUNT - train_count
        },
        "percent": {
            "total": 100,
            TRAIN_NAME: train_percent,
            "val": 100 - train_percent
        },
        "shareImagesBetweenSplits": False,
        "sliderDisabled": False,
        "inplace": False,
        "resultProjectName": "{} (with train-val tags)".format(PROJECT.name)
    }

    # Run application service
    my_app.run(data=data, state=state)


#@TODO: inplace
if __name__ == "__main__":
    sly.main_wrapper("main", main)
