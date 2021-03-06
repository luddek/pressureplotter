#!/bin/env python
"""
Copyright 2016 Ludvig Kjellsson

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
"""
==Requirements==
numpy
pyqtgraph
"""
DESC = """
===Pressure plotter script===
Script to plot pressure data from .csv files from script on rpi

==Usage==
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

"""
import os
import sys
import json
import fcntl
import argparse
import datetime
import signal
from collections import defaultdict

import numpy as np
from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph as pg

parser = argparse.ArgumentParser(description=DESC,
                                 formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('-c','--crosshair', help="Add a crosshair to plot",
                    action="store_true")
parser.add_argument('-v','--verbose', help="Print debugging data",
                    action="store_true")
args = vars(parser.parse_args())
VERBOSE = args['verbose']
CROSSHAIR = args['crosshair']


## Makes stdin nonblocking
## Works only on UNIX
## Beware is hack
fd = sys.stdin.fileno()
fl = fcntl.fcntl(fd, fcntl.F_GETFL)
fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)


class PressureData(object):
    """
    Class to read and handle pressuredata from stdin
    Usage:
    data = PressureData()
    data.read_new_data()
    timestamps = data[0]
    """
    def __init__(self):
        self.data = defaultdict(list)

    def __getitem__(self, key):
        return self.data[key]

    def __len__(self):
        return len(self.data)

    def _add_data(self, row):
        """
        Split the row and add it to the correct place in table
        """
        if VERBOSE:
            print "Parsing: {0}".format(row)
        values = row.split("\t")
        if len(values) < 2:
            print "WARNING: Row skipped: {0}".format(row)
            return
        for value in values:
            try:
                eval(value)
            except Exception as e:
                print "BAD LINE: {0}{1}".format(values, e)
                return
        for i, value in enumerate(values):
            value = eval(value)
            self.data[i].append(value)

    def read_new_data(self):
        """
        Read stdin until end. Add rows to the data
        """
        while True:
            try:
                lines = sys.stdin.readline()
            except IOError:
                break
            if lines == "":
                break
            for line in lines.splitlines():
                if "\x00" in line:
                    print "Line contains NULL, skipping..."
                    continue
                self._add_data(line.rstrip())

    def wait_for_initialdata(self):
        """
        read_new_data blocking until we have first lines
        """
        while len(self) == 0:
            self.read_new_data()


class TimeAxisItem(pg.AxisItem):
    """
    Customg pyqtgraph axisitem to get nice datetime on axis
    """
    def __init__(self, *args, **kwargs):
        pg.AxisItem.__init__(self, *args, **kwargs)

    def tickStrings(self, values, scale, spacing):
        return [datetime.datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S') for value in values]


class PressurePlotter(object):
    """
    Launches a pyqtgraph window and adds plot with data from PressureData
    """
    def __init__(self):
        # Data connection
        self.data = PressureData()
        if VERBOSE:
            print "Waiting for initial data"
        self.data.wait_for_initialdata()

        self.app = QtGui.QApplication([])
        self.win = pg.GraphicsWindow()
        self.win.setWindowTitle("Pressure")
        if CROSSHAIR:
	    self.crosshairlabel = pg.LabelItem(justify='right')
	    self.win.addItem(self.crosshairlabel)
        
        self.win.resize(1000,600)
        self.plotitem = self.win.addPlot(row=1, col=0,
                axisItems={'bottom': TimeAxisItem(orientation='bottom')})
        self.plotDataItems = []

        # Add right click to polyfit
        self.polyfitaction = QtGui.QAction("Fit log(y)=ax^2+bx+c", self.plotitem.vb.menu)
        self.polyfitaction.setCheckable(True)
        self.polyfitaction.triggered.connect(self.dopolyfitaction)
        self.plotitem.vb.menu.addAction(self.polyfitaction)

        if CROSSHAIR:
            self.vLine = pg.InfiniteLine(angle=90, movable=False)
            self.hLine = pg.InfiniteLine(angle=0, movable=False)
            self.plotitem.addItem(self.vLine, ignoreBounds=True)
            self.plotitem.addItem(self.hLine, ignoreBounds=True)

        # Keep track of mouse
        self.mousePoint = None
        self.proxy = pg.SignalProxy(
               self.plotitem.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(500)

    def dopolyfitaction(self, evt):
        """
        Poly fit is clicked in context menu.
        Add the plot item. If already added, remove it!
        """
        if not evt:
            self.plotitem.removeItem(self.polyfititem)
            self.polyfititem = None
            self.plotitem.removeItem(self.polyfitroiitem)
        if evt:
            self.plotitem.disableAutoRange('xy') # Disable so it doesn't go crazy
            x = self.mousePoint.x()
            y = self.mousePoint.y()
            self.polyfititem = pg.PlotDataItem()
            self.plotitem.addItem(self.polyfititem)
            self.polyfitroiitem = pg.PolyLineROI([[x, y], [x, y]], closed=False,
                                                 movable=False)
            self.polyfitroiitem.sigRegionChanged.connect(self.fitroiupdated)
            self.plotitem.addItem(self.polyfitroiitem)

    def fitroiupdated(self, roi):
        """
        Poly fit roi has been updated.
        Here we do the poly fit and plot it
        """
        points = [(h.pos().x(), h.pos().y()) for h in roi.getHandles()]
        order = 2
        points = np.asarray(points)
        poly = np.polyfit(points[:,0], np.log(points[:,1]), order)
        # Fill the screen, but minimum same as handles
        xmin = min(self.plotitem.vb.viewRange()[0][0], np.min(points[:,0]))
        xmax = max(self.plotitem.vb.viewRange()[0][1], np.max(points[:,0]))
        x = np.linspace(xmin, xmax)
        y = np.exp(np.polyval(poly, x))
        self.polyfititem.setData(x,y)

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.plotitem.sceneBoundingRect().contains(pos):
            self.mousePoint = self.plotitem.vb.mapSceneToView(pos)
            mousePoint = self.mousePoint
            if CROSSHAIR:
                index = int(mousePoint.x())
                self.crosshairlabel.setText("<span style='font-size: 12pt'>{0}, <span style='color: red'>{1}</span></span>".format(datetime.datetime.fromtimestamp(mousePoint.x()).strftime('%Y-%m-%d %H:%M:%S'), mousePoint.y()))
                self.vLine.setPos(mousePoint.x())
                self.hLine.setPos(mousePoint.y())

    def update(self):
        self.data.read_new_data()
        numcols = len(self.data)
        numdata = (numcols-1)/2
        while numdata > len(self.plotDataItems):
            if VERBOSE:
                print "Adding a curve"
            pen = pg.mkPen(pg.intColor(len(self.plotDataItems)))
            newplot = pg.PlotDataItem(pen=pen)
            self.plotitem.addItem(newplot)
            self.plotDataItems.append(newplot)
        for plot, i in zip(self.plotDataItems, range(1, 1+numdata)):
            plot.setData(self.data[0], self.data[i])
 

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL) # Set ctrl+c to do default action
    PP = PressurePlotter()
    if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
        QtGui.QApplication.instance().exec_()
