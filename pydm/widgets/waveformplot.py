from pyqtgraph import BarGraphItem
from qtpy.QtGui import QColor, QCursor
from qtpy.QtCore import Slot, Property
import numpy as np
from .baseplot import BasePlot, NoDataError, BasePlotCurveItem
from .channel import PyDMChannel
import itertools
import json
from collections import OrderedDict
from pydm.utilities import remove_protocol


class WaveformCurveItem(BasePlotCurveItem):
    """
    WaveformCurveItem represents a single curve in a waveform plot.

    It can be used to plot one waveform vs. its indices, or one waveform
    vs. another.  In addition to the parameters listed below,
    WaveformCurveItem accepts keyword arguments for all plot options that
    pyqtgraph.PlotDataItem accepts.

    Parameters
    ----------
    y_addr: str, optional
        The address to waveform data for the Y axis.
        Curves must have Y data to plot.
    x_addr: str, optional
        The address to waveform data for the X axis.
        If None, the curve will plot Y data vs. the Y index.
    color: QColor, optional
        The color used to draw the curve line and the symbols.
    lineStyle: int, optional
        Style of the line connecting the data points.
        Must be a value from the Qt::PenStyle enum
        (see http://doc.qt.io/qt-5/qt.html#PenStyle-enum).
    lineWidth: int, optional
        Width of the line connecting the data points.
    redraw_mode: int, optional
        Must be one four values:

        - WaveformCurveItem.REDRAW_ON_EITHER: (Default) Redraw after either X or Y receives new data.
        - WaveformCurveItem.REDRAW_ON_X: Redraw after X receives new data.
        - WaveformCurveItem.REDRAW_ON_Y: Redraw after Y receives new data.
        - WaveformCurveItem.REDRAW_ON_BOTH: Redraw after both X and Y receive new data.
    **kargs: optional
        PlotDataItem keyword arguments, such as symbol and symbolSize.
    """

    _channels = ("x_channel", "y_channel")

    def __init__(self, y_addr=None, x_addr=None, redraw_mode=None, plot_style="Line", **kws):
        y_addr = "" if y_addr is None else y_addr
        if kws.get("name") is None:
            y_name = remove_protocol(y_addr)
            if x_addr is None:
                plot_name = y_name
            else:
                x_name = remove_protocol(x_addr)
                plot_name = "{y} vs. {x}".format(y=y_name, x=x_name)
            kws["name"] = plot_name
        self.redraw_mode = redraw_mode if redraw_mode is not None else self.REDRAW_ON_EITHER
        self.needs_new_x = True
        self.needs_new_y = True
        self.x_channel = None
        self.y_channel = None
        self.x_address = x_addr
        self.y_address = y_addr
        # The data in x_waveform and y_waveform are what actually get plotted.
        self.x_waveform = None
        self.y_waveform = None
        # Whenever the channels update, they immediately send latest_x and latest_y.
        # After each update, we check if we are ready to overwrite x_waveform and
        # y_waveform with the latest values, based on the redraw mode.
        self.latest_x = None
        self.latest_y = None
        self.plot_style = plot_style

        super().__init__(**kws)

    def to_dict(self):
        """
        Returns an OrderedDict representation with values for all properties
        needed to recreate this curve.

        Returns
        -------
        OrderedDict
        """
        dic_ = OrderedDict(
            [("y_channel", self.y_address), ("x_channel", self.x_address), ("plot_style", self.plot_style)]
        )
        dic_.update(super().to_dict())
        dic_["redraw_mode"] = self.redraw_mode
        return dic_

    @property
    def x_address(self):
        """
        The address of the channel used to get the x axis waveform data.

        Returns
        -------
        str
        """
        if self.x_channel is None:
            return None
        return self.x_channel.address

    @x_address.setter
    def x_address(self, new_address):
        """
        The address of the channel used to get the x axis waveform data.

        Parameters
        -------
        new_address: str
        """
        if new_address is None or len(str(new_address)) < 1:
            self.x_channel = None
            return
        self.x_channel = PyDMChannel(
            address=new_address, connection_slot=self.xConnectionStateChanged, value_slot=self.receiveXWaveform
        )

    @property
    def y_address(self):
        """
        The address of the channel used to get the y axis waveform data.

        Returns
        -------
        str
        """
        if self.y_channel is None:
            return None
        return self.y_channel.address

    @y_address.setter
    def y_address(self, new_address):
        """
        The address of the channel used to get the y axis waveform data.

        Parameters
        ----------
        new_address: str
        """
        if new_address is None or len(str(new_address)) < 1:
            self.y_channel = None
            return
        self.y_channel = PyDMChannel(
            address=new_address, connection_slot=self.yConnectionStateChanged, value_slot=self.receiveYWaveform
        )

    def update_waveforms_if_ready(self):
        """
        This is called whenever new waveform data is received for X or Y.
        Based on the value of the redraw_mode attribute, it decides whether
        the data_changed signal will be emitted.  The data_changed signal
        is used by the plot that owns this curve to request a redraw.
        """
        if self.redraw_mode == WaveformCurveItem.REDRAW_ON_EITHER:
            self.x_waveform = self.latest_x
            self.y_waveform = self.latest_y
            self.data_changed.emit()
        elif self.redraw_mode == WaveformCurveItem.REDRAW_ON_X:
            if not self.needs_new_x:
                self.x_waveform = self.latest_x
                self.y_waveform = self.latest_y
                self.data_changed.emit()
        elif self.redraw_mode == WaveformCurveItem.REDRAW_ON_Y:
            if not self.needs_new_y:
                self.x_waveform = self.latest_x
                self.y_waveform = self.latest_y
                self.data_changed.emit()
        elif self.redraw_mode == WaveformCurveItem.REDRAW_ON_BOTH:
            if not (self.needs_new_y or self.needs_new_x):
                self.x_waveform = self.latest_x
                self.y_waveform = self.latest_y
                self.data_changed.emit()

    @Slot(bool)
    def xConnectionStateChanged(self, connected):
        pass

    @Slot(bool)
    def yConnectionStateChanged(self, connected):
        pass

    @Slot(np.ndarray)
    def receiveXWaveform(self, new_waveform):
        """
        Handler for new x waveform data.  This method is usually called by a
        PyDMChannel when it updates.  You can call this yourself to inject data
        into the curve.

        Parameters
        ----------
        new_waveform: numpy.ndarray
            A new array values for the X axis.
        """
        if new_waveform is None:
            return
        if np.isinf(new_waveform).all():
            return
        self.latest_x = new_waveform
        self.needs_new_x = False
        # Don't redraw unless we already have Y data.
        if self.latest_y is not None:
            self.update_waveforms_if_ready()

    @Slot(np.ndarray)
    def receiveYWaveform(self, new_waveform):
        """
        Handler for new y waveform data.  This method is usually called by a
        PyDMChannel when it updates.  You can call this yourself to inject data
        into the curve.

        Parameters
        ----------
        new_waveform: numpy.ndarray
            A new array values for the Y axis.
        """
        if new_waveform is None:
            return
        if np.isinf(new_waveform).all():
            return
        self.latest_y = new_waveform
        self.needs_new_y = False
        if self.x_channel is None or self.latest_x is not None:
            self.update_waveforms_if_ready()

    def redrawCurve(self):
        """
        Called by the curve's parent plot whenever the curve needs to be
        re-drawn with new data.
        """
        # We try to be nice: if the X waveform doesn't have the same number
        # of points as the Y waveform, we'll truncate whichever was
        # longer so that they are both the same size.
        if self.y_waveform is None:
            return
        if self.x_waveform is not None:
            if self.x_waveform.shape[0] > self.y_waveform.shape[0]:
                self.x_waveform = self.x_waveform[: self.y_waveform.shape[0]]
            elif self.x_waveform.shape[0] < self.y_waveform.shape[0]:
                self.y_waveform = self.y_waveform[: self.x_waveform.shape[0]]

        if self.plot_style is None or self.plot_style == "Line":
            self._setCurveData()
        elif self.plot_style == "Bar":
            self._setBarGraphItem()

        self.needs_new_x = True
        self.needs_new_y = True

    def _setCurveData(self):
        """Sets the most recently received waveform data for display as a line graph."""
        if self.x_waveform is None:
            self.setData(y=self.y_waveform.astype(float))
            return
        self.setData(x=self.x_waveform.astype(float), y=self.y_waveform.astype(float))

    def _setBarGraphItem(self):
        """Sets the most recently received waveform data for display as a bar graph."""
        if self.y_waveform is None:
            return

        brushes = np.array([self.color] * len(self.y_waveform))
        if self.threshold_color is not None:
            if self.upper_threshold is not None:
                brushes[np.argwhere(self.y_waveform > self.upper_threshold)] = self.threshold_color
            if self.lower_threshold is not None:
                brushes[np.argwhere(self.y_waveform < self.lower_threshold)] = self.threshold_color

        if self.x_waveform is None:
            self.bar_graph_item.setOpts(x=np.arange(len(self.y_waveform)), height=self.y_waveform, brushes=brushes)
            return

        self.bar_graph_item.setOpts(x=self.x_waveform, height=self.y_waveform, brushes=brushes)

    def limits(self):
        """
        Limits of the data for this curve.
        Returns a nested tuple of limits: ((xmin, xmax), (ymin, ymax))

        Returns
        -------
        tuple
        """
        if self.y_waveform is None or self.y_waveform.shape[0] == 0:
            raise NoDataError("Curve has no Y data, cannot determine limits.")
        if self.x_waveform is None:
            yspan = float(np.amax(self.y_waveform)) - float(np.amin(self.y_waveform))
            return (
                (0, len(self.y_waveform)),
                (float(np.amin(self.y_waveform) - yspan), float(np.amax(self.y_waveform) + yspan)),
            )
        else:
            return (
                (float(np.amin(self.x_waveform)), float(np.amax(self.x_waveform))),
                (float(np.amin(self.y_waveform)), float(np.amax(self.y_waveform))),
            )

    def channels(self):
        return [self.y_channel, self.x_channel]


class PyDMWaveformPlot(BasePlot):
    """
    PyDMWaveformPlot is a widget to plot one or more waveforms.

    Each curve can plot either a Y-axis waveform vs. its indices,
    or a Y-axis waveform against an X-axis waveform.

    Parameters
    ----------
    parent : optional
        The parent of this widget.
    init_x_channels: optional
        init_x_channels can be a string with the address for a channel,
        or a list of strings, each containing an address for a channel.
        If not specified, y-axis waveforms will be plotted against their
        indices. If a list is specified for both init_x_channels and
        init_y_channels, they both must have the same length.
        If a single x channel was specified, and a list of y channels are
        specified, all y channels will be plotted against the same x channel.
    init_y_channels: optional
        init_y_channels can be a string with the address for a channel,
        or a list of strings, each containing an address for a channel.
        If a list is specified for both init_x_channels and init_y_channels,
        they both must have the same length.
        If a single x channel was specified, and a list of y channels are
        specified, all y channels will be plotted against the same x channel.
    background: optional
        The background color for the plot.  Accepts any arguments that
        pyqtgraph.mkColor will accept.
    """

    def __init__(self, parent=None, init_x_channels=[], init_y_channels=[], background="default"):
        super().__init__(parent, background)
        # If the user supplies a single string instead of a list,
        # wrap it in a list.
        if isinstance(init_x_channels, str):
            init_x_channels = [init_x_channels]
        if isinstance(init_y_channels, str):
            init_y_channels = [init_y_channels]
        if len(init_x_channels) == 0:
            init_x_channels = list(itertools.repeat(None, len(init_y_channels)))
        if len(init_x_channels) != len(init_y_channels):
            raise ValueError("If lists are provided for both X and Y " + "channels, they must be the same length.")
        # self.channel_pairs is an ordered dictionary that is keyed on a
        # (x_channel, y_channel) tuple, with WaveformCurveItem values.
        # It gets populated in self.addChannel().
        self.channel_pairs = OrderedDict()
        init_channel_pairs = zip(init_x_channels, init_y_channels)
        for x_chan, y_chan in init_channel_pairs:
            self.addChannel(y_chan, x_channel=x_chan)

    def initialize_for_designer(self):
        # If we are in Qt Designer, don't update the plot continuously.
        # This function gets called by PyDMTimePlot's designer plugin.
        pass

    def addChannel(
        self,
        y_channel=None,
        x_channel=None,
        plot_style=None,
        name=None,
        color=None,
        lineStyle=None,
        lineWidth=None,
        symbol=None,
        symbolSize=None,
        barWidth=None,
        upperThreshold=None,
        lowerThreshold=None,
        thresholdColor=None,
        redraw_mode=None,
        yAxisName=None,
    ):
        """
        Add a new curve to the plot.  In addition to the arguments below,
        all other keyword arguments are passed to the underlying
        pyqtgraph.PlotDataItem used to draw the curve.

        Parameters
        ----------
        y_channel: str
            The address for the y channel for the curve.
        x_channel: str, optional
            The address for the x channel for the curve.
        name: str, optional
            A name for this curve.  The name will be used in the plot legend.
        color: str or QColor, optional
            A color for the line of the curve.  If not specified, the plot will
            automatically assign a unique color from a set of default colors.
        lineStyle: int, optional
            Style of the line connecting the data points.
            0 means no line (scatter plot).
        lineWidth: int, optional
            Width of the line connecting the data points.
        redraw_mode: int, optional
            WaveformCurveItem.REDRAW_ON_EITHER: (Default)
                Redraw after either X or Y receives new data.
            WaveformCurveItem.REDRAW_ON_X:
                Redraw after X receives new data.
            WaveformCurveItem.REDRAW_ON_Y:
                Redraw after Y receives new data.
            WaveformCurveItem.REDRAW_ON_BOTH:
                Redraw after both X and Y receive new data.
        symbol: str or None, optional
            Which symbol to use to represent the data.
        symbolSize: int, optional
            Size of the symbol.
        barWidth: float, optional
            Width of any bars drawn on the plot
        upperThreshold: float, optional
            Bars that are above this value will be drawn in the threshold color
        lowerThreshold: float, optional
            Bars that are below this value will be drawn in the threshold color
        thresholdColor: QColor, optional
            Color to draw bars that exceed either threshold
        yAxisName : str, optional
            The name of the y axis to associate with this curve. Will be created if it
            doesn't yet exist
        """
        plot_opts = {}
        plot_opts["symbol"] = symbol
        if symbolSize is not None:
            plot_opts["symbolSize"] = symbolSize
        if lineStyle is not None:
            plot_opts["lineStyle"] = lineStyle
        if lineWidth is not None:
            plot_opts["lineWidth"] = lineWidth
        if redraw_mode is not None:
            plot_opts["redraw_mode"] = redraw_mode
        self._needs_redraw = False
        curve = self.createCurveItem(
            y_addr=y_channel,
            x_addr=x_channel,
            plot_style=plot_style,
            name=name,
            color=color,
            yAxisName=yAxisName,
            **plot_opts,
        )
        self.channel_pairs[(y_channel, x_channel)] = curve
        if plot_style == "Bar":
            if barWidth is None:
                barWidth = 1.0  # Can't use default since it can be explicitly set to None and avoided
            curve.bar_graph_item = BarGraphItem(x=[], height=[], width=barWidth, brush=color)
            curve.setBarGraphInfo(barWidth, upperThreshold, lowerThreshold, thresholdColor)
        self.addCurve(curve, curve_color=color, y_axis_name=yAxisName)
        if curve.bar_graph_item is not None:
            # Must happen after addCurve() so that the view box has been created
            curve.getViewBox().addItem(curve.bar_graph_item)
        curve.data_changed.connect(self.set_needs_redraw)

    def createCurveItem(self, *args, **kwargs):
        return WaveformCurveItem(*args, **kwargs)

    def removeChannel(self, curve):
        """
        Remove a curve from the plot.

        Parameters
        ----------
        curve: WaveformCurveItem
            The curve to remove.
        """
        self.removeCurve(curve)

    def removeChannelAtIndex(self, index):
        """
        Remove a curve from the plot, given an index
        for a curve.

        Parameters
        ----------
        index: int
            Index for the curve to remove.
        """
        curve = self._curves[index]
        self.removeChannel(curve)

    @Slot()
    def set_needs_redraw(self):
        self._needs_redraw = True

    @Slot()
    def redrawPlot(self):
        """
        Request a redraw from each curve in the plot.
        Called by curves when they get new data.
        """
        if not self._needs_redraw:
            return
        for curve in self._curves:
            curve.redrawCurve()
        self._needs_redraw = False

        if self.crosshair:
            global_pos = QCursor.pos()
            local_pos = self.mapFromGlobal(global_pos)
            scene_pos = self.mapToScene(local_pos)

            if self.plotItem.sceneBoundingRect().contains(scene_pos):
                mapped_point = self.plotItem.vb.mapSceneToView(scene_pos)
                self.vertical_crosshair_line.setPos(mapped_point.x())
                self.horizontal_crosshair_line.setPos(mapped_point.y())
                self.crosshair_position_updated.emit(scene_pos.x(), scene_pos.y())

    def clearCurves(self):
        """
        Remove all curves from the plot.
        """
        super().clear()

    def getCurves(self):
        """
        Get a list of json representations for each curve.
        """
        return [json.dumps(curve.to_dict()) for curve in self._curves]

    def setCurves(self, new_list):
        """
        Replace all existing curves with new ones.  This function
        is mostly used as a way to load curves from a .ui file, and
        almost all users will want to add curves through addChannel,
        not this method.

        Parameters
        ----------
        new_list: list
            A list of json strings representing each curve in the plot.
        """
        try:
            new_list = [json.loads(str(i)) for i in new_list]
        except ValueError as e:
            print("Error parsing curve json data: {}".format(e))
            return
        self.clearCurves()
        for d in new_list:
            color = d.get("color")
            thresholdColor = d.get("thresholdColor")
            if color:
                color = QColor(color)
            if thresholdColor:
                thresholdColor = QColor(thresholdColor)
            self.addChannel(
                d["y_channel"],
                d["x_channel"],
                plot_style=d.get("plot_style"),
                name=d.get("name"),
                color=color,
                lineStyle=d.get("lineStyle"),
                lineWidth=d.get("lineWidth"),
                symbol=d.get("symbol"),
                symbolSize=d.get("symbolSize"),
                barWidth=d.get("barWidth"),
                upperThreshold=d.get("upperThreshold"),
                lowerThreshold=d.get("lowerThreshold"),
                thresholdColor=thresholdColor,
                redraw_mode=d.get("redraw_mode"),
                yAxisName=d.get("yAxisName"),
            )

    curves = Property("QStringList", getCurves, setCurves, designable=False)

    def channels(self):
        """
        Returns the list of channels used by all curves in the plot.

        Returns
        -------
        list
        """
        chans = []
        chans.extend([curve.y_channel for curve in self._curves])
        chans.extend([curve.x_channel for curve in self._curves if curve.x_channel is not None])
        return chans

    # The methods for autoRangeX, minXRange, maxXRange, autoRangeY, minYRange,
    # and maxYRange are all defined in BasePlot, but we don't expose them as
    # properties there, because not all plot subclasses necessarily want them
    # to be user-configurable in Designer.
    autoRangeX = Property(
        bool,
        BasePlot.getAutoRangeX,
        BasePlot.setAutoRangeX,
        BasePlot.resetAutoRangeX,
        doc="""
Whether or not the X-axis automatically rescales to fit the data.
If true, the values in minXRange and maxXRange are ignored.""",
    )

    minXRange = Property(
        float,
        BasePlot.getMinXRange,
        BasePlot.setMinXRange,
        doc="""
Minimum X-axis value visible on the plot.""",
    )

    maxXRange = Property(
        float,
        BasePlot.getMaxXRange,
        BasePlot.setMaxXRange,
        doc="""
Maximum X-axis value visible on the plot.""",
    )

    autoRangeY = Property(
        bool,
        BasePlot.getAutoRangeY,
        BasePlot.setAutoRangeY,
        BasePlot.resetAutoRangeY,
        doc="""
Whether or not the Y-axis automatically rescales to fit the data.
If true, the values in minYRange and maxYRange are ignored.""",
    )

    minYRange = Property(
        float,
        BasePlot.getMinYRange,
        BasePlot.setMinYRange,
        doc="""
Minimum Y-axis value visible on the plot.""",
    )

    maxYRange = Property(
        float,
        BasePlot.getMaxYRange,
        BasePlot.setMaxYRange,
        doc="""
Maximum Y-axis value visible on the plot.""",
    )
