# MT5 REST Server — Install as Windows Services
# Usage: .\install-service.ps1 -NssmPath "C:\nssm\nssm.exe"

param(
    [string]$NssmPath = "C:\nssm\nssm.exe",
    [string]$ServerDir = $PSScriptRoot,
    [string]$PythonPath = "$ServerDir\venv\Scripts\python.exe",
    [string]$LogDir = "$ServerDir\logs"
)

# Create log directory
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Find all .env.account* files
$envFiles = Get-ChildItem -Path $ServerDir -Filter ".env.account*"

if ($envFiles.Count -eq 0) {
    Write-Host "No .env.account* files found in $ServerDir"
    Write-Host "Create files like .env.account1, .env.account2, etc."
    Write-Host "Each must contain: MT5_API_KEY, MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_TERMINAL_PATH, PORT"
    exit 1
}

foreach ($envFile in $envFiles) {
    $accountName = $envFile.Name -replace '\.env\.', ''
    $serviceName = "mt5-rest-$accountName"

    Write-Host "Installing service: $serviceName (from $($envFile.Name))"

    # Read PORT from env file
    $port = (Get-Content $envFile.FullName | Where-Object { $_ -match '^PORT=' }) -replace 'PORT=', ''

    # Install service
    & $NssmPath install $serviceName $PythonPath
    & $NssmPath set $serviceName AppParameters "-m uvicorn server:app --host 0.0.0.0 --port $port"
    & $NssmPath set $serviceName AppDirectory $ServerDir
    & $NssmPath set $serviceName AppEnvironmentExtra "ENV_FILE=$($envFile.FullName)"
    & $NssmPath set $serviceName AppStdout "$LogDir\$accountName.log"
    & $NssmPath set $serviceName AppStderr "$LogDir\$accountName.log"
    & $NssmPath set $serviceName AppRotateFiles 1
    & $NssmPath set $serviceName AppRotateBytes 10485760
    & $NssmPath set $serviceName AppStopMethodSkip 6
    & $NssmPath set $serviceName AppStopMethodConsole 3000
    & $NssmPath set $serviceName AppStopMethodWindow 3000
    & $NssmPath set $serviceName AppStopMethodThreads 3000

    Write-Host "  Service $serviceName installed (port $port)"
    Write-Host "  Start with: net start $serviceName"
}

Write-Host ""
Write-Host "All services installed. Start all with:"
foreach ($envFile in $envFiles) {
    $accountName = $envFile.Name -replace '\.env\.', ''
    Write-Host "  net start mt5-rest-$accountName"
}
