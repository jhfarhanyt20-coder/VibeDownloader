# VibeDownloader — update ও GitHub release গাইড

## ব্যবহারকারীরা যেভাবে update পাবেন

1. প্রথমবার [latest release](https://github.com/jhfarhanyt20-coder/BD-Downloader/releases/latest) থেকে **VibeDownloader_Installer.exe** install করবেন।
2. App startup-এ এবং tray-তে চলার সময় latest stable release check করে। সফল check-এর মধ্যে অন্তত **১২ ঘণ্টা** ব্যবধান থাকে।
3. সঙ্গে সঙ্গে check করতে **Help → Check for Updates**, tray menu-এর **Check for Updates**, অথবা **Options → Application updates** ব্যবহার করবেন।
4. নতুন version থাকলে release notes এবং download size দেখাবে। **Update now** চাপলে installer download ও SHA-256 verify হবে।
5. Windows permission approve করলে চলমান downloads pause হবে, app পুরোপুরি exit করবে, installer একই folder-এ upgrade করে app আবার চালু করবে।

Settings, history, downloaded files এবং resume files upgrade-এ delete হয় না। Pause করা download restart-এর পর **Resume** দিয়ে চালু করা যাবে। Options-এর automatic update checkbox বন্ধ করলে automatic check বন্ধ হয়; manual check কাজ করে।

Internet না থাকলে বা GitHub rate limit দিলে manual check error দেখায়—ভুল করে “up to date” বলে না। Failed automatic checks এক ঘণ্টা পরে retry করতে পারে। **Later** চাপলে কিছু install হয় না। Download cancel বা Windows UAC decline করলেও পুরোনো app অপরিবর্তিত থাকে।

### পুরোনো 2.4 installation

2.5 installer পুরোনো updater-এর `/SILENT` ও `/DIR=` arguments-ও গ্রহণ করে। তবে 2.4-এর পুরোনো **Help → Check for Updates** শুধু yt-dlp update করে; **Options → Check for App Update** ব্যবহার করুন। পুরোনো updater কাজ না করলে latest installer manually download করুন, tray থেকে app **Exit** করুন, তারপর installer চালান। 2.5 থেকে নতুন verified update flow ব্যবহার হবে।

## ভবিষ্যতে নতুন version publish করবেন যেভাবে

**GitHub Actions → Build Windows installer** workflow-এ কোনো personal token secret লাগবে না। GitHub নিজের `GITHUB_TOKEN` দিয়ে release job চালাবে; app-এও token রাখা যাবে না। Repository এবং releases public থাকতে হবে, যাতে ব্যবহারকারীরা login ছাড়া update পান।

উদাহরণ হিসেবে পরের release `2.6.0`:

1. Code পরিবর্তন করুন।
2. `app_info.py`-তে `APP_VERSION = "2.6.0"` করুন। App title, updater, EXE properties এবং installer একই version পাবে।
3. `CHANGELOG.md`-তে `## 2.6.0 (তারিখ)` entry লিখুন। Browser extension বদলালে `extension/manifest.json`-এর version-ও বাড়ান।
4. Test করে code commit এবং push করুন।
5. Version tag push করুন:

```powershell
git add <আপনার পরিবর্তন করা ফাইলগুলো>
git commit -m "Release VibeDownloader 2.6.0"
git push origin master
git tag -a v2.6.0 -m "VibeDownloader 2.6.0"
git push origin v2.6.0
```

Tag **অবশ্যই** `v` + `APP_VERSION` হতে হবে। ভুল version হলে build fail করবে।

Tag push-এর পরে Actions নিজে:

- Python syntax এবং offline regression tests চালাবে।
- Windows x64 EXE বানাবে; Python/Tk, packages, media tools এবং extension installer-এ থাকবে।
- Fresh install, frozen app-এর update window ও media tools, in-place update, data retention এবং uninstall smoke test চালাবে।
- `VibeDownloader_Installer.exe` ও `SHA256SUMS.txt` বানাবে।
- Draft release-এ দুটো file upload করে একসঙ্গে public/latest করবে।

Release public হওয়ার পর পুরোনো app-এর পরবর্তী automatic/manual check-এ update দেখাবে। শুধু branch push করলে tests চলে; ব্যবহারকারীদের update দিতে **নতুন version tag** push করতে হবে।

**Published release বা tag force-replace করবেন না।** ভুল থাকলে নতুন patch version দিন, যেমন `2.6.1`। Failed build-এর draft থাকলে fix করে workflow rerun করা যায়; public release overwrite করতে workflow অস্বীকার করবে।

Installer শুধু build করে দেখতে চাইলে workflow-টি `master` branch থেকে manually **Run workflow** করুন; artifact পাওয়া যাবে, public release তৈরি হবে না।

## Local Windows build

`build_windows.bat` চালান। নতুন app EXE যায় `dist\release\VibeDownloader.exe`-তে; root-এ তৈরি হয়:

- `VibeDownloader_Installer.exe`
- `SHA256SUMS.txt`

Checksum build অনুযায়ী বদলায়, তাই source Git-এ track করা হয় না। GitHub থেকে installer নামালে **সেই release-এর** `SHA256SUMS.txt` ব্যবহার করুন।

Release notes: `dist\release\RELEASE_NOTES.md`। চলমান পুরোনো `dist\VibeDownloader.exe` build দ্বারা overwrite হবে না।

## নিরাপত্তা ও সীমাবদ্ধতা

- Updater শুধু এই repository-এর exact installer asset এবং trusted GitHub HTTPS/CDN redirects গ্রহণ করে।
- Download-এর exact size, Windows PE header এবং SHA-256 check হয়; partial/corrupt file run হয় না।
- App-এ GitHub credential bundle করা হয় না। Local `github.txt`, `gihub.txt` এবং `.vibe-scratch/` Git-এ ignored।
- SHA-256 integrity check **code-signing certificate নয়**। Certificate ছাড়া installer/EXE unsigned থাকবে; Windows SmartScreen warning দিতে পারে। বড় সফটওয়্যারের মতো publisher identity দেখাতে বৈধ Authenticode certificate দিয়ে release files sign করতে হবে—**checksum বানানোর আগে**।
- Chrome/Edge-এর unpacked extension silent install/update করা যায় না। নতুন extension files upgrade-এ replace হয়, কিন্তু browser-এ **Reload** দরকার হতে পারে।
- Uninstall app files এবং shortcuts সরায়; settings/history ও downloaded files রেখে দেয়।
- Third-party binary redistribution-এর আগে `THIRD_PARTY_NOTICES.md` এবং exact FFmpeg/yt-dlp license/source obligations যাচাই করুন।
