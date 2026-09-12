# Radix for Android (personal build)

A touch-first front-end over the same Python engine as the desktop app,
embedded with [Chaquopy](https://chaquo.com/chaquopy/). Sideload only — this
is not set up for the Play Store. Design: `../docs/superpowers/specs/2026-09-12-android-touch-ui-design.md`.

## Prerequisites

- JDK 17
- Android SDK with `platforms;android-36`, `build-tools;36.0.0`, `platform-tools`
  (`ANDROID_HOME` set, or `sdk.dir=` in `android/local.properties`)
- A Python 3.12 on the host for Chaquopy's build step — the repo's `.venv`
  (from `uv sync`) is picked up automatically
- The Gradle wrapper: `gradle wrapper --gradle-version 8.11.1` once, or open the
  folder in Android Studio, which generates it

## Build and install

```sh
cd android
./gradlew test                 # ViewModel unit tests (JVM, no device)
./gradlew assembleDebug        # → app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
./gradlew connectedDebugAndroidTest   # Chaquopy smoke test, needs a device
```

Debug signing is fine for a personal phone. The APK is arm64-v8a only; add
`"x86_64"` to `abiFilters` in `app/build.gradle.kts` for an emulator.

The engine is bundled straight from `../src` (no copy step), so a desktop
engine change is in the next `assembleDebug`. The version is read from
`radix.__version__`.

## Install on phone via USB (adb)

```sh
cd android && ./gradlew assembleDebug
# → app/build/outputs/apk/debug/app-debug.apk  (arm64-v8a, ~33 MB)
```

### Route A — adb over USB (recommended)

1. On the phone: Settings → About phone → tap Build number seven times (unlocks Developer options). Then Settings → System → Developer options → turn on USB debugging.
2. Plug in the USB cable. If a "Charging this device via USB" notification appears, leave it on charging — file-transfer mode isn't needed for adb.
3. On the PC:
   `adb devices`
   The first time, the phone shows Allow USB debugging? with the PC's fingerprint — tick Always allow from this computer and accept. adb devices should then list it as device
   (not unauthorized).
4. If the emulator is still running, adb will have two targets and refuse to guess. Pick the phone with its serial from adb devices:
   `adb -s <phone-serial> install -r app/build/outputs/apk/debug/app-debug.apk`
   (Just adb install -r … when the phone is the only device.)
5. Radix appears in the launcher. Open it — the first launch takes a few seconds while Chaquopy unpacks Python; after that it's fast.

-r means "replace" — use the same command for every later build. The debug signing key is generated per machine (~/.android/debug.keystore) and stays stable, so updates install
straight over the top without losing history or variables.

### Route B — copy the file

If you'd rather not enable USB debugging: get app-debug.apk onto the phone any way you like (USB file transfer, Drive, email to yourself), open it from the Files app, and:

- Android will ask to allow Files to install unknown apps — allow it (once).
- Play Protect will warn that the app is from an unknown developer, because it's debug-signed and not from the store. Choose More details → Install anyway.

### Two things that trip people up

- adb server version doesn't match — you have both the system /usr/bin/adb and the SDK's platform-tools/adb; if they're different versions they fight over the daemon. Run adb
  kill-server and then use whichever one your PATH picks up first (the README's PATH line puts the SDK's first).
- Signature mismatch on install — only happens if you build on a different machine (different debug key). Fix: uninstall the old one first (adb uninstall dev.radix.calc or from
  Settings), then install.

Wireless debugging (Developer options → Wireless debugging → Pair device with pairing code, then adb pair / adb connect) works too on the Pixel 9 if the cable is a nuisance,
but USB is the fewer-moving-parts option for the first install.

## Environment

The build needs `JAVA_HOME` (JDK 17) and `ANDROID_HOME`; a user-local install
without root works fine:

```sh
export JAVA_HOME=~/.local/opt/jdk-17 ANDROID_HOME=~/.local/opt/android-sdk
export PATH=$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH
```

The second line is what puts `sdkmanager`, `avdmanager`, `adb` and `emulator`
on your `PATH` — none of them are installed system-wide. AGP pulls the
build-tools it wants (35.0.0) on the first run.

## Emulator (for UI checks without a phone)

```sh
sdkmanager --install emulator "system-images;android-36;google_apis;x86_64"   # once
export ANDROID_AVD_HOME=/tmp/radix-avd            # see below; mkdir -p it first
avdmanager create avd -n radix -k "system-images;android-36;google_apis;x86_64" -d pixel_9   # `avdmanager list device` for others
emulator -avd radix -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot &
adb wait-for-device; ./gradlew assembleDebug -Pradix.abi=x86_64 && adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -W -n dev.radix.calc/.MainActivity   # -W waits for the first frame
sleep 2; adb exec-out screencap -p > shot.png
```

A screenshot taken straight after `am start` shows the launch splash (the
Radix icon on a blank ground): the first frame waits for the embedded Python
to start, and the very first launch also unpacks the stdlib and the engine,
which takes several seconds on a software-rendered emulator. `-W` blocks
until the activity has drawn; the extra `sleep` covers the first preview.

Gotchas, all hit in practice:

- Recent cmdline-tools write AVDs to `~/.config/.android/avd`, which the
  emulator does not search — set `ANDROID_AVD_HOME` for both tools.
- The emulator forces a 6 GiB userdata partition for API 34+ images and
  refuses to start unless 1.2× that is free on the AVD's filesystem, whatever
  `config.ini` or `-partition-size` say. Putting `ANDROID_AVD_HOME` on tmpfs
  (`/tmp`) sidesteps it; the image is sparse and boots in well under 1 GB.
- `./gradlew connectedDebugAndroidTest` (the Chaquopy smoke test) uninstalls
  the app when it finishes, taking history and state with it.
- Drive the UI with `adb shell input tap X Y` / `input swipe`; a swipe that
  starts within ~30 dp of the left edge is a system back gesture. The register
  grid opts out of that zone (`systemGestureExclusion`), the rest of the
  screen does not.
- `adb shell input text` goes through the focused field; quote `<<` and `|`
  (`adb shell "input text '0xFF<<2'"`) or the device shell eats them.
