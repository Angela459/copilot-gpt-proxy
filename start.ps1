[CmdletBinding()]
param(
    [string]$CopilotConfigDirectory,
    [string]$ModelId,
    [string]$ConfigPath,
    [string]$TemplatePath,
    [switch]$Reconfigure,
    [switch]$EnableNgrok,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $ConfigPath = Join-Path $repoRoot "config.yaml"
}
if ([string]::IsNullOrWhiteSpace($TemplatePath)) {
    $TemplatePath = Join-Path $repoRoot "config.example.yaml"
}

function Select-CopilotConfigDirectory {
    param([string]$InitialPath)

    if (-not [string]::IsNullOrWhiteSpace($InitialPath)) {
        return $InitialPath
    }

    $commonLocations = @(
        "$env:APPDATA\Code\User",
        "$env:APPDATA\Code - Insiders\User",
        "$env:APPDATA\VSCodium\User"
    )
    Write-Host "Common Copilot configuration directories:"
    foreach ($location in $commonLocations) {
        Write-Host "  $location"
    }
    Write-Host "Select the directory used by your editor; no disk scan will run."

    try {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select the Copilot configuration directory containing settings.json. Common: %APPDATA%\Code\User"
        $dialog.ShowNewFolderButton = $false
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            return $dialog.SelectedPath
        }
    } catch {
        Write-Verbose "Folder picker is unavailable: $($_.Exception.Message)"
    }

    return Read-Host "Copilot configuration directory containing settings.json"
}

function ConvertTo-YamlDoubleQuoted {
    param([string]$Value)

    $escaped = $Value.Replace("\", "\\").Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Confirm-CopilotSettingsUpdate {
    $message = @"
The selected Copilot model will be connected to this proxy.

A one-time settings.json.copilot-gpt-proxy.bak backup will be kept.
Continue?
"@
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $result = [System.Windows.Forms.MessageBox]::Show(
            $message,
            "Copilot GPT Proxy",
            [System.Windows.Forms.MessageBoxButtons]::OKCancel,
            [System.Windows.Forms.MessageBoxIcon]::Information
        )
        return $result -eq [System.Windows.Forms.DialogResult]::OK
    } catch {
        Write-Host $message
        $confirmation = Read-Host "Press Enter to continue, or type N to cancel"
        return $confirmation -notmatch "^(?i:n|no)$"
    }
}

function Write-GeneratedConfig {
    param(
        [string]$BaseUrl,
        [string]$SelectedModelId,
        [string]$SettingsPath,
        [bool]$UseNgrok
    )

    if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        throw "Configuration template does not exist: $TemplatePath"
    }

    $template = [System.IO.File]::ReadAllText($TemplatePath)
    $content = $template.Replace('"__BASE_URL__"', (ConvertTo-YamlDoubleQuoted $BaseUrl))
    $content = $content.Replace('"__MODEL_ID__"', (ConvertTo-YamlDoubleQuoted $SelectedModelId))
    $content = $content.Replace(
        '"__COPILOT_SETTINGS_PATH__"',
        (ConvertTo-YamlDoubleQuoted $SettingsPath)
    )
    $content = $content.Replace("__NGROK__", $UseNgrok.ToString().ToLowerInvariant())

    $configDirectory = Split-Path -Parent $ConfigPath
    if (-not [string]::IsNullOrWhiteSpace($configDirectory)) {
        [System.IO.Directory]::CreateDirectory($configDirectory) | Out-Null
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($ConfigPath, $content, $utf8)
}

if ($Reconfigure -or -not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    $selectedDirectory = Select-CopilotConfigDirectory $CopilotConfigDirectory
    if ([string]::IsNullOrWhiteSpace($selectedDirectory)) {
        throw "No Copilot configuration directory was selected."
    }

    $resolvedSelection = (Resolve-Path -LiteralPath $selectedDirectory).Path
    $settingsPath = if (Test-Path -LiteralPath $resolvedSelection -PathType Leaf) {
        $resolvedSelection
    } else {
        Join-Path $resolvedSelection "settings.json"
    }
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw "settings.json was not found in the selected directory: $resolvedSelection"
    }

    $inspectOutput = & uv run copilot-gpt-proxy --inspect-copilot-settings $settingsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect Copilot settings: $settingsPath"
    }
    $inspection = ($inspectOutput -join [Environment]::NewLine) | ConvertFrom-Json
    $models = @($inspection.models | Where-Object {
        $_.model_id -and
        -not $_.model_id.StartsWith("__provider__") -and
        ($null -eq $_.api_mode -or $_.api_mode -in @("openai", "openai-responses"))
    })
    if ($models.Count -eq 0) {
        throw "No supported Copilot models were found in $settingsPath"
    }

    $selectedModel = $null
    if (-not [string]::IsNullOrWhiteSpace($ModelId)) {
        $selectedModel = $models | Where-Object { $_.model_id -eq $ModelId } | Select-Object -First 1
        if ($null -eq $selectedModel) {
            throw "The requested model was not found in Copilot settings: $ModelId"
        }
    } elseif ($models.Count -eq 1) {
        $selectedModel = $models[0]
        Write-Host "Selected model: $($selectedModel.model_id)"
    } else {
        Write-Host "Available Copilot models:"
        for ($index = 0; $index -lt $models.Count; $index++) {
            Write-Host "  $($index + 1). $($models[$index].model_id)"
        }
        do {
            $choice = Read-Host "Select a model number"
            $parsedChoice = 0
            $validChoice = [int]::TryParse($choice, [ref]$parsedChoice) -and
                $parsedChoice -ge 1 -and $parsedChoice -le $models.Count
        } until ($validChoice)
        $selectedModel = $models[$parsedChoice - 1]
    }

    $upstreamModel = $selectedModel
    $upstreamGlobalBaseUrl = $inspection.base_url
    $backupPath = "$settingsPath.copilot-gpt-proxy.bak"
    if (Test-Path -LiteralPath $backupPath -PathType Leaf) {
        $backupOutput = & uv run copilot-gpt-proxy `
            --inspect-copilot-settings $backupPath `
            --copilot-model-id $selectedModel.model_id
        if ($LASTEXITCODE -eq 0) {
            $backupInspection = ($backupOutput -join [Environment]::NewLine) |
                ConvertFrom-Json
            if ($null -ne $backupInspection.selected_model) {
                $upstreamModel = $backupInspection.selected_model
                $upstreamGlobalBaseUrl = $backupInspection.base_url
            }
        }
    }

    $baseUrl = if (-not [string]::IsNullOrWhiteSpace($upstreamModel.base_url)) {
        $upstreamModel.base_url
    } else {
        $upstreamGlobalBaseUrl
    }
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
        throw "The selected Copilot model does not define a third-party API base URL."
    }

    Write-GeneratedConfig $baseUrl $selectedModel.model_id $settingsPath $EnableNgrok.IsPresent
    Write-Host "Generated configuration: $ConfigPath"
    Write-Host "Upstream model: $($selectedModel.model_id)"
    Write-Host "Upstream base URL: $baseUrl"
}

if ($NoStart) {
    exit 0
}

if (-not (Confirm-CopilotSettingsUpdate)) {
    exit 0
}

$ngrokArgument = if ($EnableNgrok) { "--ngrok" } else { "--no-ngrok" }
& uv run copilot-gpt-proxy --config $ConfigPath $ngrokArgument
exit $LASTEXITCODE
