# Upstream source and adaptations

Repository: https://github.com/anomalyco/opencode

Pinned commit: `b471c2b4495747353af768fbf2e0790c9d820ce2` (inspected September 27, 2026).
The selected packages/desktop/package.json identifies Electron 42.3.3,
SolidJS, electron-vite 5 and electron-builder 26.15.2; its builder uses Windows
NSIS. Photo Workflow updates Electron to 42.11.8, Solid to 1.9.15 and Vite to
7.3.6 after dependency audit found advisories in earlier pins. The exact graph
is committed in package-lock.json.

| OpenCode source | Photo Workflow adaptation |
| --- | --- |
| packages/desktop/src/main/windows.ts | src/main/windows.ts retains BrowserWindow lifecycle, saved state, sandbox/isolation, custom renderer protocol, bounded file resolution, ready-to-show and navigation policy. Removes WSL, coding server, telemetry and unrelated platform code. Original snapshot under vendor/opencode/windows.ts. |
| packages/desktop/electron.vite.config.ts | Main/preload/renderer build boundaries and CJS preload; original snapshot retained. |
| packages/desktop/electron-builder.config.ts | Windows NSIS, per-user install and artifact structure adapted in package.json; original snapshot retained. |
| packages/desktop/src/preload/index.ts | contextBridge, event unsubscribe and webUtils pattern adapted to photo-only IPC. |
| packages/ui/src/components/spinner.tsx, spinner.css | Actual upstream Solid component used for assistant/job activity. |
| packages/ui/src/components/resize-handle.tsx | Actual upstream resizable detail component, with keyboard separator controls supplied at its call site. |

Session navigation, conversation, composer and detail panels retain the interaction
model while their domain implementation is first-party photo UI. OpenCode's
assistant, coding tools, providers, terminal and telemetry are not included.
Oh My Pi 18.3.2 uses its documented --mode rpc --no-ui interface, protocol v1
bounded NDJSON, with actual message, tool, progress and prompt_result events.

The original MIT notice is preserved verbatim in vendor/opencode/LICENSE and
copied into the installed backend/licenses folder.
