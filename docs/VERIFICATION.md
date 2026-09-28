# Verification record

Windows x64 verification, September 27–28, 2026. Tests used synthetic images;
private photographs and notes were not uploaded.

## Passed locally

- Fresh pinned redistributable Python imports, TypeScript/Vite production build,
  desktop bridge test, and npm audit (zero reported vulnerabilities).
- Nine setup, prompt-authorization and focus-correction tests. Focus tests cover
  known mild Gaussian blur, tiled continuity, unchanged flat fields, cancellation,
  numeric bounds, precision, and unchanged pixels outside the supplied mask.
- Existing major-editing boundary suite: reconstruction opt-ins, selection/no-op,
  failed follow-up, no mutation retry, cancellation, profile isolation, Adobe locks.
- Packaged app in an empty workspace: startup without developer Python/models,
  file picker, unsupported IPC rejection, actionable missing-model errors,
  synthetic tone edit and soft-focus operation, 16-bit TIFF, original-byte
  preservation, embedded split/100% review, safe cancellation, and saved data
  after shutdown/relaunch.
- Public HTTPS navigation in the embedded reference browser. Remote pages have
  no preload, photo bridge or Node integration; sandbox enabled. File/loopback/
  private-network addresses are rejected and switching tabs hides the view.
- Actual pinned Torch CUDA download, integrity check and extraction; packaged
  SCUNet on RTX 5090 32 GB, Torch 2.7.1+cu128. This uses downloaded/reused verified
  assets in a separate acceptance workspace, not the developer virtualenv.
- Real Oh My Pi RPC, local Prompt Master spelling correction with both versions
  saved, real photo_status tool and message events, session reopen with selected
  input, worker-lock availability, native Tk review readiness, graceful shutdown.
- Dark/light setup and empty-studio screens inspected visually. Upstream controls
  are adapted with quieter button styling; this is not pixel-identical coverage
  of all OpenCode screens.
- NSIS install to a chosen test directory, desktop shortcut creation, installed
  app launch, 0.1.0 → 0.1.1 upgrade, and uninstall. Original image, 16-bit output,
  note and settings hashes remained identical across upgrade and uninstall.
  Upgraded AppData output preview and soft-focus controls passed. The test install
  was removed; its test user data is preserved.

Local detailed reports are retained in .cache/desktop-smoke-report.json,
.cache/desktop-integration-report.json, .cache/desktop-download-acceptance-report.json,
and .cache/desktop-browser-report.json. Installer evidence is in
.cache/desktop-installer-report.json. They are intentionally not committed.

## Verification limits

- A clean interactive Windows VM was unavailable. A GitHub Windows runner builds
  and runs packaged smoke checks; that is not a full clean-machine installer test.
- Packaged real Adobe editing and optional Obsidian installation have not been
  revalidated in this acceptance run. Existing integration boundaries are retained.
- Installer signing is not configured. Local installer Authenticode status is
  NotSigned; generic electron-builder signing log entries do not change that.
- Soft-focus improvement is tested against known synthetic mild blur. Recovery of
  real severe defocus, motion blur or missing detail is not promised. Review halos
  and noise at 100%; choose a smaller radius/strength where appropriate.
- CUDA inference is tested on RTX 5090 32 GB. Other hardware is unverified;
  the Mamba native binary specifically requires compute capability 12.0.
- The browser is for public reference reads, not uploads, downloads or account
  logins. Browser pages are not automatically supplied to the assistant.
- Advanced masking/batch/legacy assistant controls still use native panels.
  Prompt Master applies to desktop conversation submissions, not the legacy panel.
- Video remains future work.
