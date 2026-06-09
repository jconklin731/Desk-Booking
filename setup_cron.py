"""
Sets up a cron job to run book_desk.py every weekday at 5:00 AM.

Usage:
    python setup_cron.py           # Install the cron job
    python setup_cron.py --remove  # Remove the cron job
    python setup_cron.py --show    # Show current cron jobs
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


CRON_COMMENT = "# desk-booking-agent"


def get_project_dir():
    return str(Path(__file__).parent.resolve())


def get_python_path():
    return sys.executable


def get_cron_line(project_dir, python_path):
    log_path = os.path.join(project_dir, "cron.log")
    # Run at 5:00 AM Monday-Friday
    return (
        f"0 5 * * 1-5 cd {project_dir} && {python_path} book_desk.py >> {log_path} 2>&1 "
        f"{CRON_COMMENT}"
    )


def get_current_crontab():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    if "no crontab" in result.stderr.lower():
        return ""
    print(f"Error reading crontab: {result.stderr}")
    sys.exit(1)


def set_crontab(content):
    proc = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"Error writing crontab: {proc.stderr}")
        sys.exit(1)


def install_cron():
    project_dir = get_project_dir()
    python_path = get_python_path()
    new_line = get_cron_line(project_dir, python_path)

    current = get_current_crontab()

    if CRON_COMMENT in current:
        print("Cron job already exists. Updating it...")
        lines = [l for l in current.splitlines() if CRON_COMMENT not in l]
        current = "\n".join(lines).strip()

    updated = (current + "\n" + new_line + "\n").lstrip()
    set_crontab(updated)

    print(f"\n✓ Cron job installed!")
    print(f"  Schedule: 5:00 AM Monday-Friday")
    print(f"  Project:  {project_dir}")
    print(f"  Python:   {python_path}")
    print(f"  Log file: {project_dir}/cron.log")
    print(f"\nCron entry:")
    print(f"  {new_line}")
    print(f"\nTo verify: python setup_cron.py --show")


def remove_cron():
    current = get_current_crontab()
    if CRON_COMMENT not in current:
        print("No desk-booking cron job found.")
        return
    lines = [l for l in current.splitlines() if CRON_COMMENT not in l]
    updated = "\n".join(lines).strip() + "\n"
    set_crontab(updated)
    print("✓ Cron job removed.")


def show_cron():
    current = get_current_crontab()
    if not current.strip():
        print("No cron jobs installed.")
        return
    print("Current crontab:")
    for line in current.splitlines():
        marker = " <-- desk-booking-agent" if CRON_COMMENT in line else ""
        print(f"  {line}{marker}")


def main():
    parser = argparse.ArgumentParser(description="Manage the desk booking cron job")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true", help="Remove the cron job")
    group.add_argument("--show", action="store_true", help="Show current crontab")
    args = parser.parse_args()

    if args.remove:
        remove_cron()
    elif args.show:
        show_cron()
    else:
        install_cron()


if __name__ == "__main__":
    main()
