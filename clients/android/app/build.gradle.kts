import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

val localProperties = Properties()
val localPropertiesFile = rootProject.file("local.properties")
if (localPropertiesFile.exists()) {
    localPropertiesFile.inputStream().use { localProperties.load(it) }
}

// Each debug surface has its own flag so one feature can be inspected at a time.
// Off unless set: `-PNAME=true` on the Gradle command line wins over local.properties.
fun debugFlag(name: String): String {
    val raw = (findProperty(name) as String?) ?: localProperties.getProperty(name)
    return when (raw?.trim()?.lowercase()) {
        "true", "1", "yes" -> "true"
        else -> "false"
    }
}

// The repo-root VERSION file is the single release version for the CLI and this app.
// versionCode must increase with every release, so it is derived as MAJOR*1_000_000 + MINOR*1_000 + PATCH.
val appVersionName: String = rootProject.file("../../VERSION").readText().trim()
val appVersionCode: Int = run {
    val match = Regex("""(\d+)\.(\d+)\.(\d+)""").matchEntire(appVersionName)
        ?: throw GradleException("VERSION must be MAJOR.MINOR.PATCH, got '$appVersionName'")
    val (major, minor, patch) = match.destructured.toList().map { it.toInt() }
    if (minor > 999 || patch > 999) {
        throw GradleException("VERSION minor and patch must be at most 999, got '$appVersionName'")
    }
    major * 1_000_000 + minor * 1_000 + patch
}

// Release signing comes only from the environment (CI secrets), never from files in the repo.
// Without it, release builds fall back to the debug key so the APK is still installable.
val releaseKeystorePath: String? = System.getenv("ANDROID_KEYSTORE_PATH")?.takeIf { it.isNotBlank() }

android {
    namespace = "com.aiagent.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.aiagent.android"
        minSdk = 26
        targetSdk = 36
        versionCode = appVersionCode
        versionName = appVersionName

        buildConfigField("boolean", "AUTH_DEBUG", debugFlag("AUTH_DEBUG"))
    }

    signingConfigs {
        if (releaseKeystorePath != null) {
            create("release") {
                storeFile = file(releaseKeystorePath)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (releaseKeystorePath != null) {
                signingConfigs.getByName("release")
            } else {
                logger.warn("ANDROID_KEYSTORE_PATH is not set; signing the release APK with the debug key.")
                signingConfigs.getByName("debug")
            }
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.navigation.compose)

    implementation(platform(libs.supabase.bom))
    implementation(libs.supabase.auth)
    implementation(libs.supabase.postgrest)
    implementation(libs.ktor.client.android)

    debugImplementation(libs.androidx.compose.ui.tooling)

    testImplementation(libs.junit)
}
