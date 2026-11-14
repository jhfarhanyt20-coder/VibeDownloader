# Recon map: Internet Download Manager (Windows desktop)

Scope: The familiar desktop download-management loop: classic main window, URL/file-info dialogs, category navigation, per-download controls, browser hand-off, tray/background operation, and Windows startup. Advanced grabber and full scheduler parity are roadmap items rather than part of the first visual pass.
For: A publicly distributed, independently branded VibeDownloader Windows x64 application.
Date: 2026-10-31

## Clean-room boundary

This map records public behavior and navigation only. VibeDownloader will not ship IDM's name, logo, toolbar artwork, screenshots, copy, source code, private APIs, or binary resources. The public IDM screenshots are linked below but are not copied into this repository because Tonec's terms identify the site's images and software as protected content. The implementation uses original VibeDownloader icons and branding with a familiar Windows download-manager structure.

## Sources

| # | source | URL | notes |
| --- | --- | --- | --- |
| 1 | Official product page | https://www.internetdownloadmanager.com/ | Core promise, current main-window screenshot, browser integration, queues, categories, and scheduler overview. |
| 2 | Official features page | https://www.internetdownloadmanager.com/features2.html | Segmentation, resume, dark theme, browser takeover, scheduler, categories, customization, and drag/drop. |
| 3 | Official main-dialog help | https://www.internetdownloadmanager.com/support/main.html | Toolbar order, table fields, category tree, selection-dependent controls, queue column, and context-menu behavior. |
| 4 | Official starting-downloads help | https://www.internetdownloadmanager.com/support/using_idm/starting.html | Browser capture, Download File Info, Download Later, clipboard monitoring, context menu, drag/drop, and command-line paths. |
| 5 | Official options help | https://www.internetdownloadmanager.com/support/options.html | Automatic startup, browser integration, file types, connection count, category save paths, and dialog behavior. |
| 6 | Official scheduler help | https://www.internetdownloadmanager.com/support/idm-scheduler/idm_scheduler.html | Queue list, start/stop times, ordering, retries, simultaneous downloads, and completion actions. |
| 7 | Official toolbar help | https://www.internetdownloadmanager.com/support/toolbar2.html | Large/small toolbar modes and user-selectable toolbar looks. Referenced for structure only; artwork is not reused. |
| 8 | Official changelog | https://www.internetdownloadmanager.com/news.html | Current version context, active browser/video work, HTTP/2 improvements, and UI/search history. |
| 9 | Official terms | https://www.internetdownloadmanager.com/support/terms-and-conditions.html | Confirms protected logos, images, software, and other site content must not be reused in the distributed app. |

## Core loop

Keep the manager running quietly in the Windows tray, capture or accept a URL, confirm its category and save path, download it with resumable connections, and manage the result from one dense list.

## Screens

| ID | screen | route / how to reach | purpose | key components | states seen |
| --- | --- | --- | --- | --- | --- |
| S01 | Main manager | Launch app or open tray icon | See and control all downloads | Native menu, large action toolbar, category tree, sortable dense table, status bar | empty, filled, selected, active, paused, complete, error, background-restored |
| S02 | Add URL | Toolbar/Menu/Ctrl+N | Add a direct or media URL manually | URL input, optional file name, destination, authorization/headers path, start-now choice | clipboard-filled, blank, invalid URL, valid |
| S03 | Download File Info | Browser capture or resolved URL | Confirm filename, category, directory, and start timing | URL, category, save-as, remember-folder option, description, size, Start Download, Download Later | resolving metadata, resolved, invalid folder, cancelled |
| S04 | Download Progress | Start/resume a download | Inspect and control one active transfer | Percent, segment/progress area, URL, status, size, downloaded, speed, ETA, limiter, completion action | connecting, downloading, stopping, paused, complete, error |
| S05 | Options | Toolbar/Menu | Configure system and download behavior | General, connection, save-to, downloads, integration/tools sections | saved, cancelled, registry unavailable, tool missing/installed |
| S06 | Scheduler / Queues | Toolbar/Menu or queue context action | Start/stop and order queued files | Queue list, files table, start/stop controls, simultaneous count, schedule fields | empty, populated, running, stopped, retrying |
| S07 | Browser integration popup/panel | Browser toolbar, context menu, or video overlay | Send current page/link/media to desktop app | Connection status, catch toggle, page action, port, in-page download control | connected, disconnected, sent, fallback |
| S08 | Tray/background menu | Close main window or Windows startup | Keep capture service alive without a visible window | Show, Add URL, Start all, Stop all, Exit | visible, hidden, startup-hidden, active downloads |
| S09 | Completion/error feedback | Transfer completes or fails | Explain result and provide the next action | Status row, optional dialog/toast, open file/folder, retry | complete, recoverable error, permanent error |

## Flows

```
F01 Capture and start a browser download
    S07 -> S03 -> S04 -> S09 -> S01
    happy path clicks: 2 (download link, Start Download)
    edge: app not running, expired URL, cookies required, no range support, duplicate filename

F02 Add a URL manually
    S01 -> S02 -> S04 -> S09
    happy path clicks: 3 (Add URL, enter/paste, OK)
    edge: malformed URL, unresolved name, read-only folder, media metadata unavailable

F03 Pause and resume
    S01 -> S04 -> S01
    happy path clicks: 1 per action
    edge: server changed ETag/size, server ignores Range, app or PC restarts

F04 Run in the background
    installer/Options -> S08 -> S07 -> S03
    happy path clicks after Windows sign-in: 0 until a download is captured
    edge: startup entry denied, second app instance, tray dependency unavailable, port occupied

F05 Organize and find a download
    S01 category tree -> S01 table -> file/folder action
    happy path clicks: 2
    edge: missing downloaded file, custom path removed, no items in category

F06 Queue several downloads
    S03 Download Later -> S01/S06 -> S04 -> S09
    happy path clicks: 3
    edge: queue empty, failed item retries, concurrency limit, manual stop
```

## Components

| component | variants | states | used on |
| --- | --- | --- | --- |
| Native menu | Tasks, File, Downloads, View, Help | default, keyboard-open, disabled item | S01 |
| Large toolbar action | add, resume, stop, stop-all, delete, clear-complete, options, scheduler, queue controls, browser | default, hover, pressed, disabled | S01 |
| Category tree item | root, child category, state filter, queue | collapsed, expanded, selected, counted | S01, S06 |
| Download table row | direct file, media | queued, downloading, pausing, paused, complete, error, selected | S01, S06 |
| Sortable column header | text, numeric, date | ascending, descending, neutral | S01, S06 |
| Dialog action button | primary, secondary, destructive | default, focus, disabled, busy | S02-S06, S09 |
| Text/path field | editable, read-only, browseable | blank, resolving, valid, invalid, disabled | S02, S03, S05 |
| Progress/status field | overall, per-segment summary | indeterminate, active, paused, complete, error | S04 |
| Tray menu item | show, add, start-all, stop-all, exit | enabled, disabled | S08 |
| Connection indicator | desktop server, browser hand-off | ready, busy-port fallback, unavailable | S01, S07 |

## Inferred data model

```
DownloadTask  id, url, name, save_dir, save_path, kind, quality, headers,
              size, downloaded, speed, progress, status, error, description,
              speed_limit, completion_action, queue_id, created_at
              evidence: S01, S03, S04 and main-dialog/options help
              confidence: high

Category      id, name, extensions[], default_directory, built_in, sort_order
              evidence: S01, S03 and official main-dialog/options help
              confidence: high

Queue         id, name, task_ids[], max_concurrent, mode, schedule, retry_limit,
              completion_action, running
              evidence: S01, S06 and official scheduler help
              confidence: high

SegmentState  task_id, index, start, end, downloaded, complete, etag
              evidence: S04 and official segmentation description
              confidence: high for concept; exact IDM internals intentionally not inferred

AppSettings   start_with_windows, start_minimized, close_to_tray,
              default_save_dir, category_paths, max_concurrent,
              connections_per_file, ask_save_path, show_progress_window,
              theme, integration_port
              evidence: S05 and official options help
              confidence: high
```

Relationships: Category 1-n DownloadTask; Queue n-n DownloadTask; DownloadTask 1-n SegmentState; one local AppSettings record controls the application.

## Design direction for the first pass

- **Color:** Windows surface `#F3F3F3`, paper `#FFFFFF`, divider `#C8C8C8`, ink `#161616`, muted `#5B5B5B`, Vibe blue `#1769AA`, active green `#2E8B57`, error red `#C43B32`.
- **Type:** Segoe UI throughout because this is a dense native Windows utility; 9-10 pt for tables/menus and 9 pt labels under toolbar icons.
- **Layout:** Native menu, one horizontal band of large original icons, then a narrow tree beside a dense table, with a one-line status bar. Everything is left-aligned and optimized for scanning rather than card-based presentation.
- **Principles:** familiar keyboard/mouse utility behavior; high information density; controls visibly disable when unavailable; no decorative cards or rounded SaaS styling; VibeDownloader identity remains visible.

Self-review: a generic modern dashboard would use dark cards, large rounded buttons, and sparse rows—the current app already does that. The revised direction deliberately uses native Windows density and a strong toolbar/category/table hierarchy because that is specific to desktop download managers. The distinct Vibe blue and newly drawn icons avoid reproducing IDM's protected toolbar skin.

## Feature matrix

See `features.csv`. Must: 17, should: 12, could: 7, skip: 4.

## Out of scope (cannot or should not be cloned)

- IDM trademarks, product name, logo, toolbar skins, screenshots, help copy, binaries, and proprietary dynamic-segmentation implementation.
- Any private site rules, private APIs, licensed databases, or browser-store identity belonging to Tonec.
- FTP/MMS, OS-level network-driver interception, legacy IE monitor, dial-up control, and site-login password storage in the first pass.
- Pixel-for-pixel branded imitation. Public distribution requires independent branding and original visual assets.

## Size

Screens 9, flows 6, entities 5. Hard parts: reliable browser hand-off/cookies, resumable segmented I/O across restarts, single-instance Windows background lifecycle, and scheduled queues. Size: **M** for the requested look/startup pass; **L** for the complete must/should matrix.
