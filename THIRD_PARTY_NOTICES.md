# Third-party notices for VibeDownloader

This file is a release checklist, not legal advice. Keep each component's original license and notices with redistributed releases.

- **Python** — Python Software Foundation License; the PyInstaller bundle contains a Python runtime and standard-library components.
- **CustomTkinter** — MIT License.
- **Requests** — Apache-2.0 License.
- **Pillow** — HPND License.
- **pystray** — LGPL-3.0 License (check the exact version/package notices used by the build).
- **yt-dlp** — refer to the upstream yt-dlp license and the `THIRD_PARTY_LICENSES.txt` / license material supplied with the exact Windows executable that is bundled.
- **FFmpeg/FFprobe** — this build script fetches `ffmpeg-release-essentials.zip` from Gyan.dev. Review the package's `README.txt`, configuration, and license terms for the exact build. Essentials builds may enable GPL components; redistribution can require providing the corresponding source and notices under the applicable license. A URL alone is not a substitute for fulfilling those obligations.
- **NSIS** — used only to assemble the Windows installer; end users do not need NSIS installed.

Before publishing a public installer, verify the actual licenses and source-offer requirements for the exact versions downloaded by `prepare_build.py`. If you cannot satisfy the FFmpeg binary's obligations, do not distribute that bundled FFmpeg build; choose a build with suitable terms or leave the FFmpeg feature as an optional user-installed dependency.
