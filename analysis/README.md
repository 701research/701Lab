# analysis

This directory contains the post-acquisition analysis pipeline for the 701Lab project.

The analysis workflow is divided into two main execution environments:

- [pi-side/](./pi-side/)  
  Raspberry Pi–side lightweight post-run processing.  
  This area generates derived artifacts such as QC reports, provenance and schema files, segments, events, and run indices directly from the run-based acquisition outputs.

- [windows-side/](./windows-side/)  
  Windows-side cross-run and sensor-level analysis.  
  This area organizes immutable run archives into structured datasets for comparison, visualization, quality evaluation, and downstream analysis.

The purpose of this directory is to keep the analysis pipeline structured according to execution environment and processing role, while maintaining a clear separation between lightweight Pi-side derivation and richer Windows-side analysis workflows.
