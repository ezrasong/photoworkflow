# Photo Studio

A private, local Windows photo studio for editing, restoration and before/after
review. Built with Electron/Solid components adapted from OpenCode, Oh My Pi as
the assistant, and a Python photo pipeline.

## Install and use

Download the Windows x64 installer from this private repository's Releases page.
The installer downloads and verifies **all app-managed components before it
finishes**: CUDA runtime, photo and assistant models, Oh My Pi, and Obsidian with
Photo Vault (about 34.7 GiB of downloads; allow 105 GiB free for extraction).
Progress and Cancel are available during installation. Interrupted downloads are
kept; rerun the installer to resume. Failed or cancelled setup does not reach Finish.
Launch **Photo Studio** from its shortcut when installation completes; no separate
first-launch download or developer tools are required. Settings retains
**Install / repair complete setup** for recovery and individual component repair.
The installer also includes Photoshop, Lightroom Classic and DaVinci Resolve
MCP servers with private Node/Python dependencies. The licensed creative apps
and NVIDIA driver must already be installed separately.

### Automatic updates

Install version 0.1.7 once to enable the updater; older builds cannot update themselves.
In **Settings > App updates**, enter a GitHub fine-grained token restricted to this
repository with **Contents: read-only** permission. Photo Studio stores it encrypted
with your Windows account; no shared token is bundled in the application.

The app checks the private release channel on launch and every six hours, downloads
new stable installers, and verifies their SHA-512 digest. Choose **Restart and install
update** when idle. Active editing is never interrupted by an automatic restart;
normal app exit does not install updates. **Disconnect updates** removes saved access.
Network/authentication failures leave the current installation working. Your workspace
remains outside the install directory, and setup resumes changed component downloads.

Windows can be resized down to 640×480. Use the menu for navigation; narrower
views switch between Conversation and Controls & review. Short views scroll.
Composer actions stay on one row; scroll the actions horizontally in narrow panes.
Send stays visible, and Ctrl + Enter sends from the text box.

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
Editing preserves originals and existing results. Upgrades preserve the workspace.
Uninstall removes the default AppData workspace, including downloaded models,
runtime, sessions, results, Photo Vault notes and settings, plus the updater cache.
Back up anything you want to keep before uninstalling. Original files outside the
workspace and custom workspaces set with `PHOTOWORKFLOW_HOME` are left in place.
No photo or private note upload is part of
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

Upstream repositories are pinned as Git submodules:

| Submodule | Pin | Purpose |
| --- | --- | --- |
| `vendor/oh-my-pi` | `v18.3.2` | Assistant source, protocol documentation and upstream license. |
| `vendor/obsidian-releases` | `v1.13.7` | Official Obsidian release metadata; the desktop application is closed-source. |
| `vendor/photoshop-mcp` | `v1.7.24` | Photoshop MCP source matching the bundled server. |
| `vendor/lightroom-mcp` | `v0.17.0` | Lightroom MCP server and plug-in source. |
| `vendor/davinci-resolve-mcp` | `v4.8.22` | DaVinci Resolve MCP source matching the bundled server. |

Clone with `git clone --recurse-submodules <repository-url>`, or run
`git submodule update --init --recursive` in an existing checkout. The parent
repository records exact commits; updating a submodule does not automatically
upgrade the packaged application. Setup still downloads the checksum-pinned
Windows releases in `packaging/downloads.json` and verifies Obsidian's publisher.
Submodule checkouts are for upstream reference and maintenance; they are not
installed or required to run Photo Studio. Runtime licenses/notices remain in
the installer, and user vaults and assistant profiles stay outside the submodules.

Dependabot checks **all five submodules daily at 09:00 America/Toronto** and opens
update pull requests. Each PR automatically runs the Windows Actions workflow.
All upstream changes are eligible, including stability fixes, security patches
and features; detection can take up to a day and does not rely on commit-message
keywords. Source updates are proposed for review, never automatically merged or
shipped to installed apps.

CI checks the Git submodule commits against `packaging/creative-mcp.json` and
`packaging/downloads.json` before building. A source-only update intentionally
fails this check until its matching release URLs, versions, hashes, notices and
source pins are reviewed together. Update any corresponding seed manifests too,
then rerun the build and integration checks. An upstream change without a suitable
Windows release stays pending. The existing version-tag release process publishes
approved updates to the app's updater.

Redundant branch builds are cancelled when newer commits arrive. CI artifacts
expire after 14 days; published release installers remain available independently.

See [build/setup and architecture](docs/DESKTOP.md),
[capability coverage](docs/CAPABILITIES.md),
[upstream provenance](desktop/UPSTREAM.md), and
[actual verification results](docs/VERIFICATION.md).
Third-party notices and pinned download manifests are included in the repository.
Windows CI builds an NSIS installer and checksums; version tags publish release
assets. Signing requires configured certificate secrets. Unsigned builds remain
unsigned, regardless of generic signing messages in the packaging log.

## Integration and roadmap

**Current integration:** the desktop talks to Python through private stdio IPC.
Python controls Oh My Pi through its RPC interface, and an explicitly loaded
extension calls a restricted, authenticated local photo-tool broker. Obsidian
opens a dedicated local Markdown vault. The desktop also connects to three bundled MCP (Model Context Protocol) servers
through a bounded inspection tool and Setup connection checks. Photo edits still
use the tested Python bridges. Project-provided MCP configuration stays disabled
in the isolated assistant profile. **Settings → Creative app connections** shows
versions, checks servers, inspects app state, and reveals the Lightroom MCP
plug-in and optional configuration for other MCP clients. DaVinci Resolve is the
chosen video editor; integrated video editing/export remains planned.

After comparing alternatives, the selected servers are
[alisaitteke/photoshop-mcp](https://github.com/alisaitteke/photoshop-mcp) (531 stars),
[Automaat/lightroom-mcp](https://github.com/Automaat/lightroom-mcp) (108 stars), and
[samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp)
(3,211 stars), checked September 28, 2026. Selection also considered maintenance,
Windows support, licenses and installability. See the
[comparison and setup requirements](docs/DESKTOP.md#creative-mcp-selection-september-28-2026).

The following are planned work, not capabilities of the current release:

- **MCP interoperability:** expose selected existing photo and vault tools through
  an optional local MCP server for compatible assistants. Reuse the current Python
  operations and their path authorization, original preservation, cancellation
  and reconstruction opt-ins. Start with inspection and explicit file selection;
  add editing only with the same safeguards. Remote servers and arbitrary tools
  require a separate permissions design. MCP standardizes tool access; it does
  not replace processing models or improve image quality by itself.
- **Creative MCP editing adapters:** extend the bundled servers beyond bounded
  inspection only after synthetic host tests preserve virtual copies, original
  documents, explicit export destinations and cancellation without mutation retries.
  Upstream tools are available through the optional external-client configuration;
  that does not give them unrestricted access inside Photo Studio chat.
- **Video editing with DaVinci Resolve:** build on the bundled Resolve MCP for
  local import/probing, timeline trim/split, audio
  sync, proxy playback and explicit export presets. Keep originals and edit
  decisions separate, with cancellable jobs and verified duration, timestamps,
  frame rate, audio and color metadata. Evaluate FFmpeg-based processing and its
  distribution licenses before choosing a dependency. Add restoration/upscaling
  only after motion, temporal consistency, flicker and VRAM tests pass; applying
  photo models independently to frames is not sufficient.
- **Higher-quality photo outputs:** retain today's full-resolution, 16-bit sRGB
  TIFF and optional layered PSD/PSB exports. Benchmark denoise, deblur and upscale
  choices on representative paired samples and native-pixel crops, checking fine
  texture, halos, face identity, color and tile seams. Plan a floating-point
  working pipeline to reduce repeated rounding, wider-gamut ICC-managed export,
  and separately validated HDR support. Add explicit quality/time/VRAM choices
  only where tests show a useful improvement. Larger dimensions or bit depth
  alone do not recover lost detail; the current 8-bit preview is separate from
  the saved high-precision output.

Export baseline testing has started: synthetic TIFF round-trips retain all
65,536 levels exactly, and actual Photoshop PSD/PSB composites differed from
the test TIFFs by at most 2/65535 per channel. See the
[measured export checks and reproduction commands](docs/VERIFICATION.md).
These results establish export fidelity, not improved model or HDR quality.
