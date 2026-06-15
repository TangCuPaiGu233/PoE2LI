"""Shared SSH helpers for NAS / Tencent remote ops (scripts/nas, scripts/tencent)."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import paramiko

REPO_ROOT = Path(__file__).resolve().parents[1]

NAS_HOST = os.getenv("NAS_HOST", "192.168.110.26")
NAS_PORT = int(os.getenv("NAS_PORT", "2212"))
NAS_USER = os.getenv("NAS_USER", "skc")
NAS_PASS = os.getenv("NAS_PASS", "SKChaidao@123")
NAS_ROOT = os.getenv("NAS_ROOT", "/volume1/docker/PoE2LI")
DOCKER = os.getenv("NAS_DOCKER", "/usr/local/bin/docker")

TENCENT_HOST = os.getenv("TENCENT_HOST", "159.75.231.110")
TENCENT_PORT = int(os.getenv("TENCENT_PORT", "22"))
TENCENT_USER = os.getenv("TENCENT_USER", "root")
TENCENT_PASS = os.getenv("TENCENT_SSH_PASS", os.getenv("TENCENT_PASS", "SKChaidao123"))


def configure_utf8_stdio() -> None:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def connect_nas(*, timeout: int = 15) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(NAS_HOST, NAS_PORT, NAS_USER, NAS_PASS, timeout=timeout)
    return client


def connect_tencent(*, timeout: int = 20) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(TENCENT_HOST, TENCENT_PORT, TENCENT_USER, TENCENT_PASS, timeout=timeout)
    return client


def run(
    client: paramiko.SSHClient,
    cmd: str,
    *,
    timeout: int = 120,
    echo: bool = True,
    tail: int = 4000,
) -> tuple[int, str, str]:
    if echo:
        preview = cmd if len(cmd) <= 160 else cmd[:160] + "..."
        print(f"\n$ {preview}")
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    if echo and out.strip():
        text = out.rstrip()
        print(text[-tail:] if len(text) > tail else text)
    if echo and err.strip():
        text = err.rstrip()
        print("STDERR:", text[-800:] if len(text) > 800 else text)
    return code, out, err
