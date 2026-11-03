import QtQuick
import QtQuick.Controls

TextField {
    id: control

    property color fillColor: "#F7F4ED"
    property color lineColor: "#DDD8CB"
    property color focusColor: "#E16B3A"
    property color textColor: "#1E2723"
    property color placeholderColor: "#7B837E"

    implicitHeight: 44
    leftPadding: 14
    rightPadding: 14
    color: textColor
    placeholderTextColor: placeholderColor
    selectionColor: focusColor
    selectedTextColor: "#FFFFFF"
    font.family: "Segoe UI Variable Text"
    font.pixelSize: 14

    background: Rectangle {
        radius: 11
        color: control.fillColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusColor : control.lineColor

        Behavior on border.color {
            ColorAnimation { duration: 120 }
        }
    }
}
