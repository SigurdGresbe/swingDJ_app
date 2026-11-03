import QtQuick

Rectangle {
    property color fillColor: "#FFFFFF"
    property color lineColor: "#DDD8CB"
    property real cornerRadius: 18

    color: fillColor
    radius: cornerRadius
    border.width: 1
    border.color: lineColor
}
