# Luma Atelier

A private, local Windows photo studio for editing, restoration and before/after
review. Built with Electron/Solid components adapted from OpenCode, Oh My Pi as
the assistant, and a Python photo pipeline.

## Install and use

Download the Windows x64 installer from this private repository's Releases page.
Install and launch **Luma Atelier** from its shortcut; developer tools are not
required. First launch opens setup when downloads are missing. Choose
**Install / repair complete setup** for all models, runtimes, Oh My Pi, Obsidian
and Photo Vault (about 35 GiB of downloads). Individual components can be repaired.
Downloads show sizes, check disk space, resume interruption and verify SHA-256.
Complete setup installs dependencies in order. Restart when setup finishes.

Windows can be resized down to 640×480. Use the menu for navigation; narrower
views switch between Conversation and Controls & review. Short views scroll.

Create a session, choose a photo/folder, then describe your edit. Manual tone,
denoise, upscale and restoration controls run directly through Python. Advanced
precision panels retain mask painting, clone donors, recipe loading, batch/watch,
reference search, person mappings and vault operations. Review completed results
in the embedded before/after tab, including native-pixel view and panning.
Every desktop conversation prompt passes through local Prompt Master correction;
original and corrected text remain visible. The original controls permissions.
A separate in-app reference browser is available beside the conversation.
Choose **Suggest prompts from photo** for local vision suggestions, then **Use as
draft** to review one before sending. **Search references** opens public image
search; only the query you submit goes online. The chooser can save selected
references with attribution and provenance in Obsidian. References guide comparison
and repair planning; the current models do not reconstruct pixels from references.
For mildly out-of-focus photos choose **Correct soft focus**, adjust blur radius
and correction strength, and compare at 100%. Local deconvolution can improve
recoverable softness; it cannot reliably recover severe defocus or motion blur.

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
- Obsidian is included in complete setup using its official signed release. Vault files
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
