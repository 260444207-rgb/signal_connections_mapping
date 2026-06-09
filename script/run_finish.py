import sys
sys.path.insert(0, r'C:\Users\x00810332\gucciai\project\skills\diagram-logical-connection-mapping\script')
from run_pipeline import run_finish
from pathlib import Path
run_finish(
    Path(r'C:\Users\x00810332\gucciai\project\data\20260605'),
    r'C:\Users\x00810332\gucciai\project\data\20260605\block_info_pin.json',
    r'C:\Users\x00810332\gucciai\project\data\20260605\aggregated_connections_20260605_100957.xlsx',
    'template_sheets'
)