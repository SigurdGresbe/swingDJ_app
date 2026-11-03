import QtQuick
import QtQuick.Controls

Button {
    id: control

    property bool active: false
    property color accentColor: "#E16B3A"
    property color activeColor: "#29312D"
    property color hoverColor: "#242B28"
    property color textColor: "#D9DED9"
    property color mutedColor: "#8F9A94"
    property string marker: "01"

    implicitHeight: 54
    leftPadding: 18
    rightPadding: 16

    contentItem: Row {
        spacing: 14

        Text {
            width: 26
            anchors.verticalCenter: parent.verticalCenter
            text: control.marker
            color: control.active ? control.accentColor : control.mutedColor
            font.family: "Cascadia Mono"
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: control.text
            color: control.active ? "#FFFFFF" : control.textColor
            font.family: "Segoe UI Variable Text"
            font.pixelSize: 15
            font.weight: control.active ? Font.DemiBold : Font.Medium
        }
    }

    background: Rectangle {
        radius: 12
        color: control.active ? control.activeColor
                              : control.hovered ? control.hoverColor : "transparent"

        Rectangle {
            width: 4
            height: 24
            radius: 2
            anchors.left: parent.left
            anchors.leftMargin: 2
            anchors.verticalCenter: parent.verticalCenter
            color: control.accentColor
            visible: control.active
        }

        Behavior on color {
            ColorAnimation { duration: 130 }
        }
    }
}
