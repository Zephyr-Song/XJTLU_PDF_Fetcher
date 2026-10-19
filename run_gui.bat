@echo off
chcp 65001 >nul
title XJTLU 试卷下载器
python main.py --gui
if errorlevel 1 (
    echo.
    echo 启动失败。如果提示缺少 tkinter，请改用带 tkinter 的 Python，
    echo 或使用命令行模式: python main.py --help
    pause
)
