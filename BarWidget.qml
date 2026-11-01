import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "endmin.system-monitor"

  property string scriptPath: Quickshell.env("HOME") + "/.config/omarchy/plugins/endmin.system-monitor/monitor.py"
  property string displayText: "CPU …"
  property string details: "Loading system information…"
  property bool popupOpen: false

  function deferPopupClose() {
    closeTimer.restart()
  }

  function close() {
    popupOpen = false
  }

  function refresh() {
    if (!monitorProc.running) monitorProc.running = true
  }

  function update(raw) {
    try {
      const data = JSON.parse(raw)
      displayText = String(data.text || "System info unavailable")
      details = String(data.tooltip || "System information unavailable")
    } catch (e) {
      displayText = "System info unavailable"
      details = "Could not read system monitor output"
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: monitorProc
    command: ["/usr/bin/python3", root.scriptPath]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.update(text)
    }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.displayText = "System info unavailable"
        root.details = "The system monitor script could not run"
      }
    }
  }

  Timer {
    interval: 3000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Timer {
    id: closeTimer
    interval: 250
    onTriggered: {
      if (!button.tooltipHovered && !popup.containsMouse) root.close()
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText
    tooltipText: ""
    HoverHandler {
      onHoveredChanged: {
        if (hovered) {
          closeTimer.stop()
          root.popupOpen = true
        } else {
          root.deferPopupClose()
        }
      }
    }
  }

  PopupCard {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.popupOpen
    triggerMode: "hover"
    contentWidth: popup.fittedContentWidth(Style.space(360), Style.space(360))
    contentHeight: popup.fittedContentHeight(detailsLabel.implicitHeight)

    Item {
      anchors.fill: parent

      Text {
        id: detailsLabel
        anchors.fill: parent
        text: root.details
        color: button.foreground
        font.family: button.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignLeft
        verticalAlignment: Text.AlignTop
      }

      HoverHandler {
        onHoveredChanged: hovered ? closeTimer.stop() : root.deferPopupClose()
      }
    }
  }
}
