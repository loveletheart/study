param(
    [switch]$SetupOnly,
    [switch]$Test,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Find-BootstrapPython {
    $candidates = @()
    if ($Python) {
        $candidates += @{ Command = $Python; Arguments = @() }
    }
    else {
        $candidates += @{ Command = 'py'; Arguments = @('-3') }
        $installRoots = @()
        if ($env:LOCALAPPDATA) {
            $installRoots += Join-Path $env:LOCALAPPDATA 'Programs\Python'
        }
        if ($env:USERPROFILE) {
            $installRoots += Join-Path $env:USERPROFILE 'AppData\Local\Programs\Python'
        }
        foreach ($installRoot in ($installRoots | Select-Object -Unique)) {
            if (Test-Path -LiteralPath $installRoot) {
                $installations = Get-ChildItem -LiteralPath $installRoot -Directory -Filter 'Python*' |
                    Sort-Object Name -Descending
                foreach ($installation in $installations) {
                    $candidates += @{
                        Command = Join-Path $installation.FullName 'python.exe'
                        Arguments = @()
                    }
                }
            }
        }
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($pythonCommand -and $pythonCommand.Source -notlike '*\Microsoft\WindowsApps\*') {
            $candidates += @{ Command = $pythonCommand.Source; Arguments = @() }
        }
    }

    foreach ($candidate in $candidates) {
        try {
            $candidateArguments = $candidate.Arguments
            & $candidate.Command @candidateArguments -c 'import sys, venv; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
            # 실행기나 별칭이 정상 동작하지 않으면 다음 Python 실행 파일을 확인합니다.
        }
    }
    throw 'Python 3.11+ was not found. Install Python or pass -Python with its executable path.'
}

function Test-FrontendBuild([IO.FileInfo]$Index) {
    $html = Get-Content -LiteralPath $Index.FullName -Raw -Encoding UTF8
    $assetPattern = '\b(?:src|href)\s*=\s*["''](?:/app/|\./)?(assets/[^"''?#]+\.(?:js|css))(?:[?#][^"'']*)?["'']'
    $assetPaths = foreach ($asset in [regex]::Matches($html, $assetPattern)) {
        $asset.Groups[1].Value
    }
    if (-not ($assetPaths | Where-Object { $_ -like '*.js' })) {
        return $false
    }
    foreach ($assetPath in $assetPaths) {
        if (-not (Test-Path -LiteralPath (Join-Path $Index.DirectoryName $assetPath) -PathType Leaf)) {
            return $false
        }
    }
    return $true
}

function Initialize-Frontend([string]$FrontendDirectory) {
    Push-Location -LiteralPath $FrontendDirectory
    try {
        $packageFiles = Get-Item -LiteralPath 'package.json', 'package-lock.json'
        $installedLock = Get-Item -LiteralPath 'node_modules/.package-lock.json' -ErrorAction SilentlyContinue
        $needsInstall = -not $installedLock -or
            -not (Test-Path -LiteralPath 'node_modules/vite/client.d.ts' -PathType Leaf) -or
            -not (Test-Path -LiteralPath 'node_modules/.bin/vue-tsc.cmd' -PathType Leaf) -or
            ($packageFiles | Where-Object { $_.LastWriteTimeUtc -gt $installedLock.LastWriteTimeUtc })

        $builtIndex = Get-Item -LiteralPath 'dist/index.html' -ErrorAction SilentlyContinue
        if (-not $needsInstall -and $builtIndex -and (Test-FrontendBuild $builtIndex)) {
            $buildInputs = @(
                $installedLock
                Get-Item -LiteralPath 'index.html', 'tsconfig.json', 'vite.config.js', 'src', 'public'
                Get-ChildItem -LiteralPath 'src', 'public' -Recurse
            )
            if (-not ($buildInputs | Where-Object { $_.LastWriteTimeUtc -gt $builtIndex.LastWriteTimeUtc })) {
                Write-Host '[setup] Frontend is up to date.'
                return
            }
        }

        $npm = Get-Command npm.cmd -CommandType Application -ErrorAction SilentlyContinue
        if (-not $npm) {
            throw 'Frontend setup requires Node.js 20.19+ (20.x) or 22.12+ with npm on PATH.'
        }
        if ($needsInstall) {
            Write-Host '[setup] Installing frontend dependencies...'
            & $npm.Source ci --include=dev --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) {
                throw 'Frontend dependency installation failed. The application was not started.'
            }
        }

        Write-Host '[setup] Building frontend...'
        & $npm.Source run build
        if ($LASTEXITCODE -ne 0) {
            throw 'Frontend build failed. The application was not started.'
        }
    }
    finally {
        Pop-Location
    }
}

Push-Location $PSScriptRoot
try {
    $venvDirectory = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
    $activateScript = Join-Path $venvDirectory 'Scripts\Activate.ps1'
    $backendDirectory = Join-Path $PSScriptRoot 'backend'
    $frontendDirectory = Join-Path $PSScriptRoot 'frontend'
    $requirements = Join-Path $backendDirectory 'requirements.txt'

    if (-not (Test-Path -LiteralPath $requirements)) {
        throw 'backend/requirements.txt was not found.'
    }

    if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-Path -LiteralPath $activateScript)) {
        Write-Host '[setup] Creating or repairing .venv...'
        $bootstrap = Find-BootstrapPython
        $bootstrapArguments = $bootstrap.Arguments
        & $bootstrap.Command @bootstrapArguments -m venv $venvDirectory
        if ($LASTEXITCODE -ne 0) {
            throw 'Virtual environment creation failed. The application was not started.'
        }
    }

    # 패키지를 설치하거나 애플리케이션을 실행하기 전에 가상환경을 활성화합니다.
    . $activateScript
    & $venvPython -c 'import pathlib, sys; expected = pathlib.Path(sys.argv[1]).resolve(); sys.exit(0 if sys.prefix != sys.base_prefix and pathlib.Path(sys.prefix).resolve() == expected else 1)' $venvDirectory
    if ($LASTEXITCODE -ne 0) {
        throw 'The project virtual environment is invalid. The application was not started.'
    }
    Write-Host "[venv] Active: $venvDirectory"

    try {
        & $venvPython -m pip --version *> $null
        $pipReady = $LASTEXITCODE -eq 0
    }
    catch {
        $pipReady = $false
    }
    if (-not $pipReady) {
        & $venvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            throw 'pip setup failed. The application was not started.'
        }
    }

    Write-Host '[setup] Checking and installing project dependencies...'
    & $venvPython -m pip install --disable-pip-version-check -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw 'Dependency installation failed. The application was not started.'
    }

    if (-not $Test -and (Test-Path -LiteralPath (Join-Path $frontendDirectory 'package.json') -PathType Leaf)) {
        Initialize-Frontend $frontendDirectory
    }

    if ($SetupOnly) {
        Write-Host '[setup] Ready.'
    }
    elseif ($Test) {
        Set-Location -LiteralPath $backendDirectory
        & $venvPython -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    else {
        Set-Location -LiteralPath $backendDirectory
        Write-Host "[server] http://127.0.0.1:$Port/docs"
        & $venvPython -m uvicorn main:app --host 127.0.0.1 --port $Port --reload
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
finally {
    Pop-Location
}
