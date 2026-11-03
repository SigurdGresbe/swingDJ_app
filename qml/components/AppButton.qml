import QtQuick
import QtQuick.Controls

Button {
    id: control

    property string kind: "quiet"
    property color accentColor: "#E16B3A"
    property color accentTextColor: "#FFFFFF"
    property color quietColor: "#F0ECE3"
    property color hoverColor: "#E8E2D7"
    property color textColor: "#1E2723"
    property color lineColor: "#DDD8CB"
    opacity: enabled ? 1 : 0.55
    implicitHeight: 42
    leftPadding: horizontalPadding
    rightPadding: horizontalPadding
    font.family: "Segoe UI Variable Text"
    font.pixelSize: 14
    font.weight: Font.DemiBold

    contentItem: Text {
        text: control.text
        color: control.kind === "primary" && control.enabled ? control.accentTextColor : control.textColor
        font: control.font
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 11
        color: {
            if (!control.enabled)
                return control.quietColor
            if (control.kind === "primary")
                return control.down ? Qt.darker(control.accentColor, 1.08)
                                    : control.hovered ? Qt.lighter(control.accentColor, 1.06)
                                                      : control.accentColor
            if (control.kind === "outline")
                return control.hovered ? control.hoverColor : "transparent"
            return control.hovered ? control.hoverColor : control.quietColor
        }
        border.width: control.kind === "primary" ? 0 : 1
        border.color: control.lineColor

        Behavior on color {
            ColorAnimation { duration: 120 }
        }
    }
}
