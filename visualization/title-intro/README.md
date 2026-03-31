# title-intro

This directory contains title and introduction sequence generators for the 701Lab project.

The programs in this directory are used to generate frame-based opening sequences placed before the main dashboard or ride visualization.

At the current stage, the main scripts are:

- [make_title_intro_K1600GT.py](./make_title_intro_K1600GT.py)  
  Title-intro generator for the BMW K1600GT configuration.

- [make_title_intro_R18.py](./make_title_intro_R18.py)  
  Title-intro generator for the BMW R18 configuration.

These scripts generate title frames and can also create intro video clips and concatenate them with dashboard videos where needed. The current implementation keeps separate scripts for each bike configuration while preserving a common structure for layout, typography, fade timing, and output generation. :contentReference[oaicite:8]{index=8} :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10} :contentReference[oaicite:11]{index=11}

As with the dashboard programs, the current files represent the present working configuration of 701Lab.  
Future integration is expected to move toward a more unified design using imported configuration files such as JSON.
