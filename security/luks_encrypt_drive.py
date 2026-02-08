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
logging.basicConfig(level=logging.INFO, format="%(message)s")


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
        self.pass_phrase: str | None = None
        self.backup_path: Path | None = None
        self.key_file: Path | None = None

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

        try:
            subprocess.check_output(
                ["cryptsetup", "isLuks", self.device_path.as_posix()],
                stderr=subprocess.DEVNULL
            )
            raise SystemExit(f"ERROR: {self.device_path} is already a LUKS container.")
        except subprocess.CalledProcessError:
            pass  # not LUKS → good

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

    def unmount_drive(self) -> None:
        logger.info(f"Checking for active mounts on {self.device_path}...")
        try:
            # -p: full paths, -n: no headings, -l: list format, -o: specify columns
            args = ["lsblk", "-p", "-n", "-l", "-o", "MOUNTPOINT", self.device_path.as_posix()]
            output = subprocess.check_output(args, text=True).strip()

            if mount_points := [mp for mp in output.split('\n') if mp.strip()]:
                logger.info(f"Found {len(mount_points)} active mount(s). Unmounting now...")
                for mp in mount_points:
                    logger.info(f"Unmounting: {mp}")
                    subprocess.run(["umount", "-l", mp], check=True)
                logger.info("All associated mounts removed.")
            else:
                logger.info("No active mounts found on device.")

        except subprocess.CalledProcessError:
            raise SystemExit("ERROR: Failed to verify mount status with lsblk. Aborting.")

    def format_luks(self) -> None:
        logger.info("Formatting with LUKS2...")
        args = ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", self.device_path.as_posix()]
        subprocess.run(args, input=(self.pass_phrase + "\n").encode(), check=True)

    def backup_luks_header(self) -> None:
        backups_dir = self.user_home / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        self.backup_path = backups_dir / f"{self.label}-luks-header-{date_str}.bak"

        logger.info(f"Backing up LUKS header to: {self.backup_path}")
        args = [
            "cryptsetup", "luksHeaderBackup", self.device_path.as_posix(),
            "--header-backup-file", self.backup_path.as_posix()
        ]
        subprocess.run(args, check=True)
        self.backup_path.chmod(0o600)
        os.chown(
            path=self.backup_path.as_posix(),
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
            cmd.extend(["--key-file", self.key_file.as_posix()])
            logger.info(f"Opening container {self.crypt_name} with keyfile...")
            subprocess.run(cmd, check=True)
        else:
            logger.info(f"Opening container {self.crypt_name} with passphrase...")
            subprocess.run(cmd, input=(self.pass_phrase + "\n").encode(), check=True)

    def create_filesystem(self) -> None:
        logger.info(f"Creating ext4 filesystem with label '{self.label}'...")
        args = ["mkfs.ext4", "-L", self.label, f"/dev/mapper/{self.crypt_name}"]
        subprocess.run(args, check=True)

    def create_keyfile(self) -> None:
        self.key_file = Path("/etc/luks-keys") / f"{self.label}.key"
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        self.key_file.write_bytes(secrets.token_bytes(512))
        self.key_file.chmod(0o600)
        os.chown(path=self.key_file.as_posix(), uid=0, gid=0)
        logger.info(f"Created secure keyfile: {self.key_file}")

    def add_keyfile_to_luks(self) -> None:
        logger.info("Adding keyfile as additional unlock slot...")
        args = ["cryptsetup", "luksAddKey", self.device_path.as_posix(), self.key_file.as_posix()]
        subprocess.run(args, input=(self.pass_phrase + "\n").encode(), check=True)

    def setup_mount_and_symlink(self) -> None:
        logger.info("Mounting filesystem and creating symlink...")
        self.mount_point.mkdir(parents=True, exist_ok=True)
        subprocess.run(["mount", f"/dev/mapper/{self.crypt_name}", str(self.mount_point)], check=True)
        os.chown(
            path=self.mount_point.as_posix(),
            uid=pwd.getpwnam(self.calling_user).pw_uid,
            gid=pwd.getpwnam(self.calling_user).pw_gid
        )
        self.mount_point.chmod(0o755)

        if self.symlink_path.is_symlink():
            self.symlink_path.unlink()
        elif self.symlink_path.exists():
            raise SystemExit(
                f"ERROR: {self.symlink_path} already exists and is not a symlink.\n"
                "Please remove it manually first."
            )
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

    def create_systemd_service(self) -> None:
        outer_uuid = subprocess.check_output(
            ["blkid", "-s", "UUID", "-o", "value", str(self.device_path)]
        ).decode().strip()
        stable_device = f"/dev/disk/by-uuid/{outer_uuid}"

        service_path = Path(f"/etc/systemd/system/{self.service_name}")
        service_content = textwrap.dedent(f"""\
            [Unit]
            Description=Unlock and Mount LUKS {self.label} drive
            After=local-fs-pre.target

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            TimeoutStartSec=30

            ExecStart=/bin/sh -c '\\
                cryptsetup luksOpen --key-file "{self.key_file}" \\
                    "{stable_device}" "{self.crypt_name}" && \\
                udevadm settle && mount "{self.mount_point}"'

            ExecStop=/bin/sh -c '\\
                umount "{self.mount_point}" || true; \\
                cryptsetup luksClose "{self.crypt_name}" || true'

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
        logger.info(f"Systemd service:            {self.label}-crypt.service (enabled)")
        logger.info("fstab entry added (noauto)")
        logger.info(f"To mount now:\n   sudo systemctl start {self.service_name}")


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

    new_args = [sys.executable, *sys.argv, "--no-reinstall"]
    os.execvp(sys.executable, new_args)


def main() -> None:
    args = parse_arguments()

    if not xpw:
        if args.no_reinstall:
            raise SystemExit(
                "xkcdpass still not importable after install attempt. "
                "Install manually with: 'sudo python3 -m pip install xkcdpass'"
            )
        else:
            handle_missing_xkcdpass()

    if os.getuid() != 0:
        raise SystemExit("ERROR: This script must be run as root (sudo python3 ...)")

    luks = LuksEncryptor(args.device, args.label)

    luks.generate_passphrase()
    luks.confirm_destruction()
    luks.unmount_drive()
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
