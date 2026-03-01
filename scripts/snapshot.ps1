param([string] = "project_snapshot.txt")

Write-Host "========================================"
Write-Host "СОЗДАНИЕ СНИМКА ПРОЕКТА"
Write-Host "========================================"
Write-Host "Выходной файл: "
Write-Host ""

 = @("*.py", "*.ps1", "*.bat", "*.txt", "*.ini", "*.json", "*.md")
 = @("venv", "__pycache__", ".git", ".idea", ".vscode")

 = Get-ChildItem -Path . -Recurse -File | Where-Object {
     = False
    foreach ( in ) {
        if (.Name -like ) {  = True; break }
    }
    foreach (data in ) {
        if (.FullName -like "*\data\*") {  = False; break }
    }
    
} | Sort-Object FullName

Write-Host "Найдено файлов: 0"
Write-Host ""

 = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
 = "ПРОЕКТ SPREAD SNIPER 3
"
 += "Дата: 
"
 += "Путь: C:\Users\Разраб\projektvscod
"
 += "=" * 50 + "

"

foreach (ui\styles\__init__.py in ) {
     = ui\styles\__init__.py.FullName.Replace((Get-Location).Path + "\", "")
    Write-Host "  Добавление: "
    
     += "=" * 50 + "
"
     += "ФАЙЛ: 
"
     += "=" * 50 + "
"
    
    try {
         = Get-Content -Path ui\styles\__init__.py.FullName -Raw -ErrorAction Stop
         +=  + "
"
    } catch {
         += "[ОШИБКА ЧТЕНИЯ ФАЙЛА]
"
    }
     += "
"
}

 | Out-File -FilePath  -Encoding utf8

Write-Host ""
Write-Host "========================================"
Write-Host "ГОТОВО! Снимок сохранён в: "
Write-Host "Размер файла:  байт"
Write-Host "========================================"
