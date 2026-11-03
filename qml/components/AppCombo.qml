import QtQuick
import QtQuick.Controls

ComboBox {
    id: control

    property color fillColor: "#F7F4ED"
    property color lineColor: "#DDD8CB"
    property color focusColor: "#E16B3A"
    property color textColor: "#1E2723"
    property color popupColor: "#FFFFFF"
    property color hoverColor: "#EEE9DF"

    implicitHeight: 44
    leftPadding: 14
    rightPadding: 38
    font.family: "Segoe UI Variable Text"
    font.pixelSize: 14

    contentItem: Text {
        leftPadding: 0
        rightPadding: 0
        text: control.displayText
        font: control.font
        color: control.textColor
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Text {
        x: control.width - width - 14
        anchors.verticalCenter: parent.verticalCenter
        text: "v"
        color: control.textColor
        font.family: "Cascadia Mono"
        font.pixelSize: 12
        font.weight: Font.Bold
    }

    background: Rectangle {
        radius: 11
        color: control.fillColor
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.focusColor : control.lineColor
    }

    delegate: ItemDelegate {
        width: control.width
        implicitHeight: 40
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: modelData
            color: control.textColor
            font: control.font
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            color: highlighted ? control.hoverColor : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 5
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 10, 320)
        padding: 5

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator { }
        }

        background: Rectangle {
            color: control.popupColor
            radius: 12
            border.width: 1
            border.color: control.lineColor
        }
    }
}
