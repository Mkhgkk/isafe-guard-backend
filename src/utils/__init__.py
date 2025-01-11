import os
import subprocess

def get_directory_size(directory):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
    return total_size


def du(path):
    return subprocess.check_output(['du','-sh', path]).split()[0].decode('utf-8')

def df():
    try:
        result = subprocess.check_output(
            'df -h | awk \'$NF=="/" {print $2, $3, $4}\'',
            shell=True,
            text=True
        )
        return result.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return None