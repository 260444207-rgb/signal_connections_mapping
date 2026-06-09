import sys, shutil
from pathlib import Path
sys.path.insert(0, r'C:\Users\x00810332\gucciai\project\skills\diagram-logical-connection-mapping\script')

# 1. 清理旧的 model_resolution_tasks（带空 source_device_pins）
old_dir = Path(r'C:\Users\x00810332\gucciai\project\data\20260605\intermediate\model_resolution_tasks')
if old_dir.exists():
    shutil.rmtree(old_dir)
old_dir.mkdir()

# 2. 清空旧的 model_resolved_decisions.jsonl
jsonl_file = Path(r'C:\Users\x00810332\gucciai\project\data\20260605\intermediate\model_resolved_decisions.jsonl')
if jsonl_file.exists():
    jsonl_file.unlink()

# 3. 重新生成带真实 pin 列表的 context JSON
from run_pipeline import run_model_tasks
run_model_tasks(
    Path(r'C:\Users\x00810332\gucciai\project\data\20260605'),
    r'C:\Users\x00810332\gucciai\project\data\20260605\block_info_pin.json'
)