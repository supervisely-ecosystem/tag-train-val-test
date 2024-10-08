import os
import random
from collections import defaultdict
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

    datasets = api.dataset.get_list(PROJECT.id)
    images_train, images_val, _cnt_train, _cnt_val = sample_images(api, datasets, train_count)

    res_name = validate_project_name(state["resultProjectName"])
    new_project = api.project.create(WORKSPACE_ID, res_name, sly.ProjectType.IMAGES,
                                     description="train/val", change_name_if_conflict=True)
    api.project.update_meta(new_project.id, META_RESULT.to_json())

    progress = sly.Progress("Tagging", TOTAL_IMAGES_COUNT)

    if share_images is True:
        if _cnt_val == 0:
            _created_datasets = {}
            _assign_tag(task_id, api, images_train, [TRAIN_TAG_META, VAL_TAG_META], new_project, _created_datasets, progress)
        else:
            raise RuntimeError("_cnt_val != 0")
    else:
        if train_count + val_count != TOTAL_IMAGES_COUNT:
            raise ValueError("train_count + val_count != TOTAL_IMAGES_COUNT")

        _created_datasets = {}
        _assign_tag(task_id, api, images_train, [TRAIN_TAG_META], new_project, _created_datasets, progress)
        _assign_tag(task_id, api, images_val, [VAL_TAG_META], new_project, _created_datasets, progress)

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
