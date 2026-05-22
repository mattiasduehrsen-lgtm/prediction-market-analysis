# List all running python processes with their command lines
Get-WmiObject Win32_Process -Filter "Name='python.exe'" |
    Select-Object ProcessId, CommandLine |
    Format-Table -AutoSize -Wrap
