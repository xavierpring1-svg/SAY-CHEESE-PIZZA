"""Visible controls and speech boundaries in the holographic dashboard."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("XDG_CACHE_HOME", "/workspace/.cache")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QLabel

from jarvis.core import Store
from jarvis.ui import STYLE, Window
from jarvis.ui_components import Hologram


@pytest.fixture(scope="module")
def hologram_app():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    return app


@pytest.fixture
def dashboard(hologram_app, tmp_path):
    window = Window(Store(tmp_path), start_workers=False)
    window.show()
    hologram_app.processEvents()
    yield window
    window.cleanup()
    window.close()
    hologram_app.processEvents()


def test_mouth_moves_only_during_actual_speech(dashboard, hologram_app):
    face = dashboard.hologram
    dashboard.preparing_changed(True)
    dashboard.assistant_busy(True)
    dashboard.level_changed(.95)
    dashboard.set_mode("SPEAKING")
    for _ in range(12):
        face.animate()
    assert face.mouth_openness == 0

    # Drive the same signal the real playback worker emits.
    dashboard.speaker.speaking.emit(True)
    hologram_app.processEvents()
    openings = []
    for _ in range(20):
        face.animate()
        openings.append(face.mouth_openness)
    assert all(0 < value <= 1 for value in openings)
    assert max(openings) - min(openings) > .2
    dashboard.speaker.speaking.emit(False)
    hologram_app.processEvents()
    assert face.mouth_openness == 0


def test_stopping_and_sleeping_close_the_mouth_immediately(dashboard):
    dashboard.speech_changed(True)
    dashboard.hologram.animate()
    assert dashboard.hologram.mouth_openness > 0
    dashboard.stop_reply()
    assert not dashboard.hologram.speaking
    assert dashboard.hologram.mouth_openness == 0
    dashboard.speech_changed(True)
    dashboard.hologram.animate()
    dashboard.sleep()
    assert not dashboard.hologram.speaking
    assert dashboard.hologram.mouth_openness == 0


def test_portrait_mouth_visibly_changes_and_restores(hologram_app):
    face = Hologram()
    assert not face.portrait.isNull(), "The packaged portrait must be available"
    face.resize(400, 500)
    face.show()
    hologram_app.processEvents()
    face.timer.stop()
    rect = face._portrait_rect()
    x = rect.x() + rect.width() * face.MOUTH_POSITION[0]
    y = rect.y() + rect.height() * face.MOUTH_POSITION[1]
    mouth = QRect(int(x - 32), int(y - 15), 64, 32)
    idle_phase = face.phase
    closed = face.grab().toImage().copy(mouth)
    face.set_speaking(True)
    for _ in range(7):
        face.animate()
    opened = face.grab().toImage().copy(mouth)
    assert opened != closed
    face.set_speaking(False)
    # Keep the separate decorative scan at the same position for comparison.
    face.phase = idle_phase
    assert face.grab().toImage().copy(mouth) == closed
    face.close()


def test_missing_portrait_renders_human_fallback_and_stops_hidden_animation(hologram_app, tmp_path):
    face = Hologram(tmp_path / "missing.png")
    assert face.portrait.isNull()
    face.resize(320, 430)
    face.show()
    hologram_app.processEvents()
    assert face.timer.isActive()
    face.set_speaking(True)
    face.animate()
    image = face.grab().toImage()
    assert not image.isNull()
    # The fallback eyes and chest are brighter than the dark panel background.
    assert image.pixelColor(125, 155).lightness() > image.pixelColor(1, 1).lightness()
    face.hide()
    hologram_app.processEvents()
    assert not face.timer.isActive()
    face.close()


def test_music_buttons_and_slider_submit_app_controls(dashboard, monkeypatch):
    commands = []
    monkeypatch.setattr(dashboard.assistant, "submit", commands.append)
    dashboard.music_buttons["Replay"].click()
    dashboard.music_buttons["Next"].click()
    dashboard.music_buttons["Previous"].click()
    dashboard.spotify_volume.setValue(37)
    assert commands == ["replay song", "next song", "previous song"]
    dashboard.spotify_volume.sliderReleased.emit()
    assert commands[-1] == "spotify volume 37%"
    assert dashboard.spotify_volume_preview.text() == "37%"


def test_clock_side_tabs_and_compact_layout_without_resource_panels(dashboard, hologram_app):
    dashboard.resize(dashboard.minimumSize())
    hologram_app.processEvents()
    assert dashboard.clock_label.text().count(":") == 2
    visible_labels = [item.text() for item in dashboard.findChildren(QLabel)]
    assert not any("UTILISATION" in text for text in visible_labels)
    assert not hasattr(dashboard, "gpu_timer")
    assert not hasattr(dashboard, "stat_labels")
    assert dashboard.hologram.height() >= 270
    assert dashboard.command_entry.isVisible()
    dashboard.nav_buttons[1].click()
    assert dashboard.stack.currentIndex() == 1
    dashboard.task_entry.setText("Keep the tasks tab")
    tasks = []
    dashboard.assistant.submit = tasks.append
    dashboard.add_task()
    assert tasks == ["add task Keep the tasks tab"]
    dashboard.nav_buttons[3].click()
    assert dashboard.stack.currentIndex() == 3
    assert dashboard.settings_widgets["ai_provider"].currentText() == "Built-in AI (local)"
    dashboard.nav_buttons[0].click()
    hologram_app.processEvents()
    assert dashboard.hologram.isVisible()
