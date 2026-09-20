# Darwin infrastructure diagram

- `darwin-infrastructure.excalidraw`: native editable scene, 90 elements. Open it with Excalidraw's Open file action. Components and labels are grouped; no raster image is embedded in the editable file.
- `darwin-infrastructure.svg`: scalable vector preview.
- `darwin-infrastructure.png`: rendered preview, 1800 × 1240.
- `build_infrastructure_diagram.py`: deterministic layout source (JSON + SVG).

The diagram follows the implemented Darwin software interfaces and planned physical wiring. It separates the Mac application, physical hardware, and simulation/test adapters. Solid arrows carry data, commands or power; the green dashed loop is camera observation. The hidden actuator mapping is excluded from learner inputs. Firmware and adapters are software tested; actual hardware commissioning remains pending.

Format checked against [Excalidraw's official JSON schema documentation](https://docs.excalidraw.com/docs/codebase/json-schema). Native schema version 2; all content is editable text, rectangles and arrows.
