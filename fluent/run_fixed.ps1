param(
    [ValidateSet('2impeller', '3impeller', '4impeller')]
    [string[]]$Models = @('2impeller', '3impeller', '4impeller'),
    [switch]$ComplexGeometry,
    [switch]$Plan
)
$ErrorActionPreference = 'Stop'
$pythonExe = Join-Path $PSScriptRoot '.venv312/Scripts/python.exe'
$configFile = Join-Path $PSScriptRoot 'repeatable_config.json'
$scheme = 'pump_repeatable'
if ($ComplexGeometry) {
    $configFile = Join-Path $PSScriptRoot 'complex_config.json'
    $scheme = 'pump_complex'
}
$action = 'batch'
if ($Plan) { $action = 'plan' }
$runArguments = @('-u', (Join-Path $PSScriptRoot 'run_meshing.py'), $action,
    '--schemes', $scheme, '--skip-prepare', '--config', $configFile, '--models') + $Models
& $pythonExe @runArguments
exit $LASTEXITCODE
