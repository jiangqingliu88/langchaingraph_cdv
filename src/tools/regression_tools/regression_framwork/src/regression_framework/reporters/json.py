# src/regression_framework/reporters/json.py
import os
import json
from datetime import datetime
from ..core.logging_config import get_logger

logger = get_logger(__name__)

class JsonReporter:
    def generate(self, tasks, root_dir, total_time="N/A"):
        data = {
            'timestamp': datetime.now().isoformat(),
            'root_dir': root_dir,
            'total_time': total_time,
            'total': len(tasks),
            'stats': {'pass': 0, 'fail': 0, 'unknown': 0},
            'tasks': []
        }
        for task in tasks:
            data['stats'][task.status] += 1
            task_entry = {
                'name': task.name,
                'status': task.status,
                'work_dir': task.work_dir,
                'elapsed': round(getattr(task, 'elapsed', 0.0), 2),
                'job_id': getattr(task, 'job_id', None),
                'fingerprint': getattr(task, 'fingerprint', 'unknown'),
                'sim_time': round(getattr(task, 'sim_time', 0.0), 2),
                'wave_path': getattr(task, 'wave_path', None),
                'performance_degraded': getattr(task, 'performance_degraded', False)
            }
            data['tasks'].append(task_entry)
        json_path = os.path.join(root_dir, 'report.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"JSON report: {json_path}")