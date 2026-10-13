@echo off
rem Windows launcher: runs run.sh under Git Bash. Usage: run.cmd [max_applications]
"%ProgramFiles%\Git\bin\bash.exe" -l "%~dp0run.sh" %*
