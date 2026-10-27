<div align="center" markdown>

<img src="https://user-images.githubusercontent.com/48245050/182362563-ca05f75c-0480-4ba1-8e4f-f53e11238d4f.png"/>

# Assign train/val tags to images

<p align="center">

  <a href="#Overview">Overview</a> •
  <a href="#How-To-Run">How To Run</a> •
  <a href="#How-To-Use">How To Use</a>
</p>

[![](https://img.shields.io/badge/slack-chat-green.svg?logo=slack)](https://supervisely.com/slack)
![GitHub release (latest SemVer)](https://img.shields.io/github/v/release/supervisely-ecosystem/tag-train-val-test)
[![views](https://app.supervisely.com/img/badges/views/supervisely-ecosystem/tag-train-val-test.png)](https://supervisely.com)
[![runs](https://app.supervisely.com/img/badges/runs/supervisely-ecosystem/tag-train-val-test.png)](https://supervisely.com)

</div>

## Overview

Application tags images in project. User can choose percentage of images that will be tagged as "train" or "val" and several additional options. Neural Networks will use these tags to split data into training/validation datasets.

The original project is not changed: the app creates a new project in the same workspace with the same
datasets (including nested ones), images, annotations and object bindings, and puts exactly one of the tags
`train` / `val` on every image (both tags with "Train == Validation"). Images are picked at random across the
whole project. Existing `train` / `val` tags on images are replaced; existing `train` / `val` tags in the project
meta are reused and must have no value (the app stops with an error otherwise).

<img src="https://i.imgur.com/KA8kXBr.png"/>

## How To Run

**Step 1**: Add app to your team from Ecosystem if it is not there.

**Step 2**: Run from context menu of project: `thee dots button` -> `Run App` -> `Training data` -> `Assign train\val tags to images`.

**Step 3**: You will be redirected to `Current Workspace`->`Tasks` page. Wait until app is started and press `Open` button.

**Note**: Running procedure is similar for almost all apps that are started from context menu. Example steps with screenshots are [here in how-to-run section](https://github.com/supervisely-ecosystem/merge-classes#how-to-run).

## How to Use

**Step 1**: Choose proportion of train/val images with the slider (1-100 %, default 80 %): the number of train
images is `floor(total * percent / 100)`, the rest are val. Optional settings:
- **Result project name** (default `<project name> (with train-val tags)`); characters `/ \ |` are removed, and if the
  name is taken a numeric suffix is added (e.g. `_001`).
- **Train == Validation** (for NN debugging on tiny datasets): every image gets both `train` and `val`.

**Step 2**: Press `Run` button.

**Step 3**: Wait until process is finished. Link to resulting project will be created both on application page (`Output` section) and in workspace tasks table.

**Step 4**: App shuts down automatically on finish.
