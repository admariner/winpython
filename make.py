# -*- coding: utf-8 -*-
#
# Copyright © 2012 Pierre Raybaut
# Copyright © 2014-2024+  The Winpython development team https://github.com/winpython/
# Licensed under the terms of the MIT License
# (see winpython/__init__.py for details)

"""
WinPython build script
Created on Sun Aug 12 11:17:50 2012
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from winpython import wppm, utils
# Local imports
import diff

CHANGELOGS_DIR = Path(__file__).parent / "changelogs"
PORTABLE_DIR = Path(__file__).parent / "portable"

assert CHANGELOGS_DIR.is_dir(), f"Changelogs directory not found: {CHANGELOGS_DIR}"
assert PORTABLE_DIR.is_dir(), f"Portable directory not found: {PORTABLE_DIR}"


def find_7zip_executable() -> str:
    """
    Locates the 7-Zip executable (7z.exe) in common installation directories.

    Raises:
        RuntimeError: If 7-Zip executable is not found.

    Returns:
        str: Path to the 7-Zip executable.
    """
    program_files_dirs = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
        Path(sys.prefix).parent.parent / "7-Zip",
    ]
    for base_dir in program_files_dirs:
        for subdir in [".", "App"]:
            exe_path = base_dir / subdir / "7-Zip" / "7z.exe"
            if exe_path.is_file():
                return str(exe_path)
    raise RuntimeError("7ZIP is not installed on this computer.")


def replace_lines_in_file(filepath: Path, replacements: list[tuple[str, str]]):
    """
    Replaces lines in a file that start with a given prefix.

    Args:
        filepath: Path to the file to modify.
        replacements: A list of tuples, where each tuple contains:
            - The prefix of the line to replace (str).
            - The new text for the line (str).
    """
    lines: list[str] = []
    with open(filepath, "r") as f:
        lines = f.readlines()

    updated_lines = list(lines)  # Create a mutable copy

    for index, line in enumerate(lines):
        for prefix, new_text in replacements:
            start_prefix = prefix
            if prefix not in ("Icon", "OutFile") and not prefix.startswith("!"):
                start_prefix = "set " + prefix
            if line.startswith(start_prefix + "="):
                updated_lines[index] = f"{start_prefix}={new_text}\n"

    with open(filepath, "w") as f:
        f.writelines(updated_lines)
    print(f"Updated 7-zip script: {filepath}")


def build_installer_7zip(
    script_template_path: Path, output_script_path: Path, replacements: list[tuple[str, str]]
):
    """
    Creates a 7-Zip installer script by copying a template and applying text replacements.

    Args:
        script_template_path: Path to the template 7-Zip script (.bat file).
        output_script_path: Path to save the generated 7-Zip script.
        replacements: A list of tuples for text replacements (prefix, new_text).
    """
    sevenzip_exe = find_7zip_executable()
    shutil.copy(script_template_path, output_script_path)

    # Standard replacements for all 7zip scripts
    data = [
        ("PORTABLE_DIR", str(PORTABLE_DIR)),
        ("SEVENZIP_EXE", sevenzip_exe),
    ] + replacements

    replace_lines_in_file(output_script_path, data)

    try:
        # Execute the generated 7-Zip script
        command = f'"{output_script_path}"'
        print(f"Executing 7-Zip script: {command}")
        subprocess.run(
            command, shell=True, check=True, stderr=sys.stderr, stdout=sys.stderr #=sys.stdout
        )  # Use subprocess.run for better error handling
    except subprocess.CalledProcessError as e:
        print(f"Error executing 7-Zip script: {e}", file=sys.stderr)


class WinPythonDistributionBuilder(object):
    """WinPython distribution"""

    JULIA_PATH = r"\t\Julia\bin"
    NODEJS_PATH = r"\n"  # r'\t\n'

    def __init__(
        self,
        build_number,
        release_level,
        target,
        wheeldir,
        toolsdirs=None,
        verbose=False,
        basedir=None,
        install_options=None,
        flavor="",
        docsdirs=None,
    ):
        assert isinstance(build_number, int)
        assert isinstance(release_level, str)
        self.build_number = build_number
        self.release_level = release_level
        self.target = target
        self.wheeldir = wheeldir
        self._toolsdirs = toolsdirs if toolsdirs is not None else []
        self._docsdirs = docsdirs if docsdirs is not None else []
        self.verbose = verbose
        self.winpy_dir: Path | None = None  # Will be set during build
        self.distribution = None
        self.installed_packages = []
        self.basedir = basedir  # added to build from winpython
        self.install_options = install_options
        self.flavor = flavor

        # python_fname = the .zip of the python interpreter PyPy !
        try:  # PyPy
            self.python_fname = self.get_package_fname(
                r"(pypy3|python-)([0-9]|[a-zA-Z]|.)*.zip"
            )
        except:  # normal Python
            self.python_fname = self.get_package_fname(
                r"python-([0-9\.rcba]*)((\.|\-)amd64)?\.(zip|zip)"
            )
        self.python_name = Path(self.python_fname).name[:-4]
        self.python_dir_name = "python"

    @property
    def package_index_wiki(self):
        """Return Package Index page in Wiki format"""
        installed_tools = []

        def get_tool_path_file(relpath):
            path = Path(self.winpy_dir) / relpath
            if Path(path).is_file():
                return path

        def get_tool_path_dir(relpath):
            path = Path(self.winpy_dir) / relpath
            if Path(path).is_dir():
                return path

        juliapath = get_tool_path_dir(self.JULIA_PATH)
        if juliapath is not None:
            juliaver = utils.get_julia_version(juliapath)
            installed_tools += [("Julia", juliaver)]
        nodepath = get_tool_path_dir(self.NODEJS_PATH)
        if nodepath is not None:
            nodever = utils.get_nodejs_version(nodepath)
            installed_tools += [("Nodejs", nodever)]
            npmver = utils.get_npmjs_version(nodepath)
            installed_tools += [("npmjs", npmver)]
        pandocexe = get_tool_path_file(r"\t\pandoc.exe")
        if pandocexe is not None:
            pandocver = utils.get_pandoc_version(str(Path(pandocexe).parent))
            installed_tools += [("Pandoc", pandocver)]
        vscodeexe = get_tool_path_file(r"\t\VSCode\Code.exe")
        if vscodeexe is not None:
            installed_tools += [
                ("VSCode", utils.getFileProperties(vscodeexe)["FileVersion"])
            ]
        tools = []
        for name, ver in installed_tools:
            metadata = utils.get_package_metadata("tools.ini", name)
            url, desc = (
                metadata["url"],
                metadata["description"],
            )
            tools += [f"[{name}]({url}) | {ver} | {desc}"]
        # get all packages installed in the changelog, whatever the method
        self.installed_packages = self.distribution.get_installed_packages(update=True)

        packages = [
            f"[{pack.name}]({pack.url}) | {pack.version} | {pack.description}"
            for pack in sorted(
                self.installed_packages,
                key=lambda p: p.name.lower(),
            )
        ]
        python_desc = "Python programming language with standard library"
        tools_f = "\n".join(tools)
        packages_f = "\n".join(packages)
        return (
            f"""## WinPython {self.winpyver2 + self.flavor} 

The following packages are included in WinPython-{self.winpy_arch}bit v{self.winpyver2+self.flavor} {self.release_level}.

<details>

### Tools

Name | Version | Description
-----|---------|------------
{tools_f}

### Python packages

Name | Version | Description
-----|---------|------------
[Python](http://www.python.org/) | {self.python_fullversion} | {python_desc}
{packages_f}"""
            + "\n\n</details>\n"
        )

    # @property makes self.winpython_version_name becomes a call to self.winpython_version_name()
    @property
    def winpython_version_name(self):
        """Return WinPython version (with flavor and release level!)"""
        return f"{self.python_fullversion}.{self.build_number}{self.flavor}{self.release_level}"

    @property
    def python_dir(self):
        """Return Python dirname (full path) of the target distribution"""
        if (Path(self.winpy_dir) / self.python_dir_name).is_dir(): # 2024-12-22
            return str(Path(self.winpy_dir) / self.python_dir_name) # /python path
        else:
            return str(Path(self.winpy_dir) / self.python_name)  # python.exe path

    @property
    def winpy_arch(self):
        """Return WinPython architecture"""
        return f"{self.distribution.architecture}"

    @property
    def pre_path_entries(self) -> list[str]:
        """Return PATH contents to be prepend to the environment variable"""
        path = [
            r"Lib\site-packages\PyQt5",
            "",  # Python root directory
            "DLLs",
            "Scripts",
            r"..\t",
        ]
        path += [r".." + self.JULIA_PATH]

        path += [r".." + self.NODEJS_PATH]

        return path

    @property
    def post_path_entries(self) -> list[str]:
        """Return PATH contents to be append to the environment variable"""
        return []

    @property
    def toolsdirs(self):
        """Return tools directory list"""
        return [] + self._toolsdirs

    @property
    def docsdirs(self):
        """Return docs directory list"""
        if (Path(__file__).resolve().parent / "docs").is_dir():
            return [str(Path(__file__).resolve().parent / "docs")] + self._docsdirs
        else:
            return self._docsdirs

    def get_package_fname(self, pattern):
        """Get package matching pattern in wheeldir"""
        path = self.wheeldir
        for fname in os.listdir(path):
            match = re.match(pattern, fname)
            if match is not None or pattern == fname:
                return str((Path(path) / fname).resolve())
        else:
            raise RuntimeError(f"Could not find required package matching {pattern}")

    def create_batch_script(self, name: str, contents: str, replacements: list[tuple[str, str]] = None):
        """
        Creates a batch script in the WinPython scripts directory.

        Args:
            name: The name of the batch script file.
            contents: The contents of the batch script.
            replacements: A list of tuples for text replacements in the content.
        """
        script_dir = Path(self.winpy_dir) / "scripts" if self.winpy_dir else None
        if not script_dir:
            print("Warning: WinPython directory not set, cannot create batch script.")
            return
        script_dir.mkdir(parents=True, exist_ok=True)
        final_contents = contents
        if replacements:
            for old_text, new_text in replacements:
                final_contents = final_contents.replace(old_text, new_text)
        script_path = script_dir / name
        with open(script_path, "w") as f:
            f.write(final_contents)
        print(f"Created batch script: {script_path}")

    def create_python_launcher_batch(
        self,
        name: str,
        script_name: str,
        working_dir: str = None,
        options: str = None,
        command: str = None,
    ):
        """
        Creates a batch file to launch a Python script within the WinPython environment.

        Args:
            name: The name of the batch file.
            script_name: The name of the Python script to execute.
            working_dir: Optional working directory for the script.
            options: Optional command-line options for the script.
            command: Optional command to execute python, defaults to python.exe or pythonw.exe
        """
        options_str = f" {options}" if options else ""
        if command is None:
            command = '"%WINPYDIR%\\pythonw.exe"' if script_name.endswith(".pyw") else '"%WINPYDIR%\\python.exe"'
        change_dir_cmd = f"cd /D {working_dir}\n" if working_dir else ""
        script_name_str = f" {script_name}" if script_name else ""
        batch_content = f"""@echo off
call "%~dp0env_for_icons.bat"
{change_dir_cmd}{command}{script_name_str}{options_str} %*"""
        self.create_batch_script(name, batch_content)

    def create_installer_7zip(self, installer_type: str = ".exe"):
        """
        Creates a WinPython installer using 7-Zip.

        Args:
            installer_type: Type of installer to create (".exe", ".7z", ".zip").
        """
        self._print_action(f"Creating WinPython installer ({installer_type})")
        template_name = "installer_7zip.bat"
        output_name = "installer_7zip-tmp.bat" # temp file to avoid overwriting template
        if installer_type not in [".exe", ".7z", ".zip"]:
            print(f"Warning: Unsupported installer type '{installer_type}'. Defaulting to .exe")
            installer_type = ".exe"

        replacements = [
            ("DISTDIR", str(self.winpy_dir)),
            ("ARCH", str(self.winpy_arch)),
            ("VERSION", f"{self.python_fullversion}.{self.build_number}{self.flavor}"),
            (
                "VERSION_INSTALL",
                f'{self.python_fullversion.replace(".", "")}{self.build_number}',
            ),
            ("RELEASELEVEL", self.release_level),
            ("INSTALLER_OPTION", installer_type), # Pass installer type as option to bat script
        ]

        build_installer_7zip(
            PORTABLE_DIR / template_name,
            PORTABLE_DIR / output_name,
            replacements
        )
        self._print_action_done()


    def _print_action(self, text: str):
        """Prints an action message with progress indicator."""
        if self.verbose:
            utils.print_box(text)
        else:
            print(f"{text}... ", end="", flush=True)

    def _print_action_done(self):
        """Prints "OK" to indicate action completion."""
        if not self.verbose:
            print("OK")

    def _extract_python(self):
        """Extracting Python installer, creating distribution object"""
        self._print_action("Extracting Python .zip version")
        utils.extract_archive(
            self.python_fname,
            targetdir=self.python_dir + r"\..",
        )
        self._print_action_done()
        # relocate to /python
        if Path(self.python_dir_name) != Path(self.winpy_dir) / self.python_dir_name: #2024-12-22 to /python
            os.rename(Path(self.python_dir), Path(self.winpy_dir) / self.python_dir_name)

    def _copy_dev_tools(self):
        """Copy dev tools"""
        self._print_action(f"Copying tools from {self.toolsdirs} to {self.winpy_dir}/t")
        toolsdir = Path(self.winpy_dir) / "t"
        toolsdir.mkdir(parents=True, exist_ok=True)
        for dirname in [ok_dir for ok_dir in self.toolsdirs if Path(ok_dir).is_dir()]:
            for name in os.listdir(dirname):
                path = Path(dirname) / name
                copy = shutil.copytree if path.is_dir() else shutil.copyfile
                if self.verbose:
                    print(f"{path} --> {toolsdir / name}")
                copy(path, toolsdir / name)
        self._print_action_done()
        # move node higher
        nodejs_current = toolsdir / "n"
        nodejs_target = Path(self.winpy_dir) / self.NODEJS_PATH
        if nodejs_current != nodejs_target and nodejs_current.is_dir():
            shutil.move(nodejs_current, nodejs_target)

    def _copy_dev_docs(self):
        """Copy dev docs"""
        docsdir = Path(self.winpy_dir) / "notebooks"
        self._print_action(f"Copying Notebook docs from {self.docsdirs} to {docsdir}")
        docsdir.mkdir(parents=True, exist_ok=True)
        docsdir = docsdir / "docs"
        docsdir.mkdir(parents=True, exist_ok=True)
        for dirname in self.docsdirs:
            for name in os.listdir(dirname):
                path = Path(dirname) / name
                copy = shutil.copytree if path.is_dir() else shutil.copyfile
                copy(path, docsdir / name)
                if self.verbose:
                    print(f"{path} --> {docsdir / name}")
        self._print_action_done()

    def _create_launchers(self):
        """Create launchers"""
        self._print_action("Creating launchers")
        # 2025-01-04: copy launchers premade per the Datalab-Python way
        portable_dir = Path(__file__).resolve().parent / "portable" / "launchers_final"
        for path in portable_dir.rglob('*.exe'):
            shutil.copy2(path, Path(self.winpy_dir))
            print("new way !!!!!!!!!!!!!!!!!! ", path , " -> ",Path(self.winpy_dir))
        for path in (Path(__file__).resolve().parent / "portable").rglob('licence*.*'):
            shutil.copy2(path, Path(self.winpy_dir))
        self._print_action_done()


    def _create_initial_batch_scripts(self):
        """Creates initial batch scripts, including environment setup."""
        self._print_action("Creating initial batch scripts")

        path_entries_str = ";".join([rf"%WINPYDIR%\{pth}" for pth in self.pre_path_entries])
        full_path_env_var = f"{path_entries_str};%PATH%;" + ";".join([rf"%WINPYDIR%\{pth}" for pth in self.post_path_entries])

        path_entries_ps_str = ";".join([rf"$env:WINPYDIR\\{pth}" for pth in self.pre_path_entries])
        full_path_ps_env_var = f"{path_entries_ps_str};$env:path;" + ";".join([rf"$env:WINPYDIR\\{pth}" for pth in self.post_path_entries])

        # Replacements for batch scripts (PyPy compatibility)
        exe_name = self.distribution.short_exe if self.distribution else "python.exe" # default to python.exe if distribution is not yet set
        batch_replacements = [
            (r"DIR%\\python.exe", rf"DIR%\\{exe_name}"),
            (r"DIR%\\PYTHON.EXE", rf"DIR%\\{exe_name}"),
        ]
        if self.distribution and (Path(self.distribution.target) / r"lib-python\3\idlelib").is_dir():
            batch_replacements.append((r"\Lib\idlelib", r"\lib-python\3\idlelib"))


        env_bat_content = f"""@echo off
set WINPYDIRBASE=%~dp0..

rem get a normalized path
set WINPYDIRBASETMP=%~dp0..
pushd %WINPYDIRBASETMP%
set WINPYDIRBASE=%__CD__%
if "%WINPYDIRBASE:~-1%"=="\\" set WINPYDIRBASE=%WINPYDIRBASE:~0,-1%
set WINPYDIRBASETMP=
popd

set WINPYDIR=%WINPYDIRBASE%\\{self.python_dir_name}
rem 2019-08-25 pyjulia needs absolutely a variable PYTHON=%WINPYDIR%\\python.exe
set PYTHON=%WINPYDIR%\\python.exe
set PYTHONPATHz=%WINPYDIR%;%WINPYDIR%\\Lib;%WINPYDIR%\\DLLs
set WINPYVER={self.winpython_version_name}

rem 2023-02-12 utf-8 on console to avoid pip crash
rem see https://github.com/pypa/pip/issues/11798#issuecomment-1427069681
set PYTHONIOENCODING=utf-8
rem set PYTHONUTF8=1 creates issues in "movable" patching

set HOME=%WINPYDIRBASE%\\settings
rem see https://github.com/winpython/winpython/issues/839
rem set USERPROFILE=%HOME%
set JUPYTER_DATA_DIR=%HOME%
set JUPYTER_CONFIG_DIR=%WINPYDIR%\\etc\\jupyter
set JUPYTER_CONFIG_PATH=%WINPYDIR%\\etc\\jupyter
set FINDDIR=%WINDIR%\\system32
echo ";%PATH%;" | %FINDDIR%\\find.exe /C /I ";%WINPYDIR%\\;" >nul
if %ERRORLEVEL% NEQ 0 (
   set "PATH={full_path_env_var}"
   cd .
)

rem force default pyqt5 kit for Spyder if PyQt5 module is there
if exist "%WINPYDIR%\\Lib\\site-packages\\PyQt5\\__init__.py" set QT_API=pyqt5
"""

        self.create_batch_script("env.bat", env_bat_content, replacements=batch_replacements)

        ps1_content = r"""### WinPython_PS_Prompt.ps1 ###
$0 = $myInvocation.MyCommand.Definition
$dp0 = [System.IO.Path]::GetDirectoryName($0)
# $env:PYTHONUTF8 = 1 would create issues in "movable" patching
$env:WINPYDIRBASE = "$dp0\.."
# get a normalize path
# http://stackoverflow.com/questions/1645843/resolve-absolute-path-from-relative-path-and-or-file-name
$env:WINPYDIRBASE = [System.IO.Path]::GetFullPath( $env:WINPYDIRBASE )

# avoid double_init (will only resize screen)
if (-not ($env:WINPYDIR -eq [System.IO.Path]::GetFullPath( $env:WINPYDIRBASE+""" + '"\\' + self.python_dir_name + '"' + r""")) ) {
$env:WINPYDIR = $env:WINPYDIRBASE+""" + '"\\' + self.python_dir_name + '"' + r"""
# 2019-08-25 pyjulia needs absolutely a variable PYTHON=%WINPYDIR%python.exe
$env:PYTHON = "%WINPYDIR%\python.exe"
$env:PYTHONPATHz = "%WINPYDIR%;%WINPYDIR%\Lib;%WINPYDIR%\DLLs"

$env:WINPYVER = '""" + self.winpython_version_name + r"""'
# rem 2023-02-12 try utf-8 on console
# rem see https://github.com/pypa/pip/issues/11798#issuecomment-1427069681
$env:PYTHONIOENCODING = "utf-8"

$env:HOME = "$env:WINPYDIRBASE\settings"

# rem read https://github.com/winpython/winpython/issues/839
# $env:USERPROFILE = "$env:HOME"

$env:WINPYDIRBASE = ""
$env:JUPYTER_DATA_DIR = "$env:HOME"

if (-not $env:PATH.ToLower().Contains(";"+ $env:WINPYDIR.ToLower()+ ";"))  {
 $env:PATH = """ + '"' + full_path_ps_env_var + '"' + r""" }

#rem force default pyqt5 kit for Spyder if PyQt5 module is there
if (Test-Path "$env:WINPYDIR\Lib\site-packages\PyQt5\__init__.py") { $env:QT_API = "pyqt5" } 

# PyQt5 qt.conf creation and winpython.ini creation done via Winpythonini.py (called per env_for_icons.bat for now)
# Start-Process -FilePath $env:PYTHON -ArgumentList ($env:WINPYDIRBASE + '\scripts\WinPythonIni.py')


### Set-WindowSize

Function Set-WindowSize {
Param([int]$x=$host.ui.rawui.windowsize.width,
      [int]$y=$host.ui.rawui.windowsize.heigth,
      [int]$buffer=$host.UI.RawUI.BufferSize.heigth)
    
    $buffersize = new-object System.Management.Automation.Host.Size($x,$buffer)
    $host.UI.RawUI.BufferSize = $buffersize
    $size = New-Object System.Management.Automation.Host.Size($x,$y)
    $host.ui.rawui.WindowSize = $size   
}
# Windows10 yelling at us with 150 40 6000
# Set-WindowSize 195 40 6000 

### Colorize to distinguish
$host.ui.RawUI.BackgroundColor = "Black"
$host.ui.RawUI.ForegroundColor = "White"
}
"""

        self.create_batch_script("WinPython_PS_Prompt.ps1", ps1_content, replacements=batch_replacements)


        cmd_ps_bat_content = r"""@echo off
call "%~dp0env_for_icons.bat"
Powershell.exe -Command "& {Start-Process PowerShell.exe -ArgumentList '-ExecutionPolicy RemoteSigned -noexit -File ""%~dp0WinPython_PS_Prompt.ps1""'}"
"""
        self.create_batch_script("cmd_ps.bat", cmd_ps_bat_content, replacements=batch_replacements)

        env_for_icons_bat_content = r"""@echo off
call "%~dp0env.bat"

rem default is as before: Winpython ..\Notebooks
set WINPYWORKDIR=%WINPYDIRBASE%\Notebooks
set WINPYWORKDIR1=%WINPYWORKDIR%

rem if we have a file or directory in %1 parameter, we use that directory to define WINPYWORKDIR1
if not "%~1"=="" (
   if exist "%~1" (
      if exist "%~1\" (
         rem echo it is a directory %~1
	     set WINPYWORKDIR1=%~1
	  ) else (
	  rem echo  it is a file %~1, so we take the directory %~dp1
	  set WINPYWORKDIR1=%~dp1
	  )
   )
) else (
rem if it is launched from another directory than icon origin , we keep it that one echo %__CD__%
if not "%__CD__%"=="%~dp0" if not "%__CD__%scripts\"=="%~dp0" set  WINPYWORKDIR1="%__CD__%"
)
rem remove potential doublequote
set WINPYWORKDIR1=%WINPYWORKDIR1:"=%
rem remove some potential last \
if "%WINPYWORKDIR1:~-1%"=="\" set WINPYWORKDIR1=%WINPYWORKDIR1:~0,-1%

rem you can use winpython.ini to change defaults
FOR /F "delims=" %%i IN ('""%WINPYDIR%\python.exe" "%~dp0WinpythonIni.py""') DO set winpythontoexec=%%i
%winpythontoexec%set winpythontoexec=


rem Preventive Working Directories creation if needed
if not "%WINPYWORKDIR%"=="" if not exist "%WINPYWORKDIR%" mkdir "%WINPYWORKDIR%"
if not "%WINPYWORKDIR1%"=="" if not exist "%WINPYWORKDIR1%" mkdir "%WINPYWORKDIR1%"


rem Change of directory only if we are in a launcher directory
if  "%__CD__%scripts\"=="%~dp0"  cd/D %WINPYWORKDIR1%
if  "%__CD__%"=="%~dp0"          cd/D %WINPYWORKDIR1%


if not exist "%HOME%\.spyder-py%WINPYVER:~0,1%"  mkdir "%HOME%\.spyder-py%WINPYVER:~0,1%"
if not exist "%HOME%\.spyder-py%WINPYVER:~0,1%\workingdir" echo %HOME%\Notebooks>"%HOME%\.spyder-py%WINPYVER:~0,1%\workingdir"

"""
        self.create_batch_script("env_for_icons.bat", env_for_icons_bat_content, replacements=batch_replacements)


        # Replaces winpython.vbs, and a bit of env.bat
        winpython_ini_py_content = r"""
# Prepares a dynamic list of variables settings from a .ini file
import os
import subprocess
from pathlib import Path

winpython_inidefault=r'''
[debug]
state = disabled
[inactive_environment_per_user]
## <?> changing this segment to [active_environment_per_user] makes this segment of lines active or not
HOME = %HOMEDRIVE%%HOMEPATH%\Documents\WinPython%WINPYVER%\settings
USERPROFILE = %HOME%
JUPYTER_DATA_DIR = %HOME%
WINPYWORKDIR = %HOMEDRIVE%%HOMEPATH%\Documents\WinPython%WINPYVER%\Notebooks
[inactive_environment_common]
USERPROFILE = %HOME%
[environment]
## <?> Uncomment lines to override environment variables
#JUPYTERLAB_SETTINGS_DIR = %HOME%\.jupyter\lab
#JUPYTERLAB_WORKSPACES_DIR = %HOME%\.jupyter\lab\workspaces
#R_HOME=%WINPYDIRBASE%\t\R
#R_HOMEbin=%R_HOME%\bin\x64
#JULIA_HOME=%WINPYDIRBASE%\t\Julia\bin\
#JULIA_EXE=julia.exe
#JULIA=%JULIA_HOME%%JULIA_EXE%
#JULIA_PKGDIR=%WINPYDIRBASE%\settings\.julia
#QT_PLUGIN_PATH=%WINPYDIR%\Lib\site-packages\pyqt5_tools\Qt\plugins
'''

def get_file(file_name):
    if file_name.startswith("..\\"):
        file_name = os.path.join(os.path.dirname(os.path.dirname(__file__)), file_name[3:])
    elif file_name.startswith(".\\"):
        file_name = os.path.join(os.path.dirname(__file__), file_name[2:])
    try:
        with open(file_name, 'r') as file:
           return file.read()
    except FileNotFoundError:
        if file_name[-3:] == 'ini':
            os.makedirs(Path(file_name).parent, exist_ok=True)
            with open(file_name, 'w') as file:
                file.write(winpython_inidefault)
            return winpython_inidefault

def translate(line, env):
    parts = line.split('%')
    for i in range(1, len(parts), 2):
        if parts[i] in env:
            parts[i] = env[parts[i]]
    return ''.join(parts)

def main():
    import sys
    args = sys.argv[1:]
    file_name = args[0] if args else "..\\settings\\winpython.ini"
    
    my_lines = get_file(file_name).splitlines()
    segment = "environment"
    txt = ""
    env = os.environ.copy() # later_version: env = os.environ
    
    # default directories (from .bat)
    os.makedirs(Path(env['WINPYDIRBASE']) / 'settings' / 'Appdata' / 'Roaming', exist_ok=True) 

    # default qt.conf for Qt directories
    qt_conf='''echo [Paths]
    echo Prefix = .
    echo Binaries = .
    '''

    pathlist = [Path(env['WINPYDIR']) / 'Lib' / 'site-packages' / i for i in ('PyQt5', 'PyQt6', 'Pyside6')] 
    for p in pathlist:
        if p.is_dir():
            if not (p / 'qt.conf').is_file():
                with open(p / 'qt.conf', 'w') as file:
                    file.write(qt_conf)

    for l in my_lines:
        if l.startswith("["):
            segment = l[1:].split("]")[0]
        elif not l.startswith("#") and "=" in l:
            data = l.split("=", 1)
            if segment == "debug" and data[0].strip() == "state":
                data[0] = "WINPYDEBUG"
            if segment in ["environment", "debug", "active_environment_per_user", "active_environment_common"]:
                txt += f"set {data[0].strip()}={translate(data[1].strip(), env)}&& "
                env[data[0].strip()] = translate(data[1].strip(), env)
            if segment == "debug" and data[0].strip() == "state":
                txt += f"set WINPYDEBUG={data[1].strip()}&&"
    
    print(txt)

    # set potential directory
    for i in ('HOME', 'WINPYWORKDIR'):
        if i in env:
            os.makedirs(Path(env[i]), exist_ok=True)
    # later_version:
    # p = subprocess.Popen(["start", "cmd", "/k", "set"], shell = True)
    # p.wait()    # I can wait until finished (although it too finishes after start finishes)

if __name__ == "__main__":
    main()
        """
        
        self.create_batch_script("WinPythonIni.py", winpython_ini_py_content)

        self._print_action_done()



    def _create_standard_batch_scripts(self):
        """Creates standard WinPython batch scripts for various actions."""
        self._print_action("Creating standard batch scripts")

        exe_name = self.distribution.short_exe if self.distribution else "python.exe"
        batch_replacements = [
            (r"DIR%\\python.exe", rf"DIR%\\{exe_name}"),
            (r"DIR%\\PYTHON.EXE", rf"DIR%\\{exe_name}"),
        ]
        if self.distribution and (Path(self.distribution.target) / r"lib-python\3\idlelib").is_dir():
            batch_replacements.append((r"\Lib\idlelib", r"\lib-python\3\idlelib"))


        self.create_batch_script(
            "readme.txt",
            r"""These batch files are required to run WinPython icons.

These files should help the user writing his/her own
specific batch file to call Python scripts inside WinPython.
The environment variables are set-up in 'env_.bat' and 'env_for_icons.bat'.""",
        )

        self.create_batch_script(
            "make_winpython_movable.bat",
            r"""@echo off
call "%~dp0env.bat"
echo patch pip and current launchers for move

"%WINPYDIR%\python.exe" -c "from winpython import wppm;dist=wppm.Distribution(r'%WINPYDIR%');dist.patch_standard_packages('pip', to_movable=True)"
pause""",
            replacements=batch_replacements
        )

        self.create_batch_script(
            "make_winpython_fix.bat",
            r"""@echo off
call "%~dp0env.bat"
echo patch pip and current launchers for non-move

"%WINPYDIR%\python.exe" -c "from winpython import wppm;dist=wppm.Distribution(r'%WINPYDIR%');dist.patch_standard_packages('pip', to_movable=False)"
pause""",
            replacements=batch_replacements
        )

        for ini_patch_script in [
            ("make_working_directory_be_not_winpython.bat", "[active_environment", "[inactive_environment", "[inactive_environment_per_user]", "[active_environment_per_user]"),
            ("make_working_directory_be_winpython.bat", "[active_environment", "[inactive_environment"),
            ("make_working_directory_and_userprofile_be_winpython.bat", "[active_environment", "[inactive_environment", "[inactive_environment_common]", "[active_environment_common]")
            ]:
            name, patch1_start, patch1_end, *patch2 = ini_patch_script
            content = f"""call "%~dp0env_for_icons.bat"
"%PYTHON%" -c "from winpython.utils import patch_sourcefile;patch_sourcefile(r'%~dp0..\\settings\winpython.ini', '{patch1_start}', '{patch1_end}' )"
"""
            if patch2:
                content += f""""%PYTHON%" -c "from winpython.utils import patch_sourcefile;patch_sourcefile(r'%~dp0..\\settings\winpython.ini', '{patch2[0]}', '{patch2[1]}' )" """
            self.create_batch_script(name, content)


        self.create_batch_script("cmd.bat", r"""@echo off
call "%~dp0env_for_icons.bat" %*
cmd.exe /k""", replacements=batch_replacements)

        self.create_batch_script("WinPython_Terminal.bat", r"""@echo off
Powershell.exe -Command "& {Start-Process PowerShell.exe -ArgumentList '-ExecutionPolicy RemoteSigned -noexit -File ""%~dp0WinPython_PS_Prompt.ps1""'}"
exit""", replacements=batch_replacements)

        self.create_batch_script("python.bat", r"""@echo off
call "%~dp0env_for_icons.bat" %*
"%WINPYDIR%\python.exe"  %*""", replacements=batch_replacements)

        self.create_batch_script(
            "winpython.bat",
            r"""@echo off
call "%~dp0env_for_icons.bat" %*
rem backward compatibility for non-ptpython users
if exist "%WINPYDIR%\scripts\ptpython.exe" (
    "%WINPYDIR%\scripts\ptpython.exe" %*
) else (
    "%WINPYDIR%\python.exe"  %*
)""",
            replacements=batch_replacements
        )

        self.create_batch_script(
            "winidle.bat",
            r"""@echo off
call "%~dp0env_for_icons.bat" %*
"%WINPYDIR%\python.exe" "%WINPYDIR%\Lib\idlelib\idle.pyw" %*""",
            replacements=batch_replacements
        )

        self.create_batch_script(
            "winspyder.bat",
            r"""@echo off
call "%~dp0env_for_icons.bat" %*
"%WINPYDIR%\scripts\spyder.exe" %* -w "%WINPYWORKDIR1%" """,
        )

        self.create_batch_script(
            "spyder_reset.bat",
            r"""@echo off
call "%~dp0env_for_icons.bat"
"%WINPYDIR%\scripts\spyder.exe" --reset %*""",
        )

        for jupyter_script in [
            ("winipython_notebook.bat", "jupyter-notebook.exe"),
            ("winjupyter_lab.bat", "jupyter-lab.exe"),
            ("winqtconsole.bat", "jupyter-qtconsole.exe"),
            ]:
            name, exe = jupyter_script
            self.create_batch_script(name, f"""@echo off
call "%~dp0env_for_icons.bat" %*
"%WINPYDIR%\\scripts\\{exe}" %*""")


        self.create_python_launcher_batch(
            "register_python.bat",
            r'"%WINPYDIR%\Lib\site-packages\winpython\register_python.py"',
            working_dir=r'"%WINPYDIR%\Scripts"',
        )

        self.create_python_launcher_batch(
            "unregister_python.bat",
            r'"%WINPYDIR%\Lib\site-packages\winpython\unregister_python.py"',
            working_dir=r'"%WINPYDIR%\Scripts"',
        )

        for register_all_script in [
            ("register_python_for_all.bat", "register_python.bat"),
            ("unregister_python_for_all.bat", "unregister_python.bat"),
            ]:
            name, base_script = register_all_script
            self.create_batch_script(name, f"""@echo off
call "%~dp0env.bat"
call "%~dp0{base_script}" --all""")


        self.create_batch_script("wpcp.bat", r"""@echo off
call "%~dp0env_for_icons.bat" %*
cmd.exe /k "echo wppm & wppm" """, replacements=batch_replacements)

        self.create_batch_script(
            "upgrade_pip.bat",
            r"""@echo off
call "%~dp0env.bat"
echo this will upgrade pip with latest version, then patch it for WinPython portability ok ?
pause
"%WINPYDIR%\python.exe" -m pip install --upgrade pip
"%WINPYDIR%\python.exe" -c "from winpython import wppm;dist=wppm.Distribution(r'%WINPYDIR%');dist.patch_standard_packages('pip', to_movable=True)
pause""",
            replacements=batch_replacements
        )

        self.create_batch_script("activate.bat", r"""@echo off
call "%~dp0env.bat"  %*""", replacements=batch_replacements)


        vscode_bat_content = r"""@echo off
call "%~dp0env_for_icons.bat"
if exist "%WINPYDIR%\..\t\vscode\code.exe" (
    "%WINPYDIR%\..\t\vscode\code.exe" %*
) else (
if exist "%LOCALAPPDATA%\Programs\Microsoft VS Code\code.exe" (
    "%LOCALAPPDATA%\Programs\Microsoft VS Code\code.exe"  %*
) else (
    "code.exe" %*
))"""
        self.create_batch_script("winvscode.bat", vscode_bat_content)

        self._print_action_done()


    def _run_complement_batch_scripts(self, this_batch="run_complement.bat"):
        """tools\..\run_complement.bat for final complements"""
        print(f"now {this_batch} in tooldirs\..")
        unique_toolsdirs = set([str(Path(s).parent) for s in self._toolsdirs])
        for post_complement in unique_toolsdirs:
            filepath = str(Path(post_complement) / this_batch)
            if Path(filepath).is_file():
                print(f'launch "{filepath}"  for  "{self.winpy_dir}"')
                self._print_action(f'launch "{filepath}"  for  "{self.winpy_dir}" !')
                try:
                    retcode = subprocess.call(
                        f'"{filepath}"   "{self.winpy_dir}"',
                        shell=True,
                        stdout=sys.stderr,
                    )
                except subprocess.CalledProcessError as e:
                    print("Execution failed:", e, file=sys.stderr)
                    self._print_action("Execution failed !:", e, file=sys.stderr)
        self._print_action_done()

    def make(
        self,
        remove_existing=True,
        requirements=None,
        my_winpydir=None,
    ):
        """Make WinPython distribution in target directory from the installers
        located in wheeldir

        remove_existing=True: (default) install all from scratch
        remove_existing=False: for complementary purposes (create installers)
        requirements=file(s) of requirements (separated by space if several)"""
        print(
            self.python_fname,
            self.python_name,
        )
        if my_winpydir is None:
            raise RuntimeError("WinPython base directory to create is undefined") 
        else:
            self.winpy_dir = str(
                Path(self.target) / my_winpydir
            )  # Create/re-create the WinPython base directory
        self._print_action(f"Creating WinPython {my_winpydir} base directory")
        if Path(self.winpy_dir).is_dir() and remove_existing:
            try:
                shutil.rmtree(self.winpy_dir, onexc=utils.onerror)
            except TypeError: # before 3.12
                shutil.rmtree(self.winpy_dir, onerror=utils.onerror)    
        os.makedirs(Path(self.winpy_dir), exist_ok=True)    
        if remove_existing:
            # preventive re-Creation of settings directory
            # (necessary if user is starting an application with a batch)
            os.makedirs(Path(self.winpy_dir) / "settings" / "AppData" / "Roaming", exist_ok=True)
            self._extract_python()  # unzip Python interpreter
        self._print_action_done()

        self.distribution = wppm.Distribution(
            self.python_dir,
            verbose=self.verbose,
            indent=True,
        )

        # get Fullversion from the executable
        self.python_fullversion = utils.get_python_long_version(
            self.distribution.target
        )

        # Assert that WinPython version and real python version do match
        self._print_action(
            f"Python version{self.python_fullversion.replace('.','')}"
            + f"\nDistro Name {self.distribution.target}"
        )
        assert self.python_fullversion.replace(".", "") in self.distribution.target, (
            "Distro Directory doesn't match the Python version it ships"
            + f"\nPython version: {self.python_fullversion.replace('.','')}"
            + f"\nDistro Name: {self.distribution.target}"
        )

        if remove_existing:
            self._create_initial_batch_scripts()
            self._create_standard_batch_scripts()
            self._create_launchers()
            # PyPy must ensure pip via: "pypy3.exe -m ensurepip"
            utils.python_execmodule("ensurepip", self.distribution.target)

            self.distribution.patch_standard_packages("pip")
            # not forced update of pip (FIRST) and setuptools here
            for req in ("pip", "setuptools", "wheel", "winpython"):
                actions = ["install", "--upgrade", "--pre", req]
                if self.install_options is not None:
                    actions += self.install_options
                print(f"piping {' '.join(actions)}")
                self._print_action(f"piping {' '.join(actions)}")
                self.distribution.do_pip_action(actions)
                self.distribution.patch_standard_packages(req)
            self._copy_dev_tools()
            self._copy_dev_docs()

            if requirements:
                if not list(requirements) == requirements:
                    requirements = requirements.split()
                for req in requirements:
                    actions = ["install", "-r", req]
                    if self.install_options is not None:
                        actions += self.install_options
                    print(f"piping {' '.join(actions)}")
                    self._print_action(f"piping {' '.join(actions)}")
                    self.distribution.do_pip_action(actions)
            self._run_complement_batch_scripts()
            self.distribution.patch_standard_packages()

            self._print_action("Cleaning up distribution")
            self.distribution.clean_up()
            self._print_action_done()
        # Writing package index
        self._print_action("Writing package index")
        # winpyver2 = the version without build part but with self.distribution.architecture
        self.winpyver2 = f"{self.python_fullversion}.{self.build_number}"
        fname = str(
            Path(self.winpy_dir).parent
            / (
                f"WinPython{self.flavor}-"
                + f"{self.distribution.architecture}bit-"
                + f"{self.winpyver2}.md"
            )
        )
        open(fname, "w", encoding='utf-8').write(self.package_index_wiki)
        # Copy to winpython/changelogs
        shutil.copyfile(
            fname,
            str(Path(CHANGELOGS_DIR) / Path(fname).name),
        )
        self._print_action_done()

        # Writing changelog
        self._print_action("Writing changelog")
        diff.write_changelog(
            self.winpyver2,
            basedir=self.basedir,
            flavor=self.flavor,
            release_level=self.release_level,
            architecture=self.distribution.architecture,
        )
        self._print_action_done()


def rebuild_winpython(codedir, targetdir, architecture=64, verbose=False):
    """Rebuild winpython package from source"""
    
    for name in os.listdir(targetdir):
        if name.startswith("winpython-") and name.endswith((".exe", ".whl", ".gz")):
            os.remove(str(Path(targetdir) / name))
    #  utils.build_wininst is replaced per flit 2023-02-27
    utils.buildflit_wininst(
        codedir,
        copy_to=targetdir,
        verbose=verbose,
    )


def transform_in_list(list_in, list_type=None):
    """Transform a 'String or List' in List"""
    if list_in is None:
        list_in = ""
    if not list_in == list(list_in):
        list_in = list_in.split()
    if list_type:
        print(list_type, list_in)
    return list_in


def make_all(
    build_number,
    release_level,
    pyver,
    architecture,
    basedir,
    verbose=False,
    remove_existing=True,
    create_installer=True,
    install_options=["--no-index"],
    flavor="",
    requirements=None,
    find_links=None,
    source_dirs=None,
    toolsdirs=None,
    docsdirs=None,
    python_target_release=None,  # 37101 for 3.7.10
):
    """Make WinPython distribution, for a given base directory and
    architecture:
    `build_number`: build number [int]
    `release_level`: release level (e.g. 'beta1', '') [str]
    `pyver`: python version ('3.4' or 3.5')
    `architecture`: [int] (32 or 64)
    `basedir`: where will be created tmp_wheel and Winpython build
              r'D:\Winpython\basedir34'.
    `requirements`: the package list for pip r'D:\requirements.txt',
    `install_options`: pip options r'--no-index --pre --trusted-host=None',
    `find_links`: package directories r'D:\Winpython\packages.srcreq',
    `source_dirs`: the python.zip + rebuilt winpython wheel package directory,
    `toolsdirs`: r'D:\WinPython\basedir34\t.Slim',
    `docsdirs`: r'D:\WinPython\basedir34\docs.Slim'"""

    assert basedir is not None, "The *basedir* directory must be specified"
    assert architecture in (32, 64)
    utils.print_box(
        f"Making WinPython {architecture}bits"
        + f" at {Path(basedir) / ('bu' + flavor)}"
    )

    # Create Build director, where Winpython will be constructed
    builddir = str(Path(basedir) / ("bu" + flavor))
    os.makedirs(Path(builddir), exist_ok=True)    
    # use source_dirs as the directory to re-build Winpython wheel
    wheeldir = source_dirs

    # Rebuild Winpython in this wheel dir
    rebuild_winpython(
        codedir=str(Path(__file__).resolve().parent), # winpython source dir
        targetdir=wheeldir,
        architecture=architecture,
    )

    # Optional pre-defined toolsdirs
    toolsdirs = transform_in_list(toolsdirs, "toolsdirs=")

    # Optional pre-defined toolsdirs
    print("docsdirs input", docsdirs)
    docsdirs = transform_in_list(docsdirs, "docsdirs=")
    print("docsdirs output", docsdirs)

    # install_options = ['--no-index', '--pre', f'--find-links={wheeldir)']
    install_options = transform_in_list(install_options, "install_options")

    find_links = transform_in_list(find_links, "find_links")

    find_list = [f"--find-links={l}" for l in find_links + [wheeldir]]
    builder = WinPythonDistributionBuilder(
        build_number,
        release_level,
        builddir,
        wheeldir,
        toolsdirs,
        verbose=verbose,
        basedir=basedir,
        install_options=install_options + find_list,
        flavor=flavor,
        docsdirs=docsdirs,
    )
    # define a pre-defined winpydir, instead of having to guess

    # extract the python subversion to get WPy64-3671b1
    my_x = "".join(builder.python_fname.replace(".amd64", "").split(".")[-2:-1])
    while not my_x.isdigit() and len(my_x) > 0:
        my_x = my_x[:-1]
    # simplify for PyPy
    if not python_target_release == None:
        my_winpydir = (
            "WPy"
            + f"{architecture}"
            + "-"
            + python_target_release
            + ""
            + f"{build_number}"
        ) + release_level
    # + flavor
    else:
        my_winpydir = (
            "WPy"
            + f"{architecture}"
            + "-"
            + pyver.replace(".", "")
            + ""
            + my_x
            + ""
            + f"{build_number}"
        ) + release_level
    # + flavor

    builder.make(
        remove_existing=remove_existing,
        requirements=requirements,
        my_winpydir=my_winpydir,
    )
    if str(create_installer).lower() != "false":
        if ".zip" in str(create_installer).lower():
            builder.create_installer_7zip(".zip")
        if ".7z" in str(create_installer).lower():
            builder.create_installer_7zip(".7z")
        if "7zip" in str(create_installer).lower():
            builder.create_installer_7zip(".exe")
    return builder


if __name__ == "__main__":
    # DO create only one version at a time
    # You may have to manually delete previous build\winpython-.. directory

    make_all(
        1,
        release_level="build3",
        pyver="3.4",
        basedir=r"D:\Winpython\basedir34",
        verbose=True,
        architecture=64,
        flavor="Barebone",
        requirements=r"D:\Winpython\basedir34\barebone_requirements.txt",
        install_options=r"--no-index --pre --trusted-host=None",
        find_links=r"D:\Winpython\packages.srcreq",
        source_dirs=r"D:\WinPython\basedir34\packages.win-amd64",
        toolsdirs=r"D:\WinPython\basedir34\t.Slim",
        docsdirs=r"D:\WinPython\basedir34\docs.Slim",
    )
