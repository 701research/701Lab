# acquisition

This directory contains acquisition-related programs and supporting resources for the 701Lab project.

The acquisition layer in 701Lab is organized around two main purposes:

- individual sensor bring-up and verification
- integrated data acquisition for actual measurement runs

At the current stage, this directory is structured as follows:

- [sensor-tests/](./sensor-tests/)  
  Individual test and verification programs for each sensor or device.  
  These scripts are intended for connection checks, recognition tests, basic data readout, and bring-up work.

- [integrated/](./integrated/)  
  Integrated acquisition programs used in the actual 701Lab measurement workflow.  
  This area is intended for multi-sensor logging, state-based operation, and run-oriented data recording.

- [common/](./common/)  
  Shared utilities and reusable components used across acquisition programs.  
  Examples include time handling, path generation, logging helpers, and other common functions.

- [configs/](./configs/)  
  Configuration examples, templates, and environment-dependent parameter files related to acquisition.  
  This area is intended to separate configurable settings from program logic where appropriate.

The goal of this directory is not only to store acquisition scripts, but to organize them in a way that makes the distinction between device-level verification and integrated operation clear.

Additional programs, configuration examples, and supporting notes will be added here as the repository structure is further developed.
