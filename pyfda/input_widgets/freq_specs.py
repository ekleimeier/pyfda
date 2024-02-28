# -*- coding: utf-8 -*-
#
# This file is part of the pyFDA project hosted at https://github.com/chipmuenk/pyfda
#
# Copyright © pyFDA Project Contributors
# Licensed under the terms of the MIT License
# (see file LICENSE in root directory for details)

"""
Subwidget for entering frequency specifications
"""
import sys
import re
from pyfda.libs.compat import (
    QtCore, Qt, QWidget, QLabel, QLineEdit, QFrame, QFont, QVBoxLayout, QHBoxLayout,
    QGridLayout, pyqtSignal, QEvent)

import pyfda.filterbroker as fb
from pyfda.libs.pyfda_lib import to_html, safe_eval, unique_roots
from pyfda.libs.pyfda_qt_lib import qstyle_widget
from pyfda.pyfda_rc import params  # FMT string for QLineEdit fields, e.g. '{:.3g}'

import logging
logger = logging.getLogger(__name__)

MIN_FREQ_STEP = 1e-4

class FreqSpecs(QWidget):
    """
    Build and update widget for entering the frequency
    specifications like F_sb, F_pb etc.
    """
    # class variables (shared between instances if more than one exists)
    sig_tx = pyqtSignal(object)  # outgoing
    sig_rx = pyqtSignal(object)  # incoming
    from pyfda.libs.pyfda_qt_lib import emit

    def __init__(self, parent=None, title="Frequency Specs"):

        super(FreqSpecs, self).__init__(parent)
        self.title = title

        self.qlabels = []    # list with references to QLabel widgets
        self.qlineedit = []  # list with references to QLineEdit widgetss

        self.spec_edited = False  # flag whether QLineEdit field has been edited

        self._construct_UI()

# -------------------------------------------------------------
    def process_sig_rx(self, dict_sig=None):
        """
        Process signals coming in via subwidgets and sig_rx
        """
        # logger.debug("Processing {0}: {1}".format(type(dict_sig).__name__, dict_sig))
        if dict_sig['id'] == id(self):
            # logger.warning("Stopped infinite loop:\n{0}".format(pprint_log(dict_sig)))
            return
        elif 'view_changed' in dict_sig and dict_sig['view_changed'] == 'f_S':
            self.recalc_freqs()

# -------------------------------------------------------------
    def _construct_UI(self):
        """
        Construct the User Interface
        """
        bfont = QFont()
        bfont.setBold(True)

        lblTitle = QLabel(str(self.title), self)  # field for widget title
        lblTitle.setFont(bfont)
        lblTitle.setWordWrap(True)
        self.lblUnit = QLabel(self)
        self.lblUnit.setText("in " + to_html(fb.fil[0]['freq_specs_unit'], frmt='bi'))

        layHTitle = QHBoxLayout()
        layHTitle.addWidget(lblTitle)
        layHTitle.addWidget(self.lblUnit)
        layHTitle.addStretch(1)

        # Create a gridLayout consisting of QLabel and QLineEdit fields
        # for the frequency specs:
        self.layGSpecs = QGridLayout()  # sublayout for spec fields
        # set the title as the first (fixed) entry in grid layout. The other
        # fields are added and hidden dynamically in _show_entries and _hide_entries()
        self.layGSpecs.addLayout(layHTitle, 0, 0, 1, 2)
        self.layGSpecs.setAlignment(Qt.AlignLeft)

        self.frmMain = QFrame(self)
        self.frmMain.setLayout(self.layGSpecs)

        self.layVMain = QVBoxLayout()  # Widget main layout
        self.layVMain.addWidget(self.frmMain)  # , Qt.AlignLeft)
        self.layVMain.setContentsMargins(*params['wdg_margins'])
        self.setLayout(self.layVMain)

        self.n_cur_labels = 0  # number of currently visible labels / qlineedits

        # ----------------------------------------------------------------------
        # GLOBAL SIGNALS & SLOTs
        # ----------------------------------------------------------------------
        self.sig_rx.connect(self.process_sig_rx)

        # ----------------------------------------------------------------------
        # EVENT FILTER
        # ----------------------------------------------------------------------
        # DYNAMIC SIGNAL SLOT CONNECTION:
        # Every time a field is edited, call self.store_entries
        # This is achieved by dynamically installing and
        # removing event filters when creating / deleting subwidgets.
        # The event filter monitors the focus of the input fields.
        # ----------------------------------------------------------------------

# ------------------------------------------------------------------------------
    def eventFilter(self, source, event):
        """
        Filter all events generated by the QLineEdit widgets. Source and type
        of all events generated by monitored objects are passed to this eventFilter,
        evaluated and passed on to the next hierarchy level.

        - When a QLineEdit widget gains input focus (QEvent.FocusIn`), display
          the stored value from filter dict with full precision
        - When a key is pressed inside the text field, set the `spec_edited` flag
          to True.
        - When a QLineEdit widget loses input focus (QEvent.FocusOut`), store
          current value normalized to f_S with full precision (only if
          `spec_edited`== True) and display the stored value in selected format
        """
        if isinstance(source, QLineEdit):  # could be extended for other widgets
            if event.type() == QEvent.FocusIn:
                self.spec_edited = False
                # store current entry in case new value can't be evaluated:
                self.data_prev = source.text()
                self.update_f_display(source)
            elif event.type() == QEvent.KeyPress:
                self.spec_edited = True  # entry has been changed
                key = event.key()
                if key in {QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter}:
                    self._store_entry(source)
                elif key == QtCore.Qt.Key_Escape:  # revert changes
                    self.spec_edited = False
                    self.update_f_display(source)
            elif event.type() == QEvent.FocusOut:
                self._store_entry(source)
        # Call base class method to continue normal event processing:
        return super(FreqSpecs, self).eventFilter(source, event)

    # --------------------------------------------------------------------------
    def _store_entry(self, event_source):
        """
        `_store_entry()` is triggered by `QEvent.focusOut` in the eventFilter:
        When the `event_source` has been edited (`self.spec_edited ==  True`),
        evaluate the text field, normalize it with f_S and store it in the filter
        dict. Sort and store all entries in filter dict, then reload the text fields.
        Finally, emit a 'specs_changed': 'f_specs' signal.
        """
        logger.warning("freq_units: _store_entry")
        if self.spec_edited:
            f_label = str(event_source.objectName())
            f_value = safe_eval(
                event_source.text(), self.data_prev, sign='pos') / fb.fil[0]['f_S']
            fb.fil[0].update({f_label: f_value})
            self.sort_dict_freqs()
            self.emit({'specs_changed': 'f_specs'})
            self.spec_edited = False  # reset flag
        else:
            self.update_f_display(event_source)  # just update / restore display

    # --------------------------------------------------------------------------
    def update_UI(self, new_labels=()):
        """
        Called by `input_specs.update_UI()` and `target_specs.update_UI()`
        Set labels and get corresponding values from filter dictionary.
        When number of entries has changed, the layout of subwidget is rebuilt,
        using

        - `self.qlabels`, a list with references to existing QLabel widgets,
        - `new_labels`, a list of strings from the filter_dict for the current
          filter design
        - 'num_new_labels`, their number
        - `self.n_cur_labels`, the number of currently visible labels / qlineedit
          fields
        """
        state = new_labels[0]
        new_labels = new_labels[1:]
        num_new_labels = len(new_labels)
        # hide / show labels / create new subwidgets if neccessary:
        self._show_entries(num_new_labels)

#        W_lbl = max([self.qfm.width(l) for l in new_labels]) # max. label width in pixel

        # ---------------------------- logging -----------------------------
        logger.debug("update_UI: {0}-{1}-{2}".format(
                            fb.fil[0]['rt'], fb.fil[0]['fc'], fb.fil[0]['fo']))

        f_range = " (0 &lt; <i>f</i> &lt; <i>f<sub>S </sub></i>/2)"
        for i in range(num_new_labels):
            # Update ALL labels and corresponding values
            self.qlabels[i].setText(
                to_html(new_labels[i][0].lower() + new_labels[i][1:], frmt='bi'))
            self.qlineedit[i].setText(str(fb.fil[0][new_labels[i]]))
            self.qlineedit[i].setObjectName(new_labels[i])  # update ID
            qstyle_widget(self.qlineedit[i], state)

            if "sb" in new_labels[i].lower():
                self.qlineedit[i].setToolTip(
                    "<span>Corner frequency for (this) stop band" + f_range + ".</span>")
            elif "pb" in new_labels[i].lower():
                self.qlineedit[i].setToolTip(
                    "<span>Corner frequency for (this) pass band" + f_range + ".</span>")
            else:
                self.qlineedit[i].setToolTip(
                    "<span>Corner frequency for (this) band" + f_range + ".</span>")

        self.n_cur_labels = num_new_labels  # update number of currently visible labels
        self.sort_dict_freqs()  # sort frequency entries in dictionary and update display

    # --------------------------------------------------------------------------
    def recalc_freqs(self):
        """
        Update normalized frequencies when absolute frequencies are locked. This is called by via signal
        ['view_changed': 'f_S']
        """
        if fb.fil[0]['freq_locked']:
            for i in range(len(self.qlineedit)):
                f_name = str(self.qlineedit[i].objectName()).split(":", 1)
                f_label = f_name[0]
                f_value = fb.fil[0][f_label] * fb.fil[0]['f_S_prev'] / fb.fil[0]['f_S']
                logger.warning(f"Updating freq_specs: f_S = {fb.fil[0]['f_S']}, f_S_prev = {fb.fil[0]['f_S_prev']}\n"
                               f"{f_label}: {f_value}")

                fb.fil[0].update({f_label: f_value})
            self.emit({'specs_changed': 'f_specs'})

        # Always reload normalized frequencies from dict, check whether they are outside
        # the Nyquist range and display them in the selected unit.
        self.load_dict()

        # Always set label for frequency unit according to selected unit.
        unit = fb.fil[0]['plt_fUnit']
        if unit in {"f_S", "f_Ny"}:
            unit_frmt = 'bi'
        else:
            unit_frmt = 'b'
        self.lblUnit.setText(" in " + to_html(unit, frmt=unit_frmt))

# -------------------------------------------------------------
    def update_f_display(self, source):
        """
        Update frequency display when frequency or sampling frequency has been
        updated. Depending on whether it has focus or not, the value is displayed
        with full precision or rounded.

        Triggered by
        """
        f_name = str(source.objectName()).split(':', 1)
        f_label = f_name[0]
        f_value = fb.fil[0][f_label] * fb.fil[0]['f_S']

        if source.hasFocus():
            # widget has focus, show full precision
            logger.warning(f"freq_specs: update_f_display {f_label}: {f_value} (disp) "
                            f"{fb.fil[0][f_label]} (dict) FOK")
            source.setText(str(f_value))
        else:
            # widget has no focus, round the display
            logger.warning(f"freq_specs: update_f_display {f_label}: {f_value} (disp) "
                            f"{fb.fil[0][f_label]} (dict) NFOK")
            source.setText(params['FMT'].format(f_value))

        # Check whether normalized freqs are inside the range ]0, 0.5[. If not, highlight
        # widget.
        if fb.fil[0][f_label] <= 0:
            logger.warning(
                f"Frequency {str(source.objectName())} has to be >= 0")
            source.setProperty("state", 'failed')
        elif fb.fil[0][f_label] >= 0.5:
            logger.warning(
                f"Frequency {str(source.objectName())} has to be < f_S /2.")
            qstyle_widget(source, 'failed')
        else:
            qstyle_widget(source, 'normal')

        return

# -------------------------------------------------------------
    def load_dict(self):
        """
        Triggered by FocusIn, FocusOut and ESC-Key in LineEdit fields and by
        `sort_dict_freqs():

        `load_dict()` is called during init and when the frequency unit or the
          sampling frequency have been changed via
          `filter_specs.update_UI()` -> `self.update_UI()` -> `self.sort_dict_freqs()`

        - Reload textfields from filter dictionary

        - Transform the displayed frequency spec input fields according to the units
          setting (i.e. f_S). Spec entries are always stored normalized w.r.t. f_S
          in the dictionary; when f_S or the unit are changed, only the displayed values
          of the frequency entries are updated, not the dictionary!

        - Update the displayed frequency unit

        It should be called when `specs_changed` or `data_changed` is emitted
        at another place, indicating that a reload is required.
        """
        # update displayed freq spec values for (maybe) changed f_S
        for i in range(len(self.qlineedit)):
            self.update_f_display(self.qlineedit[i])

            # Print label with "f" for absolute and with "F" for normalized frequencies
            lbl_text = self.qlabels[i].text()
            if fb.fil[0]['freq_specs_unit'] in {'f_S', 'f_Ny'}:
                lbl_text = re.sub(r'[fF]', 'F', lbl_text)
            else:
                lbl_text = re.sub(r'[fF]', 'f', lbl_text)

            self.qlabels[i].setText(lbl_text)

# ------------------------------------------------------------------------
    def _show_entries(self, num_new_labels):
        """
        Called by `update_UI()` when filter has changed
        - check whether subwidgets need to be shown or hidden
        - check whether enough subwidgets (QLabel und QLineEdit) exist for the
          the required number of `num_new_labels`:
              - create new ones if required
              - initialize them with dummy information
              - install eventFilter for new QLineEdit widgets so that the filter
                  dict is updated automatically when a QLineEdit field has been
                  edited.
        - if enough subwidgets exist already, make enough of them visible to
          show all spec fields
        """

        num_tot_labels = len(self.qlabels)  # number of existing labels (vis. + invis.)

        # less new subwidgets than currently displayed -> _hide some
        if num_new_labels < self.n_cur_labels:
            # less new labels/qlineedit fields than before
            for i in range(num_new_labels, num_tot_labels):
                self.qlabels[i].hide()
                self.qlineedit[i].hide()
        # enough hidden subwidgets but need to make more labels visible
        elif num_tot_labels >= num_new_labels:
            for i in range(self.n_cur_labels, num_new_labels):
                self.qlabels[i].show()
                self.qlineedit[i].show()

        else:  # new subwidgets need to be generated
            for i in range(num_tot_labels, num_new_labels):
                self.qlabels.append(QLabel(self))
                self.qlabels[i].setText(to_html("dummy", frmt='bi'))

                self.qlineedit.append(QLineEdit(""))
                self.qlineedit[i].setObjectName("dummy")
                self.qlineedit[i].installEventFilter(self)  # filter events

                # first entry is the title
                self.layGSpecs.addWidget(self.qlabels[i], i+1, 0)
                self.layGSpecs.addWidget(self.qlineedit[i], i+1, 1)

# ------------------------------------------------------------------------------
    def sort_dict_freqs(self):
        """
        - Sort visible filter dict frequency spec entries with ascending frequency if
             the sort button is activated
        - Update the visible QLineEdit frequency widgets

        The method is called when:
        - update_UI has been called after changing the filter design algorithm
          that the response type has been changed
          eg. from LP -> HP, requiring a different order of frequency entries
        - a frequency spec field has been edited
        - the sort button has been clicked (from filter_specs.py)
        """
        logger.warning("freq_specs: sort_dict_freqs")
        # create list with the normalized frequency values of visible
        # QLineEdit widgets from the filter dict
        f_specs = [fb.fil[0][str(self.qlineedit[i].objectName())]
                   for i in range(self.n_cur_labels)]
        # sort them if required
        if fb.fil[0]['freq_specs_sort']:
            f_specs.sort()
        # and write them back to the filter dict
        for i in range(self.n_cur_labels):
            fb.fil[0][str(self.qlineedit[i].objectName())] = f_specs[i]

        # Update QLineEdit fields from list
        # Flag normalized freqs when outside the range ]0, 0.5[
        # for i in range(self.n_cur_labels):
        #     # fb.fil[0][str(self.qlineedit[i].objectName())] = f_specs[i]
        #     if f_specs[i] <= 0:
        #         logger.warning(
        #             f"Frequency {str(self.qlineedit[i].objectName())} has to be >= 0")
        #         self.qlineedit[i].setProperty("state", 'failed')
        #     elif f_specs[i] >= 0.5:
        #         logger.warning(
        #             f"Frequency {str(self.qlineedit[i].objectName())} has to be < f_S /2.")
        #         qstyle_widget(self.qlineedit[i], 'failed')
        #     else:
        #         qstyle_widget(self.qlineedit[i], 'normal')

        # verify that elements differ by at least MIN_FREQ_STEP by
        # checking for (nearly) identical elements:
        _, mult = unique_roots(f_specs, tol=MIN_FREQ_STEP)
        ident = [x for x in mult if x > 1]
        if ident:
            logger.warning("Frequencies must differ by at least {0:.4g}"
                           .format(MIN_FREQ_STEP * fb.fil[0]['f_S']))
        self.load_dict()
# ------------------------------------------------------------------------------
if __name__ == '__main__':
    """ Run widget standalone with `python -m pyfda.input_widgets.freq_specs` """
    from pyfda.libs.compat import QApplication
    from pyfda import pyfda_rc as rc

    app = QApplication(sys.argv)
    app.setStyleSheet(rc.qss_rc)
    mainw = FreqSpecs()
    mainw.update_UI(new_labels=['F_SB', 'F_SB2', 'F_PB', 'F_PB2'])
#    mainw.update_UI(new_labels = ['F_PB','F_PB2'])

    app.setActiveWindow(mainw)
    mainw.show()
    sys.exit(app.exec_())
