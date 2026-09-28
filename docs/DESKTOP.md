# Windows desktop architecture and build

The renderer is sandboxed with Node integration off, context isolation on and
a restrictive CSP. The main process validates caller frames and an action
allowlist. Pickers/drop grant local-file access; preview/reveal paths must be
selected or within the workspace. External navigation, webviews and permissions
are denied for the privileged renderer. Model/tool text is never executed as HTML.
The reference browser is an isolated WebContentsView, without Node, preload or
photo IPC, using a separate memory-only session. It permits public HTTP(S) reads
on standard ports; local/private addresses, non-read requests, downloads and
permission requests are denied. It is intended for reference browsing, not logins,
file uploads or authenticated web applications. Browsing does not add page content
to the assistant automatically.

Prompt Master makes one local, tool-free correction request before every desktop
conversation submission. Both versions are recorded. The broker binds that exact
forwarded submission to the original text before accept_prompt, so rewritten text
cannot authorize reconstruction, path selection or expanded scope. Invalid or
cancelled corrections send no editing request; the composer retains the original.
The existing advanced native panel's legacy assistant is a separate workflow.

**Suggest prompts from photo** uses the same pinned local Qwen3-VL reviewer on the
selected source and references. It returns validated suggestion drafts in Prompt
Master. **Use as draft** fills the composer; only **Send** submits a request.
Suggestions are stored with the session and source path, and grant no permission
to edit. Reference search remains an explicit public query in the local chooser.
**Save chosen references in Photo Vault** archives selected images, attribution,
source links and SHA-256 provenance into new notes under References/Collected.
Closing the chooser cancels selection and saving. Existing notes are preserved.
References support comparison and repair planning; they do not condition the
restoration models or establish factual missing detail.

Before/after review decodes through the existing color-managed backend, displays
8-bit sRGB PNGs in fit or native-pixel mode, and preserves full-precision TIFFs.
The existing image-size/decoder limits and 512 MiB preview source limit apply.

Soft-focus correction uses 12 damped Richardson–Lucy iterations with an estimated
Gaussian point-spread function in linear-light luminance. OpenCV/NumPy are already
bundled; no model or network download is required. Tiled processing includes the
full iterative halo, checks cancellation, preserves uint16 output, and reuses the
existing mask/layer/opacity pipeline. Radius is Gaussian sigma in source pixels
(0.4–3), strength is 0–0.75. It is intended for mild defocus; noise, an incorrect
radius or severe blur can leave artifacts. It does not infer missing faces.

Python is an owned child over private stdio. OMP retains its authenticated
loopback broker, bounded photo tools, isolated profile, GPU locks, opt-in checks,
Adobe preservation and no automatic mutation retries. Its supported RPC mode
needs no separately installed Bun runtime.

Installed code/Python remain under the installation directory. Mutable data is
under Electron userData/Workspace in AppData. Tests may set PHOTOWORKFLOW_HOME.
Selected inputs can remain in external folders; outputs stay workspace bounded.
Upgrades refresh maintained seed assets, never user notes/settings/photos/results.
NSIS is per-user and preserves app data on uninstall. No service, firewall rule,
driver or CUDA toolkit is installed.

## Window sizing and upgrade identity

Photo Studio supports a 640×480 minimum window in Windows device-independent
pixels. This leaves room for native window controls and a usable scrolling pane.
Available width selects split panes or Conversation / Controls & review; height
controls scrolling independently. Navigation can be opened with the menu button.
Setup, messages, controls and review have their own scroll areas. Long paths are
available as tooltips; tabs wrap and retain keyboard focus. At high scaling in a
small window, scroll to reach actions and photo pixels. Native dialogs retain
Windows keyboard and sizing behavior.

The product, executable, installer and shortcuts use Photo Studio. Compatibility
identifiers deliberately remain `photo-workflow`, `local.photoworkflow.desktop`,
`PHOTOWORKFLOW_HOME`, `photo:` and the Lightroom bridge identifier/path. Electron
explicitly retains `%APPDATA%/photo-workflow`, including its Workspace and saved
window state. NSIS retains its upgrade/uninstall identity. No data copy or rename
is necessary; existing user notes are never rewritten for branding.

## Build

Use `git submodule update --init --recursive` to populate the pinned Oh My Pi
source and Obsidian release-metadata repositories under `vendor/`. These are
upstream reference checkouts, not build inputs or mutable application directories.
The installer remains reproducible from the pinned release manifests without
fetching the submodules. To upgrade either application, review its upstream
changes, update the gitlink and release/version/hash pins together, retain the
matching distribution notices, and repeat setup/integration acceptance checks.

Use Node 22, Python 3.12+ and uv 0.12.13 on Windows x64. Download
selective_scan_cuda.pyd from the private repository's native-runtime-v1 release.
The bundle builder verifies its pinned SHA-256. Reproduction source and Windows
adaptations are in scripts/build_mamba_scan.py (CUDA 12.8/MSVC required only to
rebuild that native asset).

```
python packaging/build_backend.py --native <downloaded-selective_scan_cuda.pyd>
cd desktop
npm ci
npm run build
npm test
npm run package
npm run smoke
npm run test:layout
npm run test:installer
```

The bundle uses a fresh hash-pinned Python archive and hash-locked distributions,
never the developer .venv. Tk, image codecs, native Windows dependencies and VC
runtime DLLs are included. Large Torch/cu128 wheels, including CUDA DLLs, are
downloaded/extracted during NSIS installation without pip or compilers. The shipped
Mamba binary requires CPython 3.12/Torch 2.7.1/cu128 and compute capability 12.0.

GitHub Actions builds Windows artifacts and checksums. Version tags publish
installer/checksum assets to private releases. CSC_LINK and CSC_KEY_PASSWORD
secrets optionally enable signing; absent secrets mean unsigned artifacts.
Only the release job gets contents:write.

## Installation and first launch

NSIS `customInstall` synchronously runs `scripts/install_desktop.py` with the
bundled Python in isolated mode. The Tk progress window shows verified downloads
and extraction with cancellation. Silent NSIS installs pass `--silent` and return
nonzero on failure (1) or cancellation (2). Finish / Launch requires success;
logs are saved under `Workspace/desktop/install-logs`. Failed installs retain
program files and partial downloads for resume/repair; user data is preserved.
No additional download is scheduled on first launch after successful installation.

The installer and desktop share seed refresh, downloads and a process-owned setup
lock. Only maintained seed assets are updated. Runtime import paths are refreshed
before photo model conversion, so a fresh installation needs no intermediate
restart. All downloads retain HTTPS, pinned size/SHA-256 and resume checks.
Photoshop, Lightroom Classic, Resolve and GPU drivers remain separately installed.

1. Install all components in order: CUDA runtime, assistant/vision, photo models,
   legacy text models, then Obsidian. Photo Vault is initialized and registered
   with its isolated Obsidian profile. Setup estimates 34.7 GiB of downloads and
   requires 105 GiB free for download/extraction. Settings offers repair if files
   are later removed or damaged; unpacked development builds still open Setup.
2. In licensed Lightroom Classic use File → Plug-in Manager → Add at the displayed
   plug-in path. Photoshop uses its existing supported COM registration.
3. Create a session, select a photo/folder and describe the edit. Manual raster
   controls also work without Adobe. Advanced panels retain precision features.
4. Review locally. Obsidian setup uses its official signed release;
   vault notes remain ordinary local files.

Interrupted downloads retain a partial file, resume with Range or restart when
the server ignores Range. Hash failure removes only the invalid partial. Disk
space is checked before downloading. Inference also verifies model hashes.
After failed mutation inspect preserved evidence before starting a new job.

## Creative MCP selection (September 28, 2026)

GitHub repository searches for Photoshop MCP, Lightroom MCP and DaVinci Resolve
MCP were sorted by stars. Stars are a popularity signal, not a correctness score.
README/source review also checked maintenance, Windows support, licensing,
packaging and mutation behavior. These are the strongest direct candidates found:

| App / repository | Stars | Finding and decision |
| --- | ---: | --- |
| [alisaitteke/photoshop-mcp](https://github.com/alisaitteke/photoshop-mcp) | 531 | Selected: active, MIT, Windows script bridge, packaged dependencies, broad tools. Telemetry disabled by Photo Studio. |
| [loonghao/photoshop-python-api-mcp-server](https://github.com/loonghao/photoshop-python-api-mcp-server) | 306 | Credible Windows COM alternative; Python fits our stack, but narrower advertised tools and lower adoption. |
| [Automaat/lightroom-mcp](https://github.com/Automaat/lightroom-mcp) | 108 | Selected: active, MIT, standalone Windows executable and authenticated local plug-in bridge. |
| [noopz/lightroom_mcp](https://github.com/noopz/lightroom_mcp) | 15 | Apache-2.0 Python/Lua alternative with many Develop controls; last push December 2025 and more manual installation. |
| [samuelgursky/davinci-resolve-mcp](https://github.com/samuelgursky/davinci-resolve-mcp) | 3,211 | Selected: active, MIT, 37 compound tools, documented Windows support, guarded operations and optional in-app bridge. |
| [barckley75/resolve-claude-mcp](https://github.com/barckley75/resolve-claude-mcp) | 369 | Closest popular alternative; README says tested only on macOS, Windows unverified, some tools macOS-only. |
| [hiteshK03/davinci-resolve-mcp](https://github.com/hiteshK03/davinci-resolve-mcp) | 100 | In-app bridge alternative; lower adoption and older activity than the selected Resolve project. |

The user's example repositories were not treated as fixed choices. They emerged
as the best fits in this comparison. Pins: Photoshop **1.7.24**, Lightroom
**0.17.0**, Resolve **4.8.22**, Node **22.23.3**. Exact commits, SHA-256 hashes
and sizes live in `packaging/creative-mcp.json`. `build_creative_mcp.py` validates
archives and bundles servers plus an isolated, hash-locked Python dependency
set; NSIS includes the complete payload. No runtime npm, pip, uv, compiler or
system Node/Python is needed. Updating pins is an explicit build change.

### Setup and usable scope

- **Settings → Creative app connections → Check server** performs a real MCP
  initialize/tools-list exchange. Server readiness does not certify the creative
  application is connected. **Inspect app** returns a bounded state read and
  preserves upstream errors. These checks do not download models.
- Photoshop must already be open with a document for document inspection.
  Lightroom Classic needs the bundled `apps/LightroomMCP.lrplugin` added in
  Plug-in Manager, followed by its **Start Server** control. Its token stays at
  the plug-in's standard local user path. Keep the separate `PhotoWorkflow`
  plug-in enabled for existing virtual-copy editing.
- DaVinci Resolve is the video direction, replacing the earlier Premiere plan.
  Studio supports external scripting with **Preferences → General → External
  scripting using: Local**. Free-edition compatibility depends on version and
  the upstream in-app bridge; that bridge is not silently installed. Photo
  Studio's current Resolve inspection reports running state, not a live project
  scripting connection. Optional FFmpeg, transcription and analysis models are
  not bundled, and dependent upstream operations may report them missing.
- The local assistant exposes only `creative_app_status` through its existing
  authenticated broker. It accepts a fixed app enum, never arbitrary tool names,
  executable paths, scripts or model-supplied MCP arguments. Existing photo
  edits/export tests and original/virtual-copy safeguards remain authoritative.
- **Show MCP configuration** reveals an app-owned `desktop/mcp/servers.json`,
  regenerated with installed absolute paths on startup. It is optional for other
  MCP clients and exposes full upstream tools, including mutations. Those tools
  have upstream semantics, not Photo Studio's virtual-copy/export guarantees.
  No external assistant configuration is changed automatically.
- Child runtimes use private writable profiles, a restricted environment,
  disabled Photoshop analytics/feedback and disabled Resolve update checks.
  Only Resolve's eager log-directory default is patched to the writable profile;
  its dependency versions are isolated from the photo pipeline. Inspection
  cancellation stops the owned server processes; mutation calls are never routed
  through this timeout/cancellation path or retried through another bridge.

MCP standardizes access and expands the available application commands; it does
not improve pixel quality by itself. Integrated Resolve timelines, video export
and broader assistant editing tools remain future work. No live Resolve editing
has been verified on this computer.

## Future video boundary

Sessions, media browsing, jobs/events, installation, settings and result navigation
belong to the desktop. Photo validation, recipes, codecs and Adobe tools remain
in Python photo modules. Future video can add concrete job methods and result
readers at these boundaries. No video engine or speculative plugin system exists.


## Private GitHub automatic updates

`electron-updater` 6.8.9 owns release selection, installer download, digest validation
and NSIS launch. The main process fixes the provider to ezrasong/photoworkflow and
stable releases, with downgrades disabled. Metadata (`latest.yml`), installer and
blockmap are generated together and verified against the package version and SHA-512.
CI publishes the release as a draft, uploads all assets, then marks it latest only
after validation. Reruns preserve published releases and can finish a partial draft.
Version tags must match desktop/package.json.

Private releases require user-supplied GitHub access. A fine-grained Contents: read-only
token for this repository is sufficient. Electron safeStorage uses Windows DPAPI;
only encrypted bytes are atomically saved in userData/update-access.bin. Tokens stay
in the main process, never enter Python/MCP environments or the update manifest, and
are never returned through IPC or included in forwarded error messages. The update
bridge shares renderer/frame validation with the existing capabilities and exposes
only status, connect, disconnect, check and install. No generic URL or process launch
is exposed. No repository visibility or GitHub account settings are changed.

Once connected, checks run on app launch and every six hours while idle. New installers
download automatically, with a single in-flight operation. Settings displays progress,
errors and the ready-to-install action. Installation requires idle status and no pending
backend calls; IPC stops accepting photo jobs while Python drains and releases owned
runtimes. NSIS runs interactively so changed component downloads and failures remain
visible. Ordinary exit never triggers an update. Full installer downloads are used
because private old-version blockmap access is unreliable. User data remains preserved.

Signing secrets are not currently configured. Release transport and SHA-512 are checked;
Authenticode publisher verification becomes available when a signing certificate is
configured. There is no embedded signing identity or GitHub credential.
