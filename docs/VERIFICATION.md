# Verification record

Windows x64 verification, September 27–28, 2026. Tests used synthetic images;
private photographs and notes were not uploaded.

## Version 0.1.4 — Photo Studio

The simpler product name replaces Luma Atelier. Wide windows again open with the
familiar navigation sidebar and split chat/controls view; the icon rail remains
available in narrower views. The 640×480 Windows minimum remains enforced.
A CI-only test fixture failure caused by an unresolved Windows short temporary
path was fixed by resolving the fixture root, preserving production validation.

- Rebuilt the redistributable Python backend and NSIS installer. TypeScript/Vite,
  desktop bridge tests, all 13 focused Python tests, major-editing boundaries and
  npm audit passed (zero advisories).
- Repeated the six-size layout matrix, effective 100–200% scaling and separate
  enlarged-text checks. Native Windows computer-use checks inspected wide,
  portrait and short layouts, navigation, scrolling and the file dialog.
  Attempting a smaller window clamped to the 640×480 minimum; the composer and
  Controls & review switch remained reachable, including the lower controls.
- Repeated packaged empty-workspace smoke and public-browser isolation checks.
  Browser bounds passed all six sizes at actual Electron zoom 1, 1.25, 1.5 and 2.
  Smoke verified synthetic tone/focus output, original preservation, cancellation,
  review, missing-dependency errors and settings/results after restart with
  developer Python/Node removed from PATH.

## Version 0.1.3 — Luma Atelier

- TypeScript/Vite build, desktop bridge test, 13 Python unit tests, existing
  major-editing boundary suite and dependency audit passed (zero advisories).
- Rendered synthetic layout checks passed at 640×480, 800×600, 1280×720,
  1920×1080, 900×1400 and 2560×720, with effective viewports representing
  100%, 125%, 150% and 200% scaling. Separate 125–200% enlarged-text checks
  passed at 640×480. Fixtures include 24 sessions, long paths/messages, crowded
  setup and comparison pixels. Checks cover reachable actions/composer,
  keyboard tab focus, image aspect ratio and absence of document overflow.
  Representative rendered screenshots were inspected.
- Packaged public HTTPS browser navigation and isolation passed. Native child
  bounds matched clipped renderer rectangles across all six window sizes at
  actual Electron zoom factors 1, 1.25, 1.5 and 2. File/private-network URLs,
  preload/Node access and tab visibility protections remain enforced.
- Packaged smoke passed with developer Python/Node removed from the child PATH
  and a fresh isolated workspace: setup entry, picker, IPC rejection, missing
  dependencies, synthetic 16-bit tone/focus edits, split/native-pixel review,
  cancellation, original preservation and settings/results after restart.
- Packaged SCUNet CUDA denoise and the actual local assistant passed on a
  synthetic image using retained pinned assets. Prompt correction preserved both
  versions; real Oh My Pi RPC/tool events, session reopening, worker-lock
  availability, native Tk review readiness and graceful shutdown passed.
- Actual NSIS 0.1.2 → 0.1.3 rename upgrade passed. The uninstall GUID stayed
  unchanged, the old executable/shortcuts were replaced, and the renamed app
  reopened the same AppData workspace. Synthetic original, TIFF output, note and
  settings hashes matched; output preview and soft-focus controls worked.
- Git branch/tag history and commit metadata were inspected. Published history
  contains no private context Markdown or development-agent commit attribution;
  a rewrite was unnecessary. The existing five-document allowlist was retained
  and explicit context exclusions strengthened. Native runtime release retained.

Evidence: .cache/layout-acceptance/report.json and rendered PNGs,
.cache/desktop-browser-report.json, .cache/desktop-smoke-report.json,
.cache/desktop-integration-report.json and .cache/rename-installer-report.json.
Scaling checks exercise effective viewport reflow and enlarged text, plus real
Electron zoom for browser bounds; they do not replace manual Windows display
settings and assistive-technology acceptance. The user's fresh reinstall remains
an independent final acceptance test.

## Version 0.1.2 additions

- Thirteen setup, prompt, vault-reference and focus tests passed. New coverage
  includes complete setup ordering/failure/cancellation, a single final completion
  event, inspection-only suggestions, invalid model output, reference provenance,
  inert Markdown metadata and preservation of existing notes/source bytes.
- Live Wikimedia Commons search, image download, attribution/hash verification
  and chooser-to-vault saving passed. Opening a suggested query does not submit it.
- Real local Qwen3-VL inspection returned editable suggestions for a synthetic
  image. Suggestions do not submit an editing prompt.
- Obsidian's pinned official installer passed publisher verification, extraction,
  executable presence and isolated vault registration. The signature checker now
  explicitly imports Windows PowerShell's built-in security module, avoiding
  incompatible modules inherited from another PowerShell installation.
- Packaged empty-workspace smoke passed, including automatic setup display,
  synthetic tone/focus edits, cancellation, original preservation and relaunch.
- Packaged complete setup passed in a fresh workspace using cached downloads,
  with every pinned hash verified and every component extracted. Runtime,
  assistant, photo, legacy and Obsidian completed in order; only the final event
  released setup. After restart, Torch 2.7.1+cu128 detected the RTX 5090. The real
  Qwen3-VL suggestion UI filled a draft without submission, edits or source changes.
  Its synthetic screenshot was inspected.

Evidence: .cache/prompt-suggestion-acceptance/report.json,
.cache/obsidian-setup-acceptance-report.json,
.cache/complete-setup-acceptance-report.json and the updated smoke report.
The 0.1.2 checks above were performed on a local build before the 0.1.3 release.

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
- Packaged real Adobe editing has not been revalidated in this acceptance run.
  Existing integration boundaries are retained.
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
