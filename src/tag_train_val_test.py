import os
import random
import string
import supervisely_lib as sly

TEAM_ID = int(os.environ['context.teamId'])
WORKSPACE_ID = int(os.environ['context.workspaceId'])
PROJECT_ID = int(os.environ['modal.state.slyProjectId'])

my_app = sly.AppService()
PROJECT = None
TOTAL_IMAGES_COUNT = None

@my_app.callback("assign_tags")
@sly.timeit
def assign_tags(api: sly.Api, task_id, context, state, app_logger):
    train_count = state["count.train"]
    val_count = state["count.val"]
    share_images = state["shareImagesBetweenSplits"]
    if share_images is True:
        if train_count != val_count:
            raise ValueError("Share images option is enabled, but train_count != val_count")
    else:
        if train_count + val_count != TOTAL_IMAGES_COUNT:
            raise ValueError("train_count + val_count != TOTAL_IMAGES_COUNT")


def main():
    sly.logger.info("Input params", extra={"context.teamId": TEAM_ID,
                                           "context.workspaceId": WORKSPACE_ID,
                                           "modal.state.slyProjectId": PROJECT_ID})


    api = sly.Api.from_env()
    PROJECT = api.project.get_info_by_id(PROJECT_ID)

    TOTAL_IMAGES_COUNT = api.project.get_images_count(PROJECT.id)
    data = {
        "projectId": PROJECT.id,
        "projectName": PROJECT.name,
        "projectPreviewUrl": api.image.preview_url(PROJECT.reference_image_url, 100, 100),
        "progress": 0,
        "resultProjectId": None,
        "resultProject": "1",
        "resultProjectPreviewUrl": "",
        "started": False,
        "finished": False,
        "totalImagesCount": TOTAL_IMAGES_COUNT,
        "table": [
            {"name": "train", "type": "success"},
            {"name": "val", "type": "warning"},
            {"name": "total", "type": "gray"},
        ]
    }

    train_percent = 80
    train_count = int(TOTAL_IMAGES_COUNT / 100 * train_percent)
    state = {
        "count": {
            "total": TOTAL_IMAGES_COUNT,
            "train": train_count,
            "val": TOTAL_IMAGES_COUNT - train_count
        },
        "percent": {
            "total": 100,
            "train": train_percent,
            "val": 100 - train_percent
        },
        "shareImagesBetweenSplits": False,
        "sliderDisabled": False
    }

    # Run application service
    my_app.run(data=data, state=state)


if __name__ == "__main__":
    sly.main_wrapper("main", main)
