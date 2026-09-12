plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
    id("com.chaquo.python")
}

// Version is single-sourced from radix.__version__ (a plain incrementing
// integer), exactly like the desktop window title and `--version`.
val radixVersion: String = rootProject.file("../src/radix/__init__.py").readText()
    .let { Regex("""__version__\s*=\s*"([^"]+)"""").find(it) }
    ?.groupValues?.get(1)
    ?: error("radix.__version__ not found in src/radix/__init__.py")

android {
    namespace = "dev.radix.calc"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.radix.calc"
        minSdk = 26
        targetSdk = 36
        versionCode = radixVersion.toInt()
        versionName = radixVersion
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            // Personal sideload: one ABI keeps the APK small. Add "x86_64" for
            // an emulator.
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    buildFeatures {
        compose = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions {
        unitTests.isIncludeAndroidResources = false
    }
}

kotlin {
    jvmToolchain(17)
}

chaquopy {
    defaultConfig {
        // Must match the interpreter the repo is developed with (uv-managed 3.12).
        version = "3.12"
        // Prefer the repo's own venv interpreter when it exists, so the build
        // never depends on a system python3.12; falls back to Chaquopy's search.
        rootProject.file("../.venv/bin/python").takeIf { it.canExecute() }?.let {
            buildPython(it.absolutePath)
        }
        pip {
            // The engine's only runtime deps, both pure Python.
            install("mpmath")
            install("platformdirs")
        }
    }
    sourceSets {
        getByName("main") {
            // The engine is bundled *by path*: no copy step, single source of
            // truth. ui_qt/ rides along unused (never imported on Android).
            srcDir("../../src")
        }
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2025.06.00")
    implementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")

    androidTestImplementation(composeBom)
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.test:runner:1.6.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
