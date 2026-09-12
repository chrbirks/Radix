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
