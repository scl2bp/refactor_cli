param(
    [string]$Package = "jlesson",
    [ValidateSet("auto", "ast", "grimp")]
    [string]$Backend = "grimp",
    [switch]$NoMermaid,
    [string[]]$FocusGroup = @()
)

$repoRoot = Split-Path -Parent $PSScriptRoot

$pythonLauncher = $null
$pythonLauncherArgs = @()

if ($env:CONDA_PREFIX) {
    $candidate = Join-Path $env:CONDA_PREFIX "python.exe"
    if (Test-Path $candidate) {
        $pythonLauncher = $candidate
    }
}

if (-not $pythonLauncher) {
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        $pythonLauncher = $pyCommand.Source
        $pythonLauncherArgs = @("-3")
    }
}

if (-not $pythonLauncher) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source -notlike "*WindowsApps*") {
        $pythonLauncher = $pythonCommand.Source
    }
}

if (-not $pythonLauncher) {
    $condaEnvRoot = Join-Path $HOME ".conda\envs"
    if (Test-Path $condaEnvRoot) {
        $preferred = Join-Path $condaEnvRoot "py312\python.exe"
        if (Test-Path $preferred) {
            $pythonLauncher = $preferred
        }
        else {
            $fallback = Get-ChildItem -Path $condaEnvRoot -Directory |
                ForEach-Object { Join-Path $_.FullName "python.exe" } |
                Where-Object { Test-Path $_ } |
                Select-Object -First 1
            if ($fallback) {
                $pythonLauncher = $fallback
            }
        }
    }
}

if (-not $pythonLauncher) {
    throw "Could not locate a usable Python interpreter. Activate your conda environment or install the 'py' launcher."
}

$args = @(
    (Join-Path $repoRoot "tools\internal_module_dependencies.py"),
    "--package", $Package,
    "--backend", $Backend,
    "--json-out", (Join-Path $repoRoot "output\internal_module_dependencies.json")
)

if (-not $NoMermaid) {
    $args += @("--mermaid-out", (Join-Path $repoRoot "docs\internal_module_dependencies.mmd"))
}

foreach ($pair in $FocusGroup) {
    $args += @("--focus-group", $pair)
}

& $pythonLauncher @pythonLauncherArgs @args