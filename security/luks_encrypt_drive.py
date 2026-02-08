#!/usr/bin/env python3

#
#   Apache License 2.0
#
#   Copyright (c) 2026, Mattias Aabmets
#
#   The contents of this file are subject to the terms and conditions defined in the License.
#   You may not use, modify, or distribute this file except in compliance with the License.
#
#   SPDX-License-Identifier: Apache-2.0
#

import os
import sys
import pwd
import logging
import secrets
import textwrap
import argparse
import subprocess
import typing as t
from pathlib import Path
from datetime import datetime

if t.TYPE_CHECKING:
    import xkcdpass.xkcd_password as xpw
else:
    try:
        import xkcdpass.xkcd_password as xpw
    except ImportError:
        xpw = None


__all__ = ["LuksEncryptor", "main"]


logger = logging.getLogger("LUKS-ENCRYPT-DRIVE")


class LuksEncryptor:
    def __init__(self, device: str, label: str = "data"):
        self.device_path = Path(device).resolve()
        self.label = label
        self.crypt_name = f"{label}_crypt"
        self.mount_point = Path(f"/mnt/{label}")
        self.calling_user = self._get_calling_user()
        self.user_home = Path(pwd.getpwnam(self.calling_user).pw_dir)
        self.symlink_path = self.user_home / label
        self.service_name = f"{label}-crypt.service"
        self.script_file = Path("/etc/luks-scripts") / f"{self.service_name}.sh"
        self.key_file = Path("/etc/luks-keys") / f"{label}.key"
        self.script_file.parent.mkdir(parents=True, exist_ok=True)
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.pass_phrase: str | None = None
        self.backup_path: Path | None = None

        self._validate_label_safety()
        self._validate_device_safety()

    @staticmethod
    def _get_calling_user() -> str:
        return os.environ.get("SUDO_USER") or pwd.getpwuid(os.getuid())[0]

    def _validate_label_safety(self) -> None:
        label = self.label
        if not all(c.isalnum() or c == "_" for c in label):
            raise SystemExit(f"ERROR: Label '{label}' should contain only alphanumeric characters and underscores.")

        try:
            if out := subprocess.check_output(["blkid", "-L", label], text=True).strip():
                raise SystemExit(f"ERROR: Filesystem with label '{label}' already exists on {out}")
        except subprocess.CalledProcessError:
            pass

        if self.mount_point.exists():
            raise SystemExit(f"ERROR: Mount point {self.mount_point} already exists")

        service = f"{label}-crypt.service"
        if Path(f"/etc/systemd/system/{service}").exists():
            raise SystemExit(f"ERROR: Systemd service {service} already exists")

        logger.info(f"Label validation passed for '{label}'")

    def _validate_device_safety(self) -> None:
        if not self.device_path.exists() or not self.device_path.is_block_device():
            raise SystemExit(f"ERROR: {self.device_path} does not exist or is not a block device")

        critical_paths = [
            Path("/boot").resolve(),
            Path("/root").resolve(),
            Path(__file__).resolve(),
        ]
        for crit in critical_paths:
            try:
                if self.device_path.samefile(crit):
                    raise SystemExit(f"ERROR: Refusing to encrypt {self.device_path} — matches critical path {crit}")
            except OSError:
                pass

        logger.info(f"Device check passed: {self.device_path} is safe to encrypt.")

    def _is_container_open(self) -> bool:
        mapper_path = Path(f"/dev/mapper/{self.crypt_name}")
        return mapper_path.exists() and mapper_path.is_block_device()

    def generate_passphrase(self) -> None:
        if xpw is None:
            raise SystemExit("xkcdpass not available. Install it with: sudo python3 -m pip install xkcdpass")

        wordlist = xpw.generate_wordlist(wordfile=xpw.locate_wordfile())
        self.pass_phrase = xpw.generate_xkcdpassword(wordlist, numwords=6, delimiter="-")
        logger.info(f"\nGenerated initial passphrase: {self.pass_phrase}")
        logger.info("!!! SAVE THIS PASSPHRASE IN A SAFE PLACE !!!\n")

    def confirm_destruction(self) -> None:
        logger.info(f"WARNING: This will IRREVERSIBLY DESTROY all data on {self.device_path}")
        if input("Type YES in capital letters to continue: ").strip() != "YES":
            logger.info("Aborted.")
            raise SystemExit(0)

    def format_luks(self) -> None:
        logger.info("Formatting with LUKS2...")
        subprocess.run(
            ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", str(self.device_path)],
            input=(self.pass_phrase + "\n").encode(),
            check=True,
        )

    def backup_luks_header(self) -> None:
        backups_dir = self.user_home / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.backup_path = backups_dir / f"{self.label}-luks-header-{date_str}.bak"

        logger.info(f"Backing up LUKS header to: {self.backup_path}")
        subprocess.run(
            ["cryptsetup", "luksHeaderBackup", str(self.device_path), "--header-backup-file", str(self.backup_path)],
            check=True,
        )
        self.backup_path.chmod(0o644)
        os.chown(
            path=str(self.backup_path),
            uid=pwd.getpwnam(self.calling_user).pw_uid,
            gid=pwd.getpwnam(self.calling_user).pw_gid
        )

    def open_container(self, use_keyfile: bool = False) -> None:
        if self._is_container_open():
            logger.info(f"Container {self.crypt_name} is already open → closing it first...")
            try:
                subprocess.run(
                    ["cryptsetup", "luksClose", self.crypt_name],
                    check=True,
                    capture_output=True,
                    text=True
                )
                logger.info(f"Successfully closed existing mapping {self.crypt_name}")
            except subprocess.CalledProcessError as ex:
                raise SystemExit(f"Cannot clean up existing open container: {ex}")

        cmd = ["cryptsetup", "luksOpen", str(self.device_path), self.crypt_name]
        if use_keyfile:
            cmd.extend(["--key-file", str(self.key_file)])
            logger.info(f"Opening container {self.crypt_name} with keyfile...")
            subprocess.run(cmd, check=True)
        else:
            logger.info(f"Opening container {self.crypt_name} with passphrase...")
            subprocess.run(cmd, input=(self.pass_phrase + "\n").encode(), check=True)

    def create_filesystem(self) -> None:
        logger.info(f"Creating ext4 filesystem with label '{self.label}'...")
        subprocess.run(["mkfs.ext4", "-L", self.label, f"/dev/mapper/{self.crypt_name}"], check=True)

    def create_keyfile(self) -> None:
        keydir = self.key_file.parent
        keydir.mkdir(parents=True, exist_ok=True)
        self.key_file.write_bytes(secrets.token_bytes(512))
        self.key_file.chmod(0o600)
        os.chown(path=str(self.key_file), uid=0, gid=0)
        logger.info(f"Created secure keyfile: {self.key_file}")

    def add_keyfile_to_luks(self) -> None:
        logger.info("Adding keyfile as additional unlock slot...")
        subprocess.run(
            ["cryptsetup", "luksAddKey", str(self.device_path), str(self.key_file)],
            input=(self.pass_phrase + "\n").encode(),
            check=True,
        )

    def setup_mount_and_symlink(self) -> None:
        logger.info("Mounting filesystem and creating symlink...")
        self.mount_point.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", f"/dev/mapper/{self.crypt_name}", str(self.mount_point)], check=True)

        if self.symlink_path.exists() or self.symlink_path.is_symlink():
            logger.info(f"Removing existing symlink: {self.symlink_path}")
            self.symlink_path.unlink(missing_ok=True)
        self.symlink_path.symlink_to(self.mount_point)
        logger.info(f"Created symlink: {self.symlink_path} → {self.mount_point}")

    def add_fstab_entry(self) -> None:
        inner_uuid = subprocess.check_output(
            ["blkid", "-s", "UUID", "-o", "value", f"/dev/mapper/{self.crypt_name}"]
        ).decode().strip()

        fstab_line = f"UUID={inner_uuid}   {self.mount_point}   ext4   defaults,noauto   0   2\n"
        with open("/etc/fstab", "a") as f:
            f.write(fstab_line)
        logger.info("Added entry to /etc/fstab")

    def create_helper_script(self) -> None:
        outer_uuid = subprocess.check_output(
            ["blkid", "-s", "UUID", "-o", "value", str(self.device_path)]
        ).decode().strip()
        stable_device = f"/dev/disk/by-uuid/{outer_uuid}"
        script_content = textwrap.dedent(f"""\
            #!/bin/sh
            set -e

            LABEL="{self.label}"
            CRYPT_NAME="{self.crypt_name}"
            KEYFILE="{self.key_file}"
            MOUNT_POINT="{self.mount_point}"
            STABLE_DEVICE="{stable_device}"

            if [ "$1" = "start" ]; then
                # Wait max 10 s for the bare-mounted drive (200 ms steps)
                for i in $(seq 50); do
                    if [ -b "$STABLE_DEVICE" ]; then
                        break
                    elif [ $i -eq 50 ]; then
                        echo "ERROR: Device $STABLE_DEVICE did not appear within 10 seconds" >&2
                        exit 1
                    fi
                    sleep 0.2
                done
                cryptsetup luksOpen --key-file "$KEYFILE" "$STABLE_DEVICE" "$CRYPT_NAME"
                mount "$MOUNT_POINT"

            elif [ "$1" = "stop" ]; then
                umount "$MOUNT_POINT" || true
                cryptsetup luksClose "$CRYPT_NAME" || true

            else
                echo "Usage: $0 start|stop" >&2
                exit 1
            fi
        """)
        self.script_file.write_text(script_content)
        self.script_file.chmod(0o755)
        logger.info(f"Created helper script: {self.script_file.as_posix()}")

    def create_systemd_service(self) -> None:
        self.create_helper_script()
        script_path = self.script_file.as_posix()

        service_path = Path(f"/etc/systemd/system/{self.service_name}")
        service_content = textwrap.dedent(f"""\
            [Unit]
            Description=Unlock and Mount LUKS {self.label} drive
            After=local-fs-pre.target

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            ExecStart={script_path} start
            ExecStop={script_path} stop

            [Install]
            WantedBy=multi-user.target
        """)
        service_path.write_text(service_content)

        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", self.service_name], check=True)
        logger.info(f"Created and enabled systemd service {self.service_name}")

    def cleanup(self) -> None:
        subprocess.run(["umount", self.mount_point.as_posix()], check=True)
        subprocess.run(["cryptsetup", "luksClose", self.crypt_name], check=True)
        logger.info("Temporary mount and LUKS mapping closed.")

    def print_setup_summary(self) -> None:
        logger.info("\n=== SETUP COMPLETE ===")
        logger.info(f"Device encrypted:           {self.device_path.as_posix()}")
        logger.info(f"Filesystem label:           {self.label}")
        logger.info(f"Passphrase (save it!):      {self.pass_phrase}")
        logger.info(f"Keyfile:                    {self.key_file.as_posix()}")
        logger.info(f"LUKS header backup:         {self.backup_path.as_posix()}")
        logger.info(f"Mountpoint:                 {self.mount_point.as_posix()}")
        logger.info(f"Symlink in home:            {self.symlink_path.as_posix()}")
        logger.info(f"Service script:             {self.script_file.as_posix()}")
        logger.info(f"Systemd service:            {self.label}-crypt.service (enabled)")
        logger.info("fstab entry added (noauto)")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set up LUKS encryption for a bare-mounted physical drive in WSL"
    )
    parser.add_argument(
        "device",
        help="The block device to encrypt (e.g. /dev/sdd)"
    )
    parser.add_argument(
        "--label",
        default="data",
        help="Label for the target filesystem (default: data)"
    )
    parser.add_argument(
        "--no-reinstall",
        action="store_true",
        help=argparse.SUPPRESS
    )
    return parser.parse_args()


def handle_missing_xkcdpass() -> None:
    """Attempt to install xkcdpass and re-execute the script."""
    logger.info("xkcdpass not found → installing it now...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "xkcdpass"])
        logger.info("xkcdpass installed. Restarting script...")
    except subprocess.CalledProcessError as ex:
        error_message = textwrap.dedent(f"""
            ERROR: Failed to install xkcdpass (reason: {ex})
            Manual installation required with: 'sudo python3 -m pip install xkcdpass'
        """)
        raise SystemExit(error_message)

    new_argv = [sys.executable] + sys.argv[1:]
    new_argv.insert(1, "--no-reinstall")
    os.execvp(sys.executable, new_argv)


def main() -> None:
    args = parse_arguments()

    if args.no_reinstall:
        raise SystemExit("xkcdpass still not importable after install attempt. Install manually.")

    if xpw is None:
        handle_missing_xkcdpass()

    if os.getuid() != 0:
        raise SystemExit("ERROR: This script must be run as root (sudo python3 ...)")

    luks = LuksEncryptor(args.device, args.label)

    luks.generate_passphrase()
    luks.confirm_destruction()
    luks.format_luks()
    luks.backup_luks_header()

    luks.open_container(use_keyfile=False)
    luks.create_filesystem()
    luks.create_keyfile()
    luks.add_keyfile_to_luks()

    luks.open_container(use_keyfile=True)
    luks.setup_mount_and_symlink()
    luks.add_fstab_entry()
    luks.create_systemd_service()

    luks.cleanup()
    luks.print_setup_summary()


if __name__ == "__main__":
    main()
