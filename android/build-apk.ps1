# Build the Android APK on Windows (no bash/WSL needed). Run it from anywhere.
#   .\android\build-apk.ps1                          -> dist\synclayer-<version>-android.apk
#   .\android\build-apk.ps1 https://files.me.com     -> same, with a default server baked in
#   .\android\build-apk.ps1 -InstallSdk              -> first download the Android SDK (command-line tools,
#                                                       platform 34, build-tools 34) into %LOCALAPPDATA%\Android\Sdk
# Needs: JDK 17. Gradle 8.9 is downloaded automatically; the SDK can be installed with -InstallSdk.
param([string]$Server = "", [switch]$InstallSdk)
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot          # restored in 'finally', so your shell stays where it was
try {
    if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
        throw "JDK 17 not found on PATH. Run: winget install EclipseAdoptium.Temurin.17.JDK   (then open a NEW terminal)"
    }

    $sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }

    if ($InstallSdk -or -not (Test-Path (Join-Path $sdk "platforms\android-34"))) {
        if (-not $InstallSdk -and -not (Test-Path $sdk)) {
            throw "Android SDK not found. Re-run with:  .\android\build-apk.ps1 -InstallSdk   (downloads ~200 MB into $sdk)"
        }
        $sm = Join-Path $sdk "cmdline-tools\latest\bin\sdkmanager.bat"
        if (-not (Test-Path $sm)) {
            Write-Host "Downloading Android command-line tools..."
            New-Item -ItemType Directory -Force $sdk | Out-Null
            $zip = Join-Path $env:TEMP "cmdline-tools.zip"
            Invoke-WebRequest "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip" -OutFile $zip
            $tmp = Join-Path $env:TEMP "sl-cmdline"
            Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
            Expand-Archive $zip $tmp -Force
            New-Item -ItemType Directory -Force (Join-Path $sdk "cmdline-tools") | Out-Null
            Move-Item (Join-Path $tmp "cmdline-tools") (Join-Path $sdk "cmdline-tools\latest") -Force
        }
        $env:ANDROID_HOME = $sdk
        Write-Host "Accepting licenses and installing platform 34 + build-tools 34..."
        (1..30 | ForEach-Object { "y" }) | & $sm --sdk_root=$sdk --licenses | Out-Null
        & $sm --sdk_root=$sdk "platform-tools" "platforms;android-34" "build-tools;34.0.0"
        if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed ($LASTEXITCODE)" }
    }
    $env:ANDROID_HOME = $sdk
    $env:ANDROID_SDK_ROOT = $sdk
    # Gradle also reads the SDK location from local.properties (needs forward slashes / escaped backslashes)
    Set-Content -Path (Join-Path $PSScriptRoot "local.properties") -Value ("sdk.dir=" + ($sdk -replace '\\', '/')) -Encoding ascii

    # The Android Gradle Plugin used here (8.5.2) needs Gradle 8.x; a newer Gradle from winget/PATH would fail.
    if (Test-Path .\gradlew.bat) { $g = ".\gradlew.bat" }
    else {
        $gh = Join-Path $env:LOCALAPPDATA "synclayer\gradle-8.9"
        $g = Join-Path $gh "bin\gradle.bat"
        if (-not (Test-Path $g)) {
            Write-Host "Downloading Gradle 8.9..."
            $zip = Join-Path $env:TEMP "gradle-8.9-bin.zip"
            Invoke-WebRequest "https://services.gradle.org/distributions/gradle-8.9-bin.zip" -OutFile $zip
            $dst = Join-Path $env:LOCALAPPDATA "synclayer"
            New-Item -ItemType Directory -Force $dst | Out-Null
            Expand-Archive $zip $dst -Force
        }
    }

    $gargs = @("--no-daemon", "assembleRelease")
    if ($Server) { $gargs += "-PslServer=$Server" }
    & $g @gargs
    if ($LASTEXITCODE -ne 0) { throw "Gradle failed ($LASTEXITCODE)" }

    $ver = (Select-String -Path ..\synclayer\_version.py -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    New-Item -ItemType Directory -Force ..\dist | Out-Null
    $out = "..\dist\synclayer-$ver-android.apk"
    Copy-Item app\build\outputs\apk\release\app-release.apk $out -Force
    Write-Host "APK: $((Resolve-Path $out).Path)"
}
finally { Pop-Location }
