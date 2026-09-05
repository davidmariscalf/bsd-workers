param(
    [string]$Root = "C:\bsd-mcp"
)

$ErrorActionPreference = "Stop"
$WorkersRoot = Join-Path $Root "bsd-workers-bridge"
$SecretsPath = Join-Path $Root "bsd_ci_secrets.json"
$LoaderPath = Join-Path $Root "load_bsd_ci_env.ps1"
$DispatchPath = Join-Path $WorkersRoot "provider_dispatch.py"
$TasksPath = Join-Path $WorkersRoot "server-self-test.json"

Write-Host "=== BSD GitHub + GitLab server bridge setup ==="
Write-Host "Root: $Root"

if (-not (Test-Path $Root)) {
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
}
if (-not (Test-Path $WorkersRoot)) {
    New-Item -ItemType Directory -Path $WorkersRoot -Force | Out-Null
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found in PATH. The BSD server already normally uses Python; open the same user/session that runs it."
}

Write-Host "Downloading the current provider dispatcher from GitHub..."
Invoke-WebRequest `
    -Uri "https://raw.githubusercontent.com/davidmariscalf/bsd-workers/main/provider_dispatch.py" `
    -OutFile $DispatchPath `
    -UseBasicParsing

$taskJson = @'
[
  {"id":"server-bridge-self-test","type":"self_test","params":{}}
]
'@
Set-Content -Path $TasksPath -Value $taskJson -Encoding UTF8

Write-Host ""
Write-Host "Paste the GitHub fine-grained token when prompted. It will NOT be shown."
$gh = Read-Host "GitHub token" -AsSecureString
Write-Host "Paste the GitLab project/personal access token when prompted. It will NOT be shown."
$gl = Read-Host "GitLab token" -AsSecureString

# ConvertFrom-SecureString without an explicit key uses Windows DPAPI.
# Only the same Windows user on the same machine can decrypt these values.
$cfg = [ordered]@{
    github_token_enc = ConvertFrom-SecureString $gh
    gitlab_token_enc = ConvertFrom-SecureString $gl
    github_repo      = "davidmariscalf/bsd-workers"
    gitlab_project   = "86129510"
    gitlab_ref       = "main"
    created_at_utc   = [DateTime]::UtcNow.ToString("o")
}
$cfg | ConvertTo-Json | Set-Content -Path $SecretsPath -Encoding UTF8

$loader = @'
$ErrorActionPreference = "Stop"
$cfg = Get-Content "C:\bsd-mcp\bsd_ci_secrets.json" -Raw | ConvertFrom-Json

function Convert-DpapiStringToPlainText([string]$Encrypted) {
    $secure = ConvertTo-SecureString $Encrypted
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

$env:BSD_GITHUB_TOKEN = Convert-DpapiStringToPlainText $cfg.github_token_enc
$env:BSD_GITHUB_REPO = [string]$cfg.github_repo
$env:BSD_GITLAB_TOKEN = Convert-DpapiStringToPlainText $cfg.gitlab_token_enc
$env:BSD_GITLAB_PROJECT = [string]$cfg.gitlab_project
$env:BSD_GITLAB_REF = [string]$cfg.gitlab_ref
'@
Set-Content -Path $LoaderPath -Value $loader -Encoding UTF8

# Restrict ACLs to the current user and SYSTEM where possible.
try {
    $me = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    icacls $SecretsPath /inheritance:r /grant:r "${me}:(R,W)" "SYSTEM:(F)" | Out-Null
} catch {
    Write-Warning "Could not tighten ACLs automatically: $($_.Exception.Message)"
}

. $LoaderPath

Write-Host ""
Write-Host "Testing GitHub dispatch..."
& python $DispatchPath github $TasksPath
if ($LASTEXITCODE -ne 0) {
    throw "GitHub dispatch test failed. Check the token permissions and repository selection."
}

Write-Host ""
Write-Host "Testing GitLab dispatch..."
& python $DispatchPath gitlab $TasksPath
if ($LASTEXITCODE -ne 0) {
    throw "GitLab dispatch test failed. Check token scope/role and project access."
}

Write-Host ""
Write-Host "=== BRIDGE AUTHENTICATION TESTS DISPATCHED ==="
Write-Host "Encrypted secrets: $SecretsPath"
Write-Host "Environment loader: $LoaderPath"
Write-Host "Dispatcher: $DispatchPath"
Write-Host ""
Write-Host "Important: this proves the server can dispatch to both providers."
Write-Host "The existing bsd_lab_controller_v3.py still needs its queue routing/result collection patch before production tasks are sent automatically."
