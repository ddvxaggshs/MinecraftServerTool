Option Explicit

Dim shell, files, folder, source, result, pythonw, candidate
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
source = files.BuildPath(folder, "src\main.py")

' Use the GUI interpreter, not py.exe/python.exe with a hidden console.
' Python Install Manager can otherwise leave its console attached for the session.
pythonw = "pyw.exe"
candidate = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Python\bin\pythonw.exe")
If files.FileExists(candidate) Then pythonw = """" & candidate & """"
candidate = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")
If files.FileExists(candidate) Then pythonw = """" & candidate & """"

If Not files.FileExists(source) Then
    MsgBox "MinecraftRelay.py was not found beside this launcher.", 16, "Minecraft Relay"
    WScript.Quit 1
End If

' All probes and the application use the same windowless interpreter.
On Error Resume Next
result = shell.Run(pythonw & " -c ""import sys""", 0, True)
If Err.Number <> 0 Then
    Err.Clear
    result = 1
End If
On Error GoTo 0
If result <> 0 Then
    MsgBox "Windowless Python (pythonw/pyw) is required for source mode. Install Python with its GUI launcher, or use the packaged MinecraftRelay.exe.", 16, "Minecraft Relay"
    WScript.Quit 1
End If

result = shell.Run(pythonw & " -c ""import PySide6""", 0, True)
If result <> 0 Then
    shell.Popup "Installing the interface dependency. The app will open when installation completes.", 4, "Minecraft Relay", 64
    result = shell.Run(pythonw & " -m pip install PySide6", 0, True)
    If result <> 0 Then
        MsgBox "PySide6 installation failed. Run 'py -m pip install PySide6' in a terminal to see the error, then retry.", 16, "Minecraft Relay"
        WScript.Quit 1
    End If
End If

' pythonw has no console. Show the GUI normally; SW_HIDE also hides Qt's window.
result = shell.Run(pythonw & " """ & source & """", 1, True)
If result <> 0 Then
    MsgBox "Minecraft Relay exited with an error. Run 'py src/main.py' in a terminal from this folder to see the details.", 16, "Minecraft Relay"
End If
WScript.Quit result
