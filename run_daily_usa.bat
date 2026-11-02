@echo off
rem Weekday 21:50 - fetch, scan, dashboard USA tab, Slack, upload (daily.py)
set PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe
set PYTHONIOENCODING=utf-8
cd /d %~dp0
for /f %%d in ('%PY% -c "import datetime;print(datetime.date.today())"') do set D=%%d
%PY% -u daily.py %* >> logs\daily_%D%.log 2>&1
