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
avdmanager create avd -n radix -k "system-images;android-36;google_apis;x86_64" -d pixel_6
emulator -avd radix -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect -no-snapshot &
adb wait-for-device; ./gradlew assembleDebug -Pradix.abi=x86_64 && adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n dev.radix.calc/.MainActivity; adb exec-out screencap -p > shot.png
```

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
