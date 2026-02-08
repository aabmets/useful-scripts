# Useful Scripts
Repo to showcase various useful scripts.

### `security/luks_encrypt_drive.py`
This script encrypts a mounted drive in Linux using LUKS (equivalent of Bitlocker on Windows). 
For Windows Subsystem for Linux (WSL), a scheduled task must be created in Windows, which triggers on user login 
and runs as an admin user with the highest privileges and executes powershell.exe with the following arguments: 
`-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command "wsl --mount \\.\PHYSICALDRIVE1 --bare"` 
The drive to be bare-mounted into WSL must be first marked Offline in Disk Management to avoid conflicts. 
