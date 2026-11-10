@echo off
rem kicad2ant on Windows: drag a .kicad_pcb onto this file, or
rem   run.bat BOARD.kicad_pcb [REF] [--mode dry^|coarse^|fine] [--f0 MHz] [--band LO HI] ...
rem (all options: python kicad2ant.py --help)
python "%~dp0kicad2ant.py" %*
if errorlevel 1 pause
