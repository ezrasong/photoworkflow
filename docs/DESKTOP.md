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

## Build

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
```

The bundle uses a fresh hash-pinned Python archive and hash-locked distributions,
never the developer .venv. Tk, image codecs, native Windows dependencies and VC
runtime DLLs are included. Large Torch/cu128 wheels, including CUDA DLLs, are
downloaded/extracted in first-run setup without pip or compilers. The shipped
Mamba binary requires CPython 3.12/Torch 2.7.1/cu128 and compute capability 12.0.

GitHub Actions builds Windows artifacts and checksums. Version tags publish
installer/checksum assets to private releases. CSC_LINK and CSC_KEY_PASSWORD
secrets optionally enable signing; absent secrets mean unsigned artifacts.
Only the release job gets contents:write.

## First launch

1. Setup shows sizes and disk space. Install CUDA runtime before photo models
   and/or assistant. Restart after runtime installation.
2. In licensed Lightroom Classic use File → Plug-in Manager → Add at the displayed
   plug-in path. Photoshop uses its existing supported COM registration.
3. Create a session, select a photo/folder and describe the edit. Manual raster
   controls also work without Adobe. Advanced panels retain precision features.
4. Review locally. Optional Obsidian setup uses its official signed release;
   vault notes remain ordinary local files.

Interrupted downloads retain a partial file, resume with Range or restart when
the server ignores Range. Hash failure removes only the invalid partial. Disk
space is checked before downloading. Inference also verifies model hashes.
After failed mutation inspect preserved evidence before starting a new job.

## Future video boundary

Sessions, media browsing, jobs/events, installation, settings and result navigation
belong to the desktop. Photo validation, recipes, codecs and Adobe tools remain
in Python photo modules. Future video can add concrete job methods and result
readers at these boundaries. No video engine or speculative plugin system exists.
