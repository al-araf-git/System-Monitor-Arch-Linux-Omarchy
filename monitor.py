#!/usr/bin/env python3
"""Dependency-free system monitor data provider for the Omarchy bar widget."""

from __future__ import annotations

import glob
import json
import os
import subprocess
import time


def read_cpu_times() -> tuple[int, int] | None:
    try:
        fields = list(map(int, open("/proc/stat", encoding="ascii").readline().split()[1:]))
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return sum(fields), idle
    except (OSError, ValueError, IndexError):
        return None


def cpu_usage() -> int | None:
    before = read_cpu_times()
    if before is None:
        return None
    time.sleep(0.15)
    after = read_cpu_times()
    if after is None:
        return None
    total, idle = after[0] - before[0], after[1] - before[1]
    return round(100 * (total - idle) / total) if total > 0 else 0


def temperature(path: str) -> float | None:
    try:
        value = float(open(path, encoding="ascii").read().strip())
        return value / 1000 if abs(value) > 1000 else value
    except (OSError, ValueError):
        return None


def cpu_temperature() -> float | None:
    candidates: list[tuple[int, float]] = []
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            name = open(os.path.join(hwmon, "name"), encoding="ascii").read().strip().lower()
        except OSError:
            name = ""
        for input_path in glob.glob(os.path.join(hwmon, "temp*_input")):
            value = temperature(input_path)
            if value is None or not -10 <= value <= 130:
                continue
            stem = input_path[:-6]
            try:
                label = open(stem + "_label", encoding="ascii").read().strip().lower()
            except OSError:
                label = ""
            hint = f"{name} {label}"
            priority = 0 if any(word in hint for word in ("cpu", "package", "tctl", "tdie", "core")) else 1
            candidates.append((priority, value))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    # Thermal zones are a useful fallback on laptops and embedded systems.
    zones: list[float] = []
    for path in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        value = temperature(path)
        if value is not None and -10 <= value <= 130:
            zones.append(value)
    return max(zones) if zones else None


def fan_readings(hwmons: list[str]) -> list[tuple[str, int]]:
    """Read fan speeds exported by hwmon, keeping the kernel's label when available."""
    readings: list[tuple[str, int]] = []
    for hwmon in hwmons:
        try:
            name = open(os.path.join(hwmon, "name"), encoding="ascii").read().strip()
        except OSError:
            name = ""
        for path in glob.glob(os.path.join(hwmon, "fan*_input")):
            try:
                rpm = int(open(path, encoding="ascii").read().strip())
            except (OSError, ValueError):
                continue
            stem = path[:-6]
            try:
                label = open(stem + "_label", encoding="ascii").read().strip()
            except OSError:
                label = ""
            readings.append((label or name or "Fan", rpm))
    return readings


def cpu_fan_speed() -> int | None:
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        for label, rpm in fan_readings([hwmon]):
            if "cpu" in label.lower():
                return rpm
    return None


def gpu_fan_speed() -> str | None:
    # NVIDIA reports fan speed as a percentage rather than RPM.
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=fan.speed", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.5, check=True,
        )
        value = result.stdout.splitlines()[0].strip()
        if value.lower() not in ("[n/a]", "n/a"):
            return f"{int(float(value))}%"
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        pass

    # AMD and Intel drivers may expose GPU fan tachometers through DRM hwmon.
    for hwmon in glob.glob("/sys/class/drm/card[0-9]*/device/hwmon/hwmon*"):
        readings = fan_readings([hwmon])
        if readings:
            return f"{readings[0][1]} RPM"
    return None


def memory_usage() -> tuple[int, int, int] | None:
    try:
        values = {}
        with open("/proc/meminfo", encoding="ascii") as stream:
            for line in stream:
                key, value = line.split(":", 1)
                values[key] = int(value.split()[0])
        total = values["MemTotal"]
        used = total - values.get("MemAvailable", values.get("MemFree", 0))
        return round(100 * used / total), round(used / 1024), round(total / 1024)
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return None


def gpu_info() -> tuple[str | None, float | None, str | None]:
    # NVIDIA's official CLI is the most reliable source when installed.
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.5, check=True,
        )
        line = result.stdout.splitlines()[0]
        name, usage, temp = [part.strip() for part in line.split(",", 2)]
        return str(int(float(usage))), float(temp), name
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        pass

    # Linux DRM exports utilization for many AMD and Intel GPUs.
    for busy_path in glob.glob("/sys/class/drm/card[0-9]*/device/gpu_busy_percent"):
        try:
            usage = str(int(open(busy_path, encoding="ascii").read().strip()))
        except (OSError, ValueError):
            continue
        device = os.path.dirname(busy_path)
        temp = None
        for path in glob.glob(os.path.join(device, "hwmon", "hwmon*", "temp*_input")):
            temp = temperature(path)
            if temp is not None:
                break
        return usage, temp, "GPU"

    # Temperature sensors can exist even when the driver exports no busy counter.
    for hwmon in glob.glob("/sys/class/drm/card[0-9]*/device/hwmon/hwmon*"):
        for path in glob.glob(os.path.join(hwmon, "temp*_input")):
            temp = temperature(path)
            if temp is not None and -10 <= temp <= 130:
                return None, temp, "GPU"

    return None, None, None


def main() -> None:
    cpu = cpu_usage()
    cpu_temp = cpu_temperature()
    gpu, gpu_temp, gpu_name = gpu_info()
    cpu_fan = cpu_fan_speed()
    gpu_fan = gpu_fan_speed()
    mem = memory_usage()

    text_parts = []
    if cpu is not None:
        text_parts.append(f" {cpu}%")
    if cpu_temp is not None:
        text_parts.append(f" {cpu_temp:.0f}°")
    if gpu is not None:
        text_parts.append(f"󰢮 {gpu}%")
    if gpu_temp is not None:
        text_parts.append(f"GPU {gpu_temp:.0f}°")
    details = []
    details.append(f"CPU usage: {cpu}%" if cpu is not None else "CPU usage: unavailable")
    details.append(f"CPU temperature: {cpu_temp:.1f}°C" if cpu_temp is not None else "CPU temperature: unavailable")
    if gpu is not None:
        details.append(f"{gpu_name or 'GPU'} usage: {gpu}%")
    else:
        details.append("GPU usage: unavailable (install/configure nvidia-smi or expose DRM gpu_busy_percent)")
    details.append(f"GPU temperature: {gpu_temp:.1f}°C" if gpu_temp is not None else "GPU temperature: unavailable")
    details.append(f"CPU fan: {cpu_fan} RPM" if cpu_fan is not None else "CPU fan: unavailable")
    details.append(f"GPU fan: {gpu_fan}" if gpu_fan is not None else "GPU fan: unavailable")
    if mem is not None:
        details.append(f"Memory: {mem[1]} / {mem[2]} MiB ({mem[0]}%)")
    try:
        load = open("/proc/loadavg", encoding="ascii").read().split()[:3]
        details.append(f"Load average: {' '.join(load)}")
    except OSError:
        pass
    try:
        uptime = float(open("/proc/uptime", encoding="ascii").read().split()[0])
        hours = int(uptime // 3600)
        days, hours = divmod(hours, 24)
        minutes = int(uptime % 3600 // 60)
        details.append(f"Uptime: {days}d {hours}h {minutes}m" if days else f"Uptime: {hours}h {minutes}m")
    except (OSError, ValueError, IndexError):
        pass

    level = "critical" if (cpu_temp is not None and cpu_temp >= 90) or (gpu_temp is not None and gpu_temp >= 90) else "normal"
    percent = cpu if cpu is not None else 0
    print(json.dumps({"text": "  ".join(text_parts) or "System info unavailable",
                      "tooltip": "\n".join(details), "class": level,
                      "percentage": percent}, ensure_ascii=False))


if __name__ == "__main__":
    main()
