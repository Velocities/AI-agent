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

fun escapeBuildConfigString(value: String): String =
    "\"${value.replace("\\", "\\\\").replace("\"", "\\\"")}\""

val supabaseUrl = localProperties.getProperty("SUPABASE_URL", "")
val supabaseAnonKey = localProperties.getProperty("SUPABASE_ANON_KEY", "")
val apiBaseUrl = localProperties.getProperty("API_BASE_URL", "")
val authDebugOverride = localProperties.getProperty("AUTH_DEBUG")?.trim()?.lowercase()

fun authDebugValue(default: Boolean): String =
    when (authDebugOverride) {
        "true", "1", "yes" -> "true"
        "false", "0", "no" -> "false"
        else -> default.toString()
    }

android {
    namespace = "com.aiagent.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.aiagent.android"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"

        buildConfigField("String", "SUPABASE_URL", escapeBuildConfigString(supabaseUrl))
        buildConfigField("String", "SUPABASE_ANON_KEY", escapeBuildConfigString(supabaseAnonKey))
        buildConfigField("String", "API_BASE_URL", escapeBuildConfigString(apiBaseUrl))
    }

    buildTypes {
        debug {
            buildConfigField("boolean", "AUTH_DEBUG", authDebugValue(default = true))
        }
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            buildConfigField("boolean", "AUTH_DEBUG", authDebugValue(default = false))
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
}
