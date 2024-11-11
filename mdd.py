#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2024 Roman Gilg <romangg@manjaro.org>
# SPDX-License-Identifier: MIT
import os
import sys
import uuid
from os import write

import psutil
import hashlib
import platform
import subprocess
import json
import requests
import pytz
import shutil
import logging
import argparse
import tzlocal
import re
import distro
from datetime import datetime
from dateutil import parser as date_parser

inxi = None


def http_post_info(sys_info) -> bool:
    try:
        response = requests.post(
            "https://metrics-api.manjaro.org/send",
            json=sys_info,
            headers={"Content-Type": "application/json"},
            timeout=2,
        )

        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"submitting telemetry: {e}")
        return False


def json_beaut(input, sort_keys=False, indent=4):
    return json.dumps(input, indent=indent, sort_keys=sort_keys)


def prepare_inxi():
    global inxi

    if not shutil.which("inxi"):
        logging.warning(f"Did not find inxi. Data collection is limited.")
        return

    try:
        result = subprocess.run(
            ["inxi", "-Fxxx", "--output", "json", "--output-file", "print"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        inxi = json.loads(result.stdout.strip())
    except Exception as e:
        logging.error(f"calling inxi: {str(e)}")


def get_inxi_val(parent, code):
    for key in parent.keys():
        if key.endswith(code):
            return parent[key]
    return None


def get_inxi_main_cat(code):
    for item in inxi:
        for key in item.keys():
            if key.endswith(code):
                return item[key]
    return None


def get_command_output(cmd, default=None):
    try:
        result = subprocess.run(cmd, capture_output=True, check=True, shell=True)
        return result.stdout.decode("utf-8").strip()
    except subprocess.CalledProcessError as e:
        logging.info(
            f"Command '{cmd}' failed with: '{e.returncode}: {e.stderr.decode("utf-8")}'"
        )
        return default


def get_hashed_device_id():
    # Read the machine ID
    with open("/etc/machine-id", "r") as f:
        machine_id = f.read().strip()

    # Hash the machine ID using SHA-256 to anonymize it
    hashed_id = hashlib.sha256(machine_id.encode()).digest()

    # Convert the first 16 bytes of the hash to a UUID (version 5 UUID format)
    return str(uuid.UUID(bytes=hashed_id[:16], version=5))


def dualboot_os_prober_check():
    """
    Try to detect Windows installations using os-prober
    Requires root privileges or passwordless sudo rights
    """
    logging.info("...check for Windows with os-prober")

    if not shutil.which("os-prober"):
        raise Exception("os-prober is not installed")

    try:
        # Try direct execution first (if running as root)
        result = subprocess.run(
            ["os-prober"], capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            logging.info("os-prober call failed, trying elevated")

        # Check if the error output indicates permission issues
        error_indicators = [
            "you must be root",
            "Operation not permitted",
            "Permission denied",
        ]

        if result.returncode != 0 or any(
                indicator in result.stderr for indicator in error_indicators
        ):
            # Permission error detected, try sudo if available without password
            result = subprocess.run(
                ["sudo", "-n", "os-prober"], capture_output=True, text=True, timeout=30
            )

        if result.returncode != 0:
            raise Exception("can not elevate os-prober call")

        # Check for successful execution and valid output
        if result.stdout.strip():
            for line in result.stdout.splitlines():
                if "windows boot manager" in line.lower():
                    logging.info("Found Windows with os-prober:", line)
                    return True
        logging.info(
            "No Windows partition found with os-prober. Assuming single-boot system."
        )
        return False

    except subprocess.TimeoutExpired:
        raise OSError("os-prober timed out")
    except Exception as e:
        raise OSError(f"os-prober failed: {str(e)}")


def dualboot_lsblk_check(min_size_gb=20):
    """
    Get all partitions using lsblk command, including unmounted ones
    """
    logging.info("...check for Windows dualboot with lsblk")

    min_size_bytes = min_size_gb * 1024 * 1024 * 1024

    cmd = ["lsblk", "-b", "-J", "-o", "NAME,SIZE,FSTYPE,MOUNTPOINT"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise OSError(f"Error running lsblk: code {result.returncode}")

    data = json.loads(result.stdout)

    def process_device(device):
        # Check the device itself
        if (
                str(device.get("fstype", "")).lower() == "ntfs"
                and int(device.get("size", 0)) >= min_size_bytes
        ):
            logging.info(
                f"Assuming Windows partition: '/dev/{device['name']}' ({int(device['size']) / (1024 ** 3):.0f} GB)"
            )
            return True

        # Check children (partitions)
        for child in device.get("children", []):
            if process_device(child):
                return True

    # Process all devices
    for device in data.get("blockdevices", []):
        if process_device(device):
            return True

    logging.info(
        "No partition found with Windows characteristics. Assuming single-boot system."
    )
    return False


def check_windows_dualboot():
    """Checks if the system has Windows partitions, indicating dual boot."""
    logging.info("...check for Windows dualboot")
    try:
        logging.info("Attempting to use os-prober...")
        return dualboot_os_prober_check()
    except Exception as e:
        logging.info(str(e))
        try:
            logging.info("Falling back to partition analysis...")
            return dualboot_lsblk_check()
        except Exception as e:
            logging.error("trying to run lsblk:", str(e))
            return False


def get_compositor():
    """Returns the compositor currently in use on a Linux system."""
    compositors = ["sway", "compiz", "mutter", "kwin", "xfwm4", "picom", "compton"]
    try:
        output = subprocess.check_output("ps -e", shell=True, text=True)
        for compositor in compositors:
            if compositor in output:
                return compositor

    except Exception as e:
        logging.error("getting compositor:", e)
        pass

    return "unknown"


def get_install_date():
    """Returns the installation date of the Linux system as a timestamp."""
    date = "unknown"
    try:
        # Using `stat` to get the creation time of the root directory
        timestamp = int(
            subprocess.check_output("stat -c %W /", shell=True, text=True).strip()
        )

        date = datetime.fromtimestamp(timestamp, pytz.UTC).isoformat()

    except Exception as e:
        logging.error(f"retrieving installation date: {e}")
        pass

    return date


def get_system_info():
    logging.info("...get system info")

    common_data = {
        "kernel": platform.release(),
        "form_factor": get_command_output("hostnamectl chassis"),
        "install_date": get_install_date(),
    }

    def get_dmi(file_name: str):
        return get_command_output("cat /sys/devices/virtual/dmi/id/" + file_name)

    if platform.machine() == "aarch64":
        product_name = get_command_output("cat /proc/device-tree/model").replace(
            chr(0), ""
        )
        device_compat = (
            get_command_output("cat /proc/device-tree/compatible")
            .replace(chr(0), " ")
            .split(",")
        )

        def get_compat(pos):
            return device_compat[pos].strip() if len(device_compat) > pos else ""

        return common_data | {
            "product_name": product_name,
            "product_family": get_compat(2),
            "sys_vendor": get_compat(0),
            "board_name": get_compat(1),
        }

    return common_data | {
        "product_name": get_dmi("product_name"),
        "product_family": get_dmi("product_family"),
        "sys_vendor": get_dmi("sys_vendor"),
        "board_name": get_dmi("board_name"),
    }


def get_boot_info():
    logging.info("...get boot info")
    return {
        "uefi": os.path.isdir("/sys/firmware/efi"),
        "uptime_seconds": int(float(get_command_output("cat /proc/uptime").split()[0])),
    }


def get_cpu_info():
    logging.info("...get cpu info")
    cpu_model = ""
    cpu_model2 = ""

    def write_cpu_model(val):
        nonlocal cpu_model
        if val not in (None, "", "N/A"):
            cpu_model = val

    if inxi:
        inxi_info = get_inxi_main_cat("#CPU")

        for item in inxi_info:
            write_cpu_model(get_inxi_val(item, "#model"))
            write_cpu_model(get_inxi_val(item, "#variant"))
            write_cpu_model(get_inxi_val(item, "#variant-1"))

            if val := get_inxi_val(item, "#variant-2"):
                cpu_model2 = "/" + val

        cpu_model += cpu_model2

    if not cpu_model:
        # Fallback to lscpu in case we did not get info from inxi
        try:
            lines = [
                line
                for line in get_command_output("lscpu").split("\n")
                if "Model name" in line
            ]

            cpu_model = lines[0].split(":")[1].strip()
            if len(lines) > 1:
                cpu_model += "/" + lines[1].split(":")[1].strip()

        except IndexError as e:
            pass

    info = {
        "arch": platform.machine(),
        "model": cpu_model,
        "cores": psutil.cpu_count(logical=False),
        "threads": psutil.cpu_count(logical=True),
    }

    return info


def get_memory_info():
    logging.info("...get memory info")
    return {
        "ram_gb": psutil.virtual_memory().total / (1024 ** 3),
        "swap_gb": psutil.swap_memory().total / (1024 ** 3),
    }


def get_graphics_info():
    logging.info("...get graphics info")

    gpus = []
    outputs = []
    compositor = get_compositor()
    dri = None

    if inxi:
        inxi_info = get_inxi_main_cat("#Graphics")

        for item in inxi_info:
            if get_inxi_val(item, "#Display"):
                compositor = get_inxi_val(item, "#compositor")
                dri = get_inxi_val(item, "#dri")

            if get_inxi_val(item, "#Device") and get_inxi_val(item, "#type") != "USB":
                gpu_info = {
                    "vendor": get_inxi_val(item, "#vendor"),
                    "model": get_inxi_val(item, "#Device"),
                    "driver": get_inxi_val(item, "#driver"),
                }
                gpus.append(gpu_info)

            if monitor_name := get_inxi_val(item, "#Monitor"):
                refresh = get_inxi_val(item, "#hz")
                dpi = get_inxi_val(item, "#dpi")
                size = get_inxi_val(item, "#size")
                mapped = get_inxi_val(item, "#mapped")
                info = {
                    "model": get_inxi_val(item, "#model"),
                    "res": get_inxi_val(item, "#res"),
                    "refresh": float(refresh) if refresh else None,
                    "dpi": float(dpi) if dpi else None,
                    "size": (size.split(" ")[0].replace("mm", "") if size else None),
                    "mapped": mapped if mapped else monitor_name,
                }
                outputs.append(info)

    # Try fallbacks for any data that inxi was not capable of gathering.
    compositor = compositor if compositor else get_compositor()

    if len(gpus) == 0:
        glxinfo = (
            get_command_output("glxinfo | grep 'OpenGL vendor'")
            if shutil.which("glxinfo")
            else None
        )
        gpu_info = {
            "vendor": "",
            "model": get_command_output("lspci | grep -i vga | cut -d ':' -f3"),
            "driver": (glxinfo.split(": ")[-1] if glxinfo else None),
        }
        gpus.append(gpu_info)

    # Run xrandr command and capture output
    if xrandr_output := shutil.which("xrandr") and get_command_output("xrandr"):
        mapped = None
        inxi_output = None

        for line in xrandr_output.split("\n"):
            if re.match(r"^(\S+) disconnected", line):
                mapped = None
                continue

            if re.match(r"^(\S+) connected", line):
                # When we encounter a line that contains the word 'connected', we mark the beginning
                # of a new connected output and continue with the line afterwards.
                mapped = line.split(" ")
                inxi_output = next(
                    (output for output in outputs if output["mapped"] == mapped[0]),
                    None,
                )

                continue

            mode_match = re.match(r"^ {3}(\d+x\d+).*\s([\d.]+)\*", line)
            if not mode_match:
                # Inactive mode
                continue

            if not mapped:
                # A mode can only be active for mapped outputs
                raise Exception(f"matched a mode '{mode_match}' without being mapped")

            resolution = mode_match.group(1)
            try:
                refresh = float(mode_match.group(2))
            except ValueError:
                refresh = None

            # Try to get size from connected line.
            size = ""
            if len(mapped) > 2:
                try:
                    width = int(mapped[-3].replace("mm", ""))
                    height = int(mapped[-1].replace("mm", ""))
                    size = str(width) + "x" + str(height)
                except ValueError as e:
                    logging.error(f"xrandr size for '{' '.join(mapped)}': {str(e)}")
                    pass

            if inxi_output:
                # If some of the data is missing from the inxi call, add it. Otherwise we prefer
                # the inxi output.
                for key, val in [
                    ("res", resolution),
                    ("refresh", refresh),
                    ("size", size),
                ]:
                    if inxi_output[key] in (None, "", "N/A"):
                        inxi_output[key] = val
            else:
                outputs.append(
                    {
                        "model": "",
                        "res": resolution,
                        "refresh": refresh,
                        "dpi": None,
                        "size": size,
                        "mapped": mapped[0],
                    }
                )

    return {
        "comp": compositor,
        "dri": dri,
        "gpus": gpus,
        "outputs": outputs,
    }


def get_audio_info():
    logging.info("...get audio info")

    info = {"servers": []}

    def is_installed(pkg):
        try:
            result = subprocess.run(
                ["pacman", "-Qi", pkg], capture_output=True, text=True
            )
            return result.returncode == 0
        except Exception as e:
            logging.error("checking install:", e)
            return False

    pulseaudio_active = False
    found_pipewire = False

    sudo = ["", ""]
    if os.geteuid() == 0:
        user = get_command_output("last -wn1").split("\n")[0].split(" ")[0]
        user_id = get_command_output("su - " + user + " -c 'id -u'")
        sudo = ["su - " + user + " -c 'XDG_RUNTIME_DIR=/run/user/" + user_id + " ", "'"]

    if is_installed("pulseaudio"):
        pulse_info = {
            "name": "PulseAudio",
            "active": False,
        }

        # pactl is a dependency of pulseaudio
        pulse_out = get_command_output(sudo[0] + "LANG=C pactl info" + sudo[1]).split(
            "\n"
        )
        for line in pulse_out:
            if line.startswith("Server Name"):
                name = line.split(" ", 2)[-1].lower()

                if name == "pulseaudio":
                    pulse_info["active"] = True
                    pulseaudio_active = True

                if "pipewire" in name:
                    # We know Pipewire is installed and active.
                    info["servers"].append(
                        {
                            "name": "PipeWire",
                            "active": True,
                        }
                    )
                    found_pipewire = True
                break

        info["servers"].append(pulse_info)

    if not found_pipewire and is_installed("pipewire"):
        # Check if PipeWire is active (PulseAudio might not be installed)
        pipew_active = False
        if pipew_out := get_command_output(sudo[0] + "LANG=C pw-cli info 0" + sudo[1]):
            pipew_active = 'core.daemon = "true"' in pipew_out
        info["servers"].append(
            {
                "name": "PipeWire",
                "active": pipew_active and not pulseaudio_active,
            }
        )
    return info


def get_disks_metrics():
    """Returns metrics about the disks and partitions containing the root and /home mounts."""

    def traverse(block, results, min_size, is_crypt):
        is_crypt = (
                is_crypt
                or block.get("type") == "crypt"
                or block.get("fstype") == "crypto_LUKS"
        )
        min_size = min(min_size, block.get("size"))

        def get_mount_data():
            return {
                "size_gb": min_size / (1024 ** 3),
                "fstype": block.get("fstype"),
                "crypt": is_crypt,
            }

        if block.get("mountpoints"):
            # Check for root or home partition mountpoints
            has_root = False

            if "/" in block["mountpoints"]:
                results["root"] = get_mount_data()
                has_root = True

            if "/home" in block["mountpoints"]:
                data = get_mount_data()
                if has_root:
                    data["subvol"] = True
                results["home"] = data

        # If it's a disk with children, traverse each child
        if "children" in block:
            for child in block["children"]:
                traverse(child, results, min_size, is_crypt)

    disks = []
    lsblk_data = json.loads(
        get_command_output("lsblk -Jbo NAME,TYPE,SIZE,FSTYPE,MOUNTPOINTS")
    )

    for device in lsblk_data["blockdevices"]:
        size = device.get("size")
        results = {
            "size_gb": size / (1024 ** 3),
            "root": None,
            "home": None,
        }
        traverse(device, results, size, False)

        if results["root"] or results["home"]:
            disks.append(results)

    return disks


def get_disk_info():
    logging.info("...get disk info")
    return {
        "disks": get_disks_metrics(),
        "windows": check_windows_dualboot(),
    }


def get_locale_info():
    logging.info("...get locale info")

    try:
        timezone = str(tzlocal.get_localzone())
    except Exception as e:
        logging.warning(f"timezone: '{str(e)}'")
        timezone = "error"

    return {
        "region": get_command_output(
            "localectl status | grep 'System Locale'", ""
        ).split("=")[-1],
        "language": get_command_output("echo $LANG", "").split("_")[0],
        "timezone": timezone,
    }


def get_pacman_mirrors_info():
    logging.info("...get pacman-mirrors info")

    if not shutil.which("pacman-mirrors"):
        return {"total": None, "ok": None, "country_config": ""}

    try:
        country_config = get_command_output("pacman-mirrors --country-config")
        output = get_command_output("pacman-mirrors --status")

        # Initialize counters for total and OK mirrors
        total_mirrors = 0
        ok_mirrors = 0

        output = subprocess.run(
            ["pacman-mirrors", "--status"], capture_output=True, text=True, timeout=30
        ).stdout

        # Parse mirror status from output
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("Mirror #"):
                total_mirrors += 1
                if "OK" in line:
                    ok_mirrors += 1

        return {
            "total": total_mirrors,
            "ok": ok_mirrors,
            "country_config": country_config,
        }

    except subprocess.CalledProcessError as e:
        logging.error(f"running pacman-mirrors: {e}")
        return {"total": None, "ok": None, "country_config": ""}


def get_package_info():
    logging.info("...get package info")

    try:
        output = get_command_output(
            'grep -a "\\[ALPM\\] upgraded" /var/log/pacman.log | tail -1'
        )
        update_time = date_parser.parse(output.split(" ")[0].strip("[]")).isoformat()
    except Exception as e:
        logging.error(f"getting update time: '{str(e)}'")
        logging.error(f"input was: '{output}'")
        update_time = "unknown"

    flatpaks = 0
    if shutil.which("flatpak"):
        flatpaks = int(get_command_output("flatpak list --app | wc -l", "0"))

    return {
        "last_update": update_time,
        "branch": get_command_output("pacman-mirrors -G", "unknown"),
        "pkgs": int(get_command_output("pacman -Q | wc -l")),
        "foreign_pkgs": int(get_command_output("pacman -Qm | wc -l")),
        "pkgs_update_pending": int(get_command_output("pacman -Qu | wc -l")),
        "flatpaks": flatpaks,
        "pacman_mirrors": get_pacman_mirrors_info(),
    }


def get_desktop_info():
    logging.info("...get desktop info")

    info = {"cli": os.getenv("SHELL")}

    if inxi:
        inxi_system_info = get_inxi_main_cat("#System")

        for item in inxi_system_info:
            desktop = get_inxi_val(item, "#Desktop")
            if desktop:
                info |= {
                    "gui": desktop,
                    "dm": get_inxi_val(item, "#dm"),
                    "wm": get_inxi_val(item, "#wm"),
                }
                break

        inxi_graphics_info = get_inxi_main_cat("#Graphics")
        for item in inxi_graphics_info:
            display = get_inxi_val(item, "#Display")
            if display:
                info |= {
                    "display": display,
                    "display_with": get_inxi_val(item, "#with"),
                }
                break
    else:
        info |= {
            "gui": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
            "dm": None,
            "wm": get_compositor(),
            "display": (
                "wayland"
                if os.getenv("XDG_SESSION_TYPE") == "wayland"
                else "x11" if os.getenv("XDG_SESSION_TYPE") == "x11" else "unknown"
            ),
            "display_with": None,
        }

    return info


def get_device_data(telemetry: bool):
    data = {
        "meta": {
            "version": 1,
            "timestamp": datetime.now(pytz.UTC).isoformat(),
            "device_id": get_hashed_device_id(),
            "distro_id": distro.id(),
        }
    }

    if not telemetry:
        return data

    data["meta"] |= {
        "release": distro.version(),
        "inxi": inxi is not None,
    }

    data |= {
        "system": get_system_info(),
        "boot": get_boot_info(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "graphics": get_graphics_info(),
        "audio": get_audio_info(),
        "disk": get_disk_info(),
        "locale": get_locale_info(),
        "package": get_package_info(),
        "desktop": get_desktop_info(),
    }

    return data


# Add ANSI color codes
HEADER = "\033[95m"  # Magenta for headers
OKBLUE = "\033[94m"  # Blue for informational messages
BOLD = "\033[1m"  # Bold text
ENDC = "\033[0m"  # Reset to normal


def main():
    # Set up command-line argument parsing
    parser = argparse.ArgumentParser(
        description="MDD enables Manjaro users to support the project by donating anonymized data."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry-run without sending data",
    )
    parser.add_argument(
        "--log",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    parser.add_argument(
        "--disable-telemetry",
        action="store_false",
        dest="telemetry",
        help="Only count the device without sending data",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.WARNING),
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    print(f"{BOLD}{HEADER}Welcome to MDD - The Manjaro Data Donor{ENDC}")
    print(f"{OKBLUE}Preparing data submission...{ENDC}")

    if os.getenv("MDD_DISABLE_INXI"):
        logging.info(f"Skipping inxi because MDD_DISABLE_INXI was set.")
    else:
        prepare_inxi()

    data = get_device_data(args.telemetry)

    separator = f"{BOLD}{HEADER}{'-' * 42}{ENDC}"
    print("\n" + separator)

    if args.dry_run:
        print(" " * 1 + f"{BOLD}Would send the following data (dry run){ENDC}")
    else:
        print(" " * 8 + f"{BOLD}Sending the following data{ENDC}")

    print(separator)
    print(json_beaut(data))
    print(separator + "\n")

    if args.dry_run:
        print("Note: Skipping data submission because of dry run.")
        return

    else:
        success = http_post_info(data)
        if success:
            print("Succesful sent at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        else:
            exit(1)


if __name__ == "__main__":
    main()
