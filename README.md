<div align="center" markdown>

<img src="https://i.imgur.com/rjoVeXV.png"/>

# Assign train/val tags to images

<p align="center">

  <a href="#Overview">Overview</a> •
  <a href="#How-To-Run">How To Run</a> •
  <a href="#How-To-Use">How To Use</a>
</p>

[![](https://img.shields.io/badge/slack-chat-green.svg?logo=slack)](https://supervise.ly/slack)
![GitHub release (latest SemVer)](https://img.shields.io/github/v/release/supervisely-ecosystem/tag-train-val-test)
[![views](https://app.supervise.ly/public/api/v3/ecosystem.counters?repo=supervisely-ecosystem/tag-train-val-test&counter=views&label=views)](https://supervise.ly)
[![runs](https://app.supervise.ly/public/api/v3/ecosystem.counters?repo=supervisely-ecosystem/tag-train-val-test&counter=runs&label=runs&123)](https://supervise.ly)

</div>

## Overview

Application tags images in project. User can choose percentage of images that will be tagged as "train" or "val" and several additional options. Neural Networks will use these tags to split data into training/validation datasets. 

<img src="https://i.imgur.com/KA8kXBr.png"/>

## How To Run 
**Step 1**: Add app to your team from Ecosystem if it is not there.

**Step 2**: Run from context menu of project: `thee dots button` -> `Run App` -> `Training data` -> `Assign train\val tags to images`.

**Step 3**: You will be redirected to `Current Workspace`->`Tasks` page. Wait until app is started and press `Open` button. 

**Note**: Running procedure is simialr for almost all apps that are started from context menu. Example steps with screenshots are [here in how-to-run section](https://github.com/supervisely-ecosystem/merge-classes#how-to-run).  

## How to Use

**Step 1**: Choose proportion of train/val images by modifying slider. Other parameters are optional with default values.

<img src="https://media2.giphy.com/media/cnApWE1MfG9522UCv5/giphy.gif"/>

**Step 2**: Press `Run` button. 

**Step 3**: Whait until process is finished. Link to resulting project will be created both on application page (`Output` section) and in workspace tasks table.

**Step 4**: App shuts down automatically on finish.

