@echo off
echo.
echo  Crawl4Noobs
echo  -----------
echo  Opening the scraper in your browser...
echo.
echo  Make sure Docker is running with:
echo  docker run -p 11235:11235 unclecode/crawl4ai:latest
echo.
start "" "%~dp0index.html"
