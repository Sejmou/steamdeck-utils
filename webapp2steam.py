#!/usr/bin/env python3
"""webapp2steam.py - add a web app to Steam as a non-Steam "game", launched in a Flatpak browser.

Run it in Desktop Mode with Steam running. Standard library only, since SteamOS's system
folders are read-only and pip packages are awkward to install.

How the app gets into Steam
    SteamOS's own steamos-add-to-steam (what Dolphin's "Add to Steam" entry uses) hands a .desktop
    file to the running Steam client, which imports it as a shortcut. That avoids restarting Steam,
    editing Steam's files (shortcuts.vdf) and Steam's CEF debug port. Steam copies Name, Exec and
    Icon once at import time; artwork, collections and the controller layout are set by hand in
    Steam afterwards.

Files per web app
    ~/.local/share/webapps/<name>/
        launch.sh        what Steam runs: the browser command and URL
        <name>.desktop   only read at import time; kept for re-importing
        profile          link to the separate browser profile, if one was chosen
    ~/.var/app/<browser>/data/webapp-profiles/<name>/
        the separate browser profile itself (reasoning in main())

To remove a web app, delete its Steam shortcut, its folder above and, if any, its profile folder.
"""

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

BROWSERS = [
    "com.brave.Browser",
    "org.mozilla.firefox",
    "io.github.ungoogled_software.ungoogled_chromium",
    "org.chromium.Chromium",
    "com.google.Chrome",
]
FIREFOX = "org.mozilla.firefox"
HOME = Path.home()
WEBAPPS = HOME / ".local/share/webapps"


def pick(options):
    for i, option in enumerate(options, 1):
        print(f"  {i}) {option}")
    while True:
        choice = input("  #? ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]


def main():
    if not shutil.which("steamos-add-to-steam"):
        sys.exit("steamos-add-to-steam not found (this needs SteamOS).")
    if subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode != 0:
        sys.exit("Start Steam first.")

    installed = subprocess.run(
        ["flatpak", "list", "--app", "--columns=application"],
        capture_output=True,
        text=True,
    ).stdout.split()
    browsers = [b for b in BROWSERS if b in installed]
    if not browsers:
        sys.exit(
            "No supported browser found. Install one of these Flathub packages "
            "(e.g. from Discover), then run this again:\n  " + "\n  ".join(BROWSERS)
        )

    name = input("1. Name in Steam: ").strip()
    url = input("2. URL: ").strip()
    if not name or not re.match(r"https?://", url):
        sys.exit("Need a name and an http(s) URL.")
    print("3. Browser:")
    browser = pick(browsers)
    isolated = (
        input("4. Separate browser profile for this app? [y/N] ")
        .strip()
        .lower()
        .startswith("y")
    )

    slug = re.sub(r"[^A-Za-z0-9]+", "_", name)
    app_dir = WEBAPPS / slug  # launcher, .desktop file and profile link
    app_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["flatpak", "run", browser]

    if isolated:
        # Where the separate profile lives, and why:
        # - ~/.var/app/<browser>/ is the browser's own Flatpak data folder. Its sandbox can always write
        #   there, so no `flatpak override --filesystem=...` is needed. Such an override would widen the
        #   browser's access for every use of it, not just for web apps.
        # - The profile belongs to that browser anyway: it only works with the browser that created it,
        #   and `flatpak uninstall --delete-data` removes it together with the browser.
        # - data/ rather than config/: Flatpak creates both for every app, but Chromium-based browsers
        #   keep their own profiles in config/, while data/ is barely used. This keeps ours clearly apart.
        # - A separate profile also stops a Chromium browser from handing the launch to an already
        #   running instance and exiting, which Steam would take as the "game" having quit.
        profile = HOME / ".var/app" / browser / "data/webapp-profiles" / slug
        profile.mkdir(parents=True, exist_ok=True)
        # Convenience link so everything about the app is reachable from its folder. The browser itself
        # gets the real path: its sandbox can't see ~/.local/share/webapps, so it couldn't follow the link.
        # Re-pointed on re-runs, e.g. when the app is switched to another browser.
        link = app_dir / "profile"
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            link.symlink_to(profile)
        if browser == FIREFOX:
            cmd += [
                "--profile",
                str(profile),
                "--no-remote",
            ]  # --no-remote: don't hand off to a running Firefox
        else:
            cmd += [f"--user-data-dir={profile}"]
    cmd += ["--kiosk", url]

    # Chromium-based browsers need udev access to see controllers via the Gamepad API
    if browser != FIREFOX:
        subprocess.run(
            ["flatpak", "override", "--user", "--filesystem=/run/udev:ro", browser],
            check=True,
        )

    # Steam runs this script rather than the browser directly, so the URL never passes through the
    # .desktop Exec= line, where % and quotes would need escaping. Edit it to change the URL or flags
    # later; Steam picks that up without re-importing.
    launcher = app_dir / "launch.sh"
    launcher.write_text(f"#!/bin/sh\nexec {shlex.join(cmd)}\n")
    launcher.chmod(0o755)

    # Only needed for the one-time import. Used instead of importing launch.sh directly because Steam
    # takes the shortcut's name from Name= exactly, rather than from a file name.
    # Kept here so the app can be re-imported later; outside ~/.local/share/applications,
    # so it doesn't also show up in the Desktop Mode app menu.
    # Icon= holds the browser's Flatpak app ID, which is looked up in the icon theme like any icon name.
    desktop = app_dir / f"{slug}.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Icon={browser}\n"
        f'Exec="{launcher}"\n'
    )

    subprocess.run(["steamos-add-to-steam", str(desktop)], check=True)
    print(
        f"Added '{name}'. To file it in a collection: in Gaming Mode, "
        "press the Options button on it, then 'Add to'."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelled.")
