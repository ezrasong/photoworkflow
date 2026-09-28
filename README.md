# Photo Workflow

A local Windows photo desktop adapted from OpenCode's actual Electron/Solid source,
with Oh My Pi as the assistant and the existing Python photo pipeline as the editor.

## Install and use

Download the Windows x64 installer from this private repository's Releases page.
Install and launch **Photo Workflow** from its shortcut; developer tools are not
required. Open **Setup & settings** to download the runtime and models you need.
Downloads show sizes, check disk space, resume interruption and verify SHA-256.
Install the CUDA runtime first and restart before installing photo models.

Create a session, choose a photo/folder, then describe your edit. Manual tone,
denoise, upscale and restoration controls run directly through Python. Advanced
precision panels retain mask painting, clone donors, recipe loading, batch/watch,
reference search, person mappings and vault operations. Review completed results
in the app or its full-resolution local comparison.

Photos, outputs, models, notes and settings live in a separate AppData workspace.
Originals and existing results are preserved. Upgrades and uninstall preserve user
work. Back up the workspace separately. No photo or private note upload is part of
processing; installation and explicit reference retrieval are separate operations.

## Requirements and limits

- Windows x64. CUDA model inference requires a compatible NVIDIA GPU and driver;
  no CPU or smaller-model fallback is promised. The primary local assistant has
  been validated previously on RTX 5090 32 GB; smaller GPUs can exhaust memory.
- The bundled MambaIRv2 native kernel supports compute capability 12.0 only.
  Real-ESRGAN remains an explicit alternative; there is no silent model fallback.
- Lightroom Classic and Photoshop require your own licensed installations for
  assistant/native Adobe workflows. Add the included Lightroom plug-in using the
  path shown in Setup. Manual deterministic raster edits do not require Adobe.
- Outputs default to 16-bit sRGB TIFF, with optional layered PSD/PSB. Higher bit
  depth does not recover missing source information. Face restoration, removal and
  upscaling estimate content; inspect results locally.
- Supported SDR HEIF preparation preserves decoded samples, but unsupported HDR,
  gain maps, auxiliary data or unknown color can be rejected. RAW development uses
  Lightroom. Dimension, model-memory and regional-edit limits remain enforced.
- Optional Obsidian is downloaded from its official signed release. Vault files
  remain plain local Markdown. No Sync, Publish or community plug-ins are configured.
- Video editing is a future phase; this release exposes photo operations only.

## Development and verification

See [build/setup and architecture](docs/DESKTOP.md),
[capability coverage](docs/CAPABILITIES.md),
[upstream provenance](desktop/UPSTREAM.md), and
[actual verification results](docs/VERIFICATION.md).
Third-party notices and pinned download manifests are included in the repository.
Windows CI builds an NSIS installer and checksums; version tags publish release
assets. Signing requires configured certificate secrets. Unsigned builds remain
unsigned, regardless of generic signing messages in the packaging log.
