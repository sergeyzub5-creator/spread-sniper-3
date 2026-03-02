param(
    [string]$OutputFile = "project_snapshot.txt"
)

Write-Host "========================================"
Write-Host "СОЗДАНИЕ СНИМКА ПРОЕКТА"
Write-Host "========================================"
Write-Host "Выходной файл: $OutputFile"
Write-Host ""

$includePatterns = @("*.py", "*.ps1", "*.bat", "*.txt", "*.ini", "*.json", "*.md")
$excludeDirs = @("venv", "__pycache__", ".git", ".idea", ".vscode", "data")

$rootPath = (Get-Location).Path
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $rootPath $OutputFile))
$files = Get-ChildItem -Path . -Recurse -File | Where-Object {
    $file = $_
    $isIncluded = $false

    foreach ($pattern in $includePatterns) {
        if ($file.Name -like $pattern) {
            $isIncluded = $true
            break
        }
    }

    if (-not $isIncluded) {
        return $false
    }

    foreach ($dir in $excludeDirs) {
        if ($file.FullName -like "*\$dir\*") {
            return $false
        }
    }

    if ([System.IO.Path]::GetFullPath($file.FullName) -ieq $outputPath) {
        return $false
    }

    return $true
} | Sort-Object FullName

Write-Host "Найдено файлов: $($files.Count)"
Write-Host ""

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$content = @()
$content += "ПРОЕКТ SPREAD SNIPER 3"
$content += ""
$content += "Дата: $timestamp"
$content += "Путь: $rootPath"
$content += "=" * 50
$content += ""

foreach ($file in $files) {
    $relativePath = $file.FullName.Replace($rootPath + "\", "")
    Write-Host "  Добавление: $relativePath"

    $content += "=" * 50
    $content += "ФАЙЛ: $relativePath"
    $content += "=" * 50

    try {
        $fileContent = Get-Content -Path $file.FullName -Raw -ErrorAction Stop
        $content += $fileContent
    }
    catch {
        $content += "[ОШИБКА ЧТЕНИЯ ФАЙЛА] $($_.Exception.Message)"
    }

    $content += ""
}

$content -join "`r`n" | Out-File -FilePath $OutputFile -Encoding utf8

$size = (Get-Item -Path $OutputFile).Length

Write-Host ""
Write-Host "========================================"
Write-Host "ГОТОВО! Снимок сохранён в: $OutputFile"
Write-Host "Размер файла: $size байт"
Write-Host "========================================"
