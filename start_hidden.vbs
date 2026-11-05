' Starts Hinata X Helper without a console window.
' Used by Windows startup (see install_autostart.bat). Waits a bit after login
' so Wi-Fi, audio and Ollama are ready first.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
delay = 15
If WScript.Arguments.Count > 0 Then delay = CInt(WScript.Arguments(0))
WScript.Sleep delay * 1000
sh.CurrentDirectory = here
sh.Run """" & here & "\run.bat""", 0, False
