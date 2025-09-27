@echo off
REM Chuyển thư mục sang nơi chứa file bat
cd /d %~dp0

REM Cài các package từ requirements.txt
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

REM Giữ cửa sổ cmd mở để xem kết quả
pause
