# VibeDownloader — বিল্ড গাইড (বাংলা)

এই ZIP-এ আপডেট করা **প্রজেক্ট + স্বয়ংক্রিয় Windows installer builder** আছে। Build করার PC-তে Python, NSIS, winget, Chocolatey বা Scoop আগে থেকে install থাকা লাগবে না। `build_windows.bat` প্রয়োজন হলে Python ও NSIS-এর official portable/build files নিজের user AppData-তে নামিয়ে নেবে।

## একবারের build ধাপ

1. ZIP extract করুন।
2. Windows x64 PC-তে internet connection চালু রাখুন।
3. `build_windows.bat`-এ double-click করুন। Script user-level folder `%LOCALAPPDATA%\VibeDownloaderBuildTools`-এ Python 3.13.17 ও NSIS 3.13 প্রয়োজন হলে download করে; system PATH বা তোমার Python 3.15 install পরিবর্তন করে না।
4. Script build packages install, Python syntax/test check, `yt-dlp.exe` ও FFmpeg asset preparation, app build এবং NSIS installer compilation নিজেই করে।
5. সফল হলে project folder-এ `VibeDownloader_Installer.exe` তৈরি হবে। অন্য ব্যবহারকারীদের শুধু এই installer-টিই দিন।
6. `SHA256SUMS.txt`-তে ওই installer-এর hash থাকবে। App EXE তৈরি হবে `dist\release\VibeDownloader.exe`-তে, যাতে পুরোনো চলমান `dist\VibeDownloader.exe` overwrite না হয়।

## ব্যবহারকারীর কম্পিউটারে

- Python, pip, FFmpeg, FFprobe বা yt-dlp আলাদা করে install করতে হবে না—এই build script দিয়ে তৈরি installer-এ এগুলো package করা থাকবে।
- Browser download ধরার জন্য Chrome/Edge-এ extension একবার manually load করতে হবে: app চালু করুন → **Install / Reload Extension** → Developer mode চালু করুন → **Load unpacked** → app যে extension path clipboard-এ copy করেছে সেটি নির্বাচন করুন। Chrome/Edge-এর সাধারণ security policy-র কারণে local unpacked extension-টি desktop installer নীরবে install করতে পারে না।
- IDM-এর মতো multi-connection speed চেষ্টা করে। তবে server Range request বন্ধ রাখলে বা connection throttle করলে speed বাড়ানো সম্ভব নয়; সে ক্ষেত্রে app single connection-এ fallback করবে।

## যাচাই

Developer machine-এ চালান:

```bat
"%LOCALAPPDATA%\VibeDownloaderBuildTools\Python313\python.exe" -m compileall -q main.py app_info.py app_updater.py update_dialog.py bundle_self_test.py release_tools.py downloader.py yt_helper.py prepare_build.py tests
"%LOCALAPPDATA%\VibeDownloaderBuildTools\Python313\python.exe" -m unittest discover -s tests -v
```

প্রকাশের আগে `THIRD_PARTY_NOTICES.md`-এর FFmpeg license/source শর্তও যাচাই করতে হবে, বিশেষত installer অন্যদের মধ্যে distribute করলে।

## GitHub release ও app update

সম্পূর্ণ নির্দেশনা: **[UPDATES_AND_RELEASES_BN.md](UPDATES_AND_RELEASES_BN.md)**। `app_info.py`-তে নতুন version দিন, changelog লিখুন, তারপর matching `vX.Y.Z` tag push করুন। GitHub Actions installer test করে release publish করবে। ব্যবহারকারীরা **Help → Check for Updates** অথবা automatic check-এর মাধ্যমে update পাবেন।
