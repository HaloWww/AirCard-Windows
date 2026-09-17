' AirCard for Windows - Silent Launcher
' Launches AirCard GUI without opening a console window.
Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
ScriptDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = ScriptDir
WshShell.Run "cmd /c run_aircard.bat", 0, False
