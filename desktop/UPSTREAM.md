# Upstream source and adaptations

Repository: https://github.com/anomalyco/opencode

Pinned commit: `b471c2b4495747353af768fbf2e0790c9d820ce2` (inspected September 27, 2026).
The selected packages/desktop/package.json identifies Electron 42.3.3,
SolidJS, electron-vite 5 and electron-builder 26.15.2; its builder uses Windows
NSIS. Luma Atelier updates Electron to 42.11.8, Solid to 1.9.15 and Vite to
7.3.6 after dependency audit found advisories in earlier pins. The exact graph
is committed in package-lock.json.

| OpenCode source | Luma Atelier adaptation |
| --- | --- |
| packages/desktop/src/main/windows.ts | src/main/windows.ts retains BrowserWindow lifecycle, saved state, sandbox/isolation, custom renderer protocol, bounded file resolution, ready-to-show and navigation policy. Removes WSL, coding server, telemetry and unrelated platform code. Original snapshot under vendor/opencode/windows.ts. |
| packages/desktop/electron.vite.config.ts | Main/preload/renderer build boundaries and CJS preload; original snapshot retained. |
| packages/desktop/electron-builder.config.ts | Windows NSIS, per-user install and artifact structure adapted in package.json; original snapshot retained. |
| packages/desktop/src/preload/index.ts | contextBridge, event unsubscribe and webUtils pattern adapted to photo-only IPC. |
| packages/ui/src/components/spinner.tsx, spinner.css | Actual upstream Solid component used for assistant/job activity. |
| packages/ui/src/components/resize-handle.tsx | Actual upstream resizable detail component, with keyboard separator controls supplied at its call site. |
| packages/ui/src/components/{tabs,button,icon,icon-button}.{tsx,css} | Copied upstream components and styles under src/renderer/upstream, used directly. Kobalte supplies their existing accessible behavior. |
| packages/ui/src/styles/{base,theme,colors}.css | Actual upstream tokens and color palette. Theme selector adapted from OS media query to the saved application preference. |
| packages/app/src/pages/layout/sidebar-shell.tsx | Rail and collapsible-panel structure adapted in components/sidebar-shell.tsx. Git worktrees, drag sorting and coding context replaced by photo workspace/session actions. |

The rail, neutral theme, compact titlebar, conversation/composer and tabbed side
panel follow the pinned OpenCode desktop structure. Photo controls and embedded
pixel comparison are first-party domain views. This is an adapted interface,
not a claim of pixel-for-pixel parity across every OpenCode screen. OpenCode's
assistant, coding tools, providers, terminal and telemetry are not included.
Oh My Pi 18.3.2 uses its documented --mode rpc --no-ui interface, protocol v1
bounded NDJSON, with actual message, tool, progress and prompt_result events.

The pinned upstream does not provide a reusable public-web browser component in
these surfaces. The reference browser uses Electron's native WebContentsView in a
separate session without a preload or photo bridge. It is a first-party addition.
Prompt Master uses one bounded local Qwen request to correct wording while
preserving the original intent and authorization scope.

The original MIT notice is preserved verbatim in vendor/opencode/LICENSE and
copied into the installed backend/licenses folder.
