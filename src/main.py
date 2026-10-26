"""Assign train/val tags to images: GUI app started from an images project's "Training data" menu.

Run with `uvicorn src.main:app` (see config.json `entrypoint`). This module is the composition root:
it reads the task context, creates the Api and wires the GUI to the tagging and platform outputs.
"""

from __future__ import annotations

import os

import supervisely as sly
from dotenv import load_dotenv

from src import platform_io
from src.core.splits import SplitOptions, build_result_meta
from src.settings import Settings
from src.tagger import tag_project
from src.ui import TrainValGui


def create_app() -> sly.Application:
    if not sly.is_production():
        load_dotenv("local.env")
        load_dotenv(os.path.expanduser("~/supervisely.env"))

    settings = Settings.from_env()
    api = sly.Api.from_env()
    project, meta = platform_io.get_project(api, settings.project_id)
    build_result_meta(meta)  # fail at startup when the project has `train`/`val` tags with values
    total_images = platform_io.count_images(api, project.id)

    def tag(options: SplitOptions, progress) -> sly.ProjectInfo:
        platform_io.register_workflow_input(api, project.id)
        return tag_project(api, project, meta, options, total_images, progress=progress)

    def finished(destination: sly.ProjectInfo) -> None:
        platform_io.set_task_output(api, destination)
        platform_io.register_workflow_output(api, destination.id)
        sly.logger.info("Destination project is created", extra={"project_id": destination.id})
        app.stop()  # the session closes itself; its page stays readable from the tasks list

    gui = TrainValGui(project, total_images, tag, finished)
    app = sly.Application(layout=gui.layout)
    return app


app = create_app()
