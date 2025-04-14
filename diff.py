# -*- coding: utf-8 -*-
#
# WinPython diff.py script
# Copyright © 2013 Pierre Raybaut
# Copyright © 2014-2025+ The Winpython development team https://github.com/winpython/
# Licensed under the terms of the MIT License
# (see winpython/__init__.py for details)


import os
from pathlib import Path
import re
import shutil
from winpython import utils

CHANGELOGS_DIR = Path(__file__).parent / "changelogs"
assert CHANGELOGS_DIR.is_dir()


class Package(object):
    # SourceForge Wiki syntax:
    PATTERN = r"\[([a-zA-Z\-\:\/\.\_0-9]*)\]\(([^\]\ ]*)\) \| ([^\|]*) \| ([^\|]*)"
    # Google Code Wiki syntax:
    PATTERN_OLD = r"\[([a-zA-Z\-\:\/\.\_0-9]*) ([^\]\ ]*)\] \| ([^\|]*) \| ([^\|]*)"

    def __init__(self):
        self.name = None
        self.version = None
        self.description = None
        self.url = None

    def __str__(self):
        text = f"{self.name} {self.version}"
        text += f"\r\n{self.description}\r\nWebsite: {self.url}"
        return text

    def from_text(self, text):
        try:
            self.url, self.name, self.version, self.description = re.match(
                self.PATTERN_OLD, text
            ).groups()
        except AttributeError:
            self.name, self.url, self.version, self.description = re.match(
                self.PATTERN, text
            ).groups()

    def to_wiki(self):
        return f"  * [{self.name}]({self.url}) {self.version} ({self.description})\r\n"

    def upgrade_wiki(self, other):
        assert self.name.replace("-", "_").lower() == other.name.replace("-", "_").lower()
        return f"  * [{self.name}]({self.url}) {other.version} → {self.version} ({self.description})\r\n"


class PackageIndex(object):
    WINPYTHON_PATTERN = r"\#\# WinPython\-*[0-9b-t]* ([0-9\.a-zA-Z]*)"
    TOOLS_LINE = "### Tools"
    PYTHON_PACKAGES_LINE = "### Python packages"
    HEADER_LINE1 = "Name | Version | Description"
    HEADER_LINE2 = "-----|---------|------------"

    def __init__(self, version, basedir=None, flavor="", architecture=64):
        self.version = version
        self.flavor = flavor
        self.basedir = basedir
        self.architecture = architecture
        self.other_packages = {}
        self.python_packages = {}
        self.from_file(basedir)

    def from_file(self, basedir):
        fname = CHANGELOGS_DIR / f"WinPython{self.flavor}-{self.architecture}bit-{self.version}.md"
        if not fname.exists():
            raise FileNotFoundError(f"Changelog file not found: {fname}")
        with open(fname, "r", encoding = 'utf-8') as fdesc:
            text = fdesc.read()
        self.from_text(text)

    def from_text(self, text):
        version = re.match(self.WINPYTHON_PATTERN + self.flavor, text).groups()[0]
        assert version == self.version
        tools_flag = python_flag = False
        for line in text.splitlines():
            if line:
                if line == self.TOOLS_LINE:
                    tools_flag, python_flag = True, False
                    continue
                elif line == self.PYTHON_PACKAGES_LINE:
                    tools_flag, python_flag = False, True
                    continue
                elif line in (
                    self.HEADER_LINE1,
                    self.HEADER_LINE2,
                    "<details>",
                    "</details>",
                ):
                    continue
                if tools_flag or python_flag:
                    package = Package()
                    package.from_text(line)
                    if tools_flag:
                        self.other_packages[package.name] = package
                    else:
                        self.python_packages[package.name] = package


def diff_package_dicts(old_packages, new_packages):
    """Return difference between package old and package new"""

    # wheel replace '-' per '_' in key
    old = {k.replace("-", "_").lower(): v for k, v in old_packages.items()}
    new = {k.replace("-", "_").lower(): v for k, v in new_packages.items()}
    text = ""
    # New packages
    if new_keys := sorted(set(new) - set(old)):
       text += "New packages:\r\n\r\n" + "".join(new[k].to_wiki() for k in new_keys) + "\r\n"

    # Upgraded packages
    if upgraded := [new[k].upgrade_wiki(old[k]) for k in sorted(set(old) & set(new)) if old[k].version != new[k].version]:
        text += "Upgraded packages:\r\n\r\n" + f"{''.join(upgraded)}" + "\r\n"

    # Removed packages
    if removed_keys := sorted(set(old) - set(new)):
        text += "Removed packages:\r\n\r\n" + "".join(old[k].to_wiki() for k in removed_keys) + "\r\n"
    return text


def find_closer_version(version1, basedir=None, flavor="", architecture=64):
    """Find version which is the closest to `version`"""
    builddir = str(Path(basedir) / f"bu{flavor}")
    func = lambda name: re.match(
        r"WinPython%s-%sbit-([0-9\.]*)\.(txt|md)" % (flavor, architecture),
        name,
    )
    versions = [func(name).groups()[0] for name in os.listdir(builddir) if func(name)]
    # versions:['3.10.0.1', '3.10.10.0', '3.10.2.0'.... '3.10.8.1', '3.10.9.0']
    try:
        index = versions.index(version1)
    except ValueError:
        raise ValueError(f"Unknown version {version1}")

    from packaging import version
    version_below = '0.0.0.0'
    for v in versions:
        if version.parse(v) > version.parse(version_below) and version.parse(v)<version.parse(version1):
            version_below = v
    if version_below =='0.0.0.0': 
        return version1
    else:
        return version_below 

def compare_package_indexes(version2, version1=None, basedir=None, flavor="", flavor1=None,architecture=64):
    """Compare two package index Wiki pages"""
    version1 = version1 if version1 else find_closer_version(version2, basedir, flavor, architecture)
    flavor1 = flavor1 if flavor1 else flavor
    pi1 = PackageIndex(version1, basedir, flavor1, architecture)
    pi2 = PackageIndex(version2, basedir, flavor, architecture)
    
    text = "\r\n".join(
        [
            f"## History of changes for WinPython-{architecture}bit {version2 + flavor}",
            "",
            f"The following changes were made to WinPython-{architecture}bit"
            f" distribution since version {version1 + flavor1}.",
            "",
            "<details>",
            "",
        ]
    )

    tools_text = diff_package_dicts(pi1.other_packages, pi2.other_packages)
    if tools_text:
        text += PackageIndex.TOOLS_LINE + "\r\n\r\n" + tools_text
    py_text = diff_package_dicts(pi1.python_packages, pi2.python_packages)
    if py_text:
        text += PackageIndex.PYTHON_PACKAGES_LINE + "\r\n\r\n" + py_text
    text += "\r\n</details>\r\n* * *\r\n"
    return text


def _copy_all_changelogs(version, basedir, flavor="", architecture=64):
    basever = ".".join(version.split(".")[:2])
    for name in os.listdir(CHANGELOGS_DIR):
        if re.match(
            r"WinPython%s-%sbit-%s([0-9\.]*)\.(txt|md)"
            % (flavor, architecture, basever),
            name,
        ):
            shutil.copyfile(CHANGELOGS_DIR / name, Path(basedir) / f"bu{flavor}" / name)


def write_changelog(version2, version1=None, basedir=None, flavor="", architecture=64):
    """Write changelog between version1 and version2 of WinPython"""
    _copy_all_changelogs(version2, basedir, flavor, architecture)
    print("comparing_package_indexes", version2, basedir, flavor, architecture)
    changelog_text = compare_package_indexes(version2, version1, basedir, flavor, architecture=architecture)
    output_file = Path(basedir) / f"bu{flavor}" / f"WinPython{flavor}-{architecture}bit-{version2}_History.md"

    with open(output_file, "w", encoding="utf-8-sig") as fdesc:
        fdesc.write(changelog_text)
    # Copy to winpython/changelogs
    shutil.copyfile(output_file, CHANGELOGS_DIR / output_file.name)


if __name__ == "__main__":
    print(compare_package_indexes("3.7.4.0", "3.7.2.0", "C:\WinP\bd37", "Zero", architecture=32))
    write_changelog("3.7.4.0", "3.7.2.0", r"C:\WinP\bd37", "Ps2", architecture=64)
