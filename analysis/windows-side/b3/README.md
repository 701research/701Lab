# b3

B3 is the composition and translation layer of the 701Lab Windows-side analysis pipeline.

While earlier stages mainly prepare, clean, summarize, and evaluate run data,  
B3 is the stage where ride data begins to be reorganized into structures that can support creative outputs such as music, section-level interpretation, and project-specific rendering.

At the current stage, B3 already includes:

- session-level feature extraction from GPS-defined sections
- conversion of those features into music control values
- session-level time-series generation
- section-specific preprocessing for coloring / local shaping
- project-specific composition scripts for rendered works

In other words, B3 is not a raw-data processing layer.  
It is the layer where structured ride data starts to be translated into expressive form.

---

## Current workflow inside B3

The current B3 pipeline can be summarized as follows:

1. **Global overview / correlation support**  
   Prepare supporting analyses such as global correlations, lag correlations, and STFT-based audio inspection for understanding overall structure and relationships.

2. **Session feature extraction**  
   Read GPS-defined session boundaries, map them onto actual run time, and extract section-level features such as speed, HR, acceleration, pitch, and lateral energy. These are then normalized within each run.

3. **Music control generation**  
   Convert normalized session features into a compact set of musical control values, currently:
   - BPM
   - note density
   - phrase span
   - harmonic tension
   - inner voice swing

4. **Session time-series generation**  
   Build time-aligned per-session tables from sensor data so that local within-section variation can later be used for coloring and shaping.

5. **Section-specific preprocessing for coloring**  
   For selected sections, derive section-specific control signals such as breathing, accent strength, shadow shape, transition events, melody arc, or drum envelope. These are used to avoid over-flat section-level rendering and to restore local motion inside each section.

6. **Project-specific composition**  
   Use the section-level controls and section-specific preprocessing signals in a composition script that renders MIDI and WAV outputs for a specific work.

At the current stage, this part still contains work-specific logic, especially for the K1600GT “First Light” project.

---

## Directory structure

This directory is currently organized as:

- **[docs/](./docs/)**  
  High-level explanations, pipeline notes, and project notes

- **[configs/](./configs/)**  
  Shared and project-specific configuration files

- **[tools/](./tools/)**  
  Executable scripts and composition utilities

- **[data/](./data/)**  
  Intermediate generated data

- **[outputs/](./outputs/)**  
  Rendered outputs such as MIDI, WAV, and debug materials

### Tools subdirectories

- **[tools/analysis_support/](./tools/analysis_support/)**  
  Supporting analytical scripts that help interpret structure, relations, and time-lag behavior, but do not directly generate compositions

- **[tools/feature_extraction/](./tools/feature_extraction/)**  
  Scripts that generate session features, music controls, and session time-series tables

- **[tools/preprocessing/](./tools/preprocessing/)**  
  Section-specific preprocessing scripts used to derive local coloring signals for selected sections

- **[tools/composition/](./tools/composition/)**  
  Composition-related code

- **[tools/composition/projects/](./tools/composition/projects/)**  
  Project-specific composition scripts, including work-level rendering entry points

---

## Data and outputs

### Intermediate data
The following kinds of intermediate data are expected inside **[data/](./data/)**:

- session features
- session music controls
- session time-series
- preprocessed-for-coloring outputs

### Final / exported outputs
The following kinds of outputs are expected inside **[outputs/](./outputs/)**:

- MIDI renders
- WAV renders
- debug plots
- debug tables

---

## Current status

At the current stage, B3 is partially reusable and partially work-specific.

### Already reusable
The upstream pipeline is already broadly reusable:

- session feature extraction
- music control generation
- session time-series generation
- correlation / lag-correlation support
- section-specific preprocessing framework

These parts are intended to be used not only for the current K1600GT work, but also for future works such as R18-based pieces.

### Still work-specific
The final composition stage remains partially specific to the current project.

For example, the current K1600GT composition workflow includes:

- work-specific section bar counts
- project-specific chord patterns
- section-role assumptions
- selected preprocessing inputs for S1 / S2 / S3 / S5
- rendering choices tuned for the current video work

This is intentional for now.  
The current priority is to preserve a functioning composition workflow while gradually separating reusable core logic from project-specific settings.

---

## Design direction

The intended long-term direction of B3 is:

- keep upstream transformation steps reusable
- move project-specific choices into project configs and project notes
- gradually separate composition core utilities from project entry scripts
- support multiple works (for example K1600GT and R18) on top of the same upstream translation pipeline

In short, B3 is expected to evolve from:

**“a working composition setup for a specific piece”**

toward:

**“a reusable translation framework for multiple 701Lab works.”**

---

## Conceptual role of B3

B3 is where 701Lab begins to move from analysis into expression.

It is the stage where ride data is no longer treated only as measured information,  
but as structured material that can be translated into musical form, section-level meaning, and eventually into finished works.

This means B3 is not only a technical stage.  
It is also the place where the 701Lab idea becomes executable:

- the bike as instrument
- the road as score
- the ride data as performance

---

## Notes

- Some current scripts are intentionally project-specific and are preserved in that form so the original work can be reproduced.
- Reusable upstream scripts should be preferred when extending the pipeline to future works.
- Work-specific scripts should gradually move toward config-driven composition entry points as the framework matures.

---

**I think I’ll ride again today.**  
**And let the ride rise as music.**
