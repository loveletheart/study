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
            # Try the next installed interpreter if a launcher or alias is broken.
        }
    }
    throw 'Python 3.11+ was not found. Install Python or pass -Python with its executable path.'
}

Push-Location $PSScriptRoot
try {
    $venvDirectory = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venvDirectory 'Scripts\python.exe'
    $activateScript = Join-Path $venvDirectory 'Scripts\Activate.ps1'
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'

    if (-not (Test-Path -LiteralPath $requirements)) {
        throw 'requirements.txt was not found.'
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

    # Activate before installing dependencies or starting application Python.
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

    if ($SetupOnly) {
        Write-Host '[setup] Ready.'
    }
    elseif ($Test) {
        & $venvPython -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    else {
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
