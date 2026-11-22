Option Explicit

Dim shell, files, projectDir, batchPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

projectDir = files.GetParentFolderName(WScript.ScriptFullName)
batchPath = projectDir & "\start_telegram_intake.bat"
shell.CurrentDirectory = projectDir
shell.Run Chr(34) & batchPath & Chr(34), 0, False
