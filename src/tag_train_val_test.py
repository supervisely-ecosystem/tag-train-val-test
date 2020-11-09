import os
import random
from collections import defaultdict
import supervisely_lib as sly

TEAM_ID = int(os.environ['context.teamId'])
WORKSPACE_ID = int(os.environ['context.workspaceId'])
PROJECT_ID = int(os.environ['modal.state.slyProjectId'])

my_app = sly.AppService()
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

    train_images = shuffled_images[:train_images_count]
    val_images = shuffled_images[train_images_count:]

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
                for tag_meta in tag_metas:
                    new_ann = new_ann.add_tag(sly.Tag(tag_meta))
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

    res_name = state["resultProjectName"]
    new_project = api.project.create(WORKSPACE_ID, res_name, sly.ProjectType.IMAGES,
                                     description="train/val", change_name_if_conflict=True)
    api.project.update_meta(new_project.id, META_RESULT.to_json())

    progress = sly.Progress("Tagging", TOTAL_IMAGES_COUNT)

    if share_images is True:
        if train_count != val_count:
            raise ValueError("Share images option is enabled, but train_count != val_count")
        if _cnt_val == 0:
            _created_datasets = {}
            _assign_tag(api, images_train, [TRAIN_TAG_META, VAL_TAG_META], new_project, _created_datasets, progress)
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
    my_app.stop()


def main():
    sly.logger.info("Input params", extra={"context.teamId": TEAM_ID,
                                           "context.workspaceId": WORKSPACE_ID,
                                           "modal.state.slyProjectId": PROJECT_ID})
    global PROJECT, TOTAL_IMAGES_COUNT, META_ORIGINAL, META_RESULT

    api = sly.Api.from_env()
    PROJECT = api.project.get_info_by_id(PROJECT_ID)
    meta_json = api.project.get_meta(PROJECT.id)
    META_ORIGINAL = sly.ProjectMeta.from_json(meta_json)
    if META_ORIGINAL.get_tag_meta(TRAIN_NAME) is not None:
        raise KeyError("Tag {!r} already exists in project meta".format(TRAIN_NAME))
    if META_ORIGINAL.get_tag_meta(VAL_NAME) is not None:
        raise KeyError("Tag {!r} already exists in project meta".format(VAL_NAME))
    META_RESULT = META_ORIGINAL.add_tag_metas([TRAIN_TAG_META, VAL_TAG_META])

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
#@TODO: workspace tasks output
if __name__ == "__main__":
    sly.main_wrapper("main", main)
