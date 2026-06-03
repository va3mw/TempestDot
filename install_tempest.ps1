#Requires -Version 5.1
<#
.SYNOPSIS
    Tempest Weather Station Display — installer
    Installs Python 3.12 (if needed) and the PyQt5 package, then offers
    to create a desktop shortcut.  Every step asks for your permission first.
#>

$ErrorActionPreference = "Stop"
$AppName   = "Tempest Weather Station Display"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppScript = Join-Path $ScriptDir "tempest_display.py"

# ── helpers ───────────────────────────────────────────────────────────────────
function Ask-YesNo($prompt) {
    do {
        $ans = (Read-Host "$prompt [Y/N]").Trim().ToUpper()
    } while ($ans -notin @("Y","N"))
    return $ans -eq "Y"
}

function Write-Header($msg) {
    Write-Host ""
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor White
    Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
}

function Find-Python {
    # Try 'python', 'python3', then the Windows Store stub path
    foreach ($cmd in @("python","python3")) {
        try {
            $ver = & $cmd --version 2>&1
            if ($ver -match "Python (\d+\.\d+)") {
                $major, $minor = $Matches[1].Split(".")
                if ([int]$major -ge 3 -and [int]$minor -ge 9) {
                    return $cmd
                }
            }
        } catch {}
    }
    return $null
}

# ── banner ────────────────────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "  ████████╗███████╗███╗   ███╗██████╗ ███████╗███████╗████████╗" -ForegroundColor Cyan
Write-Host "     ██╔══╝██╔════╝████╗ ████║██╔══██╗██╔════╝██╔════╝╚══██╔══╝" -ForegroundColor Cyan
Write-Host "     ██║   █████╗  ██╔████╔██║██████╔╝█████╗  ███████╗   ██║   " -ForegroundColor Cyan
Write-Host "     ██║   ██╔══╝  ██║╚██╔╝██║██╔═══╝ ██╔══╝  ╚════██║   ██║   " -ForegroundColor Cyan
Write-Host "     ██║   ███████╗██║ ╚═╝ ██║██║     ███████╗███████║   ██║   " -ForegroundColor Cyan
Write-Host "     ╚═╝   ╚══════╝╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝   ╚═╝   " -ForegroundColor Cyan
Write-Host ""
Write-Host "  $AppName Installer" -ForegroundColor White
Write-Host "  This script will install Python and PyQt5 only with your consent." -ForegroundColor Gray
Write-Host ""

if (-not (Ask-YesNo "Ready to begin installation?")) {
    Write-Host "Installation cancelled." -ForegroundColor Yellow; exit 0
}

# ── Step 1: Python ────────────────────────────────────────────────────────────
Write-Header "Step 1 of 3 — Python"

$pythonCmd = Find-Python

if ($pythonCmd) {
    $ver = & $pythonCmd --version 2>&1
    Write-Host "  Found: $ver" -ForegroundColor Green
    Write-Host "  No installation needed." -ForegroundColor Green
} else {
    Write-Host "  Python 3.9+ was not found on this system." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  The installer will download Python 3.12.9 from python.org (~25 MB)" -ForegroundColor White
    Write-Host "  and run the official installer with these options:" -ForegroundColor White
    Write-Host "    • Install for current user only (no admin required)" -ForegroundColor Gray
    Write-Host "    • Add Python to PATH" -ForegroundColor Gray
    Write-Host "    • No changes to file associations or registry system keys" -ForegroundColor Gray
    Write-Host ""

    if (-not (Ask-YesNo "Download and install Python 3.12.9?")) {
        Write-Host "Skipped Python install. Cannot continue without Python." -ForegroundColor Red
        exit 1
    }

    $pyUrl      = "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
    $pyInstaller = Join-Path $env:TEMP "python-3.12.9-amd64.exe"

    Write-Host "  Downloading Python 3.12.9 ..." -ForegroundColor Cyan
    try {
        Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing
    } catch {
        Write-Host "  Download failed: $_" -ForegroundColor Red; exit 1
    }

    Write-Host "  Running Python installer (a progress window will appear) ..." -ForegroundColor Cyan
    $args = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_launcher=0",
        "Include_test=0",
        "Include_doc=0",
        "AssociateFiles=0"
    )
    $proc = Start-Process -FilePath $pyInstaller -ArgumentList $args -Wait -PassThru
    Remove-Item $pyInstaller -ErrorAction SilentlyContinue

    if ($proc.ExitCode -ne 0) {
        Write-Host "  Python installer exited with code $($proc.ExitCode)." -ForegroundColor Red
        exit 1
    }

    # Reload PATH so we can find the freshly installed python
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","User") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","Machine")

    $pythonCmd = Find-Python
    if (-not $pythonCmd) {
        Write-Host "  Python installed but not found in PATH. Please restart this script." -ForegroundColor Red
        exit 1
    }
    Write-Host "  Python installed successfully." -ForegroundColor Green
}

# ── Step 2: PyQt5 ─────────────────────────────────────────────────────────────
Write-Header "Step 2 of 3 — PyQt5"

$pyqt5Check = & $pythonCmd -c "import PyQt5; print('ok')" 2>&1
if ($pyqt5Check -eq "ok") {
    Write-Host "  PyQt5 is already installed." -ForegroundColor Green
} else {
    Write-Host "  PyQt5 is the GUI framework used by $AppName." -ForegroundColor White
    Write-Host "  It will be installed for the current user only via pip (~60 MB)." -ForegroundColor White
    Write-Host ""

    if (-not (Ask-YesNo "Install PyQt5 now?")) {
        Write-Host "Skipped. The app will not run without PyQt5." -ForegroundColor Yellow
        exit 1
    }

    Write-Host "  Installing PyQt5 ..." -ForegroundColor Cyan
    & $pythonCmd -m pip install --quiet --upgrade pip
    & $pythonCmd -m pip install PyQt5

    $check = & $pythonCmd -c "import PyQt5; print('ok')" 2>&1
    if ($check -ne "ok") {
        Write-Host "  PyQt5 installation failed." -ForegroundColor Red; exit 1
    }
    Write-Host "  PyQt5 installed successfully." -ForegroundColor Green
}

# ── Step 3: Desktop shortcut ──────────────────────────────────────────────────
Write-Header "Step 3 of 3 — Desktop shortcut"

if (-not (Test-Path $AppScript)) {
    Write-Host "  tempest_display.py not found at: $AppScript" -ForegroundColor Yellow
    Write-Host "  Skipping shortcut creation." -ForegroundColor Yellow
} else {
    Write-Host "  Create a desktop shortcut to launch $AppName?" -ForegroundColor White
    Write-Host ""

    if (Ask-YesNo "Create desktop shortcut?") {
        $pythonExe = (& $pythonCmd -c "import sys; print(sys.executable)").Trim()
        $shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Tempest Display.lnk"

        $wsh  = New-Object -ComObject WScript.Shell
        $link = $wsh.CreateShortcut($shortcutPath)
        $link.TargetPath       = $pythonExe
        $link.Arguments        = "`"$AppScript`""
        $link.WorkingDirectory = $ScriptDir
        $link.Description      = $AppName
        $link.Save()

        Write-Host "  Shortcut created on your Desktop." -ForegroundColor Green
    } else {
        Write-Host "  Skipped." -ForegroundColor Gray
        Write-Host "  To run manually:  python `"$AppScript`"" -ForegroundColor Gray
    }
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host "  Installation complete!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Green
Write-Host ""
Write-Host "  To launch:  python `"$AppScript`"" -ForegroundColor White
Write-Host "  Toggle units: press M or click METRIC / IMPERIAL button" -ForegroundColor Gray
Write-Host ""
