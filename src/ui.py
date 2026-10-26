"""GUI: source project, train/val proportion, result name, "Train == Validation", Run button, result project."""

from __future__ import annotations

from collections.abc import Callable

import supervisely as sly
from supervisely.app.widgets import (
    Button,
    Card,
    Checkbox,
    Container,
    Field,
    Input,
    Progress,
    ProjectThumbnail,
    Slider,
    Text,
)

from src.core.splits import DEFAULT_TRAIN_PERCENT, SplitOptions, default_result_name, split_counts

# (options, progress callback) -> created project
TagFn = Callable[[SplitOptions, Callable[[int], object]], sly.ProjectInfo]


class TrainValGui:
    """Widgets and the Run handler. Platform side effects come in through `tag` and `on_finished`."""

    def __init__(
        self,
        project: sly.ProjectInfo,
        total_images: int,
        tag: TagFn,
        on_finished: Callable[[sly.ProjectInfo], None],
    ):
        self._total = total_images
        self._tag = tag
        self._on_finished = on_finished

        self.slider = Slider(value=DEFAULT_TRAIN_PERCENT, min=1, max=100, show_input=True)
        self.counts = Text()
        self.result_name = Input(default_result_name(project.name), placeholder="Please input project name")
        self.share = Checkbox("Train == Validation")
        self.slider.value_changed(lambda _: self._show_counts())
        self.share.value_changed(self._share_changed)
        self._show_counts()

        self.run_button = Button("Run", icon="zmdi zmdi-play")
        self.progress = Progress(hide_on_finish=True)
        self.result_text = Text("New project has been successfully created", "success")
        self.result = ProjectThumbnail()
        self.result_text.hide()
        self.result.hide()

        settings = Card(
            "Settings",
            content=Container(
                [
                    Field(
                        Container([self.slider, self.counts]),
                        "Train / Val proportion",
                        "Choose how tags will be split",
                        icon=Field.Icon(zmdi_class="zmdi zmdi-arrow-split", color_rgb=[44, 210, 110]),
                    ),
                    Field(
                        self.result_name,
                        "Result project name",
                        "Choose the name of result project. If name already exists, new name will be generated "
                        "by adding numeric suffix (e.g. '_007')",
                        icon=Field.Icon(zmdi_class="zmdi zmdi-collection-folder-image", color_rgb=[206, 173, 255]),
                    ),
                    Field(
                        self.share,
                        "FOR NN DEBUG: Use all train images in validation",
                        "Images are used for both training and validation to verify if training pipeline is capable "
                        "of overfitting. We recommend to use this option only to debug NN with tiny datasets",
                        icon=Field.Icon(zmdi_class="zmdi zmdi-share", color_rgb=[255, 132, 97]),
                    ),
                ]
            ),
        )
        input_card = Card("Input", content=ProjectThumbnail(_thumbnail_info(project)))
        output_card = Card(
            "Output",
            "A new project with train/val tags on images; the original project is not changed",
            content=Container([self.run_button, self.progress, self.result_text, self.result]),
        )
        self.layout = Container(
            [Container([input_card, output_card], direction="horizontal", fractions=[1, 2]), settings]
        )
        self.run_button.click(self.run)

    def options(self) -> SplitOptions:
        return SplitOptions(
            train_percent=int(self.slider.get_value()),
            share=self.share.is_checked(),
            result_name=self.result_name.get_value(),
        )

    def run(self) -> None:
        options = self.options()
        self._set_locked(True)
        try:
            with self.progress(message="Assigning tags", total=self._total) as bar:
                destination = self._tag(options, bar.update)
        except Exception:
            self._set_locked(False)
            raise
        self.run_button.hide()
        self.result.set(_thumbnail_info(destination))
        self.result.show()
        self.result_text.show()
        self._on_finished(destination)

    def _share_changed(self, checked: bool) -> None:
        if checked:
            self.slider.disable()
        else:
            self.slider.set_value(DEFAULT_TRAIN_PERCENT)  # as before: unchecking resets the proportion
            self.slider.enable()
        self._show_counts()

    def _show_counts(self) -> None:
        share = self.share.is_checked()
        counts = split_counts(self._total, int(self.slider.get_value()), share)
        train_pct, val_pct = (100, 100) if share else (self.slider.get_value(), 100 - self.slider.get_value())
        self.counts.set(
            f"train: {counts.train} images ({train_pct}%) · val: {counts.val} images ({val_pct}%) · "
            f"total: {counts.total} images",
            "text",
        )

    def _set_locked(self, locked: bool) -> None:
        widgets = [self.run_button, self.result_name, self.share]
        if not self.share.is_checked():
            widgets.append(self.slider)
        for widget in widgets:
            if locked:
                widget.disable()
            else:
                widget.enable()


def _thumbnail_info(project: sly.ProjectInfo) -> sly.ProjectInfo:
    """ProjectThumbnail fails on a project without images (no preview url); show it without a preview."""
    if project.reference_image_url is None:
        return project._replace(reference_image_url="")
    return project
