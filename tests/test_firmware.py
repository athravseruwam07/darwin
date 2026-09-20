"""Host execution of actual sketch for parser logic; actual AVR compile reported separately."""
from pathlib import Path
import shutil, subprocess
import pytest

def test_actual_firmware_source_harness(tmp_path):
    compiler=shutil.which('clang++') or shutil.which('g++')
    if not compiler: pytest.skip('C++ compiler unavailable')
    root=Path(__file__).resolve().parents[1]
    exe=tmp_path/'firmware-test'
    subprocess.run([compiler,'-std=c++11','-I'+str(root/'firmware/host_harness'),str(root/'firmware/host_harness/main.cpp'),'-o',str(exe)],check=True,capture_output=True)
    result=subprocess.run([str(exe)],check=True,capture_output=True,text=True)
    assert 'PASS actual firmware source' in result.stdout
