@echo off
chcp 65001 > nul
cd /d "%~dp0"

:: 統計収集
C:\Python312\python.exe -X utf8 pixiv_stats.py >> logs\run.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] COLLECT FAILED (exit code %errorlevel%) >> logs\run.log
    exit /b 1
)

:: レポート生成（ブラウザ非表示）
C:\Python312\python.exe -X utf8 analyze.py --no-browser >> logs\run.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] ANALYZE FAILED (exit code %errorlevel%) >> logs\run.log
    exit /b 1
)

:: GitHub Pages へ自動デプロイ
git add report\index.html >> logs\run.log 2>&1
git commit -m "stats %date%" >> logs\run.log 2>&1
git push >> logs\run.log 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] GIT PUSH FAILED >> logs\run.log
) else (
    echo [%date% %time%] PUSH OK >> logs\run.log
)
