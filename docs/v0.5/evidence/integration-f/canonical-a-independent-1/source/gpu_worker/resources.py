"""Bounded nvidia-smi sampling; process CUDA allocation is reported separately."""
import subprocess
import threading

class GPUResources:
    def __init__(self, mode):
        self.mode=mode
        self.stop=threading.Event()
        self.lock=threading.Lock()
        self.values={'gpuUtilizationPercent':None,'gpuTemperatureC':None,'gpuDeviceMemoryUsedBytes':None}
        self.thread=None
    def start(self):
        if self.mode=='gpu':
            self.thread=threading.Thread(target=self._run,daemon=True)
            self.thread.start()
    def _run(self):
        while not self.stop.is_set():
            values={'gpuUtilizationPercent':None,'gpuTemperatureC':None,'gpuDeviceMemoryUsedBytes':None}
            try:
                result=subprocess.run(['nvidia-smi','--query-gpu=utilization.gpu,temperature.gpu,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=2,check=True)
                rows=result.stdout.splitlines()
                # Acceptance instance has one GPU. Do not attribute another GPU's readings.
                if len(rows)==1:
                    util,temp,memory=(int(v.strip()) for v in rows[0].split(','))
                    values=dict(gpuUtilizationPercent=util,gpuTemperatureC=temp,gpuDeviceMemoryUsedBytes=memory*1024*1024)
            except (OSError,ValueError,subprocess.SubprocessError):
                pass
            with self.lock:self.values=values
            self.stop.wait(5)
    def snapshot(self):
        with self.lock:return dict(self.values)
    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(3)
