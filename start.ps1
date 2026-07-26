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

    try {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        $dialog.Description = "Select the Copilot configuration directory that contains settings.json"
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

function Write-GeneratedConfig {
    param(
        [string]$BaseUrl,
        [string]$SelectedModelId,
        [bool]$UseNgrok
    )

    if (-not (Test-Path -LiteralPath $TemplatePath -PathType Leaf)) {
        throw "Configuration template does not exist: $TemplatePath"
    }

    $template = [System.IO.File]::ReadAllText($TemplatePath)
    $content = $template.Replace('"__BASE_URL__"', (ConvertTo-YamlDoubleQuoted $BaseUrl))
    $content = $content.Replace('"__MODEL_ID__"', (ConvertTo-YamlDoubleQuoted $SelectedModelId))
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

    $baseUrl = if (-not [string]::IsNullOrWhiteSpace($selectedModel.base_url)) {
        $selectedModel.base_url
    } else {
        $inspection.base_url
    }
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
        throw "The selected Copilot model does not define a third-party API base URL."
    }

    Write-GeneratedConfig $baseUrl $selectedModel.model_id $EnableNgrok.IsPresent
    Write-Host "Generated configuration: $ConfigPath"
    Write-Host "Upstream model: $($selectedModel.model_id)"
    Write-Host "Upstream base URL: $baseUrl"
}

if ($NoStart) {
    exit 0
}

$ngrokArgument = if ($EnableNgrok) { "--ngrok" } else { "--no-ngrok" }
& uv run copilot-gpt-proxy --config $ConfigPath $ngrokArgument
exit $LASTEXITCODE
