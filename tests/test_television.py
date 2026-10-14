import gzip
import os
import shutil
import struct
import tomllib
import zlib
from pathlib import Path

import pytest

from deepwick_spec.ansi import runs
from deepwick_spec.check_port import check_port
from deepwick_spec.palette import load_palette
from deepwick_spec.tui import capture, tmux_available

REPO = Path(__file__).resolve().parents[1]
PALETTE = load_palette()
C = PALETTE.colors
THEME = REPO / "deepwick.toml"
EXPECTED = {
    "background": "background", "border_fg": "overlay", "text_fg": "foreground",
    "dimmed_text_fg": "muted", "input_text_fg": "foreground", "result_count_fg": "muted",
    "result_name_fg": "foreground", "result_line_number_fg": "muted", "result_value_fg": "foreground",
    "selection_bg": "selection", "selection_fg": "foreground", "match_fg": "gold",
    "preview_title_fg": "blue",
    "channel_mode_fg": "background", "channel_mode_bg": "blue",
    "remote_control_mode_fg": "background", "remote_control_mode_bg": "teal",
    "action_picker_mode_fg": "background", "action_picker_mode_bg": "magenta",
}


def isolated_env(tmp_path, **extra):
    dirs = {"HOME": tmp_path / "home"}
    for kind in ("CONFIG", "DATA", "STATE", "CACHE"):
        dirs[f"XDG_{kind}_HOME"] = tmp_path / kind.lower()
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    env = {key: str(path) for key, path in dirs.items()}
    env.update({key: str(value) for key, value in extra.items()})
    return env


def style_containing(text, needle):
    for chunk, style in runs(text):
        if needle in chunk:
            return style
    raise AssertionError(f"no run contains {needle!r}")


def has_bg(text, name):
    return any(style["bg"] == C[name].lower() for _, style in runs(text))


def has_fg(text, name):
    return any(style["fg"] == C[name].lower() for _, style in runs(text))


TREE_ROLES = {
    "src": "directory", "run.sh": "executable", "link": "symlink", "broken": "brokenSymlink",
    "pipe": "special", "bundle.tar.gz": "archive", "photo.png": "media", "notes.pdf": "document",
    "app.py": "source", "old.bak": "temp",
}


def tiny_png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b"")


def make_tree(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def main():\n    return 0\n")
    (root / "run.sh").write_text("#!/bin/sh\necho run\n")
    (root / "run.sh").chmod(0o755)
    (root / "app.py").write_text("print('hi')\n")
    (root / "link").symlink_to("app.py")
    (root / "broken").symlink_to("missing")
    os.mkfifo(root / "pipe")
    (root / "bundle.tar.gz").write_bytes(gzip.compress(b"deepwick"))
    (root / "photo.png").write_bytes(tiny_png())
    (root / "notes.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (root / "old.bak").write_text("old\n")
    return root


def theme():
    assert THEME.is_file(), "deepwick.toml missing"
    return tomllib.loads(THEME.read_text(encoding="utf-8"))


def test_every_key_follows_roles():
    assert theme() == {key: C[name] for key, name in EXPECTED.items()}


def test_cable_override_uses_deepwick_bat_theme():
    cable = tomllib.loads((REPO / "cable" / "files.toml").read_text(encoding="utf-8"))
    assert cable["metadata"]["name"] == "files"
    assert cable["preview"]["env"]["BAT_THEME"] == "Deepwick"


def tv_env(tmp_path):
    env = isolated_env(tmp_path, TERM="xterm-256color")
    config = Path(env["XDG_CONFIG_HOME"]) / "television"
    (config / "themes").mkdir(parents=True)
    shutil.copy(THEME, config / "themes" / "deepwick.toml")
    (config / "config.toml").write_text('[ui]\ntheme = "deepwick"\n')
    env["TELEVISION_CONFIG"] = str(config)
    return env


@pytest.mark.skipif(not (tmux_available() and shutil.which("tv") and shutil.which("fd")), reason="requires tmux, tv and fd")
def test_tv_renders_deepwick(tmp_path):
    tree = make_tree(tmp_path / "tree")
    out = capture(f"cd {tree} && tv files", tv_env(tmp_path), size=(120, 30), wait_for="run.sh",
                  literal="app", after="app.py", timeout=20)
    assert has_bg(out, "background"), "theme not loaded (tv fell back to its default)"
    assert has_bg(out, "selection")
    assert has_fg(out, "gold"), "fuzzy matches should be Gold"
    assert has_fg(out, "overlay"), "borders should be Overlay"


def test_port_conventions():
    assert check_port(REPO, PALETTE.allowed_hex()) == []
