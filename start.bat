@echo off
echo.
echo  Crawl4Noobs
echo  -----------
echo  Installing requirements (first run only)...
pip install flask aiohttp -q
echo.
echo  Starting... your browser will open automatically.
echo  Press Ctrl+C here to stop the server.
echo.
python server.py
pause
