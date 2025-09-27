@echo off
REM Chuyen console sang che do UTF-8 de hien thi tieng Viet chinh xac.
chcp 65001 >nul

REM Buoc Python su dung UTF-8, giai quyet triet de loi UnicodeEncodeError.
set PYTHONUTF8=1

REM Dat tieu de cho cua so terminal.
title KTB Creator
REM Lấy thư mục chứa file bat và cd vào đó
cd /d %~dp0

REM Chạy script Python
python main.py

REM Giữ cửa sổ cmd mở sau khi chạy
pause