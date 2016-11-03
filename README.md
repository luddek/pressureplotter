== Pressure plotter ==
Script to plot pressure data from .csv files from script on rpi
Data is from a Maxigauge and is in the following csv format

timestamp data1 data2 error1 error2

== Requirements ==
Unix system
Pyqtgraph
numpy

== Usage ==
--Plot offline data--
cat data_pressure.csv | python pressureplotter.py

--Plot parts of data--
tail -n 20000 data_pressure.csv | python pressureplotter.py
tail -n 20000 data_pressure.csv | python pressureplotter.py --crosshair

--Plot realtime over ssh--
ssh pi@host tail -f folder/data_pressure.csv 2>&1 | python pressureplotter.py
ssh pi@host tail -f folder/data_pressure.csv 2>&1 | python pressureplotter.py --crosshair

--Plot realtime over ssh, start at beginning--
ssh pi@host tail -n+1 -f folder/data_pressure.csv 2>&1 | python pressureplotter.py
