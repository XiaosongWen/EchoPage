# ==============================================================================
# EchoPage Environment & Dependency Setup Script for Windows PowerShell
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host "`n=====================================================" -ForegroundColor Cyan
Write-Host "       EchoPage Automated Environment Setup (Windows) " -ForegroundColor Cyan
Write-Host "=====================================================`n" -ForegroundColor Cyan

# 1. Check Python
Write-Host "[INFO] Checking Python installation..." -ForegroundColor Cyan
try {
    $pyVersionStr = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $pyVersionStr.Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Error "Python 3.10 or higher is required. Found Python $pyVersionStr"
        exit 1
    }
    Write-Host "[SUCCESS] Found compatible Python: $pyVersionStr" -ForegroundColor Green
} catch {
    Write-Error "Python is not installed or not found on PATH. Please install Python 3.10+ from python.org."
    exit 1
}

# 2. Check FFmpeg
Write-Host "[INFO] Checking FFmpeg and ffprobe..." -ForegroundColor Cyan
$hasFfmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue) -ne $null
$hasFfprobe = (Get-Command ffprobe -ErrorAction SilentlyContinue) -ne $null

if (-not $hasFfmpeg -or -not $hasFfprobe) {
    Write-Warning "FFmpeg or ffprobe not found on PATH."
    Write-Host "[INFO] You can easily install FFmpeg on Windows using:" -ForegroundColor Yellow
    Write-Host "       winget install Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host "       or: choco install ffmpeg`n" -ForegroundColor Yellow
} else {
    Write-Host "[SUCCESS] FFmpeg and ffprobe are ready." -ForegroundColor Green
}

# 3. Check for uv (EchoPage strictly uses uv, not pip)
Write-Host "[INFO] Checking for uv package manager..." -ForegroundColor Cyan
$hasUv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null
if (-not $hasUv) {
    Write-Host "[WARNING] uv is not found on PATH. Attempting automatic installation..." -ForegroundColor Yellow
    try {
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
        $env:Path = "$HOME\.local\bin;$HOME\.cargo\bin;$env:Path"
        $hasUv = (Get-Command uv -ErrorAction SilentlyContinue) -ne $null
    } catch {
        Write-Warning "Automatic uv installation failed."
    }
}

if (-not $hasUv) {
    Write-Error "uv is required for EchoPage. Please install uv manually: https://docs.astral.sh/uv/getting-started/installation/ or run 'winget install astral-sh.uv'"
    exit 1
}
Write-Host "[SUCCESS] Found uv: $(uv --version)" -ForegroundColor Green

# 4. Create Virtual Environment with uv
$venvPath = Join-Path $PSScriptRoot ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "[INFO] Creating virtual environment at .venv using uv..." -ForegroundColor Cyan
    uv venv .venv
    Write-Host "[SUCCESS] Virtual environment created." -ForegroundColor Green
} else {
    Write-Host "[INFO] Using existing virtual environment at .venv." -ForegroundColor Cyan
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"

# 5. Detect NVIDIA GPU and Install PyTorch via uv
Write-Host "[INFO] Detecting GPU hardware..." -ForegroundColor Cyan
$hasNvidia = (Get-Command nvidia-smi -ErrorAction SilentlyContinue) -ne $null

if ($hasNvidia) {
    try {
        $gpuName = nvidia-smi --query-gpu=name --format=csv,noheader | Select-Object -First 1
        Write-Host "[SUCCESS] NVIDIA GPU detected: $gpuName" -ForegroundColor Green
        Write-Host "[INFO] Installing PyTorch with CUDA 12.4 support via uv..." -ForegroundColor Cyan
        uv pip install --python $venvPython torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
    } catch {
        Write-Host "[INFO] Failed to query nvidia-smi. Falling back to standard PyTorch via uv..." -ForegroundColor Yellow
        uv pip install --python $venvPython torch torchvision torchaudio
    }
} else {
    Write-Host "[INFO] No NVIDIA GPU detected. Installing standard PyTorch via uv..." -ForegroundColor Cyan
    uv pip install --python $venvPython torch torchvision torchaudio
}

# 6. Install EchoPage and dependencies via uv
Write-Host "[INFO] Installing EchoPage and alignment dependencies via uv..." -ForegroundColor Cyan
uv pip install --python $venvPython -e ".[align,dev]"

# 7. Pre-cache NLTK models
Write-Host "[INFO] Pre-caching NLTK sentence tokenizers (punkt, punkt_tab)..." -ForegroundColor Cyan
& $venvPython -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# 8. Disable Pyannote telemetry
Write-Host "[INFO] Disabling Pyannote default telemetry tracking..." -ForegroundColor Cyan
& $venvPython -c "
try:
    from pyannote.audio.telemetry.metrics import set_telemetry_metrics
    set_telemetry_metrics(False, save_choice_as_default=True)
except Exception:
    pass
" 2>$null

# 9. Smoke test
Write-Host "[INFO] Verifying installation..." -ForegroundColor Cyan
& $venvPython -c "
import echopage
import whisperx
print(f'EchoPage version: {echopage.__version__}')
"

Write-Host "`n=====================================================" -ForegroundColor Green
Write-Host "             Setup Completed Successfully!           " -ForegroundColor Green
Write-Host "=====================================================`n" -ForegroundColor Green
Write-Host "To activate your virtual environment in PowerShell:"
Write-Host "  .\.venv\Scripts\Activate.ps1`n" -ForegroundColor Cyan
Write-Host "To build a narrated EPUB:"
Write-Host "  echopage build --epub <path-to-epub> --audio <path-to-audio> --output <path-to-output>`n" -ForegroundColor Cyan
