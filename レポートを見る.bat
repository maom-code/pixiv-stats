@echo off
chcp 65001 > nul
cd /d "%~dp0"
C:\Python312\python.exe -X utf8 analyze.py
