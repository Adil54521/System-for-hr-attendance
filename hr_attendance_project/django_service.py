import win32serviceutil
import win32service
import win32event
import servicemanager
import os
import sys
import subprocess

class DjangoService(win32serviceutil.ServiceFramework):
    _svc_name_ = "HRDjangoService"
    _svc_display_name_ = "HR Attendance Django Service"

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.process:
            self.process.terminate()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("HR Django Service is starting...")
        base_dir = r"C:\HR_Site 2.0"
        python_path = os.path.join(base_dir, "venv", "Scripts", "python.exe")
        script_path = os.path.join(base_dir, "hr_attendance_project", "serve.py")
        log_file = os.path.join(base_dir, "django_service_log.txt")

        self.process = subprocess.Popen(
            [python_path, script_path],
            stdout=open(log_file, "a"),
            stderr=subprocess.STDOUT,
            cwd=os.path.dirname(script_path)
        )

        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(DjangoService)
