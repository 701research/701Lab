# dashboard

This directory contains dashboard-generation programs for the 701Lab project.

The programs in this directory generate frame-based visual overlays from processed run data, including items such as speed, heart rate, temperature, position, and attitude-related values.

At the current stage, the main scripts are:

- [bviz_1_make_frames_like_sample_K1600GT.py](./bviz_1_make_frames_like_sample_K1600GT.py)  
  Dashboard frame generator for the BMW K1600GT configuration.

- [bviz_1_make_frames_like_sample_R18.py](./bviz_1_make_frames_like_sample_R18.py)  
  Dashboard frame generator for the BMW R18 configuration.

These scripts read processed data such as GPS, Polar, temperature, and IMU outputs and generate frame sequences for HUD-style visualization. The current K1600GT and R18 versions are closely related in structure, while still preserving bike-specific settings such as default labels and sensor references. :contentReference[oaicite:4]{index=4} :contentReference[oaicite:5]{index=5} :contentReference[oaicite:6]{index=6} :contentReference[oaicite:7]{index=7}

The present design reflects the practical working state of 701Lab.  
In the future, these dashboard generators are expected to be reorganized into a more unified structure using external configuration data such as JSON files.
