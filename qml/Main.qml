import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components" as C

ApplicationWindow {
    id: root
    palette.window: root.surface
    palette.windowText: root.ink
    palette.text: root.ink
    palette.base: root.surfaceAlt
    palette.alternateBase: root.surface
    palette.button: root.surfaceAlt
    palette.buttonText: root.ink
    palette.placeholderText: root.muted
    palette.highlight: root.accent
    palette.highlightedText: "white"
    palette.light: root.line
    palette.mid: root.muted
    palette.dark: root.muted
    palette.disabled.text: root.muted
    palette.disabled.buttonText: root.muted

    component ThemedButton: Button {
        id: buttonControl
        implicitHeight: 36
        leftPadding: 12
        rightPadding: 12
        opacity: enabled ? 1 : 0.55
        contentItem: Text {
            text: buttonControl.text
            font: buttonControl.font
            color: buttonControl.highlighted ? "white" : root.ink
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            implicitWidth: 80
            implicitHeight: 36
            radius: 6
            color: buttonControl.highlighted ? root.accent : buttonControl.down ? root.line : buttonControl.hovered ? Qt.lighter(root.surfaceAlt, 1.15) : root.surfaceAlt
            border.width: buttonControl.activeFocus ? 2 : 1
            border.color: buttonControl.activeFocus || buttonControl.highlighted ? root.accent : controller.darkMode ? "#68776D" : "#A5ADA7"
        }
    }

    Dialog {
        id: resetFieldDialog
        title: "Restore imported field"
        anchors.centerIn: parent
        width: Math.min(480, root.width - 40)
        modal: true
        standardButtons: Dialog.Cancel
        property var request: ({})
        property string resetError: ""
        onOpened: { acknowledgeReset.checked = false; resetError = "" }
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: "Field: " + (resetFieldDialog.request.column || ""); font.bold: true }
            Label { Layout.fillWidth: true; text: "Edited: " + (resetFieldDialog.request.current || "(blank)"); wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; text: "Latest imported value: " + (resetFieldDialog.request.original || "(blank)"); wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; visible: resetFieldDialog.request.linked === true; text: "BPM and KOD are linked. Both tempo corrections will be reset."; wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; visible: resetFieldDialog.resetError.length > 0; text: resetFieldDialog.resetError; wrapMode: Text.WordWrap }
            CheckBox { id: acknowledgeReset; text: "I want to discard this saved correction" }
            ThemedButton {
                text: "Restore imported value"
                enabled: acknowledgeReset.checked
                onClicked: { if (tableModel.resetField(resetFieldDialog.request)) resetFieldDialog.close(); else resetFieldDialog.resetError = "The field changed or could not be saved. Close this dialog and review it again." }
            }
        }
    }

    function openTagEditor(context) {
        tagEditDialog.context = context
        Qt.callLater(function() { songTable.closeEditor(); tagEditDialog.open() })
    }

    Dialog {
        id: tagEditDialog
        objectName: "tagEditDialog"
        title: "Edit " + (context.column || "tags")
        anchors.centerIn: parent
        width: Math.min(500, root.width - 40)
        modal: true
        standardButtons: Dialog.Cancel
        property var context: ({})
        property string saveError: ""
        property var choices: tableModel.tagChoices(context.column || "")
        property var suggestions: {
            var parts = tagInput.text.split(";")
            var prefix = parts.pop().trim().toLowerCase()
            if (choices.some(function(tag) { return tag.toLowerCase() === prefix })) prefix = ""
            var selected = parts.map(function(part) { return part.trim().toLowerCase() })
            return choices.filter(function(tag) { return tag.toLowerCase().indexOf(prefix) === 0 && selected.indexOf(tag.toLowerCase()) < 0 })
        }
        property var validation: tableModel.validateTagEdit(context.column || "", tagInput.text)
        function chooseTag(tag) {
            var parts = tagInput.text.split(";")
            parts.pop()
            parts.push(tag)
            tagInput.text = parts.filter(function(part) { return part.trim().length > 0 }).map(function(part) { return part.trim() }).join("; ") + "; "
            tagDropdown.currentIndex = -1
            tagInput.forceActiveFocus()
            tagInput.cursorPosition = tagInput.text.length
        }
        function completeTag() {
            var token = tagInput.text.split(";").pop().trim().toLowerCase()
            var exact = choices.filter(function(tag) { return tag.toLowerCase() === token })
            if (exact.length > 0) chooseTag(exact[0])
            else if (suggestions.length > 0) chooseTag(tagDropdown.currentIndex >= 0 ? tagDropdown.currentText : suggestions[0])
        }
        function saveTags() {
            if (!validation.valid || controller.busy) return
            if (tableModel.saveTagEdit(context, tagInput.text)) close()
            else saveError = "The song is no longer visible or the edit could not be saved. Reopen it and try again."
        }
        onOpened: { saveError = ""; tagInput.text = context.value || ""; tagInput.forceActiveFocus(); tagInput.cursorPosition = tagInput.text.length }
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: "Type a tag prefix, then press Tab to complete it. Choose more tags from the dropdown, or separate tags with semicolons."; wrapMode: Text.WordWrap }
            TextField {
                id: tagInput
                objectName: "tagEditInput"
                Layout.fillWidth: true
                placeholderText: "Predefined tags only"
                Keys.onTabPressed: function(event) { tagEditDialog.completeTag(); event.accepted = true }
                onAccepted: tagEditDialog.saveTags()
            }
            C.AppCombo {
                id: tagDropdown
                objectName: "tagEditDropdown"
                Layout.fillWidth: true
                model: tagEditDialog.suggestions
                currentIndex: -1
                displayText: currentIndex >= 0 ? currentText : "Choose a predefined tag..."
                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                onActivated: tagEditDialog.chooseTag(currentText)
            }
            Label { Layout.fillWidth: true; text: tagEditDialog.saveError || tagEditDialog.validation.error || (tagEditDialog.choices.length ? "Save keeps these tags through Spotify updates. An empty field removes all tags." : "This list has no predefined tags for this field."); wrapMode: Text.WordWrap }
            ThemedButton { objectName: "saveTagEdit"; text: "Save tags"; enabled: tagEditDialog.validation.valid && !controller.busy; onClicked: tagEditDialog.saveTags() }
        }
    }

    Dialog {
        id: tempoDialog
        objectName: "tempoDialog"
        title: "Find and save tempo"
        anchors.centerIn: parent
        width: Math.min(root.width - 40, 460)
        modal: true
        standardButtons: Dialog.Close
        property var song: ({})
        ColumnLayout {
            anchors.fill: parent
            Label { Layout.fillWidth: true; text: String(tempoDialog.song["Track Name"] || tempoDialog.song["name"] || "Song"); wrapMode: Text.WordWrap }
            Label { Layout.fillWidth: true; text: String(tempoDialog.song["Artist(s)"] || tempoDialog.song["artists"] || ""); wrapMode: Text.WordWrap }
            ThemedButton { text: "Look up BPM online"; onClicked: controller.lookupSongTempo(tempoDialog.song) }
            Label { Layout.fillWidth: true; text: "Check the recording or count its tempo, then save a correction."; wrapMode: Text.WordWrap }
            RowLayout {
                TextField { id: songTempoValue; Layout.fillWidth: true; placeholderText: "Tempo, e.g. 30*2" }
                ComboBox { id: songTempoUnit; model: ["BPM", "KOD"] }
                ThemedButton { text: "Save"; enabled: songTempoValue.text.trim().length > 0; onClicked: { if (controller.correctSongTempo(tempoDialog.song, songTempoValue.text, songTempoUnit.currentText)) tempoDialog.close() } }
            }
            Label {
                Layout.fillWidth: true
                text: controller.tempoInputPreview(songTempoValue.text, songTempoUnit.currentText)
                wrapMode: Text.WordWrap
            }
        }
    }

    Drawer {
        id: listeningDialog
        objectName: "listeningDialog"
        edge: Qt.RightEdge
        width: Math.min(540, root.width * 0.82)
        height: root.height
        modal: false
        dim: false
        closePolicy: Popup.CloseOnEscape
        padding: 16
        palette.windowText: root.ink
        palette.text: root.ink
        palette.buttonText: root.ink
        palette.base: root.surfaceAlt
        palette.button: root.surfaceAlt
        palette.highlight: root.accent
        background: Rectangle { color: root.surface; border.color: root.line; border.width: 1 }
        property bool history: false
        property bool live: true
        function selectQueueMode(historyMode, liveMode) {
            history = historyMode
            live = liveMode
            controller.listeningMode(history ? "history" : live ? "live" : "queue")
            controller.setLiveQueueActive(visible && live && !history)
        }
        onOpened: selectQueueMode(history, live)
        onClosed: controller.setLiveQueueActive(false)
        contentItem: ColumnLayout {
            spacing: 10
            RowLayout {
                Layout.fillWidth: true
                Label { text: "Queue / History"; font.pixelSize: 20; font.bold: true; Layout.fillWidth: true }
                ThemedButton { objectName: "closeQueueDrawer"; text: "Close"; onClicked: listeningDialog.close() }
            }
            ProgressBar {
                Layout.fillWidth: true
                visible: controller.working
                indeterminate: !controller.taggedUpdateRunning || controller.updateProgress.total <= 0
                            from: 0
                            to: Math.max(1, controller.updateProgress.total)
                            value: controller.updateProgress.completed
                palette.highlight: root.accent
            }
            Label {
                visible: controller.working
                text: controller.taggedUpdateRunning
                                  ? controller.updateProgress.stage + (controller.updateProgress.total > 0 ? " " + controller.updateProgress.completed + "/" + controller.updateProgress.total : "") + " | " + controller.updateProgress.detail
                                  : controller.statusMessage
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
            }
            RowLayout {
                Layout.fillWidth: true
                ThemedButton { text: "Spotify queue"; Layout.fillWidth: true; highlighted: listeningDialog.live && !listeningDialog.history; onClicked: listeningDialog.selectQueueMode(false, true) }
                ThemedButton { text: "Local queue"; Layout.fillWidth: true; highlighted: !listeningDialog.live && !listeningDialog.history; onClicked: listeningDialog.selectQueueMode(false, false) }
                ThemedButton { text: "History"; Layout.fillWidth: true; onClicked: listeningDialog.selectQueueMode(true, false) }
            }
            RowLayout {
                visible: listeningDialog.history
                Layout.fillWidth: true
                ThemedButton { text: "Refresh history"; enabled: !controller.busy; onClicked: controller.refreshListeningHistory() }
                ThemedButton { text: "Empty history"; enabled: !controller.busy && controller.listeningRows.length > 0; onClicked: controller.clearListeningHistory() }
            }
            ColumnLayout {
                visible: !listeningDialog.history && !listeningDialog.live
                Layout.fillWidth: true
                ThemedButton { text: "Copy Spotify queue locally"; Layout.fillWidth: true; enabled: !controller.busy; onClicked: controller.refreshQueuePlan() }
                ThemedButton { text: "Send local songs to Spotify queue"; Layout.fillWidth: true; enabled: !controller.busy; onClicked: controller.sendLocalPlanToQueue() }
            }
            ColumnLayout {
                visible: listeningDialog.live && !listeningDialog.history
                Layout.fillWidth: true
                RowLayout {
                    Layout.fillWidth: true
                    ThemedButton { text: controller.liveQueueState.refreshing ? "Refreshing..." : "Refresh now"; enabled: !controller.liveQueueState.refreshing; onClicked: controller.refreshLiveQueue() }
                    Label {
                        objectName: "liveQueueStatus"
                        Layout.fillWidth: true
                        text: controller.liveQueueState.stale ? "Queue stale: " + (controller.liveQueueState.error || "Waiting for Spotify...") : "Updated " + controller.liveQueueState.updated + " | " + controller.listeningRows.length + " upcoming songs | refreshes every 5 seconds"
                        wrapMode: Text.WordWrap
                    }
                }
                Label {
                    Layout.fillWidth: true
                    text: controller.liveQueueState.current.name ? (controller.liveQueueState.stale ? "Last reported song: " : "Currently playing: ") + controller.liveQueueState.current.name + " - " + controller.liveQueueState.current.subtitle : "No currently playing song reported"
                    wrapMode: Text.WordWrap
                }
            }
            Label {
                text: listeningDialog.history ? "Saved plays in chronological order. Refresh imports Spotify's latest 50 plays; timestamps are UTC."
                      : listeningDialog.live ? "Upcoming songs in Spotify order. This view is read-only and does not replace your local queue. If a refresh fails, the last received queue stays visible and is marked stale."
                      : "Queue adds songs here and to Spotify when connected. Reordering here changes the local queue. KOD uses BPM / 2 when that is at least 60; otherwise BPM."
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            RowLayout {
                Layout.fillWidth: true
                CheckBox { id: showQueuePlot; text: "Tempo graph"; checked: false }
                Item { Layout.fillWidth: true }
                ComboBox { id: tempoUnit; model: ["KOD", "BPM"]; onCurrentTextChanged: tempoPlot.requestPaint() }
            }
            Canvas {
                id: tempoPlot
                visible: showQueuePlot.checked
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(180, root.height * 0.22)
                onWidthChanged: requestPaint()
                onHeightChanged: requestPaint()
                Connections { target: controller; function onListeningChanged() { tempoPlot.requestPaint() } function onThemeChanged() { tempoPlot.requestPaint() } function onAccentChanged() { tempoPlot.requestPaint() } }
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    ctx.fillStyle = root.surface.toString(); ctx.fillRect(0, 0, width, height)
                    var rows = controller.listeningRows
                    var vals = rows.map(function(r) {
                        var v = tempoUnit.currentText === "BPM" ? Number(r.bpm) || Number(r.kod)*2 : Number(r.kod) || (Number(r.bpm) >= 120 ? Number(r.bpm)/2 : Number(r.bpm))
                        return isFinite(v) && v > 0 ? v : null
                    })
                    var known = vals.filter(function(v) { return v !== null })
                    var min = known.length ? Math.min(...known) - 5 : 0
                    var max = known.length ? Math.max(...known) + 5 : 10
                    var span = max - min
                    var left = 50, top = 22, w = width - 75, h = height - 60
                    ctx.font = "11px sans-serif"; ctx.lineWidth = 1
                    for (var tick = 0; tick <= 4; tick++) {
                        var y = top + h - tick*h/4
                        ctx.strokeStyle = root.line.toString(); ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left+w, y); ctx.stroke()
                        ctx.fillStyle = root.ink.toString(); ctx.fillText(String(Number((min + tick*span/4).toFixed(1))), 8, y+4)
                    }
                    ctx.fillText(tempoUnit.currentText, 8, 13)
                    ctx.fillText("Song order (missing tempos leave gaps)", left, height-6)
                    var previous = null
                    vals.forEach(function(v, i) {
                        var x = left + (vals.length > 1 ? i*w/(vals.length-1) : w/2)
                        if (v === null) { previous = null; return }
                        var y = top+h-(v-min)*h/span
                        ctx.strokeStyle = root.accent.toString(); ctx.lineWidth = 2
                        if (previous) { ctx.beginPath(); ctx.moveTo(previous.x, previous.y); ctx.lineTo(x,y); ctx.stroke() }
                        ctx.fillStyle = root.accent.toString(); ctx.beginPath(); ctx.arc(x,y,4,0,Math.PI*2); ctx.fill()
                        if (vals.length <= 25) { ctx.fillStyle = root.ink.toString(); ctx.fillText(String(i+1), x-3, top+h+17) }
                        previous = {x:x, y:y}
                    })
                    if (!rows.length) { ctx.fillStyle = root.ink.toString(); ctx.fillText("No songs yet", left+20, top+40) }
                }
            }
            ListView {
                id: listeningList
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: controller.listeningRows
                ScrollBar.vertical: ScrollBar {}
                spacing: 8
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: listeningList.width
                    height: listeningDialog.history || !listeningDialog.live ? 134 : 104
                    radius: 8
                    color: root.surfaceAlt
                    border.color: root.line
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: 4
                        Label {
                            text: (index + 1) + ". " + modelData.name + " - " + modelData.artists
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            font.bold: true
                        }
                        Label {
                            text: listeningDialog.history ? String(modelData.played_at || "") : (modelData.queue_status || "Local queue")
                            Layout.fillWidth: true
                            font.pixelSize: 10
                            color: root.muted
                            elide: Text.ElideRight
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { Layout.fillWidth: true; text: "BPM " + (modelData.bpm || (Number(modelData.kod) * 2) || "?") + " / KOD " + (modelData.kod || "?"); elide: Text.ElideRight }
                            ThemedButton {
                                text: "Play"
                                enabled: !controller.busy && String(modelData.uri || "").length > 0
                                onClicked: controller.spotifyPlayback("play", modelData.uri)
                            }
                            ThemedButton {
                                text: "Correct tempo"
                                onClicked: { tempoDialog.song = modelData; songTempoUnit.currentIndex = modelData.kod ? 1 : 0; songTempoValue.text = String(modelData.kod || modelData.bpm || ""); tempoDialog.open() }
                            }
                        }
                        RowLayout {
                            visible: !listeningDialog.live || listeningDialog.history
                            ThemedButton { text: "Up"; visible: !listeningDialog.history; onClicked: controller.movePlanSong(index, -1) }
                            ThemedButton { text: "Down"; visible: !listeningDialog.history; onClicked: controller.movePlanSong(index, 1) }
                            Item { Layout.fillWidth: true }
                            ThemedButton {
                                text: listeningDialog.history ? "Remove entry" : "Remove locally"
                                enabled: !controller.busy
                                onClicked: listeningDialog.history ? controller.removeHistorySong(index) : controller.removePlanSong(index)
                            }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: controller.listeningRows.length === 0; text: "No songs in this queue"; color: root.muted }
            }
            RowLayout {
                TextField { id: listeningPlaylistName; placeholderText: "Playlist name"; Layout.fillWidth: true }
                ThemedButton { text: "Create playlist"; enabled: !controller.busy && controller.listeningRows.length > 0 && listeningPlaylistName.text.trim().length > 0; onClicked: controller.exportListeningPlaylist(listeningPlaylistName.text) }
            }
            Label { text: "Corrections are saved locally and survive Spotify updates. Playlist export keeps this order and repeated plays."; wrapMode: Text.WordWrap; Layout.fillWidth: true }
        }
    }

    Dialog {
        id: errorReportDialog
        title: "Saved error reports (UTC)"
        anchors.centerIn: parent
        width: Math.min(root.width - 40, 950)
        height: Math.min(root.height - 40, 650)
        modal: true
        standardButtons: Dialog.Close
        ColumnLayout {
            anchors.fill: parent
            RowLayout {
                Label { text: controller.errorReports.length + " saved reports"; Layout.fillWidth: true }
                ThemedButton { text: "Export reports"; onClicked: controller.exportErrorReports() }
                ThemedButton {
                    text: "Empty error list"
                    enabled: controller.errorReports.length > 0
                    onClicked: controller.clearErrorReports()
                }
            }
            ListView {
                id: errorReportList
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                model: controller.errorReports
                spacing: 12
                ScrollBar.vertical: ScrollBar {}
                delegate: Column {
                    required property var modelData
                    width: errorReportList.width
                    spacing: 5
                    Label { text: modelData.time + " / " + modelData.action; font.bold: true; width: parent.width; wrapMode: Text.WordWrap }
                    TextArea { text: modelData.message; width: parent.width; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; background: Rectangle { color: root.surfaceAlt; radius: 6 } }
                }
                Label { anchors.centerIn: parent; visible: controller.errorReports.length === 0; text: "No errors recorded yet" }
            }
        }
    }

    function setting(key, fallbackValue) {
        var value = controller.settingsMap[key]
        return value === undefined || value === null ? fallbackValue : value
    }

    function accentFor(name) {
        if (name === "Ocean") return "#247C8A"
        if (name === "Golden") return "#B7791F"
        if (name === "Berry") return "#B94B67"
        return "#E16B3A"
    }

    function fileName(path) {
        if (!path) return "No list selected"
        var pieces = String(path).split(/[\\/]/)
        return pieces[pieces.length - 1]
    }

    function comboIndex(combo, value) {
        var index = combo.find(String(value))
        return index >= 0 ? index : 0
    }

    readonly property color canvas: controller.darkMode ? "#171B19" : "#ECE8DE"
    readonly property color surface: controller.darkMode ? "#222825" : "#FFFEFA"
    readonly property color surfaceAlt: controller.darkMode ? "#2B322E" : "#F5F1E8"
    readonly property color line: controller.darkMode ? "#39413C" : "#D9D3C6"
    readonly property color ink: controller.darkMode ? "#F2F2EC" : "#202724"
    readonly property color muted: controller.darkMode ? "#A8B0AA" : "#6D756F"
    readonly property color accent: accentFor(controller.accentName)
    readonly property color sidebar: controller.darkMode ? "#101311" : "#19201D"
    readonly property color sidebarText: "#DDE2DD"
    readonly property color danger: "#B84A3C"

    property int currentPage: 0
    property int editRow: -1
    property int editColumn: -1

    width: Number(setting("window_width", 1480))
    height: Number(setting("window_height", 920))
    visibility: Window.Maximized
    minimumWidth: 1080
    minimumHeight: 700
    visible: true
    title: "SpareTime Studio"
    color: canvas

    onClosing: controller.shutdown(width, height)

    component MicroLabel: Text {
        color: root.muted
        font.family: "Cascadia Mono"
        font.pixelSize: 10
        font.letterSpacing: 1.3
        font.capitalization: Font.AllUppercase
    }

    component FieldLabel: Text {
        color: root.ink
        font.family: "Segoe UI Variable Text"
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }

    component PageHeading: Column {
        property string label: ""
        property string headline: ""
        property string description: ""
        spacing: 4

        MicroLabel { text: parent.label }
        Text {
            text: parent.headline
            color: root.ink
            font.family: "Segoe UI Variable Display"
            font.pixelSize: 29
            font.weight: Font.DemiBold
        }
        Text {
            text: parent.description
            color: root.muted
            font.family: "Segoe UI Variable Text"
            font.pixelSize: 14
        }
    }

    footer: ToolBar {
        id: playbackBar
        implicitHeight: 78
        background: Rectangle { color: root.sidebar }
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16; anchors.rightMargin: 16
            spacing: 16
            ColumnLayout {
                Layout.fillWidth: true
                objectName: "playbackTrackInfo"
                Layout.preferredWidth: 320
                Layout.minimumWidth: 240
                spacing: 3
                Label {
                    Layout.fillWidth: true
                    text: controller.playbackState.stale ? "Playback unavailable" : controller.playbackState.track_name || "No active Spotify playback"
                    color: root.sidebarText
                    font.bold: true
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: controller.playbackState.artists || ""
                    color: "#AAB3AD"
                    elide: Text.ElideRight
                }
                Label {
                    Layout.fillWidth: true
                    text: [controller.playbackState.album, controller.playbackState.device_name].filter(function(value) { return value }).join(" / ")
                    color: "#AAB3AD"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                }
            }
            RowLayout {
                spacing: 8
            C.AppButton { horizontalPadding: 10; text: "Prev"; enabled: !controller.busy; onClicked: controller.spotifyPlayback("previous", ""); quietColor: "#29312D"; textColor: "white" }
            C.AppButton { horizontalPadding: 10;
                text: String(controller.playbackState.is_playing).toLowerCase() === "true" ? "Pause" : "Play"
                enabled: !controller.busy
                kind: "primary"; accentColor: root.accent
                onClicked: controller.spotifyTogglePlayback()
            }
            C.AppButton { horizontalPadding: 10; text: "Next"; enabled: !controller.busy; onClicked: controller.spotifyPlayback("next", ""); quietColor: "#29312D"; textColor: "white" }
            C.AppButton { horizontalPadding: 10;
                text: "Fade skip"
                enabled: !controller.busy
                onClicked: controller.spotifyFadeSkip()
                quietColor: "#29312D"; textColor: "white"
                ToolTip.visible: hovered
                ToolTip.text: "Fade out over 5 seconds, skip, then restore volume"
            }
            C.AppButton { horizontalPadding: 10;
                text: "Fade pause"
                enabled: !controller.busy
                onClicked: controller.spotifyFadePause()
                quietColor: "#29312D"; textColor: "white"
                ToolTip.visible: hovered
                ToolTip.text: "Fade out over 5 seconds, pause, then restore volume for Play"
            }
            C.AppButton { horizontalPadding: 10; text: "Refresh"; onClicked: controller.spotifyNowPlaying(); quietColor: "#29312D"; textColor: "white" }
            }
            Item {
                Layout.fillWidth: true
                Layout.preferredWidth: 320
                Layout.minimumWidth: rightPlaybackActions.implicitWidth
                Layout.fillHeight: true
                RowLayout {
                    id: rightPlaybackActions
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    C.AppButton {
                        text: "History / Queue"
                        horizontalPadding: 10
                        quietColor: "#29312D"; textColor: "white"
                        onClicked: listeningDialog.open()
                    }
                    C.AppButton {
                        text: "Connect"
                        horizontalPadding: 10
                        enabled: !controller.busy
                        quietColor: "#29312D"; textColor: "white"
                        onClicked: controller.spotifyAuthorize()
                    }
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: root.width < 1240 ? 196 : 224
            color: root.sidebar

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 8

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 84

                    Rectangle {
                        width: 42
                        height: 42
                        radius: 13
                        color: root.accent
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter

                        Image {
                            anchors.centerIn: parent
                            width: 32
                            height: 32
                            source: "../assets/logo-light.svg"
                            sourceSize.width: 96
                            sourceSize.height: 96
                            fillMode: Image.PreserveAspectFit
                            smooth: true
                        }
                    }

                    Column {
                        anchors.left: parent.left
                        anchors.leftMargin: 56
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1
                        Text {
                            text: "SpareTime"
                            color: "#FFFFFF"
                            font.family: "Segoe UI Variable Display"
                            font.pixelSize: 19
                            font.weight: Font.DemiBold
                        }
                        Text {
                            text: "MUSIC STUDIO"
                            color: "#87918B"
                            font.family: "Cascadia Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.2
                        }
                    }
                }

                C.NavItem {
                    Layout.fillWidth: true
                    text: "Library"
                    marker: "01"
                    active: root.currentPage === 0
                    accentColor: root.accent
                    onClicked: root.currentPage = 0
                }
                C.NavItem {
                    Layout.fillWidth: true
                    text: "Edit lists"
                    marker: "02"
                    active: root.currentPage === 1
                    accentColor: root.accent
                    onClicked: root.currentPage = 1
                }
                C.NavItem {
                    Layout.fillWidth: true
                    text: "Spotify"
                    marker: "03"
                    active: root.currentPage === 2
                    accentColor: root.accent
                    onClicked: root.currentPage = 2
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: controller.working ? 110 : 92
                    radius: 14
                    color: "#222A26"

                    Column {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 7
                        Row {
                            spacing: 8
                            Rectangle {
                                width: 8
                                height: 8
                                radius: 4
                                anchors.verticalCenter: parent.verticalCenter
                                color: controller.working ? root.accent : "#6CB486"
                            }
                            Text {
                                text: controller.working ? "WORKING" : "READY"
                                color: root.sidebarText
                                font.family: "Cascadia Mono"
                                font.pixelSize: 10
                                font.weight: Font.Bold
                            }
                        }
                        Text {
                            width: parent.width
                            text: controller.taggedUpdateRunning
                                  ? controller.updateProgress.stage + (controller.updateProgress.total > 0 ? " " + controller.updateProgress.completed + "/" + controller.updateProgress.total : "") + " | " + controller.updateProgress.detail
                                  : controller.statusMessage
                            color: "#9EA8A2"
                            font.family: "Segoe UI Variable Text"
                            font.pixelSize: 12
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                        ProgressBar {
                            width: parent.width
                            height: 6
                            visible: controller.working
                            indeterminate: !controller.taggedUpdateRunning || controller.updateProgress.total <= 0
                            from: 0
                            to: Math.max(1, controller.updateProgress.total)
                            value: controller.updateProgress.completed
                            palette.highlight: root.accent
                            background: Rectangle {
                                implicitHeight: 6
                                radius: 3
                                color: "#39413C"
                            }
                        }
                    }
                }

                C.AppButton {
                    Layout.fillWidth: true
                    text: "Error reports (" + controller.errorReports.length + ")"
                    quietColor: "#222A26"; textColor: root.sidebarText
                    onClicked: errorReportDialog.open()
                }

                ThemedButton {
                    id: settingsButton
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    text: "Settings"
                    onClicked: settingsDrawer.open()
                    contentItem: Text {
                        text: settingsButton.text
                        color: root.sidebarText
                        font.family: "Segoe UI Variable Text"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignLeft
                        verticalAlignment: Text.AlignVCenter
                        leftPadding: 12
                    }
                    background: Rectangle {
                        radius: 11
                        color: settingsButton.hovered ? "#29312D" : "transparent"
                        border.width: 1
                        border.color: "#303A35"
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            StackLayout {
                anchors.fill: parent
                currentIndex: root.currentPage

                Item {
                    id: libraryPage

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 24
                        anchors.rightMargin: 24
                        anchors.topMargin: 20
                        anchors.bottomMargin: 20
                        spacing: 14

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 16

                            PageHeading {
                                Layout.fillWidth: true
                                label: "Collection workspace"
                                headline: "Your dance library"
                                description: "Filter, sort, edit, color, and export without changing the source."
                            }

                            C.AppButton {
                                text: "History / Queue"
                                onClicked: listeningDialog.open()
                                quietColor: root.surfaceAlt; textColor: root.ink
                            }
                            C.AppButton {
                                text: controller.taggedUpdateRunning ? "Updating Spotify..." : "Update from Spotify"
                                enabled: !controller.busy && !controller.taggedUpdateRunning
                                quietColor: root.surfaceAlt
                                hoverColor: root.line
                                textColor: root.ink
                                onClicked: controller.spotifyBuildTaggedList()
                                ToolTip.visible: hovered
                                ToolTip.text: "Rebuild all songs and tags from Stil:, Event:, and Tema: playlists"
                            }
                            C.AppButton {
                                text: "Open list"
                                kind: "primary"
                                accentColor: root.accent
                                onClicked: controller.openTableDialog()
                            }
                            C.AppButton {
                                text: "Export view"
                                quietColor: root.surfaceAlt
                                hoverColor: root.line
                                textColor: root.ink
                                lineColor: root.line
                                onClicked: controller.exportCurrentView()
                            }
                        }

                        C.Panel {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 76
                            fillColor: root.surface
                            lineColor: root.line

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 18
                                anchors.rightMargin: 18
                                spacing: 14

                                Rectangle {
                                    width: 42
                                    height: 42
                                    radius: 12
                                    color: root.surfaceAlt
                                    border.width: 1
                                    border.color: root.line
                                    Text {
                                        anchors.centerIn: parent
                                        text: "XLS"
                                        color: root.accent
                                        font.family: "Cascadia Mono"
                                        font.pixelSize: 10
                                        font.weight: Font.Bold
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 1
                                    Text {
                                        Layout.fillWidth: true
                                        text: tableModel.currentFileName
                                        color: root.ink
                                        font.family: "Segoe UI Variable Text"
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideMiddle
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: tableModel.currentFile
                                        color: root.muted
                                        font.family: "Cascadia Mono"
                                        font.pixelSize: 10
                                        elide: Text.ElideMiddle
                                    }
                                }

                                Text {
                                    text: tableModel.summaryText
                                    color: root.muted
                                    font.family: "Segoe UI Variable Text"
                                    font.pixelSize: 13
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            CheckBox {
                                objectName: "missingTempoFilter"
                                text: "Missing tempo (" + tableModel.missingTempoCount + ")"
                                checked: tableModel.missingTempoOnly
                                onToggled: tableModel.setMissingTempoOnly(checked)
                            }
                            Label {
                                Layout.fillWidth: true
                                text: tableModel.missingTempoOnly ? "Use Find tempo beside a song to look up BPM and save a correction. Other filters still apply." : ""
                                color: root.muted
                                wrapMode: Text.WordWrap
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            C.TextBox {
                                id: filterInput
                                Layout.fillWidth: true
                                Layout.maximumWidth: 340
                                placeholderText: "Filter songs containing..."
                                text: tableModel.filterText
                                fillColor: root.surface
                                lineColor: root.line
                                focusColor: root.accent
                                textColor: root.ink
                                placeholderColor: root.muted
                                onAccepted: tableModel.setFilter(filterColumn.currentText, text, false)
                            }

                            C.AppCombo {
                                id: filterColumn
                                Layout.preferredWidth: 180
                                model: tableModel.filterColumns
                                fillColor: root.surface
                                lineColor: root.line
                                focusColor: root.accent
                                textColor: root.ink
                                popupColor: root.surface
                                hoverColor: root.surfaceAlt
                                Component.onCompleted: currentIndex = root.comboIndex(filterColumn, tableModel.filterColumn)
                            }

                            C.AppButton {
                                text: "Apply"
                                kind: "primary"
                                accentColor: root.accent
                                horizontalPadding: 16
                                onClicked: tableModel.setFilter(filterColumn.currentText, filterInput.text, false)
                            }
                            C.AppButton {
                                text: "Clear"
                                kind: "outline"
                                textColor: root.ink
                                lineColor: root.line
                                hoverColor: root.surfaceAlt
                                horizontalPadding: 14
                                onClicked: {
                                    filterInput.text = ""
                                    tableModel.clearFilter()
                                }
                            }

                            Item { Layout.fillWidth: true }

                            C.AppButton {
                                id: sortButton
                                text: tableModel.sortColumn ? "Sort: " + tableModel.sortColumn : "Sort"
                                quietColor: root.surface
                                hoverColor: root.surfaceAlt
                                textColor: root.ink
                                lineColor: root.line
                                onClicked: sortPopup.open()
                            }
                            C.AppButton {
                                id: columnsButton
                                text: "Columns"
                                quietColor: root.surface
                                hoverColor: root.surfaceAlt
                                textColor: root.ink
                                lineColor: root.line
                                onClicked: columnsPopup.open()
                            }
                            C.AppButton {
                                id: tagsButton
                                visible: tableModel.tagFiltersAvailable
                                text: tableModel.isolateTags ? "Tags (" + tableModel.isolatedTagCount + " selected)" : tableModel.hiddenTagCount > 0
                                      ? "Tags (" + tableModel.hiddenTagCount + " hidden)"
                                      : "Tags"
                                quietColor: root.surface
                                hoverColor: root.surfaceAlt
                                textColor: root.ink
                                lineColor: root.line
                                onClicked: tagsPopup.open()
                            }
                            C.AppButton {
                                id: colorsButton
                                text: "Colors"
                                quietColor: root.surface
                                hoverColor: root.surfaceAlt
                                textColor: root.ink
                                lineColor: root.line
                                onClicked: colorsPopup.open()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            CheckBox {
                                id: kodRangeCheck
                                text: "Limit KOD"
                                checked: tableModel.kodRangeEnabled
                                palette.text: root.ink
                                onClicked: tableModel.setKodRange(checked, kodRange.first.value, kodRange.second.value)
                            }
                            Label { text: "From " + kodRange.first.value.toFixed(1); color: root.ink }
                            RangeSlider {
                                id: kodRange
                                Layout.fillWidth: true
                                from: 0; to: Math.max(200, tableModel.kodMaximum)
                                stepSize: 0.5
                                first.value: tableModel.kodMinimum
                                second.value: tableModel.kodMaximum
                                first.onMoved: tableModel.setKodRange(kodRangeCheck.checked, first.value, second.value)
                                second.onMoved: tableModel.setKodRange(kodRangeCheck.checked, first.value, second.value)
                                palette.highlight: root.accent
                            }
                            Label { text: "To " + kodRange.second.value.toFixed(1); color: root.ink }
                            C.AppButton {
                                text: "Reset KOD"
                                quietColor: root.surface; textColor: root.ink
                                onClicked: tableModel.setKodRange(false, 0, 200)
                            }
                        }

                        Flickable {
                            Layout.fillWidth: true
                            Layout.preferredHeight: tableModel.legendEntries.length > 0 ? 36 : 0
                            visible: tableModel.legendEntries.length > 0
                            contentWidth: legendRow.width
                            contentHeight: height
                            clip: true

                            Row {
                                id: legendRow
                                spacing: 7
                                Repeater {
                                    model: tableModel.legendEntries
                                    delegate: Rectangle {
                                        required property var modelData
                                        height: 30
                                        width: legendText.implicitWidth + 34
                                        radius: 15
                                        color: modelData.color
                                        border.width: 1
                                        border.color: Qt.darker(modelData.color, 1.08)
                                        Text {
                                            id: legendText
                                            anchors.centerIn: parent
                                            text: modelData.label
                                            color: modelData.foreground
                                            font.family: "Segoe UI Variable Text"
                                            font.pixelSize: 11
                                            font.weight: Font.DemiBold
                                        }
                                    }
                                }
                            }
                        }

                        C.Panel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            fillColor: root.surface
                            lineColor: root.line
                            cornerRadius: 15
                            clip: true

                            GridLayout {
                                anchors.fill: parent
                                columns: 2
                                rows: 2
                                columnSpacing: 0
                                rowSpacing: 0

                                Rectangle {
                                    Layout.row: 0
                                    Layout.column: 0
                                    Layout.preferredWidth: 48
                                    Layout.preferredHeight: 42
                                    color: root.sidebar
                                    Text {
                                        anchors.centerIn: parent
                                        text: "#"
                                        color: "#AAB3AD"
                                        font.family: "Cascadia Mono"
                                        font.pixelSize: 10
                                    }
                                }

                                HorizontalHeaderView {
                                    id: horizontalHeader
                                    Layout.row: 0
                                    Layout.column: 1
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 42
                                    syncView: songTable
                                    clip: true
                                    resizableColumns: true

                                    delegate: Rectangle {
                                        required property int index
                                        implicitWidth: tableModel.preferredColumnWidth(index)
                                        implicitHeight: 42
                                        color: root.sidebar
                                        border.width: 1
                                        border.color: "#303834"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 10
                                            spacing: 6
                                            Text {
                                                Layout.fillWidth: true
                                                text: tableModel.visibleColumns[index] || ""
                                                color: "#F4F5F1"
                                                font.family: "Segoe UI Variable Text"
                                                font.pixelSize: 12
                                                font.weight: Font.DemiBold
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                visible: tableModel.sortColumn === (tableModel.visibleColumns[index] || "")
                                                text: tableModel.sortAscending ? "A-Z" : "Z-A"
                                                color: root.accent
                                                font.family: "Cascadia Mono"
                                                font.pixelSize: 9
                                                font.weight: Font.Bold
                                            }
                                        }

                                        TapHandler {
                                            cursorShape: Qt.PointingHandCursor
                                            onTapped: tableModel.sortByColumn(index)
                                        }
                                    }
                                }

                                VerticalHeaderView {
                                    id: verticalHeader
                                    Layout.row: 1
                                    Layout.column: 0
                                    Layout.preferredWidth: 48
                                    Layout.fillHeight: true
                                    syncView: songTable
                                    clip: true

                                    delegate: Rectangle {
                                        required property int index
                                        implicitWidth: 48
                                        implicitHeight: songTable.rowHeightProvider(index)
                                        color: root.surfaceAlt
                                        border.width: 1
                                        border.color: root.line
                                        Text {
                                            anchors.centerIn: parent
                                            text: index + 1
                                            color: root.muted
                                            font.family: "Cascadia Mono"
                                            font.pixelSize: 9
                                        }
                                    }
                                }

                                TableView {
                                    id: songTable
                                    objectName: "songTable"
                                    Layout.row: 1
                                    Layout.column: 1
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    model: tableModel
                                    boundsBehavior: Flickable.StopAtBounds
                                    reuseItems: true
                                    resizableColumns: true
                                    columnSpacing: 0
                                    rowSpacing: 0
                                    columnWidthProvider: function(column) {
                                        var explicitWidth = explicitColumnWidth(column)
                                        return explicitWidth >= 0 ? explicitWidth : tableModel.preferredColumnWidth(column)
                                    }
                                    rowHeightProvider: function(row) {
                                        var density = root.setting("viewer_density", "Comfortable")
                                        if (density === "Compact") return 32
                                        if (density === "Spacious") return 48
                                        return 40
                                    }

                                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                    delegate: Rectangle {
                                        id: cell
                                        required property int row
                                        required property int column
                                        required property string display
                                        required property string cellBackground
                                        required property string cellForeground
                                        required property bool numericCell
                                        required property bool cellEdited
                                        required property bool current
                                        required property bool selected
                                        required property bool editing
                                        readonly property bool isTrackCell: String(tableModel.visibleColumns[column] || "").toLowerCase() === "track name"

                                        implicitWidth: tableModel.preferredColumnWidth(column)
                                        implicitHeight: songTable.rowHeightProvider(row)
                                        color: selected ? (controller.darkMode ? Qt.darker(root.accent, 1.65) : Qt.lighter(root.accent, 1.55)) : cellBackground
                                        border.width: current ? 2 : 1
                                        border.color: current ? root.accent : root.line

                                        Text {
                                            anchors.fill: parent
                                            anchors.leftMargin: 10
                                            anchors.rightMargin: cell.isTrackCell ? 72 : 10
                                            text: cell.display
                                            color: cell.cellForeground
                                            font.family: cell.numericCell ? "Cascadia Mono" : "Segoe UI Variable Text"
                                            font.pixelSize: 12
                                            horizontalAlignment: cell.numericCell ? Text.AlignRight : Text.AlignLeft
                                            verticalAlignment: Text.AlignVCenter
                                            elide: Text.ElideRight
                                        }

                                        C.AppButton {
                                            anchors.right: parent.right
                                            anchors.rightMargin: 6
                                            anchors.verticalCenter: parent.verticalCenter
                                            height: 28
                                            visible: cell.isTrackCell
                                            enabled: !controller.busy
                                            text: tableModel.missingTempoOnly ? "Find tempo" : "Queue"
                                            horizontalPadding: 9
                                            quietColor: root.surfaceAlt
                                            hoverColor: root.accent
                                            textColor: root.ink
                                            onClicked: {
                                                if (tableModel.missingTempoOnly) {
                                                    tempoDialog.song = tableModel.rowRecord(cell.row)
                                                    songTempoValue.text = ""
                                                    tempoDialog.open()
                                                } else controller.spotifyQueueTableRow(cell.row)
                                            }
                                        }

                                        Rectangle {
                                            width: 9; height: 9; radius: 4.5
                                            anchors.left: parent.left; anchors.top: parent.top
                                            anchors.margins: 2
                                            visible: cell.cellEdited
                                            color: root.accent
                                            border.color: cell.cellForeground
                                            MouseArea {
                                                id: editedFieldHover
                                                anchors.fill: parent
                                                anchors.margins: -4
                                                hoverEnabled: true
                                                onClicked: { resetFieldDialog.request = tableModel.fieldResetPreview(cell.row, cell.column); resetFieldDialog.open() }
                                            }
                                            ToolTip.visible: editedFieldHover.containsMouse
                                            ToolTip.text: "Edited locally. Click to review or restore the imported value."
                                        }

                                        TableView.editDelegate: C.TextBox {
                                            anchors.fill: parent
                                            text: cell.display
                                            fillColor: root.surface
                                            lineColor: root.accent
                                            focusColor: root.accent
                                            textColor: root.ink
                                            Component.onCompleted: {
                                                var columnName = String(tableModel.visibleColumns[cell.column] || "")
                                                if (["style", "theme"].indexOf(columnName.toLowerCase()) >= 0) {
                                                    root.openTagEditor(tableModel.tagEditContext(cell.row, cell.column))
                                                } else {
                                                    forceActiveFocus()
                                                    selectAll()
                                                }
                                            }
                                            TableView.onCommit: tableModel.editCell(cell.row, cell.column, text)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Popup {
                        id: sortPopup
                        width: 320
                        padding: 18
                        x: libraryPage.width - width - 24
                        y: 170
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Rectangle {
                            color: root.surface
                            radius: 16
                            border.width: 1
                            border.color: root.line
                        }
                        contentItem: Column {
                            spacing: 12
                            FieldLabel { text: "Sort the current view" }
                            C.AppCombo {
                                id: sortColumnCombo
                                width: parent.width
                                model: tableModel.allColumns
                                fillColor: root.surfaceAlt
                                lineColor: root.line
                                focusColor: root.accent
                                textColor: root.ink
                                popupColor: root.surface
                                hoverColor: root.surfaceAlt
                            }
                            Row {
                                spacing: 8
                                C.AppButton {
                                    text: "Ascending"
                                    kind: "primary"
                                    accentColor: root.accent
                                    onClicked: {
                                        tableModel.setSort(sortColumnCombo.currentText, true)
                                        sortPopup.close()
                                    }
                                }
                                C.AppButton {
                                    text: "Descending"
                                    quietColor: root.surfaceAlt
                                    hoverColor: root.line
                                    textColor: root.ink
                                    onClicked: {
                                        tableModel.setSort(sortColumnCombo.currentText, false)
                                        sortPopup.close()
                                    }
                                }
                            }
                            C.AppButton {
                                text: "Clear sort"
                                kind: "outline"
                                width: parent.width
                                textColor: root.ink
                                lineColor: root.line
                                hoverColor: root.surfaceAlt
                                onClicked: {
                                    tableModel.clearSort()
                                    sortPopup.close()
                                }
                            }
                        }
                    }

                    Popup {
                        id: columnsPopup
                        width: 310
                        height: Math.min(520, columnList.contentHeight + 96)
                        padding: 14
                        x: libraryPage.width - width - 24
                        y: 170
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Rectangle {
                            color: root.surface
                            radius: 16
                            border.width: 1
                            border.color: root.line
                        }
                        contentItem: ColumnLayout {
                            spacing: 8
                            RowLayout {
                                Layout.fillWidth: true
                                FieldLabel { Layout.fillWidth: true; text: "Visible columns" }
                                ThemedButton {
                                    id: showAllButton
                                    text: "Show all"
                                    onClicked: tableModel.showAllColumns()
                                    contentItem: Text {
                                        text: showAllButton.text
                                        color: root.accent
                                        font.family: "Segoe UI Variable Text"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    background: Item { }
                                }
                            }
                            ListView {
                                id: columnList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                clip: true
                                model: tableModel.columnStates
                                spacing: 2
                                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                delegate: CheckBox {
                                    required property var modelData
                                    width: columnList.width
                                    height: 36
                                    text: modelData.name
                                    checked: modelData.visible
                                    palette.text: root.ink
                                    onClicked: tableModel.setColumnVisible(modelData.name, checked)
                                }
                            }
                        }
                    }

                    Popup {
                        id: colorsPopup
                        width: 350
                        padding: 18
                        x: libraryPage.width - width - 24
                        y: 170
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Rectangle {
                            color: root.surface
                            radius: 16
                            border.width: 1
                            border.color: root.line
                        }
                        contentItem: Column {
                            spacing: 12
                            FieldLabel { text: "Color meaning" }
                            MicroLabel { text: "Dance style column" }
                            C.AppCombo {
                                id: styleColumnCombo
                                width: parent.width
                                model: tableModel.allColumns
                                fillColor: root.surfaceAlt
                                lineColor: root.line
                                focusColor: root.accent
                                textColor: root.ink
                                popupColor: root.surface
                                hoverColor: root.surfaceAlt
                                Component.onCompleted: currentIndex = root.comboIndex(styleColumnCombo, tableModel.styleColumn)
                            }
                            MicroLabel { text: "Difficulty column" }
                            C.AppCombo {
                                id: difficultyColumnCombo
                                width: parent.width
                                model: tableModel.allColumns
                                fillColor: root.surfaceAlt
                                lineColor: root.line
                                focusColor: root.accent
                                textColor: root.ink
                                popupColor: root.surface
                                hoverColor: root.surfaceAlt
                                Component.onCompleted: currentIndex = root.comboIndex(difficultyColumnCombo, tableModel.difficultyColumn)
                            }
                            CheckBox {
                                id: colorStylesCheck
                                text: "Color rows by dance style"
                                checked: Boolean(root.setting("viewer_color_styles", true))
                                palette.text: root.ink
                            }
                            CheckBox {
                                id: colorDifficultyCheck
                                text: "Color difficulty cells"
                                checked: Boolean(root.setting("viewer_color_difficulty", true))
                                palette.text: root.ink
                            }
                            CheckBox {
                                id: highlightBlanksCheck
                                text: "Highlight blank cells"
                                checked: Boolean(root.setting("viewer_highlight_blanks", false))
                                palette.text: root.ink
                            }
                            C.AppButton {
                                width: parent.width
                                text: "Apply color rules"
                                kind: "primary"
                                accentColor: root.accent
                                onClicked: {
                                    tableModel.setSemanticColumns(styleColumnCombo.currentText, difficultyColumnCombo.currentText)
                                    tableModel.setColorOptions(colorStylesCheck.checked, colorDifficultyCheck.checked, highlightBlanksCheck.checked)
                                    colorsPopup.close()
                                }
                            }
                        }
                    }

                    Popup {
                        id: tagsPopup
                        width: Math.min(600, libraryPage.width - 48)
                        height: Math.min(540, libraryPage.height - 190)
                        padding: 16
                        x: libraryPage.width - width - 24
                        y: 170
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Rectangle {
                            color: root.surface
                            radius: 16
                            border.width: 1
                            border.color: root.line
                        }
                        contentItem: ColumnLayout {
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    FieldLabel { text: "Show or hide tags" }
                                    Text {
                                        text: "Uncheck a Style or Theme to hide every matching song."
                                        color: root.muted
                                        font.family: "Segoe UI Variable Text"
                                        font.pixelSize: 11
                                    }
                                }
                                ThemedButton {
                                    id: showAllTagsButton
                                    text: "Show all"
                                    onClicked: tableModel.showAllTags("")
                                    contentItem: Text {
                                        text: showAllTagsButton.text
                                        color: root.accent
                                        font.family: "Segoe UI Variable Text"
                                        font.pixelSize: 12
                                        font.weight: Font.DemiBold
                                    }
                                    background: Item { }
                                }
                            }

                            CheckBox {
                                text: "Only show selected tags (match any selected tag)"
                                checked: tableModel.isolateTags
                                palette.text: root.ink
                                onClicked: tableModel.setIsolateTags(checked)
                            }
                            Label {
                                visible: tableModel.isolateTags
                                text: "Pick tags such as Blues and Boogie. No selection shows no songs."
                                color: root.muted
                            }

                            RowLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                spacing: 14

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 6
                                    MicroLabel { text: "STYLES  /  " + tableModel.styleTagStates.length }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        radius: 12
                                        color: root.surfaceAlt
                                        border.width: 1
                                        border.color: root.line
                                        ListView {
                                            id: styleTagList
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            clip: true
                                            model: tableModel.styleTagStates
                                            spacing: 1
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                            delegate: CheckBox {
                                                required property var modelData
                                                width: styleTagList.width
                                                height: 34
                                                text: modelData.name
                                                checked: modelData.visible
                                                palette.text: root.ink
                                                onClicked: tableModel.setTagVisible("Style", modelData.name, checked)
                                            }
                                        }
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    spacing: 6
                                    MicroLabel { text: "THEMES  /  " + tableModel.themeTagStates.length }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        radius: 12
                                        color: root.surfaceAlt
                                        border.width: 1
                                        border.color: root.line
                                        ListView {
                                            id: themeTagList
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            clip: true
                                            model: tableModel.themeTagStates
                                            spacing: 1
                                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                            delegate: CheckBox {
                                                required property var modelData
                                                width: themeTagList.width
                                                height: 34
                                                text: modelData.name
                                                checked: modelData.visible
                                                palette.text: root.ink
                                                onClicked: tableModel.setTagVisible("Theme", modelData.name, checked)
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Item {
                    id: mergePage

                    ScrollView {
                        anchors.fill: parent
                        anchors.margins: 24
                        contentWidth: availableWidth
                        clip: true

                        ColumnLayout {
                            width: mergePage.width - 48
                            spacing: 16

                            RowLayout {
                                Layout.fillWidth: true
                                PageHeading {
                                    Layout.fillWidth: true
                                    label: "Non-destructive workspace"
                                    headline: "Edit lists"
                                    description: "Multiply tempos across rows, merge lists, or build a master. Export edits to a new file."
                                }
                                Rectangle {
                                    implicitWidth: 190
                                    implicitHeight: 42
                                    radius: 12
                                    color: root.surfaceAlt
                                    border.width: 1
                                    border.color: root.line
                                    Text {
                                        anchors.centerIn: parent
                                        text: "ORIGINALS PROTECTED"
                                        color: root.accent
                                        font.family: "Cascadia Mono"
                                        font.pixelSize: 10
                                        font.weight: Font.Bold
                                    }
                                }
                            }

                            C.Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: bulkTempoForm.implicitHeight + 40
                                fillColor: root.surface
                                lineColor: root.line
                                ColumnLayout {
                                    id: bulkTempoForm
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 10
                                    FieldLabel { text: "Multiply tempo across rows" }
                                    Label { Layout.fillWidth: true; text: tableModel.currentFileName + " | " + tableModel.summaryText; color: root.ink; wrapMode: Text.WordWrap }
                                    RowLayout {
                                        C.AppButton { text: "Open list"; onClicked: controller.openTableDialog(); quietColor: root.surfaceAlt; textColor: root.ink }
                                        C.AppButton { text: "Filter / edit songs"; onClicked: root.currentPage = 0; quietColor: root.surfaceAlt; textColor: root.ink }
                                        C.AppButton { text: "Export edited list"; onClicked: controller.exportCurrentView(); quietColor: root.surfaceAlt; textColor: root.ink }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        ComboBox { id: bulkTempoUnit; model: ["KOD", "BPM"] }
                                        Label { text: "Multiply by"; color: root.ink }
                                        TextField { id: bulkTempoFactor; text: "2"; Layout.preferredWidth: 80 }
                                        CheckBox { id: bulkTempoBelow; text: "Only below 60"; checked: true; palette.text: root.ink }
                                    }
                                    TextField { id: bulkTempoRows; Layout.fillWidth: true; placeholderText: "Rows in filtered list: 1-10, 15 (blank = all filtered rows)" }
                                    Label { Layout.fillWidth: true; text: "Corrections also apply to repeated copies of the same song. The preview includes every affected row. Missing tempos are skipped."; wrapMode: Text.WordWrap; color: root.muted }
                                    RowLayout {
                                        C.AppButton { text: "Preview x" + bulkTempoFactor.text; enabled: !controller.busy && tableModel.allColumns.length > 0; onClicked: controller.previewBulkTempo(bulkTempoUnit.currentText, bulkTempoFactor.text, bulkTempoBelow.checked, bulkTempoRows.text); quietColor: root.surfaceAlt; textColor: root.ink }
                                        C.AppButton {
                                            text: "Apply multiplication"
                                            kind: "primary"; accentColor: root.accent
                                            enabled: !controller.busy && controller.bulkTempoPreview.count > 0 && controller.bulkTempoPreview.unit === bulkTempoUnit.currentText && controller.bulkTempoPreview.factor === bulkTempoFactor.text && controller.bulkTempoPreview.below === bulkTempoBelow.checked && controller.bulkTempoPreview.selection === bulkTempoRows.text
                                            onClicked: controller.applyBulkTempo()
                                        }
                                        C.AppButton { text: "Undo last bulk edit"; enabled: !controller.busy && controller.canUndoBulkTempo; onClicked: controller.undoBulkTempo(); quietColor: root.surfaceAlt; textColor: root.ink }
                                    }
                                    Label { visible: controller.bulkTempoPreview.count !== undefined; text: (controller.bulkTempoPreview.count || 0) + " rows / " + (controller.bulkTempoPreview.songs || 0) + " songs; " + (controller.bulkTempoPreview.skipped || 0) + " missing or invalid tempos skipped"; color: root.ink; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                                    ListView {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: controller.bulkTempoPreview.count > 0 ? 180 : 0
                                        clip: true
                                        model: controller.bulkTempoPreview.rows || []
                                        ScrollBar.vertical: ScrollBar {}
                                        delegate: Label {
                                            required property var modelData
                                            width: ListView.view.width
                                            height: 32
                                            text: modelData.name + " - " + modelData.artists + ": " + modelData.before + " -> " + modelData.after + " " + modelData.unit
                                            color: root.ink
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                        }
                                    }
                                }
                            }

                            C.Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: tagSyncForm.implicitHeight + 40
                                fillColor: root.surface
                                lineColor: root.line
                                ColumnLayout {
                                    id: tagSyncForm
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 10
                                    FieldLabel { text: "Add edited tags to Spotify lists" }
                                    Label { Layout.fillWidth: true; color: root.muted; wrapMode: Text.WordWrap; text: "Preview saved Style and Theme additions across your edited songs. Matching Stil: and Tema: playlists receive only songs they do not already contain. Existing playlist songs are kept." }
                                    RowLayout {
                                        C.AppButton { text: "Preview playlist additions"; enabled: !controller.busy && !controller.taggedUpdateRunning; onClicked: controller.previewChangedTagsToSpotify(); quietColor: root.surfaceAlt; textColor: root.ink }
                                        C.AppButton { text: "Add matched songs"; kind: "primary"; accentColor: root.accent; enabled: !controller.busy && !controller.taggedUpdateRunning && controller.tagSyncPreview.count > 0; onClicked: controller.addChangedTagsToSpotify() }
                                    }
                                    Label { Layout.fillWidth: true; color: root.ink; wrapMode: Text.WordWrap; text: controller.tagSyncPreview.result || (controller.tagSyncPreview.count !== undefined ? controller.tagSyncPreview.count + " additions to " + (controller.tagSyncPreview.playlists || []).length + " playlists; " + (controller.tagSyncPreview.already_present || 0) + " already present" : "") }
                                    Repeater {
                                        model: controller.tagSyncPreview.playlists || []
                                        Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: root.ink; text: modelData.name + ": " + modelData.count + " songs - " + modelData.songs.join(", ") }
                                    }
                                    Repeater {
                                        model: controller.tagSyncPreview.issues || []
                                        Label { required property string modelData; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: root.muted; text: modelData }
                                    }
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                Layout.alignment: Qt.AlignTop
                                columns: mergePage.width < 1000 ? 1 : 2
                                columnSpacing: 16
                                rowSpacing: 16

                                C.Panel {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: mergeForm.implicitHeight + 40
                                    fillColor: root.surface
                                    lineColor: root.line

                                    ColumnLayout {
                                        id: mergeForm
                                        anchors.fill: parent
                                        anchors.margins: 20
                                        spacing: 9

                                        MicroLabel { text: "Single file merge" }
                                        Text {
                                            text: "Add one list to a master"
                                            color: root.ink
                                            font.family: "Segoe UI Variable Display"
                                            font.pixelSize: 21
                                            font.weight: Font.DemiBold
                                        }
                                        FieldLabel { text: "Source list" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: mergeSource
                                                Layout.fillWidth: true
                                                text: root.setting("merge_source_file", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("merge_source_file", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("merge_source_file", "open", "Choose source list")
                                            }
                                        }
                                        FieldLabel { text: "Master list" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: mergeMaster
                                                Layout.fillWidth: true
                                                text: root.setting("merge_master_file", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("merge_master_file", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("merge_master_file", "open", "Choose master list")
                                            }
                                        }
                                        FieldLabel { text: "New output file" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: mergeOutput
                                                Layout.fillWidth: true
                                                text: root.setting("merge_output_file", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("merge_output_file", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("merge_output_file", "save", "Choose merge output")
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.AppButton {
                                                Layout.fillWidth: true
                                                text: "Preview changes"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.runMerge(true)
                                            }
                                            C.AppButton {
                                                Layout.fillWidth: true
                                                text: "Create merged list"
                                                kind: "primary"
                                                accentColor: root.accent
                                                onClicked: controller.runMerge(false)
                                            }
                                        }
                                    }
                                }

                                C.Panel {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: batchForm.implicitHeight + 40
                                    fillColor: root.surface
                                    lineColor: root.line

                                    ColumnLayout {
                                        id: batchForm
                                        anchors.fill: parent
                                        anchors.margins: 20
                                        spacing: 9

                                        MicroLabel { text: "Folder build" }
                                        Text {
                                            text: "Combine a folder into a master"
                                            color: root.ink
                                            font.family: "Segoe UI Variable Display"
                                            font.pixelSize: 21
                                            font.weight: Font.DemiBold
                                        }
                                        FieldLabel { text: "Source folder" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: batchSource
                                                Layout.fillWidth: true
                                                text: root.setting("batch_source_dir", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("batch_source_dir", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("batch_source_dir", "folder", "Choose source folder")
                                            }
                                        }
                                        FieldLabel { text: "Template list" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: batchTemplate
                                                Layout.fillWidth: true
                                                text: root.setting("batch_template_file", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("batch_template_file", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("batch_template_file", "open", "Choose template list")
                                            }
                                        }
                                        FieldLabel { text: "New output file" }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.TextBox {
                                                id: batchOutput
                                                Layout.fillWidth: true
                                                text: root.setting("batch_output_file", "")
                                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                                textColor: root.ink; placeholderColor: root.muted
                                                onEditingFinished: controller.setSetting("batch_output_file", text)
                                            }
                                            C.AppButton {
                                                text: "Browse"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.choosePath("batch_output_file", "save", "Choose build output")
                                            }
                                        }
                                        RowLayout {
                                            Layout.fillWidth: true
                                            C.AppButton {
                                                Layout.fillWidth: true
                                                text: "Preview build"
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.runBatchBuild(true)
                                            }
                                            C.AppButton {
                                                Layout.fillWidth: true
                                                text: "Build master list"
                                                kind: "primary"
                                                accentColor: root.accent
                                                onClicked: controller.runBatchBuild(false)
                                            }
                                        }
                                    }
                                }
                            }

                            C.Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 250
                                fillColor: root.surface
                                lineColor: root.line

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 20
                                    spacing: 10

                                    RowLayout {
                                        Layout.fillWidth: true
                                        Text {
                                            Layout.fillWidth: true
                                            text: controller.mergeResult.title || "Preview results will appear here"
                                            color: root.ink
                                            font.family: "Segoe UI Variable Display"
                                            font.pixelSize: 20
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            text: controller.mergeResult.summary || "No changes calculated"
                                            color: root.accent
                                            font.family: "Cascadia Mono"
                                            font.pixelSize: 11
                                            font.weight: Font.Bold
                                        }
                                    }

                                    ListView {
                                        Layout.fillWidth: true
                                        Layout.fillHeight: true
                                        clip: true
                                        model: controller.mergeResult.preview_rows || []
                                        spacing: 5
                                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: ListView.view.width
                                            height: 42
                                            radius: 9
                                            color: root.surfaceAlt
                                            RowLayout {
                                                anchors.fill: parent
                                                anchors.leftMargin: 12
                                                anchors.rightMargin: 12
                                                spacing: 10
                                                Text {
                                                    text: String(modelData.action || "change").toUpperCase()
                                                    color: root.accent
                                                    font.family: "Cascadia Mono"
                                                    font.pixelSize: 9
                                                    font.weight: Font.Bold
                                                    Layout.preferredWidth: 62
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: (modelData["Track Name"] || "Untitled") + "  /  " + (modelData["Artist(s)"] || "Unknown artist")
                                                    color: root.ink
                                                    font.family: "Segoe UI Variable Text"
                                                    font.pixelSize: 12
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    text: modelData.source_file || ""
                                                    color: root.muted
                                                    font.family: "Cascadia Mono"
                                                    font.pixelSize: 9
                                                    elide: Text.ElideMiddle
                                                    Layout.maximumWidth: 190
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Item {
                    id: spotifyPage

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 24
                        spacing: 16

                        RowLayout {
                            Layout.fillWidth: true
                            PageHeading {
                                Layout.fillWidth: true
                                label: "Spotify web api"
                                headline: "Search, export, and control"
                                description: "The capability check shows what your app key and account can use today."
                            }
                            C.AppButton {
                                text: "Connect Spotify"
                                kind: "primary"
                                accentColor: root.accent
                                onClicked: controller.spotifyAuthorize()
                            }
                            C.AppButton {
                                text: "Capability check"
                                quietColor: root.surface
                                hoverColor: root.surfaceAlt
                                textColor: root.ink
                                onClicked: controller.spotifyCapabilityCheck()
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14

                            C.Panel {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 154
                                fillColor: root.surface
                                lineColor: root.line

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 8
                                    MicroLabel { text: "Catalog search" }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        C.TextBox {
                                            id: spotifySearchInput
                                            Layout.fillWidth: true
                                            placeholderText: "Track, artist, album, or playlist"
                                            fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                            textColor: root.ink; placeholderColor: root.muted
                                            onAccepted: controller.spotifySearch(text, spotifySearchTypes.currentText)
                                        }
                                        C.AppCombo {
                                            id: spotifySearchTypes
                                            Layout.preferredWidth: 190
                                            model: ["track,artist,album,playlist", "track", "artist", "album", "playlist"]
                                            fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                            textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                                        }
                                        C.AppButton {
                                            text: "Search"
                                            kind: "primary"
                                            accentColor: root.accent
                                            onClicked: controller.spotifySearch(spotifySearchInput.text, spotifySearchTypes.currentText)
                                        }
                                    }
                                    Row {
                                        spacing: 8
                                        MicroLabel {
                                            text: "Your music"
                                            anchors.verticalCenter: parent.verticalCenter
                                        }
                                        C.AppButton {
                                            text: "Playlists"
                                            quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                            onClicked: controller.spotifyLoadPlaylists()
                                        }
                                        C.AppButton {
                                            text: "Saved"
                                            quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                            onClicked: controller.spotifyBrowse("saved")
                                        }
                                        C.AppButton {
                                            text: "Recent"
                                            quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                            onClicked: controller.spotifyBrowse("recent")
                                        }
                                        C.AppButton {
                                            text: "Top"
                                            quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                            onClicked: controller.spotifyBrowse("top_tracks")
                                        }
                                        C.AppButton {
                                            text: controller.taggedUpdateRunning ? "Updating Spotify..." : "Update tagged list"
                                            enabled: !controller.busy && !controller.taggedUpdateRunning
                                            kind: "primary"
                                            accentColor: root.accent
                                            onClicked: controller.spotifyBuildTaggedList()
                                        }
                                        C.AppButton {
                                            text: "More tools"
                                            quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                            onClicked: spotifyToolsPopup.open()
                                        }
                                    }
                                }
                            }

                            C.Panel {
                                Layout.preferredWidth: 390
                                Layout.preferredHeight: 154
                                fillColor: root.sidebar
                                lineColor: "#303834"

                                ColumnLayout {
                                    anchors.fill: parent
                                    anchors.margins: 18
                                    spacing: 7
                                    RowLayout {
                                        Layout.fillWidth: true
                                        MicroLabel { text: "Now playing"; color: "#9DA7A1" }
                                        Item { Layout.fillWidth: true }
                                        ThemedButton {
                                            id: queueNavButton
                                            text: "Queue"
                                            onClicked: { listeningDialog.selectQueueMode(false, true); listeningDialog.open() }
                                            contentItem: Text {
                                                text: queueNavButton.text
                                                color: "#DCE2DD"
                                                font.family: "Segoe UI Variable Text"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                            }
                                            background: Item { }
                                        }
                                        ThemedButton {
                                            id: devicesNavButton
                                            text: "Devices"
                                            onClicked: controller.spotifyLoadDevices()
                                            contentItem: Text {
                                                text: devicesNavButton.text
                                                color: "#DCE2DD"
                                                font.family: "Segoe UI Variable Text"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                            }
                                            background: Item { }
                                        }
                                        ThemedButton {
                                            id: refreshPlaybackButton
                                            text: "Refresh"
                                            onClicked: controller.spotifyNowPlaying()
                                            contentItem: Text {
                                                text: refreshPlaybackButton.text
                                                color: root.accent
                                                font.family: "Segoe UI Variable Text"
                                                font.pixelSize: 11
                                                font.weight: Font.DemiBold
                                            }
                                            background: Item { }
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: controller.playbackState.track_name || "Nothing playing"
                                        color: "#FFFFFF"
                                        font.family: "Segoe UI Variable Display"
                                        font.pixelSize: 18
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: controller.playbackState.artists || controller.playbackState.device_name || "Connect to load playback"
                                        color: "#AAB3AD"
                                        font.family: "Segoe UI Variable Text"
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 7
                                        C.AppButton { text: "Prev"; horizontalPadding: 12; quietColor: "#29312D"; hoverColor: "#354039"; textColor: "#FFFFFF"; onClicked: controller.spotifyPlayback("previous", "") }
                                        C.AppButton { text: String(controller.playbackState.is_playing).toLowerCase() === "true" ? "Pause" : "Play"; enabled: !controller.busy; horizontalPadding: 14; kind: "primary"; accentColor: root.accent; onClicked: controller.spotifyTogglePlayback() }
                                        C.AppButton { text: "Next"; horizontalPadding: 12; quietColor: "#29312D"; hoverColor: "#354039"; textColor: "#FFFFFF"; onClicked: controller.spotifyPlayback("next", "") }
                                    }
                                }
                            }
                        }

                        C.Panel {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            fillColor: root.surface
                            lineColor: root.line
                            clip: true

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 18
                                spacing: 10

                                RowLayout {
                                    Layout.fillWidth: true
                                    C.AppButton {
                                        visible: controller.spotifyView.mode === "playlist"
                                        text: "Back to playlists"
                                        horizontalPadding: 12
                                        quietColor: root.surfaceAlt
                                        hoverColor: root.line
                                        textColor: root.ink
                                        onClicked: controller.spotifyLoadPlaylists()
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: controller.spotifyView.title || "Spotify results"
                                        color: root.ink
                                        font.family: "Segoe UI Variable Display"
                                        font.pixelSize: 20
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: controller.spotifyResults.length + " items"
                                        color: root.muted
                                        font.family: "Cascadia Mono"
                                        font.pixelSize: 10
                                    }
                                    C.AppButton {
                                        visible: controller.spotifyView.mode === "playlist"
                                        text: "Export playlist"
                                        horizontalPadding: 12
                                        quietColor: root.surfaceAlt
                                        hoverColor: root.line
                                        textColor: root.ink
                                        onClicked: controller.spotifyExportPlaylist(String(controller.spotifyView.reference || ""))
                                    }
                                }

                                ListView {
                                    id: spotifyResultsList
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    clip: true
                                    model: controller.spotifyResults
                                    spacing: 6
                                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                                    delegate: Rectangle {
                                        required property var modelData
                                        width: spotifyResultsList.width
                                        height: 62
                                        radius: 11
                                        color: resultTap.hovered ? root.surfaceAlt : "transparent"
                                        border.width: 1
                                        border.color: resultTap.hovered ? root.line : "transparent"

                                        RowLayout {
                                            anchors.fill: parent
                                            anchors.leftMargin: 12
                                            anchors.rightMargin: 12
                                            spacing: 12
                                            Rectangle {
                                                width: 38
                                                height: 38
                                                radius: 11
                                                color: root.surfaceAlt
                                                Text {
                                                    anchors.centerIn: parent
                                                    text: String(modelData.type || "item").substring(0, 2).toUpperCase()
                                                    color: root.accent
                                                    font.family: "Cascadia Mono"
                                                    font.pixelSize: 10
                                                    font.weight: Font.Bold
                                                }
                                            }
                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 1
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.name || "Untitled"
                                                    color: root.ink
                                                    font.family: "Segoe UI Variable Text"
                                                    font.pixelSize: 14
                                                    font.weight: Font.DemiBold
                                                    elide: Text.ElideRight
                                                }
                                                Text {
                                                    Layout.fillWidth: true
                                                    text: modelData.subtitle || modelData.type || ""
                                                    color: root.muted
                                                    font.family: "Segoe UI Variable Text"
                                                    font.pixelSize: 11
                                                    elide: Text.ElideRight
                                                }
                                            }
                                            Text {
                                                text: modelData.extra || ""
                                                color: root.muted
                                                font.family: "Cascadia Mono"
                                                font.pixelSize: 10
                                                Layout.maximumWidth: 170
                                                elide: Text.ElideRight
                                            }
                                            C.AppButton {
                                                visible: (modelData.id !== undefined && modelData.type === "device")
                                                         || (modelData.uri !== undefined && String(modelData.uri).length > 0)
                                                         || (modelData.external_url !== undefined && String(modelData.external_url).length > 0)
                                                text: modelData.type === "device" ? "Use"
                                                      : modelData.type === "playlist" ? "Open"
                                                      : String(modelData.type || "").indexOf("lastfm") === 0 ? "Open"
                                                      : "Play"
                                                horizontalPadding: 14
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: {
                                                    if (modelData.type === "device") controller.spotifyItemAction("device", modelData.id)
                                                    else if (modelData.type === "playlist") controller.spotifyOpenPlaylist(modelData.uri, modelData.name)
                                                    else if (String(modelData.type || "").indexOf("lastfm") === 0) controller.openPath(modelData.external_url)
                                                    else controller.spotifyPlayback("play", modelData.uri)
                                                }
                                            }
                                            C.AppButton {
                                                visible: modelData.type === "playlist"
                                                text: "Play"
                                                horizontalPadding: 12
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.spotifyPlayback("play", modelData.uri)
                                            }
                                            C.AppButton {
                                                visible: ["track", "current", "queue"].indexOf(String(modelData.type || "")) >= 0
                                                text: "Queue"
                                                horizontalPadding: 12
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.spotifyItemAction("queue", modelData.uri)
                                            }
                                            C.AppButton {
                                                visible: modelData.type === "track"
                                                text: "Save"
                                                horizontalPadding: 12
                                                quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                                onClicked: controller.spotifyItemAction("save", modelData.uri)
                                            }
                                        }

                                        HoverHandler { id: resultTap }
                                    }
                                }
                            }
                        }
                    }

                    Popup {
                        id: spotifyToolsPopup
                        width: 410
                        padding: 18
                        x: spotifyPage.width - width - 24
                        y: 162
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                        background: Rectangle {
                            color: root.surface
                            radius: 16
                            border.width: 1
                            border.color: root.line
                        }
                        contentItem: Column {
                            spacing: 11
                            FieldLabel { text: "Discovery and playback tools" }
                            Text {
                                width: parent.width
                                text: "Last.fm suggestions are useful when Spotify recommendations or audio features are restricted."
                                color: root.muted
                                font.family: "Segoe UI Variable Text"
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                            C.TextBox {
                                id: discoveryArtist
                                width: parent.width
                                placeholderText: "Artist name"
                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                textColor: root.ink; placeholderColor: root.muted
                            }
                            C.TextBox {
                                id: discoveryTrack
                                width: parent.width
                                placeholderText: "Track name"
                                fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                textColor: root.ink; placeholderColor: root.muted
                            }
                            Row {
                                spacing: 8
                                C.AppButton {
                                    text: "Similar tracks"
                                    kind: "primary"
                                    accentColor: root.accent
                                    onClicked: {
                                        controller.lastFmSimilar(discoveryArtist.text, discoveryTrack.text, false)
                                        spotifyToolsPopup.close()
                                    }
                                }
                                C.AppButton {
                                    text: "Similar artists"
                                    quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                    onClicked: {
                                        controller.lastFmSimilar(discoveryArtist.text, "", true)
                                        spotifyToolsPopup.close()
                                    }
                                }
                            }
                            Rectangle { width: parent.width; height: 1; color: root.line }
                            Row {
                                spacing: 8
                                C.TextBox {
                                    id: volumeInput
                                    width: 92
                                    text: controller.spotifyState.device_volume || "50"
                                    placeholderText: "0-100"
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                                    textColor: root.ink; placeholderColor: root.muted
                                }
                                C.AppButton {
                                    text: "Set volume"
                                    quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                    onClicked: controller.spotifySetVolume(volumeInput.text)
                                }
                                C.AppButton {
                                    text: "Shuffle on"
                                    quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                    onClicked: controller.spotifyPlayback("shuffle_on", "")
                                }
                                C.AppButton {
                                    text: "Off"
                                    quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                                    onClicked: controller.spotifyPlayback("shuffle_off", "")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    Drawer {
        id: settingsDrawer
        objectName: "settingsDrawer"
        edge: Qt.RightEdge
        width: Math.min(480, root.width * 0.44)
        height: root.height
        modal: true
        background: Rectangle {
            color: root.surface
            border.width: 1
            border.color: root.line
        }

        ScrollView {
            anchors.fill: parent
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: settingsDrawer.width
                spacing: 12

                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 20
                    Layout.topMargin: 22
                    Text {
                        Layout.fillWidth: true
                        text: "Settings"
                        color: root.ink
                        font.family: "Segoe UI Variable Display"
                        font.pixelSize: 27
                        font.weight: Font.DemiBold
                    }
                    ThemedButton {
                        id: closeSettingsButton
                        text: "Close"
                        onClicked: settingsDrawer.close()
                        contentItem: Text {
                            text: closeSettingsButton.text
                            color: root.accent
                            font.family: "Segoe UI Variable Text"
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        background: Item { }
                    }
                }

                MicroLabel { Layout.leftMargin: 24; text: "Appearance" }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    spacing: 10
                    C.AppCombo {
                        id: themeCombo
                        Layout.fillWidth: true
                        model: ["Paper", "Night"]
                        currentIndex: root.comboIndex(themeCombo, controller.themeName)
                        fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                        textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                        onActivated: controller.setTheme(currentText)
                    }
                    C.AppCombo {
                        id: accentCombo
                        Layout.fillWidth: true
                        model: ["Terracotta", "Ocean", "Golden", "Berry"]
                        currentIndex: root.comboIndex(accentCombo, controller.accentName)
                        fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                        textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                        onActivated: controller.setAccent(currentText)
                    }
                }

                FieldLabel { Layout.leftMargin: 24; text: "Table density" }
                C.AppCombo {
                    id: densityCombo
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    model: ["Compact", "Comfortable", "Spacious"]
                    currentIndex: root.comboIndex(densityCombo, root.setting("viewer_density", "Comfortable"))
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                    onActivated: {
                        controller.setSetting("viewer_density", currentText)
                        songTable.forceLayout()
                    }
                }

                Rectangle { Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; height: 1; color: root.line }
                MicroLabel { Layout.leftMargin: 24; text: "Files and export" }
                FieldLabel { Layout.leftMargin: 24; text: "Default output folder" }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    C.TextBox {
                        id: outputFolder
                        Layout.fillWidth: true
                        text: root.setting("output_folder", "")
                        fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                        textColor: root.ink; placeholderColor: root.muted
                        onEditingFinished: controller.setSetting("output_folder", text)
                    }
                    C.AppButton {
                        text: "Browse"
                        quietColor: root.surfaceAlt; hoverColor: root.line; textColor: root.ink
                        onClicked: controller.choosePath("output_folder", "folder", "Choose output folder")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    spacing: 10
                    C.AppCombo {
                        id: formatCombo
                        Layout.fillWidth: true
                        model: ["Excel workbook (.xlsx)", "CSV (.csv)", "TSV (.tsv)", "JSON records (.json)", "JSON Lines (.jsonl)"]
                        currentIndex: root.comboIndex(formatCombo, root.setting("output_format", "Excel workbook (.xlsx)"))
                        fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                        textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                        onActivated: controller.setSetting("output_format", currentText)
                    }
                    C.AppCombo {
                        id: delimiterCombo
                        Layout.fillWidth: true
                        model: ["Comma (,)", "Semicolon (;)", "Tab", "Pipe (|)"]
                        currentIndex: root.comboIndex(delimiterCombo, root.setting("csv_delimiter", "Comma (,)"))
                        fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                        textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                        onActivated: controller.setSetting("csv_delimiter", currentText)
                    }
                }
                C.AppCombo {
                    id: encodingCombo
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    model: ["UTF-8 with BOM", "UTF-8", "UTF-16", "Windows-1252"]
                    currentIndex: root.comboIndex(encodingCombo, root.setting("text_encoding", "UTF-8 with BOM"))
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                    onActivated: controller.setSetting("text_encoding", currentText)
                }

                Rectangle { Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; height: 1; color: root.line }
                MicroLabel { Layout.leftMargin: 24; text: "Merge behavior" }
                FieldLabel { Layout.leftMargin: 24; text: "Match columns (comma separated)" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("merge_key_columns", "Track Name, Artist(s)")
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("merge_key_columns", text)
                }
                C.AppCombo {
                    id: mergeModeCombo
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    model: ["fill_blanks", "overwrite", "keep_master"]
                    currentIndex: root.comboIndex(mergeModeCombo, root.setting("merge_update_mode", "fill_blanks"))
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; popupColor: root.surface; hoverColor: root.surfaceAlt
                    onActivated: controller.setSetting("merge_update_mode", currentText)
                }

                Rectangle { Layout.fillWidth: true; Layout.leftMargin: 24; Layout.rightMargin: 24; height: 1; color: root.line }
                MicroLabel { Layout.leftMargin: 24; text: "Spotify app credentials" }
                Text {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: "Credentials stay in this separate app folder. Use Capability check after connecting."
                    color: root.muted
                    font.family: "Segoe UI Variable Text"
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                }
                FieldLabel { Layout.leftMargin: 24; text: "Client ID" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("spotify_client_id", "")
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("spotify_client_id", text)
                }
                FieldLabel { Layout.leftMargin: 24; text: "Client secret" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("spotify_client_secret", "")
                    echoMode: TextInput.Password
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("spotify_client_secret", text)
                }
                FieldLabel { Layout.leftMargin: 24; text: "Redirect URI" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("spotify_redirect_uri", "http://127.0.0.1:8080/callback/")
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("spotify_redirect_uri", text)
                }
                FieldLabel { Layout.leftMargin: 24; text: "Default playlist IDs or URLs" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("spotify_playlist_ids", "")
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("spotify_playlist_ids", text)
                }
                FieldLabel { Layout.leftMargin: 24; text: "Preferred device ID" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: root.setting("spotify_device_id", "")
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("spotify_device_id", text)
                }
                FieldLabel { Layout.leftMargin: 24; text: "Last.fm API key (optional)" }
                C.TextBox {
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.bottomMargin: 28
                    text: root.setting("lastfm_api_key", "")
                    echoMode: TextInput.Password
                    fillColor: root.surfaceAlt; lineColor: root.line; focusColor: root.accent
                    textColor: root.ink; placeholderColor: root.muted
                    onEditingFinished: controller.setSetting("lastfm_api_key", text)
                }
            }
        }
    }

    Popup {
        id: toast
        property string heading: ""
        property string detail: ""
        x: root.width - width - 24
        y: Math.max(12, root.height - playbackBar.height - height - 24)
        width: 360
        padding: 0
        closePolicy: Popup.NoAutoClose

        background: Rectangle {
            color: root.sidebar
            radius: 15
            border.width: 1
            border.color: "#36403A"
        }
        contentItem: RowLayout {
            implicitHeight: 76
            spacing: 12
            Rectangle {
                Layout.leftMargin: 14
                width: 8
                height: 42
                radius: 4
                color: root.accent
            }
            ColumnLayout {
                Layout.fillWidth: true
                Layout.rightMargin: 16
                spacing: 2
                Text {
                    Layout.fillWidth: true
                    text: toast.heading
                    color: "#FFFFFF"
                    font.family: "Segoe UI Variable Text"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Text {
                    Layout.fillWidth: true
                    text: toast.detail
                    color: "#ACB5AF"
                    font.family: "Segoe UI Variable Text"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
        }

        Timer {
            id: toastTimer
            interval: 3800
            onTriggered: toast.close()
        }
    }

    BusyIndicator {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        width: 28
        height: 28
        running: controller.working
        visible: controller.working
        palette.highlight: root.accent
    }

    Connections {
        target: controller
        function onToastRequested(title, message) {
            toast.heading = title
            toast.detail = message
            toast.open()
            toastTimer.restart()
        }
        function onSettingsChanged() {
            mergeSource.text = root.setting("merge_source_file", "")
            mergeMaster.text = root.setting("merge_master_file", "")
            mergeOutput.text = root.setting("merge_output_file", "")
            batchSource.text = root.setting("batch_source_dir", "")
            batchTemplate.text = root.setting("batch_template_file", "")
            batchOutput.text = root.setting("batch_output_file", "")
            outputFolder.text = root.setting("output_folder", "")
        }
        function onNavigateRequested(page) {
            root.currentPage = page
        }
    }
}
