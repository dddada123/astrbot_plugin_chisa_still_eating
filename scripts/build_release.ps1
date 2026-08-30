param(
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$metadataPath = Join-Path $repoRoot "metadata.yaml"

if (-not (Test-Path -LiteralPath $metadataPath)) {
    throw "metadata.yaml not found at $metadataPath"
}

$metadataContent = Get-Content -LiteralPath $metadataPath -Raw
$nameMatch = [regex]::Match($metadataContent, '(?m)^name:\s*(.+?)\s*$')
$versionMatch = [regex]::Match($metadataContent, '(?m)^version:\s*(.+?)\s*$')

if (-not $nameMatch.Success -or -not $versionMatch.Success) {
    throw "Failed to read name/version from metadata.yaml"
}

$pluginName = $nameMatch.Groups[1].Value.Trim().Trim('"', "'")
$version = $versionMatch.Groups[1].Value.Trim().Trim('"', "'")
$mainContent = Get-Content -LiteralPath (Join-Path $repoRoot "main.py") -Raw
$webContent = Get-Content -LiteralPath (Join-Path $repoRoot "pages\manager\index.html") -Raw
$mainVersion = [regex]::Match($mainContent, '(?m)^__version__\s*=\s*["'']([^"'']+)["'']')
if (-not $mainVersion.Success -or $mainVersion.Groups[1].Value -ne $version) {
    throw "main.py version does not match metadata.yaml: $version"
}
if ($webContent -notmatch [regex]::Escape("v$version")) {
    throw "WebUI version does not match metadata.yaml: $version"
}
$artifactName = "$pluginName-$version.zip"
$outputRoot = Join-Path $repoRoot $OutputDir
$stagingRoot = Join-Path $outputRoot $pluginName
$artifactPath = Join-Path $outputRoot $artifactName

if (Test-Path -LiteralPath $stagingRoot) {
    Remove-Item -LiteralPath $stagingRoot -Recurse -Force
}

if (Test-Path -LiteralPath $artifactPath) {
    Remove-Item -LiteralPath $artifactPath -Force
}

[System.IO.Directory]::CreateDirectory($stagingRoot) | Out-Null

$includeFiles = @(
    "__init__.py",
    "_conf_schema.json",
    "CHANGELOG.md",
    "food_data.py",
    "image_manager.py",
    "LICENSE",
    "logo.png",
    "main.py",
    "metadata.yaml",
    "README.md",
    "rate_limiter.py",
    "responder.py"
)

$includeDirectories = @(
    "assets",
    "pages"
)

foreach ($relativePath in $includeFiles) {
    $sourcePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Release file missing: $relativePath"
    }

    $targetPath = Join-Path $stagingRoot $relativePath
    $targetDir = Split-Path -Parent $targetPath
    if (-not (Test-Path -LiteralPath $targetDir)) {
        [System.IO.Directory]::CreateDirectory($targetDir) | Out-Null
    }
    [System.IO.File]::Copy($sourcePath, $targetPath, $true)
}

foreach ($relativePath in $includeDirectories) {
    $sourcePath = Join-Path $repoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Release directory missing: $relativePath"
    }
    $targetRoot = Join-Path $stagingRoot $relativePath
    [System.IO.Directory]::CreateDirectory($targetRoot) | Out-Null
    foreach ($sourceFile in Get-ChildItem -LiteralPath $sourcePath -Recurse -File) {
        $fileRelativePath = $sourceFile.FullName.Substring($sourcePath.Length).TrimStart([char]'\')
        $targetPath = Join-Path $targetRoot $fileRelativePath
        [System.IO.Directory]::CreateDirectory((Split-Path -Parent $targetPath)) | Out-Null
        [System.IO.File]::Copy($sourceFile.FullName, $targetPath, $true)
    }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $stagingRoot,
    $artifactPath,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $false
)

$archive = [System.IO.Compression.ZipFile]::OpenRead($artifactPath)
try {
    $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    foreach ($requiredEntry in @("main.py", "metadata.yaml", "pages/manager/index.html")) {
        if ($requiredEntry -notin $entryNames) {
            throw "Release archive missing: $requiredEntry"
        }
    }
    foreach ($forbiddenEntry in @("reorder_schema.py", "catalog_test.json")) {
        if ($forbiddenEntry -in $entryNames) {
            throw "Developer-only file leaked into release: $forbiddenEntry"
        }
    }
} finally {
    $archive.Dispose()
}

Remove-Item -LiteralPath $stagingRoot -Recurse -Force
Write-Output "Created $artifactPath"
