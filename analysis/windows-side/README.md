# windows-side

This directory contains the Windows-side analysis pipeline for the 701Lab project.

The Windows-side workflow is currently organized into multiple analysis phases, each with a different role in preparing, evaluating, and structuring run data for downstream use.

Current subdirectories:

- [b1/](./b1/)  
  Cross-run lightweight preparation and screening.  
  This phase scans immutable run data, collects QC summaries, measures basic run-level properties, assigns preliminary use flags, and freezes a cross-run summary table.

- [b2/](./b2/)  
  Sensor-level extraction, statistics, visualization, and quality evaluation.  
  This phase extracts sensor-wise datasets, converts raw data where needed, computes basic statistics, generates diagnostic figures, evaluates signal quality, and prepares a frozen summary for the next stage.

- [b3/](./b3/)  
  Composition and translation layer for downstream creative structuring.  
  This phase reorganizes run data into section-level features, music control values, session time-series, and section-specific preprocessing signals, then connects them to project-specific composition workflows. It is the layer where ride data begins to be translated into musical structure and other work-specific expressive outputs.

The overall role of the Windows-side analysis layer is to transform immutable run archives into structured, comparable, and analysis-ready datasets while preserving a clear distinction between raw sources, derived outputs, and downstream decision tables.
