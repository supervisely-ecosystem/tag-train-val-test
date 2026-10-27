"""The GUI in-process through Application.test_client: rendering, the split controls and the Run handler."""

import asyncio

import pytest
import supervisely as sly
from supervisely.app import DataJson, StateJson
from supervisely.app.singleton import Singleton

from src.core.splits import SplitOptions
from src.ui import TrainValGui


def info(cls, **values):
    return cls(**{**{f: None for f in cls._fields}, **values})


PROJECT = info(sly.ProjectInfo, id=10, name="fruits", items_count=7, reference_image_url=None, type="images")
RESULT = info(sly.ProjectInfo, id=11, name="fruits (with train-val tags)", items_count=7, reference_image_url=None)


@pytest.fixture(autouse=True)
def fresh_app(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    Singleton._instances.clear()
    yield
    Singleton._instances.clear()


class Recorder:
    def __init__(self, fail=False):
        self.calls, self.finished, self.fail = [], [], fail

    def tag(self, options, progress):
        self.calls.append(options)
        if self.fail:
            raise RuntimeError("boom")
        for _ in range(7):
            progress(1)
        return RESULT


def make(recorder):
    gui = TrainValGui(PROJECT, 7, recorder.tag, recorder.finished.append)
    return gui, sly.Application(layout=gui.layout)


def post(app, route, state):
    return asyncio.run(app.test_client.post(route, json={"state": state, "context": {}}))


def with_values(gui, percent=None, share=None, name=None):
    state = dict(StateJson())
    if percent is not None:
        state[gui.slider.widget_id] = {**state[gui.slider.widget_id], "value": percent}
    if share is not None:
        state[gui.share.widget_id] = {**state[gui.share.widget_id], "checked": share}
    if name is not None:
        state[gui.result_name.widget_id] = {**state[gui.result_name.widget_id], "value": name}
    return state


def counts_text(gui):
    return DataJson()[gui.counts.widget_id]["text"]


def test_page_renders_with_defaults():
    gui, app = make(Recorder())

    response = asyncio.run(app.test_client.get("/"))

    assert response.status_code == 200
    assert gui.options() == SplitOptions(80, False, "fruits (with train-val tags)")
    assert counts_text(gui) == "train: 5 images (80%) · val: 2 images (20%) · total: 7 images"


def test_moving_the_slider_updates_the_counts():
    gui, app = make(Recorder())

    assert post(app, f"/{gui.slider.widget_id}/value_changed", with_values(gui, percent=100)).status_code == 200

    assert counts_text(gui) == "train: 7 images (100%) · val: 0 images (0%) · total: 7 images"


def test_train_equals_validation_disables_the_slider_and_unchecking_resets_it():
    gui, app = make(Recorder())

    post(app, f"/{gui.share.widget_id}/value_changed", with_values(gui, percent=40, share=True))
    assert DataJson()[gui.slider.widget_id]["disabled"] is True
    assert counts_text(gui) == "train: 7 images (100%) · val: 7 images (100%) · total: 7 images"

    post(app, f"/{gui.share.widget_id}/value_changed", with_values(gui, percent=40, share=False))
    assert DataJson()[gui.slider.widget_id]["disabled"] is False
    assert gui.slider.get_value() == 80
    assert counts_text(gui) == "train: 5 images (80%) · val: 2 images (20%) · total: 7 images"


def test_run_tags_with_the_chosen_options_and_shows_the_result():
    recorder = Recorder()
    gui, app = make(recorder)

    route = f"/{gui.run_button.widget_id}/button_clicked_cb"
    assert post(app, route, with_values(gui, percent=30, share=True, name="mine")).status_code == 200

    assert recorder.calls == [SplitOptions(30, True, "mine")]
    assert recorder.finished == [RESULT]
    assert DataJson()[gui.result.widget_id]["id"] == RESULT.id
    assert DataJson()[gui.run_button.widget_id]["disabled"] is True
    assert DataJson()[gui.result_name.widget_id]["disabled"] is True


def test_a_failed_run_unlocks_the_controls():
    recorder = Recorder(fail=True)
    gui, app = make(recorder)

    with pytest.raises(RuntimeError, match="boom"):  # the SDK turns it into an error dialog on the platform
        post(app, f"/{gui.run_button.widget_id}/button_clicked_cb", with_values(gui, percent=60))

    assert len(recorder.calls) == 1 and recorder.finished == []
    for widget in (gui.run_button, gui.slider, gui.share, gui.result_name):
        assert DataJson()[widget.widget_id]["disabled"] is False
