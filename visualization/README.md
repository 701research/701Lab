# visualization

This directory contains visualization-related programs for the 701Lab project.

The role of this area is to transform processed sensing and analysis results into visual outputs that can be used in video production and related presentation workflows.

At the current stage, the visualization layer is organized into two main parts:

- [dashboard/](./dashboard/)  
  Programs for generating dashboard-style visual overlays and frame-based visual outputs from processed run data.

- [title-intro/](./title-intro/)  
  Programs for generating title and introduction sequences used before the main dashboard or ride visualization.

The current implementation is based on separate scripts for different bike configurations, including BMW K1600GT and BMW R18.  
These scripts reflect the practical working setup currently used in 701Lab. The dashboard generators read processed run data and produce frame sequences for HUD-style visualization, while the title-intro generators create opening text sequences and related intro video assets.

In the future, these scripts are expected to be integrated more systematically through imported JSON-based configuration files, so that bike-specific settings and layout parameters can be handled in a more unified way.
